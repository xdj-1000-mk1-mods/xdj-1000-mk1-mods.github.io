#!/usr/bin/env python3
"""Which hard-coded XDJ-700 v1.15 addresses of a mod have an MK1 v1.13 match.

Reads the mod's source files, pulls every 7-8 digit hex literal >= 0x08000000
and classifies it against the XDJ-700 image (work/funcs_700.json):

  soc       SH7724 register (0xA4xxxxxx, 0xFExxxxxx, 0xFFxxxxxx): same SoC,
            same address on MK1
  cave      inside the mod's own allocation in the 700 image's zero run
            (RO.CAVE .. ZERO_END): needs a free run on MK1, not a mapping
  func      start of a 700 function -> its MK1 match (work/map_700_to_mk1.json)
  in-func   inside a 700 function: same offset on MK1 only if the matched
            pair's signatures are identical, else unverified
  pool      literal-pool slot of a 700 function (the hook mechanism): the
            MK1 slot at the same literal index of the matched function, when
            both have the same literal count
  ram       RAM variable (above the image, below 0x18000000): every 700
            function that loads it from a pool votes for the literal at the
            same index in its MK1 match; agreeing votes are the evidence
  data      other image address: unique 16-byte signature search in MK1
Plus the byte-level dependencies of the flash mods (version_tag, boot_banner).

    usage: python3 mk1/coverage.py MOD    (writes mk1/coverage_MOD.md)
"""
import json
import os
import re
import struct
import sys
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]

BASE = 0x08000000
CAVE, ZERO_END = 0x081D8900, 0x081E03EB          # tools/rgb_overview.py, perform_pads.py
MODS = {
    "version_tag": ["mods/version_tag.py"],
    "boot_banner": ["mods/boot_banner.py", "tools/litpatch.py"],
    "rgb3band": ["tools/rgb_overview.py", "tools/rgb_overview_apply.py", "tools/rgb_detail.py",
                 "tools/rgb_detail_apply.py", "tools/centre/cw.c", "tools/centre/build.sh"],
    "perform_pads": ["tools/perform_pads.py", "tools/perform_pads_apply.py",
                     "tools/rgb_overview.py", "tools/vredirect.py", "tools/mysettings.py"],
}
CONF_RANK = {"high": 3, "medium": 2, "low": 1, "verified (emulator)": 4}
# constants that look like addresses but are values (checked in the source)
MAGIC = {0x12345678: "test pattern (perform_pads_apply LW self-test value), not an address"}


def phys(v):
    return v & 0x1FFFFFFF if v >> 29 in (4, 5) else v


def load_funcs(p):
    d = json.load(open(p))
    fs = sorted((int(f["addr"], 16), f) for f in d["functions"])
    return [a for a, _ in fs], {a: f for a, f in fs}


def containing(starts, funcs, a):
    import bisect
    i = bisect.bisect_right(starts, a) - 1
    if i >= 0:
        s = starts[i]
        if s <= a < s + funcs[s]["size"]:
            return s
    return None


class Ctx:
    def __init__(self):
        w = lambda p: os.path.join(ROOT, p)
        self.img7 = open(w("work/MAIN_700_115.img"), "rb").read()
        self.img1 = open(w("work/MAIN_mk1_113.img"), "rb").read()
        self.s7, self.f7 = load_funcs(w("work/funcs_700.json"))
        self.s1, self.f1 = load_funcs(w("work/funcs_mk1.json"))
        m = json.load(open(w("work/map_700_to_mk1.json")))["map"]
        self.map = {int(e["a"], 16): e for e in m}
        self.slot7 = {}                      # pool slot -> (func, index)
        self.byval = defaultdict(list)       # literal value -> [(func, index)]
        for s, f in self.f7.items():
            for i, (pa, v) in enumerate(f["lits"]):
                self.slot7.setdefault(int(pa, 16), (s, i))
                self.byval[int(v, 16)].append((s, i))

    def mk1_of(self, a7):
        e = self.map.get(a7)
        return (int(e["b"], 16), e) if e else (None, None)

    def classify(self, v):
        p = phys(v)
        if v in MAGIC:
            return dict(kind="other", mk1=None, conf="n/a", note=MAGIC[v])
        if v >= 0xFE000000 or 0xA4000000 <= v < 0xA8000000 or v >= 0xE0000000:
            return dict(kind="soc", mk1=f"{v:#010x}", conf="high",
                        note="SH7724 register; MK1 is the same SoC")
        end7 = BASE + len(self.img7)
        if BASE <= p < end7:
            if CAVE <= p <= ZERO_END:
                return dict(kind="cave", mk1=None, conf="n/a",
                            note=f"mod allocation at cave+{p - CAVE:#x}")
            if p in self.slot7:
                s, i = self.slot7[p]
                return self.pool(p, s, i)
            if p in self.f7:
                b, e = self.mk1_of(p)
                if b is None:
                    return dict(kind="func", mk1=None, conf="none",
                                note=f"700 function {p:#010x} unmatched")
                return dict(kind="func", mk1=f"{b:#010x}", conf=e["confidence"],
                            note=f"{e['method']}: {e['evidence']}"
                            + ("; OUT OF ORDER" if e.get("out_of_order") else ""))
            s = containing(self.s7, self.f7, p)
            if s is not None:
                off = p - s
                b, e = self.mk1_of(s)
                if b is None:
                    return dict(kind="in-func", mk1=None, conf="none",
                                note=f"in 700 function {s:#010x}+{off:#x}, which is unmatched")
                same = self.f7[s]["sig"] == self.f1[b]["sig"]
                if same:
                    return dict(kind="in-func", mk1=f"{b + off:#010x}",
                                conf=e["confidence"],
                                note=f"{s:#010x}+{off:#x}; matched {e['method']}, "
                                     "signatures identical so the offset holds")
                return dict(kind="in-func", mk1=f"{b + off:#010x}?", conf="low",
                            note=f"{s:#010x}+{off:#x} -> {b:#010x} ({e['method']}), "
                                 "bodies differ: offset UNVERIFIED")
            return self.data(p)
        if end7 <= p < 0x18000000:
            return self.ram(v)
        return dict(kind="other", mk1=None, conf="n/a", note="not an address in a known range")

    def pool(self, p, s, i):
        b, e = self.mk1_of(s)
        val7 = self.f7[s]["lits"][i][1]
        if b is None:
            return dict(kind="pool", mk1=None, conf="none",
                        note=f"slot #{i} of 700 function {s:#010x} (value {val7}); function unmatched")
        l7, l1 = self.f7[s]["lits"], self.f1[b]["lits"]
        if len(l7) != len(l1):
            return dict(kind="pool", mk1=None, conf="low",
                        note=f"slot #{i} of {s:#010x}->{b:#010x}: literal counts differ "
                             f"({len(l7)}/{len(l1)}), slot not derivable")
        slot1, val1 = l1[i]
        # the stock value in the slot should itself map 700 -> MK1
        tv = int(val7, 16)
        tb, _ = self.mk1_of(phys(tv))
        agree = tb is not None and (phys(int(val1, 16)) == tb)
        conf = e["confidence"] if agree else ("low" if tb is None else "low")
        return dict(kind="pool", mk1=slot1, conf=conf,
                    note=f"slot #{i} of {s:#010x}->{b:#010x} ({e['method']}); stock value "
                         f"{val7} -> MK1 {val1}" + ("; value maps consistently" if agree
                                                     else "; value mapping NOT confirmed"))

    def ram(self, v):
        votes, users = Counter(), 0
        for s, i in self.byval.get(v, []):
            b, e = self.mk1_of(s)
            if b is None:
                continue
            l7, l1 = self.f7[s]["lits"], self.f1[b]["lits"]
            if len(l7) != len(l1):
                continue
            users += 1
            votes[int(l1[i][1], 16)] += 1
        n_ref = len(self.byval.get(v, []))
        if not votes:
            return dict(kind="ram", mk1=None, conf="none",
                        note=f"{n_ref} 700 function(s) load it; none with a usable MK1 match")
        (best, k), = votes.most_common(1)
        dissent = users - k
        conf = "high" if k >= 3 and not dissent else "medium" if not dissent else "low"
        return dict(kind="ram", mk1=f"{best:#010x}", conf=conf,
                    note=f"{k}/{users} matched loader functions agree (of {n_ref} 700 users)"
                         + (f"; {dissent} DISSENT {dict(votes)}" if dissent else ""))

    def data(self, p):
        o = p - BASE
        sig = self.img7[o:o + 16]
        if sig.count(0) > 12 or len(set(sig)) < 4:
            return dict(kind="data", mk1=None, conf="none",
                        note="700 bytes too uniform for a signature")
        hits = [m.start() for m in re.finditer(re.escape(sig), self.img1)]
        if len(hits) == 1 and len(re.findall(re.escape(sig), self.img7)) == 1:
            return dict(kind="data", mk1=f"{BASE + hits[0]:#010x}", conf="medium",
                        note="unique 16-byte signature in both images")
        return dict(kind="data", mk1=None, conf="none",
                    note=f"16-byte signature found {len(hits)}x in MK1")


def hex_refs(paths):
    seen = {}
    for p in paths:
        for ln, line in enumerate(open(os.path.join(ROOT, p)), 1):
            for m in re.finditer(r"\b0x([0-9A-Fa-f]{7,8})\b", line):
                v = int(m.group(1), 16)
                if v < BASE or v in (0xFFFFFFFF,):
                    continue
                seen.setdefault(v, (p, ln, line.strip()[:90]))
    return seen


def zero_runs(img, need):
    """[(start, end)] of zero runs >= need bytes, 16-aligned starts, largest first."""
    out = [(m.start(), m.end()) for m in re.finditer(rb"\x00{%d,}" % need, img)]
    out = [((s + 15) & ~15, e) for s, e in out]
    return sorted([r for r in out if r[1] - r[0] >= need], key=lambda r: r[0] - r[1])


# ---- byte-level dependencies of the two flash mods ---------------------------
def flash_blocks(flash):
    """(hdr, len) of every block the boot stub would accept (len + sum16)."""
    out, n = [], len(flash)
    for h in range(0, n - 8, 4):
        ln = struct.unpack_from("<I", flash, h)[0]
        if not (1024 < ln and h + 6 + ln <= n):
            continue
        if (sum(flash[h:h + 4 + ln]) & 0xFFFF) == struct.unpack_from("<H", flash, h + 4 + ln)[0]:
            out.append((h, ln))
    return out


def literal_map(src):
    from litpatch import map_literals
    return map_literals(src)


def flash_of(model):
    from unpack_mk1 import main_section, flash_from_section
    p = {"700": "../../FW/XDJ700/XDJ700.UPD", "mk1": "../../FW/XDJ1000/XDJ1000.UPD"}[model]
    _, sec = main_section(open(os.path.join(ROOT, p), "rb").read())
    f, _ = flash_from_section(sec)
    j = len(f)
    while j and f[j - 1] == 0xFF:
        j -= 1
    return bytes(f[:j + 2])


def flash_checks(mod):
    sys.path.insert(0, HERE)
    rows = []
    for model, anchor in (("700", b"XDJ-700"), ("mk1", b"XDJ-1000")):
        fl = flash_of(model)
        blks = []
        for h, ln in sorted(flash_blocks(fl)):
            if blks and h < blks[-1][0] + blks[-1][1]:
                continue
            blks.append((h, ln))
        rows.append(f"- **{model}** flash: {len(blks)} boot-validated blocks at "
                    + ", ".join(f"{h:#x} (len {ln:#x})" for h, ln in blks))
        for h, ln in blks:
            dec, lit = literal_map(fl[h + 4:h + 4 + ln])
            if mod == "version_tag" and h == blks[0][0]:
                i = dec.find(anchor)
                pad = dec[i + len(anchor):i + len(anchor) + 4] if i >= 0 else b""
                rows.append(f"  - blk00 @ {h:#x}: `{anchor.decode()}` "
                            + (f"at +{i:#x}, followed by {pad!r} -> "
                               + ("4 bytes of space padding: tag fits" if pad == b"    "
                                  else "NO 4-byte padding") if i >= 0 else "NOT FOUND"))
            if mod == "boot_banner":
                t = b"IDLE stack error"
                i = dec.find(t)
                if i >= 0:
                    miss = sum(1 for k in range(len(t)) if i + k not in lit)
                    rows.append(f"  - block @ {h:#x}: `IDLE stack error` at +{i:#x}, "
                                + ("all 16 bytes literal-encoded: patch applies"
                                   if not miss else f"{miss} bytes match-encoded: patch REFUSES"))
    return rows


def traced(v):
    """A mapping found by tracing (mk1/traced_map.json) wins over the static
    classification: it carries behaviour evidence from the emulator."""
    p = os.path.join(HERE, "traced_map.json")
    if not os.path.exists(p):
        return None
    for group, items in json.load(open(p)).items():
        if not isinstance(items, dict):
            continue
        for name, e in items.items():
            if isinstance(e, dict) and "700" in e and phys(int(e["700"], 16)) == phys(v):
                return dict(kind="traced/" + group, mk1=e["mk1"],
                            conf="UNVERIFIED" if e.get("unverified") else "verified (emulator)",
                            note=f"{name}: " + e.get("behaviour", e.get("evidence", "")))
    return None


def main():
    mod = sys.argv[1]
    c = Ctx()
    refs = hex_refs(MODS[mod])
    rows = []
    for v, (p, ln, line) in sorted(refs.items()):
        r = traced(v) or c.classify(v)
        rows.append((v, p, ln, line, r))
    kinds = Counter(r["kind"] for *_, r in rows)
    need = [r for *_, r in rows if r["kind"] not in ("cave", "soc", "other")]
    have = [r for r in need if r["mk1"] and not str(r["mk1"]).endswith("?")]
    good = [r for r in have if CONF_RANK.get(r["conf"], 0) >= 2]
    md = [f"# Coverage: {mod} (XDJ-700 v1.15 -> XDJ-1000 MK1 v1.13)", "",
          "Generated by `mk1/coverage.py`. Sources: " + ", ".join(f"`{p}`" for p in MODS[mod]) + ".",
          "Map: `work/map_700_to_mk1.json` (funcscan + match). Nothing here is verified on hardware.", ""]
    if mod in ("version_tag", "boot_banner"):
        md += ["## Byte-level dependencies (flash mod, no firmware addresses)", ""]
        md += flash_checks(mod) + [""]
    caves = [v for v, *_ in [(v,) for v in refs] if CAVE <= phys(v) <= ZERO_END]
    if caves:
        cave_len = ZERO_END - CAVE                 # ZERO_END is exclusive
        runs = zero_runs(c.img1, cave_len)
        md += ["## Cave (the mod's own code/data space)", "",
               f"On the 700 the mods use the zero run {CAVE:#010x}..{ZERO_END:#010x} "
               f"({cave_len:#x} bytes). MK1 zero runs of at least that size "
               "(candidates only: upstream proved its cave free by junk-filling it in the emulator, "
               "'0 px changed'; not done for MK1 yet):", ""]
        md += [f"- `{BASE + s:#010x}`..`{BASE + e - 1:#010x}` ({e - s:#x} bytes)" for s, e in runs[:8]]
        md += ["- none" if not runs else "", ""]
    md += [f"## Hard-coded addresses: {len(rows)}", "",
           f"By kind: {dict(kinds)}. Firmware addresses that need a mapping: {len(need)}; "
           f"MK1 candidate found: {len(have)}; of those medium/high confidence: {len(good)}.", ""]
    if rows:
        md += ["| 700 address | kind | MK1 | confidence | evidence | where |",
               "|---|---|---|---|---|---|"]
        for v, p, ln, line, r in rows:
            md.append(f"| `{v:#010x}` | {r['kind']} | {('`' + r['mk1'] + '`') if r['mk1'] else '—'} "
                      f"| {r['conf']} | {r['note'].replace('|', '/')} | `{os.path.basename(p)}:{ln}` |")
    notes = os.path.join(HERE, f"coverage_{mod}.notes.md")
    if os.path.exists(notes):
        md += ["", open(notes).read().rstrip()]
    out = os.path.join(HERE, f"coverage_{mod}.md")
    open(out, "w").write("\n".join(md) + "\n")
    print(f"{mod}: {len(rows)} addresses {dict(kinds)}; need {len(need)}, "
          f"MK1 candidate {len(have)}, medium+ {len(good)} -> {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
