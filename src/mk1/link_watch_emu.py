#!/usr/bin/env python3
"""qemu, two linked MK1 decks: who writes the linked stick's drive-table entry?
(models link_drive: entry 'd' at 0x0f2d80c0 + 0x64*12.) Deck B starts paused
with a gdb write watchpoint on the 12-byte entry; every hit is logged with
pc, pr, r0-r7 and the entry's bytes, while deck A (already up) is on the link.

    link_watch_emu.py [SECONDS]     -> work/link2/watch.txt + summary by pc
"""
import collections
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402

ENTRY = 0x0F2D80C0 + 0x64 * 12


def main(av):
    secs = float(av[0]) if av else 170
    os.makedirs(LR.OUT, exist_ok=True)
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log"))]
    time.sleep(60)                                             # deck A up and announcing first
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    p = E.start("xdj1000", stick=LR.A_STICK, paused=True)
    hits, out = [], open(os.path.join(LR.OUT, "watch.txt"), "w")
    try:
        g = E.Gdb("xdj1000")
        r = g.req("Z2,%x,c" % ENTRY)
        print("watchpoint:", r, flush=True)
        g.cont()
        t0 = time.time()
        g.s.settimeout(2.0)
        while time.time() - t0 < secs and len(hits) < 400:
            try:
                stop = g._read_packet()
            except (TimeoutError, OSError):
                continue
            regs = bytes.fromhex(g.req("g"))
            rr = struct.unpack_from("<16I", regs, 0)
            pc, pr = struct.unpack_from("<II", regs, 64)
            ent = g.rd(ENTRY, 12)
            hits.append((pc, pr))
            out.write("%.1f %s pc=%#010x pr=%#010x r0-7=%s entry=%s\n" % (
                time.time() - t0, stop[:24], pc, pr, " ".join("%08x" % x for x in rr[:8]), ent.hex()))
            out.flush()
            g.cont()
        g.s.settimeout(10)
        g.stop()
        g.req("z2,%x,c" % ENTRY)
        final = g.rd(ENTRY, 12)
        g.detach()
        print("entry at the end:", final.hex())
    finally:
        try:
            E.cmd("xdj1000", "quit")
        except OSError:
            pass
        LR.run(1, "cmd", "xdj1000", "quit")
        p.wait(timeout=60)
        for q in procs:
            q.terminate()
    c = collections.Counter(hits)
    print(len(hits), "hits")
    for (pc, pr), n in c.most_common(15):
        print("  %4d pc=%#010x pr=%#010x" % (n, pc, pr))


if __name__ == "__main__":
    main(sys.argv[1:])
