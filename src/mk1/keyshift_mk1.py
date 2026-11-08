#!/usr/bin/env python3
"""Live key shift engine for MK1 v1.13, built from upstream's own code.

DSP side: upstream's prebuilt v3 ks.bin (prebuilt/deck/keyshift/, == objcopy
of tools/keyshift_dsp/ks.elf). Every DSP address it uses is identical in the
MK1 DSP program (model table keyshift_dsp), so it runs unchanged.
SH side: upstream tools/keyshift_dsp/ksh.c + kshhook.S, compiled with ONLY
their model-specific constants replaced from mk1/models/xdj1000_113.json
(each must match exactly once, else the build stops), at keyshift_module.

Install (as upstream keyshift_hot_apply.py, no track loaded): module, zero
status words, ksh_prev = live flush-hook value, flag 'KSH1', then the hook
as ONE store; ksh.c checks the DSP program over the host port, writes the
code, reads it back, flips one call word and unhooks itself (status 1).
Then the deck's own store into the key word is NOPed. Key word:
0x40000000 | round(2^(semis/12) * 2^20); 0x00100000 = no shift.

    keyshift_mk1.py build    -> work/keyshift/build/ksh.bin + ksh.syms
    keyshift_mk1.py emu      qemu test: fresh boot, install, load + play with
                             MASTER TEMPO, key 0/+4/-4/+6/-6/0; checks read the
                             DSP code's own counters over the host port (k
                             latched, every block shifted, no clamps); audio
                             is recorded to work/keyshift/ks_emu.wav
"""
import json
import os
import re
import shutil
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import shbuild                                                 # noqa: E402

E_ = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))["entries"]
DSP, KSD = E_["dsp_image"], E_["keyshift_dsp"]
MOD = E_["keyshift_module"]
BASE, END_MAX = int(MOD["addr"], 16), int(MOD["end_max"], 16)
HOOK, HOOK_STOCK = int(E_["flush_hook"]["slot"], 16), int(E_["flush_hook"]["stock"], 16)
TRACK_LEN = int(E_["track_len_word"]["addr"], 16)
KW = E_["key_word"]
KEY_WORD, SITE = int(KW["addr"], 16), int(KW["store_site"], 16)
SITE_STOCK, NOP = int(KW["store_word"], 16), int(KW["nop"], 16)
MTW = int(E_["master_tempo_word"]["addr"], 16)
UP = os.path.join(ROOT, "tools", "keyshift_dsp")
PRE = os.path.join(ROOT, "prebuilt", "deck", "keyshift")
OUT = os.path.join(ROOT, "work", "keyshift", "build")
OFF = 0x00100000
FLAG = {"probe": 0x4B534850, "install": 0x4B534831, "revert": 0x4B534830}


def key_word(semis):
    return OFF if semis == 0 else 0x40000000 | int(round(2.0 ** (semis / 12.0) * (1 << 20)))


def _set(src, name, value):
    pat = r"(#define %s\s+)0x[0-9A-Fa-f]+u" % name
    if len(re.findall(pat, src)) != 1:
        raise SystemExit("keyshift_mk1: expected exactly one '#define %s' in upstream ksh.c" % name)
    return re.sub(pat, lambda m: m.group(1) + "0x%08Xu" % value, src)


def _sub(src, old, new):
    if src.count(old) != 1:
        raise SystemExit("keyshift_mk1: expected exactly one %r in upstream source" % old)
    return src.replace(old, new)


def build():
    src = os.path.join(OUT, "src")
    os.makedirs(src, exist_ok=True)
    c = open(os.path.join(UP, "ksh.c")).read()
    h = lambda v: int(v, 16)
    for name, v in (("POOL_FLUSH", HOOK), ("IMG", h(DSP["sh_addr"])), ("IMG_LEN", h(DSP["len"])),
                    ("DDR", h(DSP["ddr"])), ("CALL_OFF", h(KSD["call_site"]) - h(DSP["ddr"])),
                    ("CALL_OLD", h(KSD["call_word"])), ("TRACK_LEN", TRACK_LEN),
                    ("HPIA_P2", h(E_["host_port"]["hpia"])), ("HPID_P2", h(E_["host_port"]["hpid"]))):
        c = _set(c, name, v)
    c = _sub(c, "static const u32 PADDR[4] = { 0xC001CD40u, 0xC001CD98u, 0xC001CE34u, 0xC001CE48u };",
             "static const u32 PADDR[4] = { %s };" % ", ".join("0x%08Xu" % h(a) for a in KSD["stage_loads"]))
    c = _sub(c, "static const u32 POLD[4]  = { 0x3356B828u, 0x0308C168u, 0x01D6B828u, 0x0188C168u };",
             "static const u32 POLD[4]  = { %s };" % ", ".join("0x%08Xu" % h(a) for a in KSD["stage_load_words"]))
    open(os.path.join(src, "ksh.c"), "w").write(c)
    s = open(os.path.join(UP, "kshhook.S")).read()
    s = _sub(s, "_ksh_prev:   .long 0x08E7D278", "_ksh_prev:   .long 0x%08X" % HOOK_STOCK)
    open(os.path.join(src, "kshhook.S"), "w").write(s)
    shutil.copy(os.path.join(PRE, "ks.bin"), os.path.join(src, "ks.bin"))
    pbuf = next(int(l.split()[0], 16) for l in open(os.path.join(PRE, "ks.syms")) if l.split()[2] == "KS")
    img, syms = shbuild.build(OUT, "ksh", ["kshhook.S", "ksh.c"], BASE, END_MAX, {"PBUF": pbuf},
                              "_ksh_entry", keep=("_ksh_", "_ks_", "_end"), text_off=0x40, cwd=src)
    assert syms["ksh_entry"] == BASE, syms
    return img, syms


def install(E, model, s=None, n=None):
    """the one-shot install (no track loaded): module, status words, prev =
    live hook, flag, hook (one store); wait until ksh.c reports and has
    handed the hook back; then NOP the deck's store into the key word.
    Nothing else may re-hook the flush pool until this returns (ksh.c gives
    up, status 3, if it is no longer the head of the chain when it runs).
    Returns (status, ksh_dbg)."""
    if s is None:
        img, s = build()
        n = len(img)
    u32 = lambda a: struct.unpack("<I", E.peek(model, a, 4))[0]
    if u32(TRACK_LEN) != 0:
        raise SystemExit("keyshift install: a track is loaded (the installer needs none)")
    live = u32(HOOK)
    E.step(model, "fill %#x %#x 0" % (BASE + n, s["end"] - BASE - n))
    E.step(model, "load %#x %s" % (BASE, os.path.join(OUT, "ksh.bin")))
    for k in ("ksh_status", "ksh_tries"):
        E.step(model, "poke32 %#x 0" % s[k])
    E.step(model, "poke32 %#x %#x" % (s["ksh_prev"], live))
    E.step(model, "poke32 %#x %#x" % (s["ksh_flag"], FLAG["install"]))
    E.step(model, "poke32 %#x %#x" % (HOOK, s["ksh_entry"]))
    st = 0
    for _ in range(60):
        st = u32(s["ksh_status"])
        if st and st != 8 and u32(HOOK) != s["ksh_entry"]:
            break
        time.sleep(0.25)
    dbg = struct.unpack("<16I", E.peek(model, s["ksh_dbg"], 64))
    if st == 1:
        E.step(model, "poke16 %#x %#x" % (SITE, NOP))
    return st, dbg


def emu():
    import emu as E
    model = "xdj1000"
    wk = os.path.join(ROOT, "work", "keyshift")
    wav = os.path.join(wk, "ks_emu.wav")
    if os.path.exists(wav):
        os.unlink(wav)
    img, s = build()
    os.environ["EMU_AUDIODEV"] = "driver=wav,path=%s" % wav
    p = E.start(model)
    t0 = time.time()
    ok, marks = True, []

    def chk(label, good):
        print(("ok   " if good else "FAIL ") + label, flush=True)
        return bool(good)

    def u32(a):
        return struct.unpack("<I", E.peek(model, a, 4))[0]

    def u16(a):
        return struct.unpack("<H", E.peek(model, a, 2))[0]

    try:
        time.sleep(50)                                       # boot (smoke test: 45 s)
        E.shot(model, os.path.join(wk, "a_boot.png"))
        ok &= chk("stock: no track, hook %#x, store %#06x" % (u32(HOOK), u16(SITE)),
                  u32(TRACK_LEN) == 0 and u32(HOOK) == HOOK_STOCK and u16(SITE) == SITE_STOCK)
        ok &= chk("module area empty", E.peek(model, BASE, END_MAX - BASE) == bytes(END_MAX - BASE))
        live0 = u32(HOOK)
        st, dbg = install(E, model, s, len(img))
        print("ksh_status %d, dbg %s" % (st, " ".join("%08x" % x for x in dbg)), flush=True)
        ok &= chk("installed (status 1), hook back to %#x" % u32(HOOK), st == 1 and u32(HOOK) == live0)
        if st != 1:
            raise RuntimeError("install failed")
        ok &= chk("key-word store NOPed", u16(SITE) == NOP)
        for st_ in "0x13:0x04:300|12|rot 1|3|rot 1|3|0x11:0x01:300|12|0x11:0x01:300|15".split("|"):
            if st_.startswith("rot"):
                E.step(model, st_)
            elif ":" in st_:
                E.step(model, "key " + st_)
            else:
                time.sleep(float(st_))
        E.shot(model, os.path.join(wk, "b_playing.png"))
        ok &= chk("track loaded (len %#x)" % u32(TRACK_LEN), u32(TRACK_LEN) != 0)
        if E.peek(model, MTW, 1)[0] != 1:
            E.step(model, "key 0x15:0x10:300")
            time.sleep(2)
        ok &= chk("MASTER TEMPO on", E.peek(model, MTW, 1)[0] == 1)
        E.save(model, "ks_playing")                          # installed, playing, MT on, key off
        for semis in (0, 4, -4, 6, -6, 0):
            E.step(model, "poke32 %#x %#x" % (KEY_WORD, key_word(semis)))
            marks.append((time.time() - t0, semis))
            time.sleep(2)
            x = ks_state(E, model)
            time.sleep(6)
            y = ks_state(E, model)
            calls, sh = y["calls"] - x["calls"], y["shifted"] - x["shifted"]
            want = 2 ** (semis / 12)
            k = y["k"] if y["w_latched"] else 1.0
            good = calls > 1000 and y["clamps"] == x["clamps"] and abs(k - want) < 1e-3 and \
                (sh == calls if semis else sh == 0 and y["w_latched"] == 0)
            ok &= chk("key %+d: DSP k %.4f (want %.4f), shifted %d of %d blocks, clamps +%d" % (
                semis, k, want, sh, calls, y["clamps"] - x["clamps"]), good)
            kw = u32(KEY_WORD)
            ok &= chk("key word held at %+d (%#010x)" % (semis, kw), kw == key_word(semis))
        marks.append((time.time() - t0, None))
        E.shot(model, os.path.join(wk, "c_end.png"))
        ok &= chk("deck running", "running" in E.cmd(model, "info status"))
    except RuntimeError as e:
        print("STOP:", e)
        ok = False
    finally:
        try:
            E.cmd(model, "quit")
        except OSError:
            pass
        p.wait(timeout=60)
    # audio: recorded for listening only. qemu's DSP runs ~7% under real time
    # while shifting (753 vs 800 blocks/s), so the recording has gaps and is
    # no pass/fail criterion; analyse() is kept for a faster emulator.
    json.dump({"marks": marks}, open(os.path.join(wk, "ks_emu_marks.json"), "w"))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


HPIA, HPID = int(E_["host_port"]["hpia"], 16), int(E_["host_port"]["hpid"], 16)
KS_SYM = next(int(l.split()[0], 16) for l in open(os.path.join(PRE, "ks.syms")) if l.split()[2] == "KS")
KS_FIELDS = ("magic", "calls", "shifted", "w_latched", "k", "phi", "last_nx", "last_ny", "hl", "hr", "clamps")


def ks_state(E, model):
    """the DSP code's state block (ks.c struct ks after pbuf), read over the
    host port with the VM stopped; HPIA restored"""
    g = E.Gdb(model)
    try:
        save = g.rd(HPIA, 4)
        out = {}
        for i, n in enumerate(KS_FIELDS):
            g.wr(HPIA, struct.pack("<I", KS_SYM + 256 + 4 * i))
            v = g.rd(HPID, 4)
            out[n] = struct.unpack("<f" if n in ("k", "phi", "hl", "hr") else "<I", v)[0]
        g.wr(HPIA, save)
    finally:
        g.detach()
    return out


def bursts(wav):
    import wave
    import numpy as np
    w = wave.open(wav)
    sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, ch)[:, 0].astype(float)
    win = int(0.02 * sr)
    e = np.array([np.sqrt(np.mean(x[i:i + win] ** 2)) for i in range(0, len(x) - win, win)])
    thr = e.max() * 0.3
    out = []
    for i in range(1, len(e)):
        if e[i] > thr >= e[i - 1]:
            seg = x[i * win:i * win + int(0.08 * sr)]
            if len(seg) < int(0.08 * sr):
                continue
            f = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=sr))
            fr = np.fft.rfftfreq(sr, 1 / sr)
            m = (fr > 40) & (fr < 1000)
            out.append((i * win / sr, float(fr[m][np.argmax(f[m])])))
    return out


def analyse(wav, marks):
    """per key segment (2 s trimmed each side): median burst pitch + spacing"""
    import numpy as np
    b = bursts(wav)
    ok, res = True, []
    for (ta, semis), (tb, _) in zip(marks, marks[1:]):
        seg = [(t, f) for t, f in b if ta + 2 <= t <= tb - 2]
        if len(seg) < 4:
            print("FAIL segment %+d: only %d bursts" % (semis, len(seg)))
            return False
        res.append((semis, float(np.median([f for _, f in seg])),
                    float(np.median(np.diff([t for t, _ in seg]))), len(seg)))
    base = res[0][1]
    for semis, f, sp, n in res:
        want = 2 ** (semis / 12)
        good = abs(f / base / want - 1) < 0.04 and abs(sp - 0.5) < 0.01
        ok &= good
        print("%s key %+d: pitch %.1f Hz (x%.3f, want x%.3f), beat spacing %.3f s, %d bursts" % (
            "ok  " if good else "FAIL", semis, f, f / base, want, sp, n), flush=True)
    return ok


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    elif sys.argv[1:] == ["emu"]:
        sys.exit(emu())
    else:
        print(__doc__)
