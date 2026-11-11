#!/usr/bin/env python3
"""qemu, two linked MK1 decks: real-code probe of file access to the linked
stick (mk1/linkprobe/probe.c on the audio read slot of deck B, stock image).
Run 1 (control): B plays a track from its OWN stick, probe reads
C:/PIONEER/rekordbox/export.pdb. Run 2: B plays a track over LINK, probe
reads D:/PIONEER/rekordbox/export.pdb (deck A's stick) and then a missing
D: file. Pass: both export.pdb reads return 512 B equal to the host file.

    link_probe_emu.py
"""
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402
import shbuild                                                  # noqa: E402

BASE, END = 0x09A60000, 0x09A70000
SLOT, STOCK = 0x08D86BB4, 0x08C06B60
PDB = os.path.join(ROOT, "work", "testusb", "multi", "device", "PIONEER", "rekordbox", "export.pdb")


def main():
    src = os.path.join(HERE, "linkprobe")
    out = os.path.join(ROOT, "work", "linkprobe")
    os.makedirs(out, exist_ok=True)
    img, s = shbuild.build(out, "probe", [os.path.join(src, "probe.S"), os.path.join(src, "probe.c")], BASE, END,
                           dict(STOCK_FREAD=STOCK, FOPEN_W=0x08D8611C, FREAD_C=0x08D86876, FCLOSE_C=0x08D86572),
                           "_probe_head", keep=("_probe_", "_end"))
    blob = os.path.join(out, "probe.bin")
    pdb = open(PDB, "rb").read()
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log")),
             LR.run(0, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    M = "xdj1000"
    u32 = lambda a: struct.unpack("<I", E.peek(M, a, 4))[0]
    ST = s["probe_st"]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    def steps(*ss):
        for x in ss:
            E.step(M, x) if isinstance(x, str) else time.sleep(x)

    def arm(path):
        g = E.Gdb(M)
        g.wr(ST + 4, bytes(4 * 24))                              # arm..busy_hits
        g.wr(ST + 100, (path + "\0").encode("utf-16le"))
        g.wr(ST + 100 + 192, bytes(512))
        g.wr(ST + 4, struct.pack("<I", 1))
        g.detach()

    def result(label, want):
        v = struct.unpack("<24I", E.peek(M, ST + 4, 96))
        arm_, calls, phase, fp, opened, tries = v[:6]
        n, at = v[6:14], v[14:22]
        data = E.peek(M, ST + 100 + 192, 512)
        print("    %s: calls %d phase %d fp %#x opened@%d tries %d n %s at %s busy_hits %d"
              % (label, calls, phase, fp, opened, tries, [hex(x) for x in n[:tries]], list(at[:tries]), v[23]), flush=True)
        good = phase == 2 and tries and n[tries - 1] == 512 and data == want[:512]
        return good, phase, n[:tries]

    try:
        time.sleep(100)
        import loader_mk1 as LD
        assert u32(SLOT) == STOCK, hex(u32(SLOT))
        steps("load %#x %s" % (BASE, blob), "poke32 %#x %#x" % (SLOT, s["probe_fread"]),
              "poke32 0x08d06c98 %#x" % s["probe_fread"])
        arm("C:/PIONEER/rekordbox/export.pdb")                 # armed BEFORE the load: the deck reads ahead at load
        steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 20)
        print("    local track len %d" % u32(LD.TRACK_LEN), flush=True)
        g1 = result("control C:", pdb)
        chk("control: own stick export.pdb read from inside the read path (512 B, equal)", g1[0])
        arm("D:/PIONEER/rekordbox/export.pdb")
        steps("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2, "key 0x11:0x01:300", 25)
        print("    LINK track len %d" % u32(LD.TRACK_LEN), flush=True)
        g2 = result("LINK D:", pdb)
        chk("LINK: deck A's export.pdb read over D: (512 B, equal)", g2[0])
        arm("D:/NOSUCHFILE.BIN")
        steps("rot 1", 2, "key 0x11:0x01:300", 25)                # next track, still over LINK
        g3 = result("LINK missing", b"\xff" * 512)
        chk("LINK: missing file is told apart (phase %d, n %s)" % (g3[1], [hex(x) for x in g3[2]]), not g3[0])
        chk("deck B running", "running" in E.cmd(M, "info status"))
    finally:
        for slot in (0, 1):
            LR.run(slot, "cmd", "xdj1000", "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
