#!/usr/bin/env python3
"""qemu, two linked MK1 decks: can the task that mounts the linked drive read
a file from it? mk1/linkprobe/aopen.c on the audio-open pool word (0x08d8b86c), installed into paused deck B before it runs. Pass: stage 4,
512 B read == deck A's export.pdb, and deck B can still browse/load over LINK.

    link_mount_emu.py [NAME]     (file on the linked stick; default export.pdb)
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
POOL, STOCK = 0x08D8B86C, 0x08D8611C
DEV = os.path.join(ROOT, "work", "testusb", "multi", "device")


def main(av):
    name = av[0] if av else "PIONEER/rekordbox/export.pdb"
    want = open(os.path.join(DEV, name), "rb").read()[:512] if os.path.exists(os.path.join(DEV, name)) else None
    src, out = os.path.join(HERE, "linkprobe"), os.path.join(ROOT, "work", "linkprobe")
    os.makedirs(out, exist_ok=True)
    img, s = shbuild.build(out, "aopen", [os.path.join(src, "aopen.S"), os.path.join(src, "aopen.c")], BASE, END,
                           dict(FOPEN_W=0x08D8611C, FREAD_C=0x08D86876, FCLOSE_C=0x08D86572),
                           "_ao_head", keep=("_ao_", "_end"))
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log"))]
    time.sleep(60)
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    import loader_mk1 as LD
    E = emu_link.E
    M, ST = "xdj1000", s["ao_st"]
    p = E.start(M, stick=LR.A_STICK, paused=True)
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    try:
        g = E.Gdb(M)
        assert struct.unpack("<I", g.rd(POOL, 4))[0] == STOCK
        for o in range(0, len(img), 0x200):
            g.wr(BASE + o, img[o:o + 0x200])
        g.wr(ST + 44, (name + "\0").encode().ljust(64, b"\0")[:64])
        g.wr(ST + 4, struct.pack("<I", 1))                    # mode 1: open + read in the hook
        g.wr(POOL, struct.pack("<I", s["ao_hook"]))
        g.detach()                                            # detach = run
        E.cmd(M, "cont")
        time.sleep(110)
        for st in ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2, "key 0x11:0x01:300", 30):
            E.step(M, st) if isinstance(st, str) else time.sleep(st)
        v = struct.unpack("<11I", E.peek(M, ST, 44))
        last = E.peek(M, ST + 44 + 64, 192).decode("utf-16le", "replace").split("\0")[0]
        data = E.peek(M, ST + 44 + 64 + 192, 512)
        print("    calls %d D: calls %d stage %d | caller desc %#x: fp %#x n %#x | default desc: fp %#x n %#x | last path %s"
              % (v[2], v[3], v[4], v[10], v[5], v[6], v[7], v[8], last), flush=True)
        chk("hook saw the LINK audio open", v[3] >= 1)
        if want is not None:
            chk("%s read in the media task at the audio open (512 B, equal to deck A's file)" % name,
                v[4] == 9 and 512 in (v[6], v[8]) and data == want)
        else:
            chk("missing file told apart (fp %#x / %#x)" % (v[5], v[7]), v[4] == 9 and v[6] != 512 and v[8] != 512)
        E.shot(M, os.path.join(LR.OUT, "aopen_after.png"))
        tl = struct.unpack("<I", E.peek(M, LD.TRACK_LEN, 4))[0]
        chk("deck B still loads a track over LINK (len %d), running" % tl, tl and "running" in E.cmd(M, "info status"))
    finally:
        try:
            E.cmd(M, "quit")
        except OSError:
            pass
        LR.run(1, "cmd", "xdj1000", "quit")
        p.wait(timeout=60)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main(sys.argv[1:])
