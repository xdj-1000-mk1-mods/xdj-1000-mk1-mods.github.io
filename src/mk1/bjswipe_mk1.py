#!/usr/bin/env python3
"""Swipe the stock PERFORM BEAT JUMP row for sizes 1..64 beats (MK1 v1.13).

The 700 mod's behaviour (upstream tools/perform_pads.py): tap a pad to jump,
drag the row > 48 px to page 1-2-4 -> 4-8-16 -> 16-32-64 (left = bigger).
mk1/bjswipe/bjswipe.c hooks the hit-tester slot (model table touch_hook);
see its header for how. Install: module, zero its bss, then the slot as ONE
32-bit store (revert: the slot first, then the table to page 0).

    bjswipe_mk1.py build     -> work/bjswipe/build/bj.bin + bj.syms
    bjswipe_mk1.py emu       qemu test from state 'perform' (paused):
                             taps + swipes, jumps read off REMAIN
    bjswipe_mk1.py emu-play  qemu test while playing: jumps off the position
                             word, swipes while playing, 32/64 + edge cases
"""
import json
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                 # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
MOD, HOOK, RECTS = E_["bjswipe_module"], E_["touch_hook"], E_["bj_pad_rects"]
BASE, END_MAX = int(MOD["addr"], 16), int(MOD["end_max"], 16)
SLOT, STOCK = int(HOOK["slot"], 16), int(HOOK["stock"], 16)
TAB = int(E_["bj_table"]["alias"].split()[0], 16)               # uncached, as the handler reads it
MODEW = int(E_["screen_mode_word"]["addr"], 16)
OUT = os.path.join(ROOT, "work", "bjswipe", "build")
LBL = int(E_["bjswipe_labels"]["addr"], 16)
LBL_END = int(E_["bjswipe_labels"]["end_max"], 16)
SPR = E_["bj_pad_sprites"]


def build():
    import bjlabels
    blob, lay = bjlabels.build(bjlabels.Labels(open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()))
    assert LBL + len(blob) <= LBL_END
    spr = {p["code"]: int(p["addr"], 16) for p in SPR["pads"]}
    padx = "{" + ",".join("{%d,%d}" % tuple(RECTS["x"][str(c)]) for c in range(1, 7)) + "}"
    d = dict(MODEW=MODEW, MODE_PERFORM=E_["screen_mode_word"]["values"]["perform"], BJ_TAB=TAB,
             BJ_HANDLER=int(E_["bj_handler"]["addr"], 16), STOCK_HIT=STOCK,
             ROW_Y0=RECTS["y"][0], ROW_Y1=RECTS["y"][1], PAD_X=padx, LBL=LBL,
             SPR="{" + ",".join("%#x" % spr[c] for c in range(1, 7)) + "}",
             STYLE_STRIDE=SPR["style_stride"], BAND_OFF=lay["rows"][0] * SPR["w"] * 2,
             BAND_BYTES=lay["band_bytes"])
    src = os.path.join(HERE, "bjswipe")
    img, syms = shbuild.build(OUT, "bj", [os.path.join(src, "bjentry.S"), os.path.join(src, "bjswipe.c")],
                              BASE, END_MAX, d, "_bj_head", keep=("_bj_", "_end"))
    assert syms["bj_head"] == BASE, syms
    return img, syms


def install_steps(s):
    blob = os.path.join(OUT, "bj.bin")
    n = os.path.getsize(blob)
    return ["fill %#x %#x 0" % (BASE + n, s["end"] - BASE - n),
            "load %#x %s" % (LBL, os.path.join(OUT, "labels.bin")),
            "load %#x %s" % (BASE, blob),
            "poke32 %#x %#x" % (SLOT, s["bj_entry"])]


def emu():
    import emu as E
    import remain_ocr
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "bjswipe", "shots")
    os.makedirs(shots, exist_ok=True)
    img, s = build()
    p = E.start(model, incoming=os.path.join(E.WORK, model, "perform.vm"))
    ok, n = True, [0]
    beat = 60 / 120.2                                          # test track: 120.2 BPM

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    def remain(tag):
        n[0] += 1
        f = os.path.join(shots, "%02d_%s.png" % (n[0], tag))
        time.sleep(1.2)
        E.shot(model, f)
        return remain_ocr.read(f)

    def table():
        return [u32(TAB + 8 * c) for c in range(1, 7)]

    def st():
        b = E.peek(model, s["bj_st"], 24)
        return dict(held=b[0], swiped=b[1], page=b[4], y=struct.unpack_from("<H", b, 12)[0],
                    taps=struct.unpack_from("<I", b, 16)[0], swipes=struct.unpack_from("<I", b, 20)[0])

    lab = open(os.path.join(OUT, "labels.bin"), "rb").read()
    lay = json.load(open(os.path.join(OUT, "labels.json")))
    bb, lr0, lr1 = lay["band_bytes"], lay["rows"][0], lay["rows"][1]
    spr = {q["code"]: int(q["addr"], 16) for q in SPR["pads"]}
    px0 = {c: RECTS["x"][str(c)][0] for c in range(1, 7)}        # sprite origin x = pad left
    py0 = RECTS["y"][0] - 1                                       # sprite origin y (144)

    def labels_ok(page, tag):
        """sprite RAM == the page's bands (all styles); screen pads == style 0"""
        import numpy as np
        from PIL import Image
        ram = all(E.peek(model, spr[c] + k * SPR["style_stride"] + lr0 * SPR["w"] * 2, bb)
                  == lab[((page * 6 + c - 1) * 3 + k) * bb:][:bb] for c in range(1, 7) for k in range(3))
        f = os.path.join(shots, "labels_p%d_%s.png" % (page, tag))
        time.sleep(1.0)
        E.shot(model, f)
        scr = np.asarray(Image.open(f).convert("RGB")).astype(int)
        fr = []
        for c in range(1, 7):
            v = np.frombuffer(lab[((page * 6 + c - 1) * 3) * bb:][:bb], "<u2").reshape(lr1 - lr0, SPR["w"]).astype(int)
            want = np.dstack([(v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31])
            got = scr[py0 + lr0:py0 + lr1, px0[c]:px0[c] + SPR["w"]]
            fr.append(float((np.abs(got - want)[:, :78].max(axis=2) <= 8).mean()))   # 78-79: next pad overlaps
        return ram, min(fr)

    def tap(code, tag):
        x = sum(RECTS["x"][str(code)]) // 2
        r0 = remain("pre_" + tag)
        E.step(model, "tap %d 175 300" % x)
        r1 = remain(tag)
        return None if r0 is None or r1 is None else r1 - r0

    def swipe(dx, tag):
        x = 404
        E.step(model, "touch %d 175 1" % x)
        time.sleep(0.4)
        for k in (1, 2, 3):
            E.step(model, "touch %d 175 1" % (x + dx * k // 3))
            time.sleep(0.2)
        E.step(model, "touch %d 175 0" % (x + dx))
        time.sleep(0.6)
        return st()

    try:
        for _ in range(240):
            if "running" in E.cmd(model, "info status"):
                break
            time.sleep(0.25)
        time.sleep(2)
        E.step(model, "key 0x10:0x01:300")                    # PLAY -> pause
        time.sleep(1.5)
        ok &= chk("stock: slot -> hit-tester, table 1/1/2/2/4/4, PERFORM",
                  u32(SLOT) == STOCK and table() == [1, 1, 2, 2, 4, 4] and u32(MODEW) == 7)
        ok &= chk("module area empty", E.peek(model, BASE, END_MAX - BASE) == bytes(END_MAX - BASE))
        ram, sc = labels_ok(0, "stock")
        ok &= chk("stock pads == labels page 0 (RAM %s, screen match %.3f)" % (ram, sc), ram and sc > 0.98)
        for x in install_steps(s):
            E.step(model, x)
        time.sleep(0.5)

        def jump(code, beats, tag):
            d = tap(code, tag)
            want = beats * beat * (1 if code % 2 else -1)       # << (odd) = back = REMAIN up
            good = d is not None and abs(d - want) < 0.25
            return chk("tap pad %d: %+.3f s, want %+.3f (%d beats)" % (
                code, d if d is not None else float("nan"), want, beats), good)

        ok &= jump(1, 1, "p0_back1")
        ok &= jump(2, 1, "p0_fwd1")
        ok &= chk("y reached the hook in screen px (last y %d)" % st()["y"], abs(st()["y"] - 175) <= 3)
        r0 = remain("pre_swipeL")
        sw = swipe(-100, "L1")
        r1 = remain("swipeL")
        ok &= chk("swipe left -> page 1, table %s, no jump (%+.3f s)" % (table(), (r1 or 0) - (r0 or 0)),
                  sw["page"] == 1 and table() == [4, 4, 8, 8, 16, 16]
                  and r0 is not None and r1 is not None and abs(r1 - r0) < 0.1)
        ram, sc = labels_ok(1, "L1")
        ok &= chk("page 1 labels 4/8/16 (RAM %s, screen match %.3f)" % (ram, sc), ram and sc > 0.98)
        ok &= jump(3, 8, "p1_back8")
        ok &= jump(4, 8, "p1_fwd8")
        sw = swipe(-100, "L2")
        ok &= chk("swipe left -> page 2, table %s" % table(), sw["page"] == 2 and table() == [16, 16, 32, 32, 64, 64])
        ram, sc = labels_ok(2, "L2")
        ok &= chk("page 2 labels 16/32/64 (RAM %s, screen match %.3f)" % (ram, sc), ram and sc > 0.98)
        ok &= jump(1, 16, "p2_back16")
        ok &= jump(2, 16, "p2_fwd16")
        sw = swipe(-100, "L3")
        ok &= chk("swipe left at the last page: stays 2", sw["page"] == 2 and table()[0] == 16)
        swipe(100, "R1")
        sw = swipe(100, "R2")
        ok &= chk("2 swipes right -> page 0, table %s" % table(), sw["page"] == 0 and table() == [1, 1, 2, 2, 4, 4])
        ram, sc = labels_ok(0, "R2")
        ok &= chk("back to page 0: stock labels (RAM %s, screen match %.3f)" % (ram, sc), ram and sc > 0.98)
        ok &= jump(5, 4, "p0_back4")
        # off the row: QUANTIZE still goes to the stock hit-tester (tap twice = unchanged)
        qx, qy = E_["bj_pads_touch"]["quantize_xy"]
        t0 = st()["taps"]
        E.step(model, "tap %d %d 300" % (qx, qy))
        time.sleep(1.2)
        E.shot(model, os.path.join(shots, "q_off.png"))
        E.step(model, "tap %d %d 300" % (qx, qy))
        time.sleep(1.2)
        E.shot(model, os.path.join(shots, "q_on.png"))
        from PIL import Image
        a = Image.open(os.path.join(shots, "q_off.png")).getpixel((qx, qy - 20))
        b = Image.open(os.path.join(shots, "q_on.png")).getpixel((qx, qy - 20))
        ok &= chk("QUANTIZE toggles through stock (%s -> %s), not taken by us" % (a, b),
                  a != b and st()["taps"] == t0)
        E.step(model, "tap 711 37 300")                       # PERFORM off -> main screen
        time.sleep(1.5)
        E.step(model, "tap 154 175 300")                      # same spot on the main screen
        time.sleep(1.2)
        ok &= chk("main screen: row area not taken (mode %d)" % u32(MODEW), st()["taps"] == t0)
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
        print("state", st(), flush=True)
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def emu_play():
    """qemu test while PLAYING: jumps read off the play-position word (1/150 s)
    minus the playback in between; swipes while playing; 32 and 64 beats."""
    import emu as E
    model = "xdj1000"
    img, s = build()
    p = E.start(model, incoming=os.path.join(E.WORK, model, "perform.vm"))
    POS = int(E_["play_position"]["addr"], 16)
    PST = int(E_["play_state"]["addr"], 16)
    ok = True
    beat = 60 / 120.2                                          # test track: 120.2 BPM

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    def pos():                                                 # (seconds, wall time)
        return u32(POS) / 150.0, time.time()

    def rate():                                                # track s per wall s
        a, t0 = pos()
        time.sleep(2.0)
        b, t1 = pos()
        return (b - a) / (t1 - t0)

    def tap(code, r):
        x = sum(RECTS["x"][str(code)]) // 2
        a, t0 = pos()
        E.step(model, "tap %d 175 300" % x)
        time.sleep(1.0)
        b, t1 = pos()
        return (b - a) - r * (t1 - t0), a

    def swipe(dx):
        x = 404
        E.step(model, "touch %d 175 1" % x)
        time.sleep(0.4)
        for k in (1, 2, 3):
            E.step(model, "touch %d 175 1" % (x + dx * k // 3))
            time.sleep(0.2)
        E.step(model, "touch %d 175 0" % (x + dx))
        time.sleep(0.6)
        return E.peek(model, s["bj_st"] + 4, 1)[0]

    def table():
        return [u32(TAB + 8 * c) for c in range(1, 7)]

    try:
        for _ in range(240):
            if "running" in E.cmd(model, "info status"):
                break
            time.sleep(0.25)
        time.sleep(2)
        r = rate()
        ln = u32(POS + 4) / 150.0
        ok &= chk("playing: rate %.3f, pos %.1f s of %.1f s, play_state %d (deck read 3 while playing)"
                  % (r, pos()[0], ln, u32(PST)), r > 0.3 and u32(MODEW) == 7)
        for x in install_steps(s):
            E.step(model, x)
        time.sleep(0.5)

        def jump(code, beats, refused_ok=False):
            d, at = tap(code, r)
            want = beats * beat * (-1 if code % 2 else 1)       # << (odd) = back
            if refused_ok and abs(d) < 0.3:
                return chk("pad %d at %.1f s: refused (%+.3f s), stock limit" % (code, at, d), True)
            return chk("pad %d at %.1f s: %+.3f s, want %+.3f (%d beats)" % (code, at, d, want, beats),
                       abs(d - want) < 0.3)

        ok &= jump(2, 1)
        ok &= jump(1, 1)
        a, _ = pos()
        pg = swipe(-100)
        b, _ = pos()
        ok &= chk("swipe while playing -> page %d, table %s, no jump (moved %.2f s)" % (pg, table(), b - a),
                  pg == 1 and table() == [4, 4, 8, 8, 16, 16] and 0 <= b - a < 2.5 * max(r, 0.5))
        ok &= jump(4, 8)
        ok &= jump(3, 8)
        pg = swipe(-100)
        ok &= chk("page 2 while playing, table %s" % table(), pg == 2 and table() == [16, 16, 32, 32, 64, 64])
        ok &= jump(2, 16)
        while pos()[0] < 36 and ln > 80:                       # room for 64 back (32 s)
            ok &= jump(2, 16)
        ok &= jump(1, 16)
        ok &= jump(4, 32)
        ok &= jump(3, 32)
        if pos()[0] < 33:
            ok &= jump(4, 32)
        ok &= jump(5, 64)
        ok &= jump(6, 64, refused_ok=True)                     # stock refuses > ~46 forward
        while pos()[0] > 25:                                   # get under 64 beats behind
            ok &= jump(3, 32)
        if pos()[0] < 31:
            d, at = tap(5, r)
            ok &= chk("<< 64 with %.1f s behind: %+.3f s (stock clamps to start or refuses)" % (at, d),
                      d <= 0.3 and d >= -at - 0.3)
        swipe(100)
        pg = swipe(100)
        ok &= chk("back to page 0 while playing, table %s" % table(), pg == 0 and table() == [1, 1, 2, 2, 4, 4])
        ok &= chk("still playing (rate %.3f)" % rate(), rate() > 0.3)
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["emu"]:
        sys.exit(emu())
    elif sys.argv[1:] == ["emu-play"]:
        sys.exit(emu_play())
    else:
        print(__doc__)
