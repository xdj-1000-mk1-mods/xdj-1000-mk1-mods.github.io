#!/usr/bin/env python3
"""Line up what one action executes on the XDJ-700 and on MK1 (tbcov traces).

    align.py ACTION700:ACTIONMK1 [...]      -> work/trace/align.json

Per pair: each side's functions beyond its own baselines (mk1/trace_diff.py),
in first-execution order. Known pairs come from work/map_700_to_mk1.json and
mk1/traced_map.json (today's trace/behaviour mappings). A known pair seen on
only one side of an action is flagged. Between two consecutive known pairs
present on both sides, unknown functions are lined up in order and reported
as candidates -- trace order alone, so always "unverified".
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import trace_diff as T                                          # noqa: E402


def known_pairs():
    k = {}
    for e in json.load(open(os.path.join(ROOT, "work", "map_700_to_mk1.json")))["map"]:
        k[int(e["a"], 16)] = (int(e["b"], 16), "map:" + e["method"] + "/" + e["confidence"])
    p = os.path.join(HERE, "traced_map.json")
    if os.path.exists(p):
        for name, e in json.load(open(p))["functions"].items():
            k[int(e["700"], 16)] = (int(e["mk1"], 16), "traced:" + name)
    return k


def side(model, act, bases):
    rows = T.diff(model, [act], bases)[act]
    return [(int(r["func"], 16), r["first"]) for r in rows if not r["func"].startswith("tb:")]


def align(a7, a1, K):
    s7 = side("xdj700", a7, ["base1", "base2", "base3"] if not a7.startswith(("perf_open",)) else ["mbase1", "mbase2"])
    s1 = side("xdj1000", a1, ["base1", "base2", "base3"] if not a1.startswith(("perf_open",)) else ["mbase1", "mbase2"])
    f1 = {f for f, _ in s1}
    f7 = {f for f, _ in s7}
    both, only7, only1 = [], [], []
    for f, _ in s7:
        if f in K:
            (both if K[f][0] in f1 else only7).append((f, K[f][0], K[f][1]))
    inv = {v[0]: a for a, v in K.items()}
    for f, _ in s1:
        if f in inv and inv[f] not in f7:
            only1.append((inv[f], f))
    # order-alignment of unknowns between consecutive anchors
    anchors = [(a, b) for a, b, _ in both]
    pos7 = {f: i for i, (f, _) in enumerate(s7)}
    pos1 = {f: i for i, (f, _) in enumerate(s1)}
    cands = []
    seq = sorted(anchors, key=lambda p: pos7[p[0]])
    for (a0, b0), (a_1, b_1) in zip([(None, None)] + seq, seq + [(None, None)]):
        lo7 = pos7[a0] + 1 if a0 else 0
        hi7 = pos7[a_1] if a_1 else len(s7)
        lo1 = pos1[b0] + 1 if b0 in pos1 else 0
        hi1 = pos1[b_1] if b_1 in pos1 else len(s1)
        u7 = [f for f, _ in s7[lo7:hi7] if f not in K]
        u1 = [f for f, _ in s1[lo1:hi1] if f not in inv]
        if u7 and len(u7) == len(u1):
            cands += list(zip(u7, u1))
    return {"700": a7, "mk1": a1, "n700": len(s7), "nmk1": len(s1),
            "known_on_both": [(f"{a:#010x}", f"{b:#010x}", why) for a, b, why in both],
            "known_only_700": [(f"{a:#010x}", f"{b:#010x}", why) for a, b, why in only7],
            "known_only_mk1": [(f"{a:#010x}", f"{b:#010x}") for a, b in only1],
            "order_candidates_unverified": [(f"{a:#010x}", f"{b:#010x}") for a, b in cands]}


def main(av):
    K = known_pairs()
    out = []
    for pair in av:
        a7, a1 = pair.split(":")
        r = align(a7, a1, K)
        out.append(r)
        print(f"{a7} (700, {r['n700']} new) <-> {a1} (MK1, {r['nmk1']} new): "
              f"{len(r['known_on_both'])} known pairs on both sides, "
              f"{len(r['known_only_700'])} only-700, {len(r['known_only_mk1'])} only-MK1, "
              f"{len(r['order_candidates_unverified'])} order candidates")
    json.dump(out, open(os.path.join(ROOT, "work", "trace", "align.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
