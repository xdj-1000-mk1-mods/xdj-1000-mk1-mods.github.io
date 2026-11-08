#!/usr/bin/env python3
"""Emulator test of beat-jump presets on MK1 (data only: the jump table).

Each window restores work/emu/xdj1000/<state>.vm, sets the six table entries
to the preset with CDJ_PPOKE at the handler's entry (the bytes a build would
carry), optionally switches QUANTIZE off, taps one stock PERFORM pad and reads
REMAIN off the last screenshot (mk1/remain_ocr.py). The jump is REMAIN minus
the same-condition baseline; expected = beats x 60/BPM, reverse positive.
Table address and pad codes come from mk1/models/xdj1000_113.json.

    usage: python3 mk1/longjump_test.py PRESET [PRESET ...] [--state perform]
           -> work/longjump/<preset>/results.json
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import remain_ocr                                              # noqa: E402

MODEL = json.load(open(os.path.join(HERE, "models", "xdj1000_113.json")))
T = MODEL["entries"]["bj_table"]
PRESETS = {k: v["beats"] for k, v in T["presets"].items()}
BPM = 120.19                   # the test track's grid (work/testusb/collection.xml)
PADS = MODEL["entries"]["bj_pads_touch"]["pads"]           # code -> tap x, y
HANDLER = MODEL["entries"]["bj_handler"]["addr"]
QUANTIZE_XY = MODEL["entries"]["bj_pads_touch"]["quantize_xy"]
SECS = 7.0


def ppoke(beats):
    """beats = (b1, b2, b4): pads 1/2 -> b1, 3/4 -> b2, 5/6 -> b4."""
    base = int(T["base"], 16)
    specs = []
    for code in range(1, 7):
        b = beats[(code - 1) // 2]
        specs.append("%s:%#010x:%d:0" % (HANDLER, base + 8 * code, b))
    return ",".join(specs)


def window(out, state, beats, quantize_off, code):
    acts = []
    if quantize_off:
        acts.append("tap %d %d 200; wait 1" % tuple(QUANTIZE_XY))
    else:
        acts.append("wait 1")
    if code:
        x, y = PADS[str(code)]
        acts.append("tap %d %d 200" % (x, y))
    s = "wait 1; " + "; ".join(acts) + "; wait %.1f; shot %s" % (SECS - 2.6, out)
    env = dict(os.environ, CDJ_PPOKE=ppoke(beats))
    subprocess.run([sys.executable, os.path.join(HERE, "emu.py"), "run", "xdj1000", state,
                    str(SECS), "-", "--script", s], check=True, env=env, stdout=subprocess.DEVNULL)
    return remain_ocr.read(out)


def run_preset(name, state="perform"):
    beats = PRESETS[name]
    d = os.path.join(ROOT, "work", "longjump", name)
    os.makedirs(d, exist_ok=True)
    res = {"preset": name, "beats": beats, "bpm": BPM, "state": state, "runs": []}
    for qoff in (False, True):
        q = "qoff" if qoff else "qon"
        base = window(os.path.join(d, f"{q}_base.png"), state, beats, qoff, None)
        for code in range(1, 7):
            b = beats[(code - 1) // 2]
            rev = code % 2 == 1
            got = window(os.path.join(d, f"{q}_code{code}.png"), state, beats, qoff, code)
            exp = (1 if rev else -1) * b * 60.0 / BPM
            jump = None if (got is None or base is None) else got - base
            r = {"quantize": not qoff, "code": code, "pad": ("<<" if rev else ">>") + str(b),
                 "beats": b, "expected_s": round(exp, 3), "remain_base": base, "remain": got,
                 "jump_s": None if jump is None else round(jump, 3)}
            r["ok"] = jump is not None and abs(jump - exp) <= 0.15
            r["refused"] = jump is not None and abs(jump) <= 0.15
            res["runs"].append(r)
            js = "  n/a " if jump is None else f"{jump:+7.3f}"
            verdict = "UNREAD" if jump is None else ("OK" if r["ok"] else ("REFUSED" if r["refused"] else "MISMATCH"))
            print(f"{name} {q} {r['pad']:>5}: expected {exp:+7.3f}  jump {js}  {verdict}", flush=True)
    json.dump(res, open(os.path.join(d, "results.json"), "w"), indent=1)
    return res


def main(av):
    state = av[av.index("--state") + 1] if "--state" in av else "perform"
    names = [a for a in av if not a.startswith("--") and a != state] or list(PRESETS)
    for n in names:
        run_preset(n, state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
