#!/usr/bin/env python3
"""qemu: stick settings (MODSCFG.BIN) written by the deck and read back.

Writable stick image (snapshot=off on a copy: the deck's writes land in the
file). Boot 1: flashed loader image + MODS.BIN/MODS2.BIN; no settings file ->
status NOFILE; set WAVEFORM COLOR = 3-BAND, PHASE METER = OFF through the
UTILITY rows' words; load a track -> the file is written once. Then on the
host: the file's bytes, and fsck_msdos -n on the image. Boot 2 (same image):
the settings come back on insert (status LOADED, both words restored).

    settings_emu.py
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
os.environ.setdefault("EMU_SLOT", "3")
import emu as E                                                 # noqa: E402
import loader_mk1 as LD                                         # noqa: E402
import mods_all as MA                                           # noqa: E402

M = "xdj1000"
OUT = os.path.join(ROOT, "work", "settings")
KERNEL = os.path.join(ROOT, "work", "mk1build", "MAIN_mk1_113_version_tag_loader.img")
_argv_for = E.argv_for


def _argv_rw(*a, **kw):                                         # the stick image takes the deck's writes
    argv, env = _argv_for(*a, **kw)
    i = next(k for k, x in enumerate(argv) if x.startswith("if=none,id=usbstk,"))
    argv[i] = argv[i].replace("snapshot=on", "snapshot=off")
    return argv, env


E.argv_for = _argv_rw


def stick(boot, mods2):
    src = os.path.join(OUT, "stick")
    shutil.rmtree(src, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "work", "testusb", "device"), src)
    open(os.path.join(src, "MODS.BIN"), "wb").write(boot)
    open(os.path.join(src, "MODS2.BIN"), "wb").write(mods2)
    img = os.path.join(OUT, "stick_rw.img")
    subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"),
                    os.path.join(LD.NXS2, "scripts", "media", "make_usb_image.py"), src, img, "64"],
                   check=True, cwd=LD.NXS2, stdout=subprocess.DEVNULL)
    return img


def part(img):
    """the FAT partition of the stick image (MBR entry 0) as its own file"""
    d = open(img, "rb").read()
    if d[0x1FE:0x200] == b"\x55\xAA" and d[0x1C2] in (0x0B, 0x0C, 0x0E, 0x06, 0x04, 0x01):
        lba, n = struct.unpack_from("<II", d, 0x1C6)
        d = d[lba * 512:(lba + n) * 512]
    out = img + ".part"
    open(out, "wb").write(d)
    return out


def read_file(img, name):
    img = part(img)
    code = ("import sys, fs\nfrom pyfatfs.PyFatFS import PyFatFS\n"
            "f = PyFatFS(sys.argv[1], read_only=True)\n"
            "p = '/' + sys.argv[2]\n"
            "sys.stdout.buffer.write(f.readbytes(p) if f.exists(p) else b'')\n")
    r = subprocess.run([os.path.join(LD.NXS2, ".venv", "bin", "python"), "-c", code, img, name],
                       capture_output=True)
    return r.stdout if r.returncode == 0 else None


def main():
    os.makedirs(OUT, exist_ok=True)
    boot, mods2, ops, info, l2 = MA.cmd_build()
    img = stick(boot, mods2)
    D = MA.cfg_defs()
    CS, WAVE, PM = D["CFG_STATE"], D["CFG_WAVE"], D["CFG_PM"]
    ok = True

    def chk(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label, flush=True)
        ok &= bool(good)

    def boot_deck():
        p = E.start(M, stick=img, kernel=KERNEL)
        t0 = time.time()
        while time.time() - t0 < 240:
            time.sleep(4)
            try:
                if struct.unpack("<I", E.peek(M, MA.STATE2 + 4, 4))[0] == 0x454E4F44:
                    break
            except Exception:
                pass
        time.sleep(3)
        return p

    cs = lambda: struct.unpack("<8I", E.peek(M, CS, 32))
    u32 = lambda a: struct.unpack("<I", E.peek(M, a, 4))[0]
    u8 = lambda a: E.peek(M, a, 1)[0]

    def quit_(p):
        try:
            E.cmd(M, "quit")
        except OSError:
            pass
        p.wait(timeout=60)

    p = boot_deck()
    try:
        c = cs()
        chk("boot 1: mods in, settings: no file (status %d), stick holds = live (wave %d pm %d)"
            % (c[6], c[1], c[2]), c[0] == 0x4746434D and c[6] == 2 and c[1] == u32(WAVE) and c[2] == u8(PM))
        E.step(M, "poke32 %#x 2" % WAVE)                           # WAVEFORM COLOR = 3-BAND
        E.step(M, "poke32 %#x %#x" % (PM & ~3, u32(PM & ~3) & ~(0xFF << 8 * (PM & 3))))   # PHASE METER = OFF
        time.sleep(1)
        chk("changed live: wave %d, pm %d; nothing written yet (saves %d)" % (u32(WAVE), u8(PM), cs()[4]),
            u32(WAVE) == 2 and u8(PM) == 0 and cs()[4] == 0)
        for s in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3, "key 0x11:0x01:300", 10,
                  "key 0x11:0x01:300", 15):
            E.step(M, s) if isinstance(s, str) else time.sleep(s)
        c = cs()
        chk("track load: settings written once (saves %d, fails %d, status %d), track len %d"
            % (c[4], c[5], c[6], u32(LD.TRACK_LEN)), c[4] == 1 and c[5] == 0 and c[6] == 4 and u32(LD.TRACK_LEN))
        E.step(M, "key 0x11:0x01:300")                            # load again: no second write
        time.sleep(12)
        chk("next track load, no change: no second write (saves %d)" % cs()[4], cs()[4] == 1)
        chk("deck running", "running" in E.cmd(M, "info status"))
    finally:
        quit_(p)
    b = read_file(img, "MODSCFG.BIN")
    want = struct.pack("<5I", 0x4746434D, 1, 2, 0, 0x4746434D ^ 1 ^ 2 ^ 0 ^ 0x5A5A5A5A)
    chk("host: MODSCFG.BIN on the stick = %s" % (b.hex() if b else b), b == want)
    r = subprocess.run(["fsck_msdos", "-n", part(img)], capture_output=True, text=True)
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] if (r.stdout + r.stderr).strip() else []
    chk("host: fsck_msdos -n clean (exit %d %s)" % (r.returncode, tail), r.returncode == 0)
    for f in ("MODS.BIN", "MODS2.BIN"):
        chk("host: %s unchanged on the stick" % f, read_file(img, f) == (boot if f == "MODS.BIN" else mods2))
    p = boot_deck()
    try:
        c = cs()
        chk("boot 2: settings back from the stick (status %d loads %d): wave %d pm %d"
            % (c[6], c[3], u32(WAVE), u8(PM)), c[6] == 1 and c[3] >= 1 and u32(WAVE) == 2 and u8(PM) == 0)
        chk("deck running", "running" in E.cmd(M, "info status"))
    finally:
        quit_(p)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
