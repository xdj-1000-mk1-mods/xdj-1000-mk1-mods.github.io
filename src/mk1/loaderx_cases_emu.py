#!/usr/bin/env python3
"""qemu: more cases for the enabler v2 (loader X). See loaderx_emu.py for the two main ones.

  badcrc   deck A's MODSX.BIN is damaged: B refuses over LINK, nothing written, deck fine
  late     B is up first (no mod files); A joins later: B installs when the link appears
  track    B has a track loaded when A joins: refused (no install mid-track), B keeps playing
  mixnew   B (enabler v2), own stick with MODS.BIN + MODS2.BIN + MODSX.BIN: installs MODSX
  mixold   B (enabler v1 = the released one), same stick: the old two-file flow still works

    loaderx_cases_emu.py CASE [CASE..]
"""
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import link_rgb_emu as LR                                       # noqa: E402

KX = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loaderx.img")
K1 = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loader.img")
SLOT5, TAG_PWV5 = 0x09814000, struct.unpack("<I", b"PWV5")[0]
NAMES = ["IDLE", "RUN", "OK", "NOFILE", "TOOBIG", "BADHDR", "BADCRC", "BADOP", "NOTSTOCK", "MIDWAY"]
M = "xdj1000"


def stick(name, files):
    import loader_mk1 as LD
    src = os.path.join(LR.OUT, "c_" + name)
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(LR.EXPORT, src)
    for fn, data in files.items():
        open(os.path.join(src, fn), "wb").write(data)
    img = os.path.join(LR.OUT, "c_%s.img" % name)
    subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"),
                    os.path.join(LD.NXS2, "scripts", "media", "make_usb_image.py"), src, img, "64"],
                   check=True, cwd=LD.NXS2, stdout=subprocess.DEVNULL)
    return img


def one(case, MA, LD, blobs):
    x, ops, lx, l2, boot, mods2, ops2 = blobs
    bad = bytearray(x); bad[len(bad) // 2] ^= 0x40
    link = case in ("badcrc", "late", "track")
    a_img = stick("a_" + case, {"MODSX.BIN": bytes(bad) if case == "badcrc" else x}) if link else None
    b_img = LR.A_STICK if link else stick("b_" + case, {"MODS.BIN": boot, "MODS2.BIN": mods2, "MODSX.BIN": x})
    kern = K1 if case == "mixold" else KX
    procs = []
    startA = lambda: procs.append(LR.run(1, "boot", M, "--stick", a_img, bg=True, log=os.path.join(LR.OUT, "deckA.log")))
    if link:
        procs.append(LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")))
        if case == "badcrc":
            startA(); time.sleep(70)
    procs.append(LR.run(0, "boot", M, "--stick", b_img, "--kernel", kern, bg=True, log=os.path.join(LR.OUT, "deckB.log")))
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek(M, a, 4))[0]
    nm = lambda v: NAMES[v] if v < len(NAMES) else hex(v)
    st = lambda: struct.unpack("<16I", E.peek(M, MA.STATEX, 64))
    ok = [True]

    def chk(label, good):
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok[0] &= bool(good)

    def steps(*ss):
        for s in ss:
            E.step(M, s) if isinstance(s, str) else time.sleep(s)

    stores = [(o[1], o[2], o[3]) for o in ops if o[0] == LD.OP_STORE]
    try:
        time.sleep(110)
        if case in ("late", "track"):
            s = st()
            chk("before A: nothing installed (own stick: %s)" % nm(s[2]), s[1] != 0x454E4F44 and s[2] == 3)
            if case == "track":
                steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 15,
                      "key 0x10:0x01:300", 2)
                chk("track loaded and playing on B (len %d)" % u32(LD.TRACK_LEN), u32(LD.TRACK_LEN))
            startA(); time.sleep(260)
            print("    drive entry 'd' on B: %s" % E.peek(M, 0x0F2D80C0 + 0x64 * 12, 12).hex(), flush=True)
        s = st() if case != "mixold" else None
        if s:
            print("    loader X: done %s status %s via %d flen %d | link calls %d attempts %d status %s | bad %#x got %#x want %#x"
                  % (s[1] == 0x454E4F44, nm(s[2]), s[12], s[5], s[13], s[14], nm(s[15]), s[7], s[8], s[9]), flush=True)
        stock = [hex(a) for a, so, nw in stores if u32(a) != so and a != LD.POOL]
        new = [hex(a) for a, so, nw in stores if u32(a) != nw]
        if case == "badcrc":
            chk("damaged file over LINK refused: BADCRC, not installed", s[1] != 0x454E4F44 and s[15] == 6)
            chk("every hook word still stock", not stock)
        elif case == "late":
            chk("installed when the link appeared (via 2, OK)", s[1] == 0x454E4F44 and s[12] == 2 and s[2] == 2 and not new)
        elif case == "track":
            chk("refused with a track loaded: %s at %#x, not installed" % (nm(s[15]), s[7]),
                s[1] != 0x454E4F44 and s[15] == 8 and s[7] == LD.TRACK_LEN)
            chk("every hook word still stock, B still has its track (len %d)" % u32(LD.TRACK_LEN), not stock and u32(LD.TRACK_LEN))
        elif case == "mixnew":
            chk("enabler v2 took MODSX.BIN from the mixed stick (via 1, OK, %d B)" % s[5],
                s[1] == 0x454E4F44 and s[12] == 1 and s[2] == 2 and s[5] == len(x) and not new)
        else:
            s1 = struct.unpack("<11I", E.peek(M, LD.STATE, 44))
            s2 = struct.unpack("<11I", E.peek(M, MA.STATE2, 44))
            st2 = [(o[1], o[3]) for o in ops2 if o[0] == LD.OP_STORE]
            chk("enabler v1 on the mixed stick: MODS.BIN %s, MODS2.BIN %s (%d B), hooks in" % (nm(s1[2]), nm(s2[2]), s2[5]),
                s1[2] == 2 and s2[2] == 2 and s2[5] == len(mods2) and all(u32(a) == v for a, v in st2))
        if case in ("badcrc", "late", "mixnew", "mixold"):
            steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 18)
            want_colour = case != "badcrc"
            chk("own-stick track loads (len %d), colour data %s" % (u32(LD.TRACK_LEN), u32(SLOT5) == TAG_PWV5),
                u32(LD.TRACK_LEN) and (u32(SLOT5) == TAG_PWV5) == want_colour)
        chk("deck running", "running" in E.cmd(M, "info status"))
    finally:
        for slot in (0, 1):
            LR.run(slot, "cmd", M, "quit")
        time.sleep(4)
        for q in procs:
            q.terminate()
    print("RESULT %s: %s" % (case, "PASS" if ok[0] else "FAIL"), flush=True)


def main(av):
    import mods_all as MA
    import loader_mk1 as LD
    x, ops, info, lx, l2 = MA.cmd_build_x(stems=False)
    boot, mods2, ops2, _, _ = MA.cmd_build(stems=False)
    for case in av:
        print("== " + case, flush=True)
        one(case, MA, LD, (x, ops, lx, l2, boot, mods2, ops2))


if __name__ == "__main__":
    main(sys.argv[1:])
