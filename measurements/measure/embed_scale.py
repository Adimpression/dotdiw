"""The same two curves, with a local embedding model instead of bm25.

Vectors are already L2-normalised, so cosine is a dot product. The cutoff is
swept rather than chosen, because picking one and reporting it is how the
earlier measurements flattered themselves.

The question is narrow: is there any cutoff at which recall stays near bm25's
0.93 and silence does NOT collapse as formula count rises?
"""
import os
import json, random, statistics, sys

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
d = json.load(open(S + "/embed.json"))
meta, vec = d["meta"], d["vec"]

docs, loo, pos, negs = {}, {}, [], []
for (kind, a, b), v in zip(meta, vec):
    if kind == "doc":      docs[a] = v
    elif kind == "doc_loo": loo[(a, b)] = v
    elif kind == "pos":     pos.append((a, b, v))
    else:                   negs.append(v)

NF = len(docs)
TOP_N = 3
def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

print("%d formula documents, %d positives, %d negatives, dim %d\n"
      % (NF, len(pos), len(negs), len(vec[0])))

# where do the two populations actually sit?
best_pos, best_neg = [], []
allf = list(range(NF))
for i, j, q in pos:
    best_pos.append(max(dot(q, loo[(i, j)] if k == i else docs[k])
                        for k in allf))
for q in negs:
    best_neg.append(max(dot(q, docs[k]) for k in allf))
print("best-match cosine at all %d formulas:" % NF)
print("  real titles      median %.3f   10th pct %.3f"
      % (statistics.median(best_pos), sorted(best_pos)[len(best_pos) // 10]))
print("  uncovered titles median %.3f   90th pct %.3f"
      % (statistics.median(best_neg), sorted(best_neg)[9 * len(best_neg) // 10]))

GRID = [3, 8, 12, 20, 30, 44, 56]
CUTS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]
K = 6
rng = random.Random(56)

print("\n          " + "".join("   cut %.2f  " % c for c in CUTS))
print("   N      " + "".join("  rec  sil  " for _ in CUTS))
for N in GRID:
    acc = {c: ([], []) for c in CUTS}
    for _ in range(K if N < NF else 1):
        sub = allf if N >= NF else rng.sample(allf, N)
        subset = set(sub)
        ok = {c: 0 for c in CUTS}; tot = 0
        for i, j, q in pos:
            if i not in subset:
                continue
            tot += 1
            scored = sorted(((dot(q, loo[(i, j)] if k == i else docs[k]), k)
                             for k in sub), reverse=True)
            for c in CUTS:
                top = [k for s, k in scored if s >= c][:TOP_N]
                ok[c] += i in top
        quiet = {c: 0 for c in CUTS}
        for q in negs:
            m = max(dot(q, docs[k]) for k in sub)
            for c in CUTS:
                quiet[c] += m < c
        for c in CUTS:
            if tot:
                acc[c][0].append(ok[c] / tot)
            acc[c][1].append(quiet[c] / len(negs))
    row = "  %3d      " % N
    for c in CUTS:
        r = statistics.mean(acc[c][0]) if acc[c][0] else float("nan")
        row += " %.2f %.2f  " % (r, statistics.mean(acc[c][1]))
    print(row)
