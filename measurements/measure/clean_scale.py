"""Both sweeps again, with the contaminated negatives removed.

The negative set was written when each project held three formulas, as titles
naming work none of them covered. Pooling then added the nine formulas blind
agents wrote -- for exactly those jobs. So the first negative of each project
had become a positive, and both sweeps were scoring correct retrievals as
failures. Those eleven are dropped; the twenty-two remaining are distractors
invented for the purpose and still uncovered.
"""
import os
import importlib.machinery, importlib.util, json, random, statistics, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)
S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
sys.path.insert(0, S)
from cover_sweep import NEG

POOL = S + "/pool"
ALL = [t for v in NEG.values() for t in v]
DROP = {v[0] for v in NEG.values()}          # the job an agent wrote a formula for
KEEP = [t for t in ALL if t not in DROP]
KEEP_IDX = [i for i, t in enumerate(ALL) if t not in DROP]
print("negatives: %d written, %d dropped as now-covered, %d kept\n"
      % (len(ALL), len(ALL) - len(KEEP), len(KEEP)))

forms = dd.load_formulas(POOL)
bg = dd.background(POOL)
GRID = [3, 8, 12, 20, 30, 44, 56]
K = 6

# ---------------------------------------------------------------- bm25
rng = random.Random(56)
print("bm25 + coverage 0.15 (what ships)")
print("   N    recall@3    silence on %d negatives" % len(KEEP))
for N in GRID:
    rs, qs = [], []
    for _ in range(K if N < len(forms) else 1):
        sub = forms if N >= len(forms) else rng.sample(forms, N)
        idx = dd.Index(sub, bg)
        ok = tot = 0
        for i, f in enumerate(sub):
            for j, ex in enumerate(f["examples"]):
                tot += 1
                names = [g["name"] for _, g in
                         idx.search_without_example(i, j, ex)[:dd.TOP_N]]
                ok += f["name"] in names
        if tot:
            rs.append(ok / tot)
        qs.append(sum(1 for q in KEEP if not idx.search(q)) / len(KEEP))
    print("  %3d     %.2f        %.2f  (%.2f-%.2f)"
          % (N, statistics.mean(rs), statistics.mean(qs), min(qs), max(qs)))

# ------------------------------------------------------------ embeddings
d = json.load(open(S + "/embed.json"))
docs, loo, pos, negv = {}, {}, [], {}
for (k, a, b), v in zip(d["meta"], d["vec"]):
    if k == "doc":       docs[a] = v
    elif k == "doc_loo": loo[(a, b)] = v
    elif k == "pos":     pos.append((a, b, v))
    else:                negv[a] = v
negs = [negv[i] for i in KEEP_IDX]
dot = lambda a, b: sum(x * y for x, y in zip(a, b))
allf = list(range(len(docs)))

CUTS = [0.50, 0.55, 0.60, 0.65]
rng = random.Random(56)
print("\nlocal embeddings (nomic-embed-text-v1.5 Q8_0, mean pooled)")
print("          " + "".join("   cut %.2f  " % c for c in CUTS))
print("   N      " + "".join("  rec  sil  " for _ in CUTS))
for N in GRID:
    acc = {c: ([], []) for c in CUTS}
    for _ in range(K if N < len(docs) else 1):
        sub = allf if N >= len(docs) else rng.sample(allf, N)
        ss = set(sub)
        ok = {c: 0 for c in CUTS}; tot = 0
        for i, j, q in pos:
            if i not in ss:
                continue
            tot += 1
            sc = sorted(((dot(q, loo[(i, j)] if k == i else docs[k]), k)
                         for k in sub), reverse=True)
            for c in CUTS:
                ok[c] += i in [k for s, k in sc if s >= c][:dd.TOP_N]
        qt = {c: 0 for c in CUTS}
        for q in negs:
            m = max(dot(q, docs[k]) for k in sub)
            for c in CUTS:
                qt[c] += m < c
        for c in CUTS:
            if tot:
                acc[c][0].append(ok[c] / tot)
            acc[c][1].append(qt[c] / len(negs))
    row = "  %3d      " % N
    for c in CUTS:
        row += " %.2f %.2f  " % (statistics.mean(acc[c][0]),
                                 statistics.mean(acc[c][1]))
    print(row)
