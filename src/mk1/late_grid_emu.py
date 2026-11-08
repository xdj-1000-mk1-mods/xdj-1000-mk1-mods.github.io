#!/usr/bin/env python3
"""qemu: the phase meter takes a beat grid that lands in the deck table AFTER
the track's preview (real deck, LINK load, 2026-11-08: pm_n stayed 0).
State 'perform' (USB track loaded), meter installed; the deck table's valid +
count words are cleared and the USB ctx pointer hidden (= a LINK load before
its grid arrives) -> no grid; then put back -> grid taken from the table."""
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("EMU_SLOT", "2")
import emu as E                                                 # noqa: E402
import phasemeter_mk1 as PM                                     # noqa: E402

M = "xdj1000"


def main():
    img, s = PM.build()
    g = PM.E_["deck_grid"]
    VALID, COUNT, CTX = int(g["valid"], 16), int(g["count"], 16), int(PM.E_["anlz_ctx_table"]["addr"], 16)
    p = E.start(M, incoming=os.path.join(E.WORK, M, "perform.vm"))
    u32 = lambda a: struct.unpack("<I", E.peek(M, a, 4))[0]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("ok   " if good else "FAIL ") + label, flush=True)
        ok &= bool(good)

    try:
        for _ in range(240):
            if "running" in E.cmd(M, "info status"):
                break
            time.sleep(0.25)
        time.sleep(2)
        v, n, c = u32(VALID), u32(COUNT), u32(CTX)
        chk("stock state: table valid %d count %d, ctx %#x" % (v, n, c), v == 1 and n > 1 and c)
        for a, x in ((VALID, 0), (COUNT, 0), (CTX, 0)):            # a LINK load, grid not here yet
            E.step(M, "poke32 %#x %#x" % (a, x))
        for st in PM.install_steps(s, u32(PM.HOOK)):
            E.step(M, st)
        time.sleep(3)
        chk("before the grid: drawing (%d), no grid (n %d)" % (u32(s["pm_draws"]), u32(s["pm_n"])),
            u32(s["pm_draws"]) > 5 and u32(s["pm_n"]) == 0)
        E.step(M, "poke32 %#x %#x" % (COUNT, n))                   # the grid lands (count, then valid)
        E.step(M, "poke32 %#x 1" % VALID)
        time.sleep(3)
        chk("grid landed later: taken from the deck table (src %d, n %d of %d)"
            % (u32(s["pm_src"]), u32(s["pm_n"]), n), u32(s["pm_src"]) == 1 and u32(s["pm_n"]) == n)
        E.shot(M, os.path.join(E.WORK, "late_grid.png"))
        E.step(M, "poke32 %#x %#x" % (CTX, c))
        chk("deck running", "running" in E.cmd(M, "info status"))
    finally:
        try:
            E.cmd(M, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
