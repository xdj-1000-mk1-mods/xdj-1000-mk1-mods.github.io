#!/usr/bin/env python3
"""Functions an action executed beyond its baseline (tbcov traces).

    trace_diff.py MODEL ACTION [ACTION ...] [--base base1,base2,...] [--json OUT]

For every action trace in work/trace/<model>/: map each executed TB to its
containing function (work/funcs_<fs>.json; a TB outside every known function
is kept as 'tb:<pc>'), drop functions that ran in ANY of the baselines, and
list the rest in first-execution order (tbcov's 4th column) with TB count and
the function's 700<->MK1 map status.
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FS = {"xdj1000": "mk1", "xdj700": "700"}


def phys(v):
    return v & 0x1FFFFFFF if v >> 29 in (4, 5) else v


class Funcs:
    def __init__(self, model):
        d = json.load(open(os.path.join(ROOT, "work", f"funcs_{FS[model]}.json")))
        fs = sorted((int(f["addr"], 16), f) for f in d["functions"])
        self.starts = [a for a, _ in fs]
        self.f = dict(fs)

    def owner(self, pc):
        i = bisect.bisect_right(self.starts, pc) - 1
        if i >= 0:
            s = self.starts[i]
            if s <= pc < s + self.f[s]["size"]:
                return s
        return None


def load(model, name):
    p = os.path.join(ROOT, "work", "trace", model, name + ".txt")
    out = []
    for line in open(p):
        a = line.split()
        out.append((phys(int(a[0], 16)), int(a[1]), int(a[3]) if len(a) > 3 else 0))
    return out


def funcs_of(model, F, name):
    """{function or 'tb:pc': (first, tb count)}"""
    r = {}
    for pc, n, first in load(model, name):
        if not (0x08000000 <= pc < 0x0C000000):
            continue
        k = F.owner(pc)
        k = k if k is not None else f"tb:{pc:#010x}"
        f0, c0 = r.get(k, (first, 0))
        r[k] = (min(f0, first), c0 + n)
    return r


def mapping():
    m = {}
    for e in json.load(open(os.path.join(ROOT, "work", "map_700_to_mk1.json")))["map"]:
        a, b = int(e["a"], 16), int(e["b"], 16)
        m[("xdj700", a)] = (b, e["method"], e["confidence"])
        m[("xdj1000", b)] = (a, e["method"], e["confidence"])
    return m


def diff(model, actions, bases):
    F = Funcs(model)
    base = set()
    for b in bases:
        base |= set(funcs_of(model, F, b))
    M = mapping()
    out = {}
    for act in actions:
        r = funcs_of(model, F, act)
        new = sorted(((v[0], k, v[1]) for k, v in r.items() if k not in base),
                     key=lambda t: (t[0], str(t[1])))
        rows = []
        for first, k, n in new:
            if isinstance(k, int):
                other = M.get((model, k))
                rows.append({"func": f"{k:#010x}", "first": first, "tbs": n,
                             "insns": F.f[k]["insns"], "calls": len(F.f[k]["calls"]),
                             "strings": F.f[k]["strings"][:2],
                             "map": (f"{other[0]:#010x} {other[1]}/{other[2]}" if other else None)})
            else:
                rows.append({"func": k, "first": first, "tbs": n})
        out[act] = rows
    return out


def main(av):
    model = av[0]
    bases = ["base1", "base2", "base3"]
    js = None
    acts = []
    i = 1
    while i < len(av):
        if av[i] == "--base":
            bases = av[i + 1].split(","); i += 2
        elif av[i] == "--json":
            js = av[i + 1]; i += 2
        else:
            acts.append(av[i]); i += 1
    res = diff(model, acts, bases)
    for act, rows in res.items():
        print(f"== {model} {act}: {len(rows)} function(s) beyond baseline {','.join(bases)}")
        for r in rows[:60]:
            extra = f" insns={r['insns']} calls={r['calls']} map={r['map']} {r['strings']}" if "insns" in r else ""
            print(f"   {r['func']}  first={r['first']:>12} tbs={r['tbs']:>6}{extra}")
    if js:
        json.dump(res, open(js, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
