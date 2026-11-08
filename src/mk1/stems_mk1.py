#!/usr/bin/env python3
"""Live STEM mute/solo for MK1 v1.13, built from upstream's own code.

Upstream tools/stems/sm.c + smhook.S (hardware-tested on the XDJ-700): hooks
the media server's USB audio read; for a STEMS-4 file (tools/stems4.py) with
stems muted (PMASK bit i = stem i, vocals/drums/bass/other) a read inside the
mix's sample data returns the sum of the un-muted stem planes. Built with
only the model constants replaced (mk1/models/xdj1000_113.json stems_io,
stems_module): fread/fseek addresses (each must match exactly once), the
module home (upstream's 0x09836000 is RGB SNAP on MK1), PMASK and the 700's
version-switcher words (absent on MK1) as zero words at the end of the area.

Install (as upstream stems_apply.py): module, its bss zeroed, flags zeroed,
sm_prev = the live hook, then the pool word as ONE store, then the media
API's direct read slot (upstream found on hardware that the real reads come
through it; only while it still holds stock fread).

    stems_mk1.py build      -> work/stems/build/sm.bin + sm.syms
"""
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                 # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
IO, MOD = E_["stems_io"], E_["stems_module"]
H = lambda v: int(v, 16)
BASE, END_MAX, PMASK = H(MOD["addr"]), H(MOD["end_max"]), H(MOD["pmask"])
HOOK, HOOK_STOCK = H(IO["audio_read_pool"]), H(IO["audio_read_stock"])
DIRECT = H(IO["direct_slot"])          # upstream 2026-10-12: on hardware the real reads come through here
UP = os.path.join(ROOT, "tools", "stems")
OUT = os.path.join(ROOT, "work", "stems", "build")


def _swap(src, old, new):
    if src.count(old) != 1:
        raise SystemExit("stems_mk1: upstream sm.c no longer has exactly one %r" % old)
    return src.replace(old, new)


def build():
    src = os.path.join(OUT, "src")
    os.makedirs(src, exist_ok=True)
    c = open(os.path.join(UP, "sm.c")).read()
    c = _swap(c, "#define FREAD  0x08C61A6Cu", "#define FREAD  0x%08Xu" % H(IO["fread"]))
    c = _swap(c, "#define FSEEK3 0x08C62E1Cu", "#define FSEEK3 0x%08Xu" % H(IO["fseek"]))
    c = _swap(c, "#define POS(fp) R32((fp) + 0x2C)", "#define POS(fp) R32((fp) + 0x%X)" % H(IO["pos_off"]))
    # upstream's 'faster mute' beta rewrites the decoded audio in the DSP's DDR (ring 0xC0090000,
    # playhead 0x11837CCC: 700 DSP firmware values, unverified on MK1; writes into the running
    # audio chip need the user's explicit OK). Off: a mute is heard after the deck's read-ahead,
    # as in upstream's hardware-tested version. The SH-RAM re-mix of buffered reads stays on.
    c = _swap(c, "dr_on = 1; dr_mask = mask;", "dr_on = 0; dr_mask = mask;   /* MK1: DSP rewrite off */")
    open(os.path.join(src, "sm.c"), "w").write(c)
    shutil.copy(os.path.join(UP, "smhook.S"), os.path.join(src, "smhook.S"))
    img, syms = shbuild.build(OUT, "sm", ["smhook.S", "sm.c"], BASE, PMASK,
                              {"PMASK": PMASK, "V_VSEL": PMASK + 4, "V_VFP": PMASK + 8, "V_VTBL": PMASK},
                              "_sm_table", keep=("_sm_", "_end"), cwd=src)
    assert syms["sm_table"] == BASE, syms
    assert syms["end"] <= PMASK, "stems module runs into its flag words"
    return img, syms


def install_steps(s, live_hook):
    """emu.py steps: module (sm_prev = live hook), bss + flags zeroed, mask, hook LAST"""
    img = bytearray(open(os.path.join(OUT, "sm.bin"), "rb").read())
    struct.pack_into("<I", img, s["sm_prev"] - BASE, live_hook)
    blob = os.path.join(OUT, "sm_installed.bin")
    open(blob, "wb").write(img)
    n = len(img)
    return ["fill %#x %#x 0" % (BASE + n, END_MAX - BASE - n),
            "load %#x %s" % (BASE, blob),
            "poke32 %#x %#x" % (HOOK, s["sm_fread"]),
            "poke32 %#x %#x" % (DIRECT, s["sm_fread"])]       # only while stock fread (checked by callers)


NXS2 = os.environ.get("XDJMOD_NXS2") or os.path.abspath(os.path.join(ROOT, "..", "..", "cdj-nxs2"))
STICK_DIR = os.path.join(ROOT, "work", "stems", "stick")
STICK_IMG = os.path.join(ROOT, "work", "stems", "stems_usb.img")
TRACK = os.path.join("Contents", "MK1 Port", "Beat Jump Tests", "BJ Test 120.wav")
TONES = (220, 330, 440, 550)                 # vocals, drums, bass, other


def make_stick():
    """the test stick with its one track replaced by a STEMS-4 WAV of four tones
    (same name, format and length, so its rekordbox entry still loads it)"""
    import wave
    import numpy as np
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import stems4 as S4
    if os.path.exists(STICK_IMG):
        return os.path.join(STICK_DIR, TRACK)
    if os.path.exists(STICK_DIR):
        shutil.rmtree(STICK_DIR)
    shutil.copytree(os.path.join(ROOT, "work", "testusb", "device"), STICK_DIR)
    td = os.path.join(ROOT, "work", "stems", "src")
    os.makedirs(td, exist_ok=True)
    sr, secs = 44100, 90
    t = np.arange(sr * secs) / sr
    paths, acc = {}, np.zeros(sr * secs)
    for k, f in zip(S4.ORDER, TONES):
        x = 0.18 * np.sin(2 * np.pi * f * t)
        acc += x
        p = os.path.join(td, k + ".wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes(np.repeat((x * 32767).astype(np.int16), 2).tobytes())
        paths[k] = p
    mix = os.path.join(td, "mix.wav")
    with wave.open(mix, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(np.repeat(np.clip(acc * 32767, -32768, 32767).astype(np.int16), 2).tobytes())
    out = os.path.join(STICK_DIR, TRACK)
    S4.build(mix, out, paths)
    import subprocess
    subprocess.run([os.path.join(NXS2, ".venv", "bin", "python"), "scripts/media/make_usb_image.py",
                    STICK_DIR, STICK_IMG], check=True, cwd=NXS2)
    return out


def tone_levels(wav_path, last_s=15):
    """dB of each test tone in the last last_s seconds of the recorded deck output"""
    import wave
    import numpy as np
    w = wave.open(wav_path)
    sr, ch = w.getframerate(), w.getnchannels()
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch)[:, 0].astype(float)
    a = a[-int(last_s * sr):]
    a = a[: (len(a) // sr) * sr]
    if len(a) < sr:
        return None
    spec = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    fr = np.fft.rfftfreq(len(a), 1 / sr)
    ref = spec.max() or 1.0
    return {f: 20 * np.log10(spec[np.argmin(abs(fr - f * 1.0)) - 3:np.argmin(abs(fr - f * 1.0)) + 4].max() / ref)
            for f in TONES}


def emu(mask=0b0101):
    import time
    import emu as E
    model = "xdj1000"
    make_stick()
    img, s = build()
    wav = os.path.join(ROOT, "work", "stems", "out_%d.wav" % mask)
    os.environ["EMU_AUDIODEV"] = "driver=wav,path=%s" % wav
    p = E.start(model, stick=STICK_IMG)
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    ok = True

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)
    try:
        time.sleep(50)
        live = u32(HOOK)
        ok &= chk("stock audio-read pool %#x = %#x, direct slot %#x = %#x" % (HOOK, live, DIRECT, u32(DIRECT)),
                  live == HOOK_STOCK and u32(DIRECT) == HOOK_STOCK)
        for st in install_steps(s, live):
            E.step(model, st)
        E.step(model, "fill %#x 1 %d" % (PMASK, mask))
        ok &= chk("hooked: pool + direct slot -> sm_fread %#x, mask %s" % (u32(HOOK), bin(E.peek(model, PMASK, 1)[0])),
                  u32(HOOK) == s["sm_fread"] and u32(DIRECT) == s["sm_fread"])
        t_play = None
        for st in ("key 0x13:0x04:300", 12, "rot 1", 3, "rot 1", 3, "key 0x11:0x01:300", 12, "key 0x11:0x01:300"):
            E.step(model, st) if isinstance(st, str) else time.sleep(st)
        t_play = time.time()
        time.sleep(25)
        tl = u32(int(E_["track_len_word"]["addr"], 16))
        c = {k: u32(s[k]) for k in ("sm_calls", "sm_files", "sm_hits", "sm_valid", "sm_maxn")}
        ok &= chk("track loaded (len %d), mixer counters %s" % (tl, c), tl != 0 and c["sm_calls"] > 0)
        ok &= chk("STEMS-4 file recognised (sm_files %d)" % c["sm_files"], c["sm_files"] > 0)
        if mask:
            ok &= chk("reads mixed (sm_hits %d)" % c["sm_hits"], c["sm_hits"] > 0)
        # exact check: the bytes the deck's read put in its buffer == the stem mix for that position
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import stems4 as S4
        raw = open(os.path.join(STICK_DIR, TRACK), "rb").read()
        d_off, d_len, big, stm, mix = S4.read(os.path.join(STICK_DIR, TRACK))
        want = S4.expected(stm, mask).tobytes() if mask else mix.tobytes()   # mask 0 = pass-through
        plain = mix.tobytes()
        good = plain_n = n_in = 0
        for _ in range(12):
            pos, buf, n = u32(s["sm_lastpos"]), u32(s["sm_lastbuf"]), u32(s["sm_lastn"])
            got = E.peek(model, buf & 0x1FFFFFFF, min(n, 4096))
            a = max(pos, d_off)
            a = d_off + ((a - d_off + 3) & ~3)
            e = min(pos + len(got), d_off + d_len)
            if e - a >= 256 and pos == u32(s["sm_lastpos"]):
                n_in += 1
                seg = got[a - pos:e - pos]
                good += seg == want[a - d_off:e - d_off]
                plain_n += seg == plain[a - d_off:e - d_off] and mask != 0
            time.sleep(1.5)
        ok &= chk("read buffers checked: %d inside the sample data, %d == expected mix (mask %s), %d == plain mix"
                  % (n_in, good, bin(mask), plain_n), n_in >= 3 and good == n_in and plain_n == 0)
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    lv = tone_levels(wav) if os.path.exists(wav) else None
    if lv:      # info only: qemu's emulated output is mostly silent (no playback audio)
        print("info deck audio: %s" % ", ".join("%d Hz %.0f dB" % (f, lv[f]) for f in TONES))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["emu"]:
        sys.exit(emu(int(sys.argv[2], 0) if len(sys.argv) > 2 else 0b0101))
    if sys.argv[1:] == ["build"]:
        img, s = build()
        print("sm: %d B code, bss to %#x, sm_fread %#x, sm_prev %#x" % (len(img), s["end"], s["sm_fread"], s["sm_prev"]))
    else:
        print(__doc__)
