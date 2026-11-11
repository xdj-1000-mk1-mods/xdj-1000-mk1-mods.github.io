#!/usr/bin/env python3
"""qemu, two linked MK1 decks: is a D: (linked stick) open asynchronous?
Phase 1: at the LINK audio fopen_w (media task) open our own paths (the
remote export.pdb, a missing file) with the media task's descriptor, restore,
run on. Phase 2: when the reader task reads the audio (fread_c, pr 0x08bfa3e2)
read OUR handles there with the reader's descriptor. Pass: export.pdb gives
its real first bytes, the missing file gives an error/0, deck B carries on.

    link_async_emu.py
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
SCR = 0x09A70000
TRAP = SCR + 0xFF00
EXPORT = os.path.join(ROOT, "work", "testusb", "multi", "device")


class Hijack:
    """call firmware functions from a stopped task through the gdbstub"""
    def __init__(self, g):
        self.g = g

    def regs(self):
        return bytearray(bytes.fromhex(self.g.req("g")))

    def call(self, base, fn, args, stack=()):
        g, b = self.g, bytearray(base)
        r15 = struct.unpack_from("<I", base, 60)[0]
        sp = r15 - 128 - 4 * len(stack)
        for i, v in enumerate(args):
            struct.pack_into("<I", b, 4 * (4 + i), v)
        struct.pack_into("<I", b, 60, sp)
        struct.pack_into("<II", b, 64, fn, TRAP)
        if stack:
            g.wr(sp, struct.pack("<%dI" % len(stack), *stack))
        assert g.req("G" + b.hex()) == "OK"
        assert g.req("Z0,%x,2" % TRAP) == "OK"
        g.cont()
        g.s.settimeout(60)
        g._read_packet()
        g.req("z0,%x,2" % TRAP)
        out = bytes.fromhex(g.req("g"))
        return struct.unpack_from("<I", out, 0)[0], struct.unpack_from("<I", out, 64)[0]


def main():
    pdb = open(os.path.join(EXPORT, "PIONEER", "rekordbox", "export.pdb"), "rb").read()
    img = LR.b_stick(os.path.join(ROOT, "work", "mods_all", "MODS2.BIN"))
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log")),
             LR.run(0, "boot", "xdj1000", "--stick", img, "--kernel", LR.KERNEL, bg=True,
                    log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    import loader_mk1 as LD
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek("xdj1000", a, 4))[0]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

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
        H = Hijack(g)
        g.s.settimeout(None)
        assert g.req("Z0,%x,2" % FOPEN_W) == "OK"
        threading.Thread(target=lambda: [E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s) for s in
                                         ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6,
                                          "rot 1", 2, "key 0x11:0x01:300")], daemon=True).start()
        g.cont()
        g.s.settimeout(180)
        g._read_packet()
        base = H.regs()
        r = struct.unpack_from("<16I", base, 0)
        g.req("z0,%x,2" % FOPEN_W)
        g.wr(SCR + 0x100, b"r\0\0\0")
        fps = {}
        for name, path in (("pdb", "D:/PIONEER/rekordbox/export.pdb"), ("none", "D:/NOSUCHFILE.BIN")):
            g.wr(SCR + 0x200 * (1 + len(fps)), (path + "\0").encode("utf-16le"))
            fps[name], at = H.call(base, FOPEN_W, (SCR + 0x200 * len(fps), SCR + 0x100, r[6]))
        print("  opened in the media task: %s" % {k: hex(v) for k, v in fps.items()}, flush=True)
        assert g.req("G" + base.hex()) == "OK"               # the original audio open runs on
        assert g.req("Z0,%x,2" % FREAD_C) == "OK"
        g.cont()
        hits = 0
        while True:                                          # wait for the reader task's audio reads
            g.s.settimeout(120)
            g._read_packet()
            b2 = H.regs()
            r2 = struct.unpack_from("<16I", b2, 0)
            pr2 = struct.unpack_from("<I", b2, 68)[0]
            hits += 1
            if pr2 == 0x08BFA3E2 and hits > 3:
                break
            g.req("z0,%x,2" % FREAD_C); g.req("s"); g.req("Z0,%x,2" % FREAD_C); g.cont()
        g.req("z0,%x,2" % FREAD_C)
        desc = struct.unpack("<I", g.rd(r2[15], 4))[0]
        print("  handles: audio %#x %s" % (r2[7], g.rd(r2[7], 48).hex()), flush=True)
        for name, fp in fps.items():
            print("           %s %#x %s" % (name, fp, g.rd(fp, 48).hex()), flush=True)
        g.wr(SCR + 0x1000, bytes(0x200))
        n, at = H.call(b2, FREAD_C, (SCR + 0x1000, 1, 0x200, r2[7]), stack=(desc,))
        d0 = g.rd(SCR + 0x1000, 16)
        chk("control: the firmware's own audio handle through the same injection: %#x B, %s (back at trap: %s)"
            % (n, d0.hex(), at == TRAP), n == 0x200 and any(d0))
        for name, fp in fps.items():
            n, at = H.call(b2, FREAD_C, (SCR + 0x1000, 1, 0x200, fp), stack=(desc,))
            data = g.rd(SCR + 0x1000, 16)
            if name == "pdb":
                chk("export.pdb read in the reader task: %#x B, first bytes %s (want %s)" % (n, data.hex(), pdb[:16].hex()),
                    n == 0x200 and g.rd(SCR + 0x1000, 0x200) == pdb[:0x200])
            else:
                chk("missing file read in the reader task: %#x (not 0x200)" % n, n != 0x200)
            H.call(b2, FCLOSE_C, (fp, desc))
        assert g.req("G" + b2.hex()) == "OK"
        g.s.settimeout(10)
        g.detach()
        time.sleep(25)
        chk("deck B carried on: LINK track loaded (len %d), running" % u32(LD.TRACK_LEN),
            u32(LD.TRACK_LEN) and "running" in E.cmd("xdj1000", "info status"))
    finally:
        for slot in (0, 1):
            LR.run(slot, "cmd", "xdj1000", "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
