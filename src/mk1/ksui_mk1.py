#!/usr/bin/env python3
"""KEY SHIFT control on the MK1 PERFORM screen (mk1/ksui/ksui.c).

Tap the HOT CUE row label -> the row becomes KEY SHIFT [-] [key] [+]
[RESET] [BACK]; see ksui.c for the rules (inert unless the engine is
installed and MASTER TEMPO is on, MT change resets, key re-asserted after a
track load). Needs keyshift_mk1.py's engine for sound; without it the value
pad reads N/A.

Install (after key shift's one-shot has finished, see install_mk1.py):
images, module, its state zeroed, mt_last = current MASTER TEMPO,
ksui_fprev / ksui_tprev = the live slot values, then the flush slot and the
touch slot, each as ONE store. Revert: the two slots back to the prevs.

    ksui_mk1.py build     -> work/ksui/build/ksui.bin, ksui_img.bin
    ksui_mk1.py emu       qemu test (fresh boot, all mods via install_mk1)
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
import keyshift_mk1 as KS                                      # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
MOD, L = E_["ksui_module"], E_["ksui_layout"]
BASE, END_MAX = int(MOD["addr"], 16), int(MOD["end_max"], 16)
IMG, IMG_END = int(MOD["img"], 16), int(MOD["img_end_max"], 16)
FLUSH, FLUSH_STOCK = int(E_["flush_hook"]["slot"], 16), int(E_["flush_hook"]["stock"], 16)
TOUCH, HIT_STOCK = int(E_["touch_hook"]["slot"], 16), int(E_["touch_hook"]["stock"], 16)
MODEW = int(E_["screen_mode_word"]["addr"], 16)
OUT = os.path.join(ROOT, "work", "ksui", "build")


def build():
    import ksui_assets
    blob, _ = ksui_assets.build()
    assert IMG + len(blob) <= IMG_END
    pads = "{" + ",".join("{%d,%d}" % tuple(L["pads"][k]) for k in ("A", "B", "C", "REC", "CALL")) + "}"
    lt = L["label_touch"]
    d = dict(MODEW=MODEW, MODE_PERFORM=E_["screen_mode_word"]["values"]["perform"], MTW=KS.MTW,
             KEY_WORD=KS.KEY_WORD, SITE=KS.SITE, SITE_NOP=KS.NOP, IMG=IMG,
             ROW_Y0=L["row_y"][0], ROW_Y1=L["row_y"][1], PADS=pads,
             LABEL="{%d,%d,%d,%d}" % tuple(lt), TITLE_XY="{%d,%d}" % (L["title_x"][0], L["title_y"][0]),
             KWORDS="{" + ",".join("%#xu" % KS.key_word(s) for s in range(-6, 7)) + "}",
             FLUSH_STOCK=FLUSH_STOCK, HIT_STOCK=HIT_STOCK)
    src = os.path.join(HERE, "ksui")
    img, syms = shbuild.build(OUT, "ksui", [os.path.join(src, "ksuientry.S"), os.path.join(src, "ksui.c")],
                              BASE, END_MAX, d, "_ksui_head", keep=("_ksui_", "_end"), cwd=OUT, extra=("-I" + OUT,))
    assert syms["ksui_head"] == BASE, syms
    return img, syms


def install_steps(s, live_flush, live_touch, mt):
    img = bytearray(open(os.path.join(OUT, "ksui.bin"), "rb").read())
    struct.pack_into("<I", img, s["ksui_fprev"] - BASE, live_flush)
    struct.pack_into("<I", img, s["ksui_tprev"] - BASE, live_touch)
    blob = os.path.join(OUT, "ksui_installed.bin")
    open(blob, "wb").write(img)
    n = len(img)
    return ["load %#x %s" % (IMG, os.path.join(OUT, "ksui_img.bin")),
            "fill %#x %#x 0" % (BASE + n, s["end"] - BASE - n),
            "load %#x %s" % (BASE, blob),
            "fill %#x 1 %d" % (s["ksui_st"] + 3, mt),                 # mt_last = MT now
            "poke32 %#x %#x" % (FLUSH, s["ksui_flush"]),
            "poke32 %#x %#x" % (TOUCH, s["ksui_touch"])]


def install(E, model):
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    img, s = build()
    for st in install_steps(s, u32(FLUSH), u32(TOUCH), E.peek(model, KS.MTW, 1)[0]):
        E.step(model, st)
    return s


def emu():
    import emu as E
    import install_mk1 as I
    from PIL import Image
    import numpy as np
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "ksui", "shots")
    os.makedirs(shots, exist_ok=True)
    p = E.start(model)
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    u8 = lambda a: E.peek(model, a, 1)[0]
    blob = None

    def st():
        b = E.peek(model, s["ksui_st"], 28)                   # struct ksui_state
        draws, taps, steps, resets, reasserts = struct.unpack_from("<5I", b, 8)
        return dict(mode=b[0], key=struct.unpack_from("b", b, 4)[0], draws=draws, taps=taps,
                    steps=steps, resets=resets, reasserts=reasserts)

    def tap(x, y, wait=1.2):
        E.step(model, "tap %d %d 250" % (x, y))
        time.sleep(wait)

    def pad_center(name):
        x0, x1 = L["pads"][name]
        return (x0 + x1) // 2, (L["row_y"][0] + L["row_y"][1]) // 2

    def screen_row(tag):
        f = os.path.join(shots, tag + ".png")
        E.shot(model, f)
        return np.asarray(Image.open(f).convert("RGB")).astype(int)

    def matches(scr, name, tag):
        """screen pad == our image (RGB565 expanded), within 8/255"""
        lay = {}
        for ln in open(os.path.join(OUT, "ksui_layout.h")):
            a = ln.split()
            if len(a) == 3:
                lay[a[1]] = int(a[2].rstrip("u"))
        n = "IMG_" + tag
        w, h, off = lay[n + "_W"], lay[n + "_H"], lay[n + "_OFF"]
        v = np.frombuffer(blob[off:off + w * h * 2], "<u2").reshape(h, w).astype(int)
        want = np.dstack([(v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31])
        x0 = L["pads"][name][0] if name in L["pads"] else L["title_x"][0]
        y0 = L["row_y"][0] if name in L["pads"] else L["title_y"][0]
        got = scr[y0:y0 + h, x0:x0 + w]
        return float((np.abs(got - want).max(axis=2) <= 8).mean())

    def row_is(tag, b_tag):
        scr = screen_row(tag)
        m = [matches(scr, "A", "A"), matches(scr, "B", b_tag), matches(scr, "C", "C"),
             matches(scr, "REC", "REC"), matches(scr, "CALL", "CALL"), matches(scr, "TITLE", "TITLE")]
        print("  %s: match A %.3f B(%s) %.3f C %.3f REC %.3f CALL %.3f TITLE %.3f" % (tag, m[0], b_tag, *m[1:]))
        return min(m) > 0.99

    try:
        time.sleep(50)
        r = I.install_all(E, model, log=lambda m: print("  " + m, flush=True))
        ok &= chk("all mods installed (key shift status %d)" % r["ks_status"], r["ks_status"] == 1)
        s = r["ksui"]
        blob = open(os.path.join(OUT, "ksui_img.bin"), "rb").read()
        for st_ in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3, "key 0x11:0x01:300", 12,
                    "key 0x11:0x01:300", 15):
            E.step(model, st_) if isinstance(st_, str) else time.sleep(st_)
        tap(711, 37, 2.5)                                               # PERFORM
        ok &= chk("PERFORM up (mode %d), track playing" % u32(MODEW), u32(MODEW) == 7 and u32(KS.TRACK_LEN))
        scr0 = screen_row("a_stock")
        lx, ly = (L["label_touch"][0] + L["label_touch"][1]) // 2, (L["label_touch"][2] + L["label_touch"][3]) // 2
        tap(lx, ly, 2)
        ok &= chk("label tap -> KEY SHIFT mode (mode %d)" % st()["mode"], st()["mode"] == 1)
        ok &= chk("MT off: value pad reads MT OFF", u8(KS.MTW) == 0 and row_is("b_mt_off", "BMT"))
        w0 = u32(KS.KEY_WORD)                    # after a load the deck leaves 0 here (= no shift)
        tap(*pad_center("C"))
        ok &= chk("MT off: + is inert (key %d, word %#x unchanged)" % (st()["key"], u32(KS.KEY_WORD)),
                  st()["key"] == 0 and u32(KS.KEY_WORD) == w0)
        E.step(model, "key 0x15:0x10:300")
        time.sleep(2)
        ok &= chk("MASTER TEMPO on", u8(KS.MTW) == 1)
        tap(*pad_center("C"))
        tap(*pad_center("C"))
        ok &= chk("+ + -> key +2 (word %#010x)" % u32(KS.KEY_WORD),
                  st()["key"] == 2 and u32(KS.KEY_WORD) == KS.key_word(2) and row_is("c_plus2", "BP2"))
        time.sleep(2)
        k = KS.ks_state(E, model)
        ok &= chk("DSP latched k %.4f" % k["k"], abs(k["k"] - 2 ** (2 / 12)) < 1e-3)
        tap(*pad_center("A"))
        tap(*pad_center("A"))
        tap(*pad_center("A"))
        ok &= chk("- - - -> key -1", st()["key"] == -1 and u32(KS.KEY_WORD) == KS.key_word(-1) and
                  row_is("d_minus1", "BM1"))
        tap(*pad_center("REC"))
        ok &= chk("RESET -> 0", st()["key"] == 0 and u32(KS.KEY_WORD) == KS.key_word(0))
        tap(*pad_center("C"))
        E.step(model, "key 0x15:0x10:300")                             # MT off with a key set
        time.sleep(2)
        ok &= chk("MT change resets the key (key %d, word %#x, resets %d)" % (
            st()["key"], u32(KS.KEY_WORD), st()["resets"]),
            st()["key"] == 0 and u32(KS.KEY_WORD) == KS.key_word(0) and st()["resets"] == 1)
        E.step(model, "key 0x15:0x10:300")
        time.sleep(2)
        tap(*pad_center("C"))
        E.step(model, "poke32 %#x %#x" % (KS.KEY_WORD, KS.key_word(0)))   # as a track load does
        time.sleep(1.5)
        ok &= chk("key word cleared by the deck -> put back (+1)", u32(KS.KEY_WORD) == KS.key_word(1))
        tap(*pad_center("CALL"), 2.5)
        scr = screen_row("e_back")
        same = float((np.abs(scr[232:296, 116:617] - scr0[232:296, 116:617]).max(axis=2) <= 8).mean())
        ok &= chk("BACK -> hot cues again (mode %d, row %.3f like stock)" % (st()["mode"], same),
                  st()["mode"] == 0 and same > 0.99)
        ok &= chk("key stays +1 after BACK", u32(KS.KEY_WORD) == KS.key_word(1))
        tap(lx, ly, 2)
        ok &= chk("label tap again -> KEY SHIFT, shows +1", st()["mode"] == 1 and row_is("f_again", "BP1"))
        t0 = st()["taps"]
        tap(*pad_center("A"))
        tap(711, 37, 2)                                                 # PERFORM off
        tap(*pad_center("A"))                                           # main screen: not ours
        ok &= chk("main screen: row not taken (taps %d -> %d)" % (t0 + 1, st()["taps"]), st()["taps"] == t0 + 1)
        tap(lx, ly)
        ok &= chk("main screen: label spot not taken", st()["taps"] == t0 + 1 and st()["mode"] == 1)
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
    else:
        print(__doc__)
