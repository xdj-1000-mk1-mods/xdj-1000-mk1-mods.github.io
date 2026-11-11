#!/usr/bin/env python3
"""qemu, two linked MK1 decks: how does the firmware READ a file on the linked
player's stick (D:)? Deck B stops at the LINK audio fopen_w, runs to its
return (pr) for the handle, then logs every fread_c / fclose_c (and the first
words of the handle object) while the track loads and plays: caller, fp,
size, count, desc, return value and the first bytes read.

    link_read_emu.py         -> work/link2/reads.txt + summary
"""
import os
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402

FOPEN_W, FREAD_C, FCLOSE_C = 0x08D8611C, 0x08D86876, 0x08D86572


def main():
    img = LR.b_stick(os.path.join(ROOT, "work", "mods_all", "MODS2.BIN"))
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log")),
             LR.run(0, "boot", "xdj1000", "--stick", img, "--kernel", LR.KERNEL, bg=True,
                    log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek("xdj1000", a, 4))[0]
    out = open(os.path.join(LR.OUT, "reads.txt"), "w")
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
        g = E.Gdb("xdj1000")
        regs = lambda: bytes.fromhex(g.req("g"))
        R = lambda b: list(struct.unpack_from("<16I", b, 0)) + list(struct.unpack_from("<II", b, 64))
        done = threading.Event()

        def nav():
            for s in ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2,
                      "key 0x11:0x01:300", 25, "key 0x10:0x01:300", 6, "key 0x10:0x01:300", 2):
                E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s)
            done.set()

        def step_over(pc):
            g.req("z0,%x,2" % pc)
            g.s.settimeout(10)
            g.req("s")
            g.req("Z0,%x,2" % pc)

        def wait():
            g.s.settimeout(1.0)
            while not done.is_set():
                try:
                    g._read_packet()
                    return True
                except (TimeoutError, OSError):
                    continue
            return False

        assert g.req("Z0,%x,2" % FOPEN_W) == "OK"
        threading.Thread(target=nav, daemon=True).start()
        g.cont()
        fp = None
        while wait():
            r = R(regs())
            if r[16] == FOPEN_W and fp is None:
                path = g.rd(r[4], 160).decode("utf-16le", "replace").split("\0")[0]
                ret = r[17]
                g.req("z0,%x,2" % FOPEN_W)
                assert g.req("Z0,%x,2" % ret) == "OK"
                g.cont()
                wait()
                fp = R(regs())[0]
                g.req("z0,%x,2" % ret)
                out.write("open %s -> fp %#x  desc %#x; handle %s\n" % (path, fp, r[6], g.rd(fp, 32).hex()))
                for a in (FREAD_C, FCLOSE_C):
                    g.req("Z0,%x,2" % a)
                g.cont()
                continue
            if r[16] == FREAD_C:
                desc = struct.unpack("<I", g.rd(r[15], 4))[0]
                mine = r[7] == fp
                ret = r[17]
                step_over(FREAD_C)
                if mine:                                       # run to the return for the result
                    g.req("Z0,%x,2" % ret)
                    g.cont()
                    wait()
                    n = R(regs())[0]
                    g.req("z0,%x,2" % ret)
                    data = g.rd(r[4], 16) if 0 < n * r[5] else b""
                    out.write("%.1f fread fp %#x size %d count %d desc %#x pr %#x -> %d  %s\n"
                              % (time.time() - t0, r[7], r[5], r[6], desc, ret, n, data.hex()))
                else:
                    out.write("%.1f fread (other fp %#x) pr %#x\n" % (time.time() - t0, r[7], ret))
            elif r[16] == FCLOSE_C:
                out.write("%.1f fclose fp %#x desc %#x pr %#x\n" % (time.time() - t0, r[4], r[5], r[17]))
                step_over(FCLOSE_C)
            else:
                step_over(r[16])
            out.flush()
            g.cont()
        g.s.settimeout(10)
        g.stop()
        for a in (FOPEN_W, FREAD_C, FCLOSE_C):
            g.req("z0,%x,2" % a)
        g.detach()
    finally:
        for slot in (0, 1):
            LR.run(slot, "cmd", "xdj1000", "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    lines = open(os.path.join(LR.OUT, "reads.txt")).read().splitlines()
    print(len(lines), "lines")
    for l in lines[:25]:
        print(" ", l[:200])


if __name__ == "__main__":
    main()
