#!/usr/bin/env python3
"""Regenerate web/patch.json (the browser builder's data) after the enabler changes.
Run `./xdjmod firmware --upd F` and `./xdjmod stick --upd F` (no stems, rgb) first;
then: .venv/bin/python web/make_patch.py   (writes web/patch.json + web/stick.json)
Writes only our changes (changed byte runs + the appended boot copier) and the
expected hashes; then test with: node web/test.mjs XDJ1000.UPD"""
import hashlib, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(HERE, "..", "src", "work")
M = json.load(open(os.path.join(HERE, "..", "src", "mk1", "models", "xdj1000_113.json")))
a = open(os.path.join(W, "MAIN_mk1_113.img"), "rb").read()
b = open(os.path.join(W, "mk1build", "MAIN_mk1_113_version_tag_loader.img"), "rb").read()
h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
runs, i = [], 0
while i < len(a):
    if a[i] != b[i]:
        j = i
        while j < len(a) and a[j] != b[j]:
            j += 1
        runs.append([i, b[i:j].hex()])
        i = j
    else:
        i += 1
d = dict(note="XDJ-1000 MK1 v1.13 stick-loader enabler: our changes to the decoded MAIN image "
              "(offsets from 0x08000000). Our code and pointers only; no firmware bytes.",
         upd_sha256=M["upd_sha256"], image_sha256=hashlib.sha256(a).hexdigest(),
         out_image_sha256=hashlib.sha256(b).hexdigest(), out_len=len(b), runs=runs, tail=b[len(a):].hex(),
         block=[0x40000, 6941185], banner="1.15", restore_banner="1.16",
         enabler_sha256=h(os.path.join(W, "mk1build", "XDJ1000_version_tag_loader_v1.15.UPD")),
         restore_sha256=h(os.path.join(W, "mk1restore", "XDJ1000_restore_1.16.UPD")))
open(os.path.join(HERE, "patch.json"), "w").write(json.dumps(d, indent=0))
print("patch.json: %d runs, %d B tail, enabler %s" % (len(runs), len(b) - len(a), d["enabler_sha256"][:16]))

# stick.json: MODS.BIN whole, MODS2.BIN minus the BEAT JUMP label block (firmware-derived:
# the page renders it from the user's firmware with src/mk1/bjlabels.py)
import base64
O = os.path.join(HERE, "..", "out", "stick")
mods, m2 = open(os.path.join(O, "MODS.BIN"), "rb").read(), open(os.path.join(O, "MODS2.BIN"), "rb").read()
lab = open(os.path.join(W, "bjswipe", "build", "labels.bin"), "rb").read()
off = m2.find(lab)
assert off > 0 and m2.count(lab) == 1, "labels not found once in MODS2.BIN (built with stems?)"
sh = lambda x: hashlib.sha256(x).hexdigest()
st = dict(note="Stick files for the browser builder. MODS.BIN is ours, whole. MODS2.BIN is ours except the BEAT JUMP "
               "label block, which is left out here and rendered in the browser from the user's firmware "
               "(src/mk1/bjlabels.py under Pyodide). Built without stems, default waveform RGB.",
          mods_b64=base64.b64encode(mods).decode(), mods_sha256=sh(mods),
          mods2_pre_b64=base64.b64encode(m2[:off]).decode(), mods2_post_b64=base64.b64encode(m2[off + len(lab):]).decode(),
          label_off=off, label_len=len(lab), labels_sha256=sh(lab), mods2_sha256=sh(m2))
open(os.path.join(HERE, "stick.json"), "w").write(json.dumps(st))
print("stick.json: MODS.BIN %s, MODS2.BIN %s (labels %d B at %d left out)" % (st["mods_sha256"][:16], st["mods2_sha256"][:16], len(lab), off))
