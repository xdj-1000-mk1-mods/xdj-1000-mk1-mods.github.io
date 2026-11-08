#!/usr/bin/env python3
"""STEMS control on the MK1 PERFORM screen (mk1/stemsui/stemsui.c).

Tap the BEAT JUMP row label -> the row becomes STEMS [VOCALS] [DRUMS] [BASS]
[OTHER] [ALL ON] [BACK]; see stemsui.c. Sets the mute mask of the stem
mixer (stems_mk1.py); inert without it.

Install (after the BEAT JUMP swipe and the mixer): images, module, its state
zeroed, stemsui_fprev / stemsui_tprev = the live slot values, then the flush
slot and the touch slot, each as ONE store.

    stemsui_mk1.py build     -> work/stemsui/build/stemsui.bin, stemsui_img.bin
    stemsui_mk1.py emu       qemu test on the stems test stick (track playing)
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
import stems_mk1 as SM                                         # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
MOD, L = E_["stemsui_module"], E_["stemsui_layout"]
H = lambda v: int(v, 16)
BASE, END_MAX, IMG, IMG_END = H(MOD["addr"]), H(MOD["end_max"]), H(MOD["img"]), H(MOD["img_end_max"])
FLUSH, FLUSH_STOCK = H(E_["flush_hook"]["slot"]), H(E_["flush_hook"]["stock"])
TOUCH, HIT_STOCK = H(E_["touch_hook"]["slot"]), H(E_["touch_hook"]["stock"])
MODEW = H(E_["screen_mode_word"]["addr"])
PADS = [tuple(E_["bj_pad_rects"]["x"][str(c)]) for c in range(1, 7)]
OUT = os.path.join(ROOT, "work", "stemsui", "build")


def build():
    import stemsui_assets
    blob, _ = stemsui_assets.build()
    assert IMG + len(blob) <= IMG_END, "STEMS images do not fit"
    _, sms = SM.build()
    lt = L["label_touch"]
    d = dict(MODEW=MODEW, MODE_PERFORM=E_["screen_mode_word"]["values"]["perform"], PMASK=SM.PMASK,
             SM_BASE=SM.BASE, SM_SIG=sms["sm_fread"], IMG=IMG, ROW_Y0=L["row_y"][0], ROW_Y1=L["row_y"][1],
             PADS="{" + ",".join("{%d,%d}" % p for p in PADS) + "}",
             LABEL="{%d,%d,%d,%d}" % tuple(lt), TITLE_XY="{%d,%d}" % (L["title_x"][0], L["title_y"][0]),
             FLUSH_STOCK=FLUSH_STOCK, HIT_STOCK=HIT_STOCK)
    src = os.path.join(HERE, "stemsui")
    img, syms = shbuild.build(OUT, "stemsui", [os.path.join(src, "stemsuientry.S"), os.path.join(src, "stemsui.c")],
                              BASE, END_MAX, d, "_stemsui_head", keep=("_stemsui_", "_end"), cwd=OUT,
                              extra=("-I" + OUT,))
    assert syms["stemsui_head"] == BASE, syms
    return img, syms


def install_steps(s, live_flush, live_touch):
    img = bytearray(open(os.path.join(OUT, "stemsui.bin"), "rb").read())
    struct.pack_into("<I", img, s["stemsui_fprev"] - BASE, live_flush)
    struct.pack_into("<I", img, s["stemsui_tprev"] - BASE, live_touch)
    blob = os.path.join(OUT, "stemsui_installed.bin")
    open(blob, "wb").write(img)
    n = len(img)
    return ["load %#x %s" % (IMG, os.path.join(OUT, "stemsui_img.bin")),
            "fill %#x %#x 0" % (BASE + n, s["end"] - BASE - n),
            "load %#x %s" % (BASE, blob),
            "poke32 %#x %#x" % (FLUSH, s["stemsui_flush"]),
            "poke32 %#x %#x" % (TOUCH, s["stemsui_touch"])]


def emu():
    import numpy as np
    from PIL import Image
    import emu as E
    import bjswipe_mk1 as BJ
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "stemsui", "shots")
    os.makedirs(shots, exist_ok=True)
    SM.make_stick()
    bimg, bs = BJ.build()
    simg, ss = SM.build()
    uimg, us = build()
    blob = open(os.path.join(OUT, "stemsui_img.bin"), "rb").read()
    lay = {}
    for ln in open(os.path.join(OUT, "stemsui_layout.h")):
        a = ln.split()
        if len(a) == 3:
            lay[a[1]] = int(a[2].rstrip("u"))
    p = E.start(model, stick=SM.STICK_IMG)
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    u8 = lambda a: E.peek(model, a, 1)[0]
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def st():
        b = E.peek(model, us["stemsui_st"], 16)
        return dict(mode=b[0], draws=struct.unpack_from("<I", b, 4)[0], taps=struct.unpack_from("<I", b, 8)[0])

    def tap(x, y, wait=1.5):
        E.step(model, "tap %d %d 250" % (x, y))
        time.sleep(wait)

    def pad_xy(i):
        return (PADS[i][0] + PADS[i][1]) // 2, (L["row_y"][0] + L["row_y"][1]) // 2

    def shot(tag):
        f = os.path.join(shots, tag + ".png")
        time.sleep(1.0)
        E.shot(model, f)
        return np.asarray(Image.open(f).convert("RGB")).astype(int)

    def match(scr, tag, x0, y0):
        w, h, off = lay["IMG_%s_W" % tag], lay["IMG_%s_H" % tag], lay["IMG_%s_OFF" % tag]
        v = np.frombuffer(blob[off:off + w * h * 2], "<u2").reshape(h, w).astype(int)
        want = np.dstack([(v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31])
        return float((np.abs(scr[y0:y0 + h, x0:x0 + w] - want).max(axis=2) <= 8).mean())

    def row_is(scr, tags):
        m = [match(scr, t, PADS[i][0], L["row_y"][0]) for i, t in enumerate(tags)]
        return min(m), m

    def mixed_now(mask, prev_mask=None):
        """the next few reads land mixed with `mask` (exact, as stems_mk1.emu)"""
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import stems4 as S4
        d_off, d_len, big, stm, mix = S4.read(os.path.join(SM.STICK_DIR, SM.TRACK))
        want = S4.expected(stm, mask).tobytes() if mask else mix.tobytes()
        plain = mix.tobytes()
        prev = S4.expected(stm, prev_mask).tobytes() if prev_mask else None
        c0 = u32(ss["sm_calls"])                       # a change applies from the deck's next read call
        for _ in range(20):
            if u32(ss["sm_calls"]) >= c0 + 2:
                break
            time.sleep(0.5)
        good = n_in = 0
        kinds = []
        for _ in range(8):
            pos, buf, n = u32(ss["sm_lastpos"]), u32(ss["sm_lastbuf"]), u32(ss["sm_lastn"])
            a = max(pos, d_off)
            a = d_off + ((a - d_off + 3) & ~3)
            e = min(pos + min(n, 4096), d_off + d_len)
            if e - a < 256:
                time.sleep(1.0)
                continue
            n_in += 1
            for k in range(2):                 # a sample can land mid-read: look again once
                got = E.peek(model, (buf & 0x1FFFFFFF) + (a - pos), e - a)
                if got == want[a - d_off:e - d_off]:
                    good += 1
                    kinds.append("mix" if k == 0 else "mix(2nd look)")
                    break
                if k == 0:
                    time.sleep(0.3)
            else:
                kinds.append("plain" if got == plain[a - d_off:e - d_off] else
                             "previous mask" if prev and got == prev[a - d_off:e - d_off] else "other")
            time.sleep(1.0)
        print("  samples:", kinds, flush=True)
        return n_in, good

    try:
        time.sleep(50)
        for x in BJ.install_steps(bs):
            E.step(model, x)
        for x in SM.install_steps(ss, u32(SM.HOOK)):
            E.step(model, x)
        for x in install_steps(us, u32(FLUSH), u32(TOUCH)):
            E.step(model, x)
        ok &= chk("installed: touch slot -> stemsui %#x, flush slot -> stemsui, mixer hooked" % u32(TOUCH),
                  u32(TOUCH) == us["stemsui_touch"] and u32(FLUSH) == us["stemsui_flush"]
                  and u32(SM.HOOK) == ss["sm_fread"])
        for s_ in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3, "key 0x11:0x01:300", 12, "key 0x11:0x01:300", 8):
            E.step(model, s_) if isinstance(s_, str) else time.sleep(s_)
        tap(711, 37, 3)                                             # PERFORM
        ok &= chk("PERFORM up (mode %d), track playing" % u32(MODEW), u32(MODEW) == 7)
        lx, ly = (L["label_touch"][0] + L["label_touch"][1]) // 2, (L["label_touch"][2] + L["label_touch"][3]) // 2
        stock_row = shot("0_stock")[L["row_y"][0]:L["row_y"][1] + 1, PADS[0][0]:PADS[5][1] + 1]
        tap(lx, ly)
        scr = shot("a_open")
        mn, m = row_is(scr, ["ON0", "ON1", "ON2", "ON3", "ALL", "BACK"])
        ok &= chk("label tap opens STEMS (mode %d), pads == images (min %.3f), title %.3f"
                  % (st()["mode"], mn, match(scr, "TITLE", L["title_x"][0], L["title_y"][0])),
                  st()["mode"] == 1 and mn > 0.97)
        tap(*pad_xy(0))
        tap(*pad_xy(2))
        scr = shot("b_vocals_bass_muted")
        mn, m = row_is(scr, ["MU0", "ON1", "MU2", "ON3", "ALL", "BACK"])
        ok &= chk("VOCALS + BASS tapped: mask %s, pads (min %.3f)" % (bin(u8(SM.PMASK)), mn),
                  u8(SM.PMASK) == 0b0101 and mn > 0.97)
        n_in, good = mixed_now(0b0101, prev_mask=0b0001)
        remix = u32(ss["sm_remix"])                    # counted on the read after the change
        ok &= chk("mute during play: re-mixes %d; next reads: %d inside the data, %d == mask 0b101 mix"
                  % (remix, n_in, good), remix > 0 and n_in >= 2 and good == n_in)
        tap(*pad_xy(4))
        ok &= chk("ALL ON: mask %s" % bin(u8(SM.PMASK)), u8(SM.PMASK) == 0)
        tap(*pad_xy(1))
        tap(*pad_xy(5))
        scr = shot("c_closed_drums_muted")
        al = match(scr, "ALERT", L["title_x"][0], L["title_y"][0])
        row = scr[L["row_y"][0]:L["row_y"][1] + 1, PADS[0][0]:PADS[5][1] + 1]
        back = float((np.abs(row - stock_row).max(axis=2) <= 8).mean())
        ok &= chk("DRUMS + BACK: view closed (mode %d), mask %s kept, red STEMS label %.3f, row == stock row %.3f"
                  % (st()["mode"], bin(u8(SM.PMASK)), al, back), st()["mode"] == 0 and u8(SM.PMASK) == 0b0010
                  and al > 0.97 and back > 0.97)
        b0 = struct.unpack_from("<I", E.peek(model, bs["bj_st"] + 16, 4))[0]
        tap(*pad_xy(1))
        b1 = struct.unpack_from("<I", E.peek(model, bs["bj_st"] + 16, 4))[0]
        ok &= chk("BEAT JUMP pads still go to the swipe module (its taps %d -> %d)" % (b0, b1), b1 == b0 + 1)
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
        img, s = build()
        print("stemsui: %d B, bss to %#x" % (len(img), s["end"]))
    elif sys.argv[1:] == ["emu"]:
        sys.exit(emu())
    else:
        print(__doc__)
