#!/usr/bin/env python3
"""Record the trace windows for one model: each restored from the same saved
state, the same length, one action at the same moment, the executed TBs
written by the tbcov plugin to work/trace/<model>/<name>.txt and a screenshot
at the end to work/trace/<model>/<name>.png.

PERFORM-screen coordinates are the stock MK1 layout (work/emu/mk1_perform.png);
the 700's stock PERFORM screen is mapped separately (see ZONES_700).

A window may carry environment knobs for QEMU (third tuple field), e.g. a
direct handler call with CDJ_PCALL2.

    usage: python3 mk1/trace_set.py MODEL [name ...]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SECS = 7.0
T_ACT = 2.0                      # action at 2 s, screenshot at the end

# (name, saved state, script) -- MK1 stock PERFORM screen
ZONES_MK1 = {
    "base1": ("perform", ""), "base2": ("perform", ""), "base3": ("perform", ""),
    "bj_rev1": ("perform", "tap 154 175 200"), "bj_fwd1": ("perform", "tap 231 175 200"),
    "bj_rev2": ("perform", "tap 326 175 200"), "bj_fwd2": ("perform", "tap 404 175 200"),
    "bj_rev4": ("perform", "tap 498 175 200"), "bj_fwd4": ("perform", "tap 576 175 200"),
    "hc_a": ("perform", "tap 165 263 200"), "hc_b": ("perform", "tap 280 263 200"),
    "hc_c": ("perform", "tap 394 263 200"), "hc_rec": ("perform", "tap 498 263 200"),
    "hc_call": ("perform", "tap 576 263 200"),
    "wave": ("perform", "tap 366 100 200"), "call_l": ("perform", "tap 676 180 200"),
    "call_r": ("perform", "tap 747 180 200"), "quantize": ("perform", "tap 676 259 200"),
    "memory": ("perform", "tap 747 259 200"), "perf_close": ("perform", "tap 710 37 200"),
    "mbase1": ("main", ""), "mbase2": ("main", ""),
    "perf_open": ("main", "tap 710 37 200"),
    # the beat-jump handler called directly (no touch): CDJ_PCALL2 from its dispatcher
    "pc_bj1": ("perform", "", {"CDJ_PCALL2": "0x08ce8b20:0x08ce8d2e:1:0:0"}),
    "pc_bj2": ("perform", "", {"CDJ_PCALL2": "0x08ce8b20:0x08ce8d2e:2:0:0"}),
}

# XDJ-700 stock PERFORM screen (work/emu/700_perform.png): REV button, BEAT LOOP
# row (1/2 1 2 4 8 16) where MK1 has BEAT JUMP, the same HOT CUE row and buttons
ZONES_700 = {
    "base1": ("perform", ""), "base2": ("perform", ""), "base3": ("perform", ""),
    "bl_half": ("perform", "tap 155 180 200"), "bl_1": ("perform", "tap 240 180 200"),
    "bl_2": ("perform", "tap 324 180 200"), "bl_4": ("perform", "tap 409 180 200"),
    "bl_8": ("perform", "tap 493 180 200"), "bl_16": ("perform", "tap 577 180 200"),
    "rev": ("perform", "tap 50 104 200"),
    "hc_a": ("perform", "tap 165 263 200"), "hc_b": ("perform", "tap 280 263 200"),
    "hc_c": ("perform", "tap 394 263 200"), "hc_rec": ("perform", "tap 498 263 200"),
    "hc_call": ("perform", "tap 576 263 200"),
    "wave": ("perform", "tap 366 100 200"), "call_l": ("perform", "tap 676 180 200"),
    "call_r": ("perform", "tap 747 180 200"), "quantize": ("perform", "tap 676 259 200"),
    "memory": ("perform", "tap 747 259 200"), "perf_close": ("perform", "tap 710 37 200"),
    "mbase1": ("main", ""), "mbase2": ("main", ""),
    "perf_open": ("main", "tap 710 37 200"),
    "pc_bj1": ("perform", "", {"CDJ_PCALL2": "0x08d42f80:0x08d4318e:1:0:0"}),
    "pc_bj2": ("perform", "", {"CDJ_PCALL2": "0x08d42f80:0x08d4318e:2:0:0"}),
}


def run(model, name, state, script, env=None):
    d = os.path.join(ROOT, "work", "trace", model)
    os.makedirs(d, exist_ok=True)
    s = f"wait {T_ACT}" + (f"; {script}" if script else "") + \
        f"; wait {SECS - T_ACT - 0.6}; shot {d}/{name}.png"
    subprocess.run([sys.executable, os.path.join(HERE, "emu.py"), "run", model, state,
                    str(SECS), os.path.join(d, name + ".txt"), "--script", s], check=True,
                   env=dict(os.environ, **(env or {})))


def main(av):
    model = av[0]
    zones = {"xdj1000": ZONES_MK1, "xdj700": ZONES_700}[model]
    for name in (av[1:] or zones):
        state, script, *env = zones[name]
        run(model, name, state, script, env[0] if env else None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
