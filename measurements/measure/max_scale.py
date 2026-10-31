"""The frontier, with each formula scored by its closest part.

Leave-one-out matters more here than anywhere: the example being searched for
is itself one of the documents, so it has to be excluded or the test shows only
that a string finds itself.
"""
import os
import json, random, statistics

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
d = json.load(open(S + "/embed_max.json"))
desc, exs, pos, negs = {}, {}, [], []
for (k, a, b), v in zip(d["meta"], d["vec"]):
    if k == "desc":  desc[a] = v
    elif k == "ex":  exs.setdefault(a, {})[b] = v
    elif k == "pos": pos.append((a, b, v))
    else:            negs.append(v)

NF, TOP_N = len(desc), 3
dot = lambda a, b: sum(x * y for x, y in zip(a, b))

def score(q, i, skip=None):
    """A formula's closest part to this title, that example aside."""
    best = dot(q, desc[i])
    for j, v in exs.get(i, {}).items():
        if j == skip:
            continue
        best = max(best, dot(q, v))
    return best

GRID = [3, 8, 12, 20, 30, 44, 56]
CUTS = [0.55, 0.60, 0.65, 0.70, 0.75]
K, allf = 6, list(range(NF))
rng = random.Random(56)

bp = [max(score(q, k, skip=j if k == i else None) for k in allf) for i, j, q in pos]
bn = [max(score(q, k) for k in allf) for q in negs]
print("best-matching part at all %d formulas:" % NF)
print("  real titles      median %.3f   10th pct %.3f"
      % (statistics.median(bp), sorted(bp)[len(bp) // 10]))
print("  uncovered titles median %.3f   90th pct %.3f\n"
      % (statistics.median(bn), sorted(bn)[9 * len(bn) // 10]))

print("          " + "".join("   cut %.2f  " % c for c in CUTS))
print("   N      " + "".join("  rec  sil  " for _ in CUTS))
for N in GRID:
    acc = {c: ([], []) for c in CUTS}
    for _ in range(K if N < NF else 1):
        sub = allf if N >= NF else rng.sample(allf, N)
        ss = set(sub)
        ok = {c: 0 for c in CUTS}; tot = 0
        for i, j, q in pos:
            if i not in ss:
                continue
            tot += 1
            sc = sorted(((score(q, k, skip=j if k == i else None), k)
                         for k in sub), reverse=True)
            for c in CUTS:
                ok[c] += i in [k for s, k in sc if s >= c][:TOP_N]
        qt = {c: 0 for c in CUTS}
        for q in negs:
            m = max(score(q, k) for k in sub)
            for c in CUTS:
                qt[c] += m < c
        for c in CUTS:
            if tot:
                acc[c][0].append(ok[c] / tot)
            acc[c][1].append(qt[c] / len(negs))
    print("  %3d      " % N + "".join(
        " %.2f %.2f  " % (statistics.mean(acc[c][0]), statistics.mean(acc[c][1]))
        for c in CUTS))
