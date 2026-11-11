#!/usr/bin/env python3
"""qemu, two linked MK1 decks: can the firmware's own fopen read ANY file on
the linked player's stick (drive D:)?

link_files_emu.py showed a LINK load opens the audio as "D:/Contents/..."
through fopen_w, and the drive table entry 'd' holds the other deck's IP.
Here deck B stops at that fopen_w (the media task, the right context), and
through the gdbstub calls fopen_w / fread_c / fclose_c on other D: paths
(the remote stick's .EXT and export.pdb, and a missing file), then restores
every register and lets the original call run. Pass: existing files open and
read their real first bytes, the missing one returns 0, deck B carries on.

    link_call_emu.py
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
SCR = 0x09A70000                 # scratch (loader2 stage / .2EX buffer; idle on a LINK load)
TRAP = SCR + 0xFF00
EXPORT = os.path.join(ROOT, "work", "testusb", "multi", "device")


def main():
    ext = sorted(os.path.relpath(os.path.join(d, f), EXPORT) for d, _, fs in os.walk(EXPORT)
                 for f in fs if f == "ANLZ0000.EXT")[0]
    host = {"ext": open(os.path.join(EXPORT, ext), "rb").read(),
            "pdb": open(os.path.join(EXPORT, "PIONEER", "rekordbox", "export.pdb"), "rb").read()}
    tests = [("ext", "D:/" + ext), ("pdb", "D:/PIONEER/rekordbox/export.pdb"), ("none", "D:/NOSUCHFILE.BIN")]
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
        g.s.settimeout(None)
        assert g.req("Z0,%x,2" % FOPEN_W) == "OK"
        threading.Thread(target=lambda: [E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s) for s in
                                         ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6,
                                          "rot 1", 2, "key 0x11:0x01:300")], daemon=True).start()
        g.cont()
        g.s.settimeout(180)
        g._read_packet()                                       # first fopen_w (the LINK audio)
        saved = g.req("g")
        regs = bytearray(bytes.fromhex(saved))
        r = list(struct.unpack_from("<16I", regs, 0))
        pc, pr = struct.unpack_from("<II", regs, 64)
        orig = g.rd(r[4], 160).decode("utf-16le", "replace").split("\0")[0]
        chk("stopped at the LINK audio open: %s (pr %#x)" % (orig, pr), pc == FOPEN_W and orig.startswith("D:/"))
        g.req("z0,%x,2" % FOPEN_W)
        DESC = r[6]
        print("  desc @%#x: %s" % (DESC, g.rd(DESC, 24).hex()), flush=True)

        def call(fn, args, stack=()):
            b = bytearray(regs)
            sp = r[15] - 64 - 4 * len(stack)
            for i, v in enumerate(args):
                struct.pack_into("<I", b, 4 * (4 + i), v)
            struct.pack_into("<I", b, 4 * 15, sp)
            struct.pack_into("<II", b, 64, fn, TRAP)          # pc, pr
            if stack:
                g.wr(sp, struct.pack("<%dI" % len(stack), *stack))
            assert g.req("G" + b.hex()) == "OK"
            assert g.req("Z0,%x,2" % TRAP) == "OK"
            g.cont()
            g._read_packet()
            g.req("z0,%x,2" % TRAP)
            out = bytes.fromhex(g.req("g"))
            return struct.unpack_from("<I", out, 0)[0], struct.unpack_from("<I", out, 64)[0]

        g.wr(SCR + 0x100, b"r\0\0\0")
        for name, path in tests:
            g.wr(SCR, (path + "\0").encode("utf-16le"))
            fp, at = call(FOPEN_W, (SCR, SCR + 0x100, DESC))
            got = b""
            if fp and at == TRAP:
                n, _ = call(FREAD_C, (SCR + 0x1000, 1, 0x200, fp), stack=(DESC,))
                got = g.rd(SCR + 0x1000, min(n, 0x200)) if 0 < n <= 0x200 else b""
                call(FCLOSE_C, (fp, DESC))
            if name == "none":
                chk("missing file: fopen returns %#x" % fp, fp == 0 and at == TRAP)
            else:
                chk("%s: fopen %#x, read %d B, first bytes %s == the remote stick's file" % (path, fp, len(got),
                    got[:8].hex()), fp and got and got == host[name][:len(got)])
        assert g.req("G" + saved) == "OK"                     # the original call, untouched
        g.s.settimeout(10)
        g.detach()                                         # the VM runs on from the restored state
        time.sleep(25)
        E.shot("xdj1000", os.path.join(LR.OUT, "call_after.png"))
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
