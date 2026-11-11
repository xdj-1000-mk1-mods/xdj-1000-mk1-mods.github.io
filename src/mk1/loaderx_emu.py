#!/usr/bin/env python3
"""qemu: the enabler v2 (loader X, mk1/loader/ldr.c LINK_SET_STOCK).

  link   deck A (stock image) has the stick with MODSX.BIN; deck B (enabler v2)
         has a stick WITHOUT mod files. B must install the mods from A's stick
         over Pro DJ Link (state: via 2), then show colour on a track from its
         own stick and still load over LINK.
  local  one deck (enabler v2), MODSX.BIN on its own stick: installs at the
         mount (via 1), colour, loader2 took over the mount hook, settings read.

    loaderx_emu.py link | local
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

KERNEL = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loaderx.img")
SLOT5, TAG_PWV5 = 0x09814000, struct.unpack("<I", b"PWV5")[0]
NAMES = ["IDLE", "RUN", "OK", "NOFILE", "TOOBIG", "BADHDR", "BADCRC", "BADOP", "NOTSTOCK", "MIDWAY"]


def modsx_stick():
    import loader_mk1 as LD
    src = os.path.join(LR.OUT, "x_stick")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(LR.EXPORT, src)
    shutil.copy(os.path.join(ROOT, "work", "mods_all", "MODSX.BIN"), src)
    img = os.path.join(LR.OUT, "x_stick.img")
    subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"),
                    os.path.join(LD.NXS2, "scripts", "media", "make_usb_image.py"), src, img, "64"],
                   check=True, cwd=LD.NXS2, stdout=subprocess.DEVNULL)
    return img


def main(av):
    case = av[0]
    import mods_all as MA
    import loader_mk1 as LD
    blob, ops, info, lx, l2 = MA.cmd_build_x(stems=False)
    xs = modsx_stick()
    M = "xdj1000"
    procs = []
    if case == "link":
        procs = [LR.run(0, "dhcp", bg=True, log=os.path.join(LR.OUT, "dhcp.log")),
                 LR.run(1, "boot", M, "--stick", xs, bg=True, log=os.path.join(LR.OUT, "deckA.log"))]
        time.sleep(70)                                         # deck A up, stick mounted, on the link
        procs.append(LR.run(0, "boot", M, "--stick", LR.A_STICK, "--kernel", KERNEL, bg=True,
                            log=os.path.join(LR.OUT, "deckB.log")))
    else:
        procs = [LR.run(0, "boot", M, "--stick", xs, "--kernel", KERNEL, bg=True,
                        log=os.path.join(LR.OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
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

    def st():
        return struct.unpack("<16I", E.peek(M, MA.STATEX, 64))

    try:
        t0, s = time.time(), None
        while time.time() - t0 < 300:
            time.sleep(5)
            try:
                s = st()
                if s[1] == 0x454E4F44 and s[11] == 0:
                    break
            except Exception:
                pass
        time.sleep(8)
        s = st()
        nm = lambda v: NAMES[v] if v < len(NAMES) else hex(v)
        print("    loader X: done %s status %s via %d mounts %d attempts %d flen %d ops %d | link calls %d attempts %d "
              "status %s | bad %#x got %#x want %#x (%.0f s)" % (s[1] == 0x454E4F44, nm(s[2]), s[12], s[3], s[4], s[5],
              s[6], s[13], s[14], nm(s[15]), s[7], s[8], s[9], time.time() - t0), flush=True)
        want_via = 2 if case == "link" else 1
        chk("mods installed %s (via %d, status %s, %d B = MODSX.BIN)" % (
            "over LINK from deck A's stick" if case == "link" else "from the own stick", s[12], nm(s[2]), s[5]),
            s[1] == 0x454E4F44 and s[2] == 2 and s[12] == want_via and s[5] == len(blob))
        stores = [(o[1], o[3]) for o in ops if o[0] == LD.OP_STORE]
        bad = [hex(a) for a, v in stores if u32(a) != v]
        chk("%d hook words = new%s" % (len(stores), " BAD " + str(bad) if bad else ""), not bad)
        chk("mount hook handed to loader2 (%#x), link hook still loader X (%#x)" % (u32(LD.POOL), u32(MA.LINK_POOL)),
            u32(LD.POOL) == l2["ldr_path_build"] and u32(MA.LINK_POOL) == lx["ldr_link_mount"])
        time.sleep(10)
        steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 18)
        tl, t5 = u32(LD.TRACK_LEN), u32(SLOT5)
        E.shot(M, os.path.join(LR.OUT, "x_%s_local.png" % case))
        chk("track from the own stick: loaded (len %d), colour waveform data present" % tl, tl and t5 == TAG_PWV5)
        if case == "link":
            steps("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2,
                  "key 0x11:0x01:300", 22)
            tl2 = u32(LD.TRACK_LEN)
            E.shot(M, os.path.join(LR.OUT, "x_link_link.png"))
            n5 = struct.unpack(">I", E.peek(M, SLOT5 + 16, 4))[0] if u32(SLOT5) == TAG_PWV5 else 0
            chk("still loads over LINK afterwards (len %d vs %d), with that track's colour data (%d entries)" % (tl2, tl, n5),
                tl2 and tl2 != tl and n5 and abs(n5 - tl2) < 200)
            s2 = st()
            chk("no second install (link calls %d, attempts %d)" % (s2[13], s2[14]), s2[14] == s[14])
        else:
            cs = struct.unpack("<8I", E.peek(M, MA.cfg_defs()["CFG_STATE"], 32))
            chk("loader2 service ran on this mount: settings state %s (status %d)" % (hex(cs[0]), cs[6]),
                cs[0] == 0x4746434D)
        chk("deck running", "running" in E.cmd(M, "info status"))
    finally:
        for slot in ((0, 1) if case == "link" else (0,)):
            LR.run(slot, "cmd", M, "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
