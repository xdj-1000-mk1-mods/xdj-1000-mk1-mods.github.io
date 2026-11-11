#!/usr/bin/env python3
"""qemu, two linked MK1 decks: can the task that mounts the linked drive read
a file from it? mk1/linkprobe/mount.c on the LINK code's set-drive-type pool
word (0x08cfdc54), installed into paused deck B before it runs. Pass: stage 4,
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
POOL, STOCK = 0x08CFDC54, 0x08D88FE4
DEV = os.path.join(ROOT, "work", "testusb", "multi", "device")


def main(av):
    name = av[0] if av else "PIONEER/rekordbox/export.pdb"
    want = open(os.path.join(DEV, name), "rb").read()[:512] if os.path.exists(os.path.join(DEV, name)) else None
    src, out = os.path.join(HERE, "linkprobe"), os.path.join(ROOT, "work", "linkprobe")
    os.makedirs(out, exist_ok=True)
    img, s = shbuild.build(out, "mount", [os.path.join(src, "mount.S"), os.path.join(src, "mount.c")], BASE, END,
                           dict(STOCK_SET=STOCK, FOPEN_W=0x08D8611C, FREAD_C=0x08D86876, FCLOSE_C=0x08D86572),
                           "_mnt_head", keep=("_mnt_", "_end"))
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", "xdj1000", "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log"))]
    time.sleep(60)
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    import loader_mk1 as LD
    E = emu_link.E
    M, ST = "xdj1000", s["mnt_st"]
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
        g.wr(POOL, struct.pack("<I", s["mnt_hook"]))
        g.detach()                                            # detach = run
        E.cmd(M, "cont")
        time.sleep(150)
        v = struct.unpack("<11I", E.peek(M, ST, 44))
        data = E.peek(M, ST + 44 + 64, 512)
        print("    calls %d drive %r type %d rdrive %r ip %#x stage %d fp %#x n %#x done %d first %s"
              % (v[2], chr(v[3] & 0xFF), v[4], chr(v[5] & 0xFF), v[6], v[7], v[8], v[9], v[10], data[:16].hex()), flush=True)
        chk("hook ran for the linked drive (type 5)", v[2] >= 1 and v[4] == 5)
        if want is not None:
            chk("%s read in the link-mount task: stage %d, %#x B, equal to deck A's file" % (name, v[7], v[9]),
                v[7] == 4 and v[9] == 512 and data == want)
        else:
            chk("missing file: stage %d fp %#x n %#x (told apart)" % (v[7], v[8], v[9]), v[7] == 4 and (v[8] == 0 or v[9] != 512))
        for st in ("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2, "key 0x11:0x01:300", 25):
            E.step(M, st) if isinstance(st, str) else time.sleep(st)
        E.shot(M, os.path.join(LR.OUT, "mount_after.png"))
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
