#!/usr/bin/env python3
"""WAVEFORM COLOR row in MK1's UTILITY list (port of upstream tools/utility.py).

UTILITY (hold MENU) draws a scrolling list from a table of 52-byte records
(the model table's utility_table: RAM copy, count word, four literal pools).
The module (mk1/utility/ut_mk1.c, built at utility_module.addr) holds a
17-record copy: the 16 stock records + WAVEFORM COLOR (BLUE / RGB / 3-BAND),
which reads and writes the RGB mod's mode byte (work/rgb/build/install.json).
Install order as upstream: module, the four pools -> copy, THEN the count
16 -> 17 (revert: count first). Needs the RGB build installed (else the
row switches a byte nothing reads).

    utility_mk1.py build     -> work/utility/build/ut.bin + ut.syms
    utility_mk1.py emu       qemu test from rgb_main (3band stick), log in
                             work/logs/utility_emu.log, shots in work/utility/shots/
"""
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shbuild                                                 # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
UT, MOD = MODEL["utility_table"], MODEL["utility_module"]
RGB = json.load(open(os.path.join(ROOT, "work", "rgb", "build", "install.json")))
OUT = os.path.join(ROOT, "work", "utility", "build")
H = lambda k: int(UT[k], 16)
TAB, COUNT, NSTOCK, REC = H("ram_table"), H("count"), UT["stock_rows"], UT["rec_size"]
POOLS = [int(p, 16) for p in UT["pools"]]
BASE, END_MAX = int(MOD["addr"], 16), int(MOD["end_max"], 16)
NOURS = 2


def build():
    import phasemeter_mk1 as PM
    pimg, psyms = PM.build()
    # "meter installed" = the entry stub's literal holding pm_hook's address
    # (unique to this build) is in RAM
    sig_off = next(o for o in range(0, 0x40, 4) if struct.unpack_from("<I", pimg, o)[0] == psyms["pm_hook"])
    d = dict(NSTOCK=NSTOCK, MODEB=int(RGB["mode_addr"], 16), PM_BASE=PM.BASE + sig_off,
             PM_SIG=psyms["pm_hook"], PM_MODE=psyms["pm_mode"],
             **{k.upper(): H(k) for k in ("cb_nop", "cb_draw", "cb_begin", "cb_sel", "cb_q0", "cb_end")})
    src = os.path.join(HERE, "utility")
    img, syms = shbuild.build(OUT, "ut", [os.path.join(src, "utentry.S"), os.path.join(src, "ut_mk1.c")],
                              BASE, END_MAX, d, "_ut_head", keep=("_ut_", "_end"))
    assert syms["ut_head"] == BASE, syms
    return img, syms


def image(stock):
    """module bytes with the 16 stock records (read from the deck's RAM) copied in"""
    img, s = build()
    assert len(stock) == NSTOCK * REC
    off = s["ut_tab"] - BASE
    b = bytearray(img)
    b[off:off + NSTOCK * REC] = stock
    return bytes(b), s


def install(E, model, stock=None):
    """module (with the deck's 16 stock records copied in), its bss zeroed,
    the four pools -> the copy, THEN the count (revert: count first)"""
    if stock is None:
        stock = E.peek(model, TAB, NSTOCK * REC)
    img, s = image(stock)
    blob = os.path.join(OUT, "ut_installed.bin")
    open(blob, "wb").write(img)
    E.step(model, "fill %#x %#x 0" % (BASE + len(img), s["end"] - BASE - len(img)))
    E.step(model, "load %#x %s" % (BASE, blob))
    for a in POOLS:
        E.step(model, "poke32 %#x %#x" % (a, s["ut_tab"]))
    E.step(model, "poke32 %#x %#x" % (COUNT, NSTOCK + NOURS))
    return s


def emu():
    sys.path.insert(0, HERE)
    import emu as E
    import rgb_mk1
    model = "xdj1000"
    shots = os.path.join(ROOT, "work", "utility", "shots")
    os.makedirs(shots, exist_ok=True)
    stick = os.path.join(ROOT, "work", "testusb", "3band_usb.img")
    p = E.start(model, incoming=os.path.join(E.WORK, model, "rgb_main.vm"), stick=stick)
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def rd(a, n):
        return E.peek(model, a, n)

    def mode():
        return rd(int(RGB["mode_addr"], 16), 1)[0]

    def sym32(name):
        return struct.unpack("<I", rd(s[name], 4))[0]

    try:
        for _ in range(240):
            if "running" in E.cmd(model, "info status"):
                break
            time.sleep(0.25)
        time.sleep(2)
        # stock state: table/count/pools as the model table says
        stock = rd(TAB, NSTOCK * REC)
        img_tab = open(os.path.join(ROOT, "work", "MAIN_mk1_113.img"), "rb").read()
        it = int(UT["image_table"], 16) - 0x08000000
        ok &= chk("RAM table == image table (callbacks/flags of 16 rows)", all(
            stock[k * REC + 8:k * REC + 12] == img_tab[it + k * REC + 8:it + k * REC + 12] and
            stock[k * REC + 20:k * REC + 52] == img_tab[it + k * REC + 20:it + k * REC + 52]
            for k in range(NSTOCK)))
        ok &= chk("count == 16", struct.unpack("<I", rd(COUNT, 4))[0] == NSTOCK)
        ok &= chk("pools -> table", all(struct.unpack("<I", rd(a, 4))[0] == TAB for a in POOLS))
        ok &= chk("module area empty", rd(BASE, END_MAX - BASE) == bytes(END_MAX - BASE))
        # RGB build (mode RGB), then the utility module, pools, count
        for st in rgb_mk1.install_script(1).split("; "):
            E.step(model, st)
        s = install(E, model, stock)
        time.sleep(1)
        E.shot(model, os.path.join(shots, "a_main_rgb.png"))
        E.step(model, "tap 568 37 1500")             # hold MENU = UTILITY
        time.sleep(3)
        E.shot(model, os.path.join(shots, "b_utility_top.png"))
        E.step(model, "rot 20")                      # to the end of the list
        time.sleep(2)
        E.shot(model, os.path.join(shots, "c_utility_end.png"))
        ok &= chk("our rows drawn", sym32("ut_draws") > 0)
        # last row = PHASE METER: no meter installed here -> NOT INSTALLED, no commit
        E.step(model, "key 0x11:0x01:300")
        time.sleep(1.5)
        E.step(model, "rot 1")
        time.sleep(1)
        E.step(model, "key 0x11:0x01:300")
        time.sleep(2)
        E.shot(model, os.path.join(shots, "c2_pm_not_installed.png"))
        ok &= chk("PHASE METER without the meter: no commit", sym32("ut_commits") == 0)
        E.step(model, "rot -1")                      # up to WAVEFORM COLOR
        time.sleep(1.5)
        print("draws", sym32("ut_draws"), "mode", mode(), flush=True)
        for want, tag in ((2, "3band"), (0, "blue"), (1, "rgb")):
            E.step(model, "key 0x11:0x01:300")       # push: edit
            time.sleep(1.5)
            E.step(model, "rot %d" % (want - mode()))   # the stock editor clamps, no wrap
            time.sleep(1.5)
            E.shot(model, os.path.join(shots, "d_edit_%s.png" % tag))
            E.step(model, "key 0x11:0x01:300")       # push: commit
            time.sleep(2)
            E.shot(model, os.path.join(shots, "e_done_%s.png" % tag))
            ok &= chk("WAVEFORM COLOR -> %s (mode byte %d)" % (tag, mode()), mode() == want)
        print("commits", sym32("ut_commits"), flush=True)
        ok &= chk("3 commits", sym32("ut_commits") == 3)
        E.step(model, "key 0x11:0x01:300")           # push + no turn + push: no change
        time.sleep(1.5)
        E.step(model, "key 0x11:0x01:300")
        time.sleep(2)
        ok &= chk("unchanged choice: no commit", sym32("ut_commits") == 3 and mode() == 1)
        E.step(model, "tap 568 37 300")              # leave UTILITY
        time.sleep(3)
        E.shot(model, os.path.join(shots, "f_main_after.png"))
        ok &= chk("pools still -> copy, count %d" % (NSTOCK + NOURS),
                  all(struct.unpack("<I", rd(a, 4))[0] == s["ut_tab"] for a in POOLS)
                  and struct.unpack("<I", rd(COUNT, 4))[0] == NSTOCK + NOURS)
        ok &= chk("deck alive (status running)", "running" in E.cmd(model, "info status"))
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
