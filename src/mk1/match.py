#!/usr/bin/env python3
"""Match functions between two images from mk1/funcscan.py output.

Strongest evidence first; the map stays 1:1 and nothing is guessed:
  a. string     both functions are the only referrer of the same string, in
                both images, and every such anchor agrees (no conflicts)
  b. sig        identical masked signature, unique on both sides, >= MIN_SIG
                instructions
  c. callgraph  a matched pair whose resolved call lists have the same length:
                callees at the same position are paired, provided every
                position already matched agrees and no other pair proposes a
                different partner; repeated until nothing new
  d. the rest stays unmatched
Every match off the longest address-ordered chain gets "out_of_order": true.

Confidence:
  string     high if >= 2 anchors or the signatures are also identical, else medium
  sig        high if >= 24 instructions, else medium
  callgraph  medium if the caller pair is high and the sizes are within 2x
             (or the signatures are identical), else low

    usage: python3 mk1/match.py A.json B.json OUT.json
           python3 mk1/match.py --triangle 700.json mk2.json mk1.json
"""
import bisect
import json
import sys
from collections import defaultdict

MIN_SIG = 8
MIN_STR = 6


def load(p):
    d = json.load(open(p))
    f = {int(x["addr"], 16): x for x in d["functions"]}
    for x in f.values():
        x["_calls"] = [int(c, 16) for c in x["calls"] if c]
    return d, f


class Map:
    def __init__(self):
        self.ab, self.ba, self.info = {}, {}, {}

    def add(self, a, b, method, conf, note):
        if a in self.ab or b in self.ba:
            return False
        self.ab[a], self.ba[b] = b, a
        self.info[a] = (method, conf, note)
        return True


def match(fa, fb):
    m = Map()
    # a. unique string anchors
    def uniq(f):
        refs = defaultdict(set)
        for a, x in f.items():
            for s in x["strings"]:
                if len(s.lstrip("u:")) >= MIN_STR:
                    refs[s].add(a)
        return {s: next(iter(v)) for s, v in refs.items() if len(v) == 1}
    ua, ub = uniq(fa), uniq(fb)
    cand = defaultdict(lambda: defaultdict(list))
    for s, a in ua.items():
        if s in ub:
            cand[a][ub[s]].append(s)
    back = defaultdict(set)
    for a, bs in cand.items():
        for b in bs:
            back[b].add(a)
    for a, bs in sorted(cand.items()):
        if len(bs) != 1:
            continue                                    # anchors disagree
        b, ss = next(iter(bs.items()))
        if len(back[b]) != 1:
            continue
        same = fa[a]["sig"] == fb[b]["sig"]
        conf = "high" if len(ss) >= 2 or same else "medium"
        m.add(a, b, "string", conf,
              f"{len(ss)} unique string(s), e.g. {ss[0][:40]!r}" + ("; sig identical" if same else ""))
    n_str = len(m.ab)

    # b. unique masked signatures
    def sigs(f):
        by = defaultdict(list)
        for a, x in f.items():
            if x["insns"] >= MIN_SIG:
                by[x["sig"]].append(a)
        return {s: v[0] for s, v in by.items() if len(v) == 1}
    sa, sb = sigs(fa), sigs(fb)
    for s, a in sa.items():
        if s in sb:
            n = fa[a]["insns"]
            m.add(a, sb[s], "sig", "high" if n >= 24 else "medium",
                  f"identical masked signature, {n} insns, unique in both images")
    n_sig = len(m.ab) - n_str

    # c. call-graph spread
    rounds = 0
    while True:
        rounds += 1
        prop = defaultdict(set)
        why = {}
        for a, b in list(m.ab.items()):
            ca, cb = fa[a]["_calls"], fb[b]["_calls"]
            if not ca or len(ca) != len(cb):
                continue
            pairs = list(zip(ca, cb))
            if any((x in m.ab and m.ab[x] != y) or (y in m.ba and m.ba[y] != x)
                   for x, y in pairs):
                continue                                # lists disagree
            local = defaultdict(set)
            for x, y in pairs:
                local[x].add(y)
            if any(len(v) > 1 for v in local.values()):
                continue
            for x, y in pairs:
                if x not in m.ab and y not in m.ba and x in fa and y in fb:
                    prop[x].add(y)
                    why.setdefault((x, y), a)
        rback = defaultdict(set)
        for x, ys in prop.items():
            for y in ys:
                rback[y].add(x)
        new = 0
        for x, ys in prop.items():
            if len(ys) != 1:
                continue
            y = next(iter(ys))
            if len(rback[y]) != 1:
                continue
            parent = why[(x, y)]
            pconf = m.info[parent][1]
            nx, ny = fa[x]["insns"], fb[y]["insns"]
            same = fa[x]["sig"] == fb[y]["sig"]
            ok_size = same or (max(nx, ny) <= 2 * max(1, min(nx, ny)))
            conf = "medium" if pconf == "high" and ok_size else "low"
            if m.add(x, y, "callgraph", conf,
                     f"callee of {parent:#010x}->{m.ab[parent]:#010x} at same call position; "
                     f"{nx}/{ny} insns" + ("; sig identical" if same else "")):
                new += 1
        if not new:
            break
    n_cg = len(m.ab) - n_str - n_sig
    stats = {"functions_a": len(fa), "functions_b": len(fb), "string": n_str,
             "sig": n_sig, "callgraph": n_cg, "callgraph_rounds": rounds,
             "matched": len(m.ab), "unmatched_a": len(fa) - len(m.ab),
             "unmatched_b": len(fb) - len(m.ab)}
    return m, stats


def in_order(m):
    """Matches on the longest chain that is increasing in both images. The
    builds share layout, so a match off that chain is suspect (not dropped:
    flagged, so a reader can look)."""
    a_sorted = sorted(m.ab)
    b = [m.ab[a] for a in a_sorted]
    tails, tidx, prev = [], [], [-1] * len(b)
    for i, v in enumerate(b):
        k = bisect.bisect_left(tails, v)
        if k == len(tails):
            tails.append(v); tidx.append(i)
        else:
            tails[k] = v; tidx[k] = i
        prev[i] = tidx[k - 1] if k else -1
    keep, i = set(), (tidx[-1] if tidx else -1)
    while i != -1:
        keep.add(a_sorted[i]); i = prev[i]
    return keep


def write(m, stats, da, db, out):
    conf = defaultdict(int)
    for v in m.info.values():
        conf[v[1]] += 1
    stats["by_confidence"] = dict(conf)
    order = in_order(m)
    stats["out_of_order"] = len(m.ab) - len(order)
    entries = []
    for a in sorted(m.ab):
        e = {"a": f"{a:#010x}", "b": f"{m.ab[a]:#010x}", "method": m.info[a][0],
             "confidence": m.info[a][1], "evidence": m.info[a][2]}
        if a not in order:
            e["out_of_order"] = True
        entries.append(e)
    json.dump({"a": da["name"], "b": db["name"], "a_sha256": da["sha256"],
               "b_sha256": db["sha256"], "stats": stats, "map": entries},
              open(out, "w"), indent=1)
    print(f"{da['name']} -> {db['name']}: {stats}")


def main():
    if sys.argv[1] == "--triangle":
        p7, p2, p1 = sys.argv[2:5]
        (d7, f7), (d2, f2), (d1, f1) = load(p7), load(p2), load(p1)
        m71, s71 = match(f7, f1)
        m21, s21 = match(f2, f1)
        m72, s72 = match(f7, f2)
        write(m71, s71, d7, d1, "work/map_700_to_mk1.json")
        write(m21, s21, d2, d1, "work/map_mk2_to_mk1.json")
        write(m72, s72, d7, d2, "work/map_700_to_mk2.json")
        # cross-check: 700 -> MK1 directly vs 700 -> MK2 -> MK1
        agree, disagree = 0, []
        for a, b1 in m71.ab.items():
            b2 = m72.ab.get(a)
            if b2 is None or b2 not in m21.ab:
                continue
            via = m21.ab[b2]
            if via == b1:
                agree += 1
            else:
                disagree.append({"700": f"{a:#010x}", "mk1_direct": f"{b1:#010x}",
                                 "mk2": f"{b2:#010x}", "mk1_via_mk2": f"{via:#010x}",
                                 "direct": m71.info[a][:2], "via_700_mk2": m72.info[a][:2],
                                 "via_mk2_mk1": m21.info[b2][:2]})
        json.dump({"agree": agree, "disagree": disagree},
                  open("work/map_crosscheck.json", "w"), indent=1)
        print(f"cross-check: {agree} agree, {len(disagree)} disagree "
              f"-> work/map_crosscheck.json")
        return 0
    (da, fa), (db, fb) = load(sys.argv[1]), load(sys.argv[2])
    m, stats = match(fa, fb)
    write(m, stats, da, db, sys.argv[3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
