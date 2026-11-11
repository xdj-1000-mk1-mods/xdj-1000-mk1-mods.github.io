#!/usr/bin/env python3
"""qemu, two linked MK1 decks: which files does a deck open for a LINK load?

Research for colour-over-LINK and mods-over-LINK (2026-11-10). Deck A
(EMU_SLOT=1, stock) serves work/testusb/multi; deck B (EMU_SLOT=0, enabler
image + mods stick) loads track 2 over LINK and plays it. Breakpoints on B at
the firmware's file opens (models file_api fopen_w, wide path in r4;
stick_mount_check open wrapper, ASCII path in r4) log every path, with the
caller (pr). Also dumps the drive table (stick_mount_check: 12-byte entries
at 0x0f2d80c0 + letter*12) before and after.

    link_files_emu.py          -> work/link2/files.txt (+ summary)
"""
import collections
import os
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402

FOPEN_W, OPEN_R = 0x08D8611C, 0x08B78F00
DRV_TAB = 0x0F2D80C0


def main():
    os.makedirs(LR.OUT, exist_ok=True)
    img = LR.b_stick(os.path.join(ROOT, "work", "mods_all", "MODS2.BIN"))
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log")),
             LR.run(0, "boot", "xdj1000", "--stick", img, "--kernel", LR.KERNEL, bg=True,
                    log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek("xdj1000", a, 4))[0]
    hits, out = [], open(os.path.join(LR.OUT, "files.txt"), "w")
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(5)
            try:
                if u32(0x099EFF04) == 0x454E4F44:
                    break
            except Exception:
                pass
        time.sleep(15)
        drv0 = E.peek("xdj1000", DRV_TAB + 0x40 * 12, 0x3B * 12)          # 'A'..'z'
        g = E.Gdb("xdj1000")
        g.s.settimeout(None)
        for a in (FOPEN_W, OPEN_R):
            assert g.req("Z0,%x,2" % a) == "OK"
        done = threading.Event()

        def nav():
            for s in ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2,
                      "key 0x11:0x01:300", 25, "key 0x10:0x01:300", 8, "key 0x10:0x01:300", 3):
                E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s)
            done.set()

        th = threading.Thread(target=nav, daemon=True)
        g.cont()
        th.start()
        g.s.settimeout(1.0)
        while not done.is_set():
            try:
                g._read_packet()                                   # stop reply (breakpoint)
            except (TimeoutError, OSError):
                continue
            regs = bytes.fromhex(g.req("g"))
            r = struct.unpack_from("<16I", regs, 0)
            pc, pr = struct.unpack_from("<II", regs, 64)
            raw = g.rd(r[4], 192)
            if pc == FOPEN_W:
                path = raw.decode("utf-16le", "replace").split("\0")[0]
                mode = g.rd(r[5], 4).split(b"\0")[0].decode("latin1", "replace") if 0x08000000 <= r[5] < 0x10000000 or r[5] >= 0xA8000000 else "?"
            else:
                path, mode = raw.split(b"\0")[0].decode("latin1", "replace"), "r"
            hits.append((time.time(), "fopen_w" if pc == FOPEN_W else "open_r", path, mode, pr))
            out.write("%.2f %-7s %-3s pr=%#010x %s\n" % (time.time() - t0, hits[-1][1], mode, pr, path))
            out.flush()
            g.req("z0,%x,2" % pc)                      # step over the breakpoint, re-arm, run on
            g.s.settimeout(10)
            g.req("s")
            g.s.settimeout(1.0)
            g.req("Z0,%x,2" % pc)
            g.cont()
        g.s.settimeout(10)
        g.stop()
        for a in (FOPEN_W, OPEN_R):
            g.req("z0,%x,2" % a)
        g.detach()
        drv1 = E.peek("xdj1000", DRV_TAB + 0x40 * 12, 0x3B * 12)
        E.shot("xdj1000", os.path.join(LR.OUT, "files_link.png"))
    finally:
        for slot in (0, 1):
            LR.run(slot, "cmd", "xdj1000", "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    c = collections.Counter((h[1], h[2].rsplit("/", 1)[0] if "/" in h[2] else h[2], h[4]) for h in hits)
    print("%d opens" % len(hits))
    for (fn, d, pr), n in c.most_common(25):
        print("  %3d %-7s pr=%#010x %s" % (n, fn, pr, d))
    for i in range(0x3B):
        a, b = drv0[12 * i:12 * i + 12], drv1[12 * i:12 * i + 12]
        if a.strip(b"\0") or b.strip(b"\0"):
            print("  drive %r: before %s after %s" % (chr(0x40 + i), a.hex(), b.hex()))


if __name__ == "__main__":
    main()
