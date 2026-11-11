#!/usr/bin/env python3
"""qemu, two linked MK1 decks: colour + 3-band waveform data for a track loaded
over LINK (mk1/lnk/lnk.c). Deck A (stock) serves work/testusb/multi; deck B
(enabler image, mods from its own stick) loads:
  1. a track from its own stick      -> its own colour data (LINK_FLAG 0)
  2. a track over LINK from A        -> slots = that track's PWV5 / PWV7 from A's
                                        ANLZ files, byte for byte; LINK_FLAG 1;
                                        the centre painter accepted it
  3. its own track again             -> own colour data, LINK_FLAG 0
  4. the next track over LINK        -> that track's data

    link_colour_emu.py [MODS2.BIN]
"""
import glob
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402

SLOT5, SLOT7, FLAG = 0x09814000, 0x09900000, 0x099EFFF0
M = "xdj1000"


def sections(path):
    d = open(path, "rb").read()
    o, out = struct.unpack(">I", d[4:8])[0], {}
    while o + 12 <= len(d):
        tl = struct.unpack(">I", d[o + 8:o + 12])[0]
        out[d[o:o + 4].decode("latin1")] = d[o:o + tl]
        o += tl
    return out


def host_tracks():
    """count of PWV5 entries -> (name, PWV5 section, PWV7 section) for deck A's stick"""
    out = {}
    for ext in glob.glob(os.path.join(LR.EXPORT, "PIONEER", "USBANLZ", "*", "*", "ANLZ0000.EXT")):
        s5 = sections(ext).get("PWV5")
        s7 = sections(ext[:-3] + "2EX").get("PWV7")
        out[struct.unpack(">I", s5[16:20])[0]] = (os.path.relpath(ext, LR.EXPORT), s5, s7)
    return out


def main(av):
    mods2 = os.path.abspath(av[0]) if av else os.path.join(ROOT, "work", "mods_all", "MODS2.BIN")
    host = host_tracks()
    img = LR.b_stick(mods2)
    nm = subprocess.run([os.path.join(ROOT, "work", "sh-tools", "bin", "sh-elf-nm"),
                         os.path.join(ROOT, "work", "rgb", "build", "centre", "cw.elf")], capture_output=True, text=True).stdout
    cw = {l.split()[2].lstrip("_"): int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
    procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
             LR.run(1, "boot", M, "--stick", LR.A_STICK, bg=True, log=os.path.join(LR.OUT, "deckA.log")),
             LR.run(0, "boot", M, "--stick", img, "--kernel", LR.KERNEL, bg=True, log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    import loader_mk1 as LD
    import lnk_mk1 as LK
    _, ls = LK.build()
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek(M, a, 4))[0]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    def steps(*ss):
        for s in ss:
            E.step(M, s) if isinstance(s, str) else time.sleep(s)

    def slot(a, n):
        g = E.Gdb(M)
        try:
            return b"".join(g.rd(a + o, min(0x800, n - o)) for o in range(0, n, 0x800))
        finally:
            g.detach()

    def link_check(label, shot):
        tl = u32(LD.TRACK_LEN)
        st = struct.unpack("<11I", E.peek(M, ls["lnk_st"], 44))
        n5 = struct.unpack(">I", E.peek(M, SLOT5 + 16, 4))[0]
        E.shot(M, os.path.join(LR.OUT, shot))
        print("    %s: track len %d, flag %d, lnk opens %d (D: %d) fetches %d status %d pages %d got 4/5/6/7 %s, "
              "PWV5 entries %d, guard link %d" % (label, tl, u32(FLAG), st[1], st[2], st[3], st[4], st[5], st[6:10], n5,
                                                  u32(cw["cw_guard_link"])), flush=True)
        t = host.get(n5)
        chk("%s: LINK track loaded, colour data fetched (flag 1, status OK)" % label, tl and u32(FLAG) == 1 and st[4] == 1)
        chk("%s: data is deck A's track with that length (%s)" % (label, t and t[0]), t and abs(n5 - tl) <= tl // 50 + 150)
        if t:
            chk("%s: PWV5 (colour) in the slot == A's file, %d B" % (label, len(t[1])), slot(SLOT5, len(t[1])) == t[1])
            chk("%s: PWV7 (3-band) in the slot == A's file, %d B" % (label, len(t[2])), slot(SLOT7, len(t[2])) == t[2])
        chk("%s: the centre painter accepted the LINK data" % label, u32(cw["cw_guard_link"]) > 0)
        return n5

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
        steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 15)
        l1, n1 = u32(LD.TRACK_LEN), struct.unpack(">I", E.peek(M, SLOT5 + 16, 4))[0]
        chk("1. own stick: track len %d, own colour data (%d entries), flag %d" % (l1, n1, u32(FLAG)),
            l1 and abs(n1 - l1) < 200 and u32(FLAG) == 0)
        t1 = time.time()
        steps("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2, "key 0x11:0x01:300", 30)
        na = link_check("2. LINK", "colour_2_link.png")
        chk("2. LINK: a different track than step 1", na != n1)
        steps("key 0x13:0x04:300", 8, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 20)
        l3, n3 = u32(LD.TRACK_LEN), struct.unpack(">I", E.peek(M, SLOT5 + 16, 4))[0]
        E.shot(M, os.path.join(LR.OUT, "colour_3_local.png"))
        chk("3. own stick again: len %d, own colour data (%d entries), flag %d" % (l3, n3, u32(FLAG)),
            l3 == l1 and n3 == n1 and u32(FLAG) == 0 and u32(SLOT5) != 0)
        steps("tap 55 197 300", 8, "rot 1", 2, "key 0x11:0x01:300", 30)
        nb = link_check("4. LINK next track", "colour_4_link.png")
        chk("4. another track than step 2", nb != na)
        chk("deck B running", "running" in E.cmd(M, "info status"))
    finally:
        for sl in (0, 1):
            LR.run(sl, "cmd", M, "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main(sys.argv[1:])
