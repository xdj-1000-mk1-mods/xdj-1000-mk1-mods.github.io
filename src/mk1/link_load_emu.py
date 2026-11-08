#!/usr/bin/env python3
"""qemu, two linked MK1 decks: the phase meter on a track loaded over LINK.

Deck A (EMU_SLOT=1, stock image, MAC :02) serves the test stick. Deck B
(EMU_SLOT=0, the flashed loader image, MAC :01) gets the same stick with
MODS.BIN + MODS2.BIN (mods_all.py emu builds work/mods_all/stick.img), so its
mods install on the mount; then B browses LINK > A's USB > TRACK and loads
the first track. Pass: B's phase meter took its grid from the deck table
(pm_src 1), n beats > 0, and keeps drawing.

    link_load_emu.py          (run mods_all.py emu once first: it makes stick.img)
"""
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
P = os.path.join(ROOT, ".venv", "bin", "python")
OUT = os.path.join(ROOT, "work", "link2")
STICK = os.path.join(ROOT, "work", "mods_all", "stick.img")
KERNEL = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loader.img")
PMB = os.path.join(ROOT, "work", "pm", "build")


def run(slot, *a, bg=False, log=None):
    env = dict(os.environ, EMU_SLOT=str(slot))
    argv = [P, os.path.join(HERE, "emu_link.py")] + list(a)
    if bg:
        return subprocess.Popen(argv, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT, cwd=ROOT)
    return subprocess.run(argv, env=env, capture_output=True, text=True, cwd=ROOT).stdout


def main():
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, HERE)
    import loader_mk1 as LD
    assert open(os.path.join(PMB, "pm.bin"), "rb").read() == open(os.path.join(LD.SNAP, "bin", "pm.bin"), "rb").read()
    ps = {l.split()[1]: int(l.split()[0], 16) for l in open(os.path.join(PMB, "pm.syms")) if l.strip()}
    procs = [run(0, "dhcp", bg=True, log=os.path.join(OUT, "dhcp.log")),
             run(1, "boot", "xdj1000", "--stick", STICK, bg=True, log=os.path.join(OUT, "deckA.log")),
             run(0, "boot", "xdj1000", "--stick", STICK, "--kernel", KERNEL, bg=True,
                 log=os.path.join(OUT, "deckB.log"))]
    os.environ["EMU_SLOT"] = "0"
    import emu_link
    E = emu_link.E
    u32 = lambda a: struct.unpack("<I", E.peek("xdj1000", a, 4))[0]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    try:
        t0 = time.time()
        while time.time() - t0 < 240:                      # B's mods in (loader2 done)
            time.sleep(5)
            try:
                if u32(0x099EFF04) == 0x454E4F44:
                    break
            except Exception:
                pass
        chk("deck B: mods installed from its stick (%.0f s)" % (time.time() - t0), u32(0x099EFF04) == 0x454E4F44)
        time.sleep(20)
        for s in ("tap 55 197 300", 4, "rot 1", 1.5, "rot 1", 1.5, "key 0x11:0x01:300", 6,
                  "key 0x11:0x01:300", 15):
            E.step("xdj1000", s) if isinstance(s, str) else time.sleep(s)
        E.shot("xdj1000", os.path.join(OUT, "B_linkload.png"))
        tl = u32(LD.TRACK_LEN)
        chk("deck B: track loaded over LINK (len %d)" % tl, tl != 0)
        E.step("xdj1000", "key 0x10:0x01:300")             # play
        time.sleep(4)
        d0 = u32(ps["pm_draws"])
        time.sleep(2)
        src, n, d1 = u32(ps["pm_src"]), u32(ps["pm_n"]), u32(ps["pm_draws"])
        E.shot("xdj1000", os.path.join(OUT, "B_linkload_playing.png"))
        chk("phase meter own row: grid from the deck table (src %d), %d beats, drawing %d -> %d"
            % (src, n, d0, d1), src == 1 and n > 1 and d1 > d0)
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
    sys.exit(main())
