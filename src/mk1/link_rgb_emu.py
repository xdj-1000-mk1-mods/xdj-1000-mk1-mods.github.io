#!/usr/bin/env python3
"""qemu, two linked MK1 decks: colour waveform of a track loaded over LINK.

User reports 2026-11-10: after a LINK load, the RGB overview + centre
waveform kept showing the track last loaded from the deck's OWN stick. The
colour snapshots read the USB slot's ANLZ context, which a LINK load never
fills. Deck A (EMU_SLOT=1, stock) serves work/testusb/multi (3 synthetic
tracks). Deck B (EMU_SLOT=0, enabler image) has the same export plus
MODS.BIN + MODS2.BIN on its own stick, and:
  1. loads track 1 from its own stick  -> colour (SLOT5 = that track's PWV5)
  2. loads track 2 over LINK from A     -> fixed: colour slots empty (stock
                                           blue); bug: SLOT5 still track 1
  3. loads track 1 from its own stick   -> colour again

    link_rgb_emu.py [MODS2.BIN]     (default work/mods_all/MODS2.BIN)
"""
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
P = os.path.join(ROOT, ".venv", "bin", "python")
OUT = os.path.join(ROOT, "work", "link2")
EXPORT = os.path.join(ROOT, "work", "testusb", "multi", "device")
A_STICK = os.path.join(ROOT, "work", "testusb", "multi_usb.img")
KERNEL = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loader.img")
SLOT5, TAG_PWV5 = 0x09814000, struct.unpack("<I", b"PWV5")[0]
SLOT4 = 0x09810000


def run(slot, *a, bg=False, log=None):
    env = dict(os.environ, EMU_SLOT=str(slot))
    argv = [P, os.path.join(HERE, "emu_link.py")] + list(a)
    if bg:
        return subprocess.Popen(argv, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT, cwd=ROOT)
    return subprocess.run(argv, env=env, capture_output=True, text=True, cwd=ROOT).stdout


def b_stick(mods2):
    sys.path.insert(0, HERE)
    import loader_mk1 as LD
    src = os.path.join(OUT, "b_stick")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(EXPORT, src)
    shutil.copy(os.path.join(ROOT, "work", "mods_all", "MODS.BIN"), src)
    shutil.copy(mods2, os.path.join(src, "MODS2.BIN"))
    img = os.path.join(OUT, "b_stick.img")
    subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"),
                    os.path.join(LD.NXS2, "scripts", "media", "make_usb_image.py"), src, img, "64"],
                   check=True, cwd=LD.NXS2, stdout=subprocess.DEVNULL)
    return img


def main(av):
    mods2 = os.path.abspath(av[0]) if av else os.path.join(ROOT, "work", "mods_all", "MODS2.BIN")
    os.makedirs(OUT, exist_ok=True)
    img = b_stick(mods2)
    procs = [run(0, "dhcp", bg=True, log=os.path.join(OUT, "dhcp.log")),
             run(1, "boot", "xdj1000", "--stick", A_STICK, bg=True, log=os.path.join(OUT, "deckA.log")),
             run(0, "boot", "xdj1000", "--stick", img, "--kernel", KERNEL, bg=True, log=os.path.join(OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    sys.path.insert(0, HERE)
    import emu_link
    import loader_mk1 as LD
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek("xdj1000", a, 4))[0]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    def steps(*ss):
        for s in ss:
            E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s)

    def colour():
        t5, t4 = u32(SLOT5), u32(SLOT4)
        n = struct.unpack(">I", E.peek("xdj1000", SLOT5 + 16, 4))[0] if t5 == TAG_PWV5 else 0
        return t5 == TAG_PWV5, t4 != 0, n

    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            time.sleep(5)
            try:
                if u32(0x099EFF04) == 0x454E4F44:
                    break
            except Exception:
                pass
        chk("deck B: mods installed from its stick (%.0f s)" % (time.time() - t0), u32(0x099EFF04) == 0x454E4F44)
        time.sleep(15)
        # 1. own stick, first track
        steps("key 0x13:0x04:300", 10, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 15)
        l1, c1 = u32(LD.TRACK_LEN), colour()
        E.shot("xdj1000", os.path.join(OUT, "rgb_1_local.png"))
        chk("1. own stick: track loaded (len %d), colour slots %s (PWV5 %d entries)" % (l1, c1[:2], c1[2]),
            l1 and c1[0])
        # 2. LINK: deck A's stick, second track
        steps("tap 55 197 300", 6, "rot 1", 2, "rot 1", 2, "key 0x11:0x01:300", 6, "rot 1", 2,
              "key 0x11:0x01:300", 20)
        l2, c2 = u32(LD.TRACK_LEN), colour()
        E.shot("xdj1000", os.path.join(OUT, "rgb_2_link.png"))
        chk("2. LINK: other track loaded (len %d vs %d)" % (l2, l1), l2 and l2 != l1)
        chk("2. LINK: no colour from the other track (slots %s, PWV5 %d entries)" % (c2[:2], c2[2]),
            not c2[0] and not c2[1])
        # 3. own stick again
        steps("key 0x13:0x04:300", 8, "key 0x11:0x01:300", 6, "key 0x11:0x01:300", 20)
        l3, c3 = u32(LD.TRACK_LEN), colour()
        E.shot("xdj1000", os.path.join(OUT, "rgb_3_local.png"))
        chk("3. own stick again: track len %d, colour slots %s (PWV5 %d entries)" % (l3, c3[:2], c3[2]),
            l3 and c3[0])
        chk("deck B running", "running" in E.cmd("xdj1000", "info status"))
    finally:
        for slot in (0, 1):
            run(slot, "cmd", "xdj1000", "quit")
        time.sleep(3)
        for q in procs:
            q.terminate()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
