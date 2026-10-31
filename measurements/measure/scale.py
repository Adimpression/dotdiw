"""Does retrieval hold as the formula count rises?

Formula count is the only thing that varies: the background corpus is the
pooled 123 prose documents in every run, so word weights are fixed. For each
count N, K random subsets are drawn from the 56 pooled formulas and two things
measured on each:

  recall@3  each subset formula's own example titles, with that example removed
            from the index first -- does the formula still come back top three
  silence   33 titles naming real work none of the 56 formulas covers -- does
            anything surface for them

Both are the quantities the whole design rests on, and neither has been
measured above four formulas before.
"""
import os
import importlib.machinery, importlib.util, random, statistics, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
sys.path.insert(0, S)
from cover_sweep import NEG

POOL = S + "/pool"
NEGS = [t for v in NEG.values() for t in v]

forms_all = dd.load_formulas(POOL)
bg = dd.background(POOL)
print("pooled: %d formulas (%d with examples), %d background documents"
      % (len(forms_all), sum(1 for f in forms_all if f["examples"]), len(bg)))
print("negatives: %d titles naming work none of them covers\n" % len(NEGS))

GRID = [3, 5, 8, 12, 20, 30, 44, 56]
K = 8
rng = random.Random(56)

def measure(subset):
    idx = dd.Index(subset, bg)
    ok = tot = 0
    for i, f in enumerate(subset):
        for j, ex in enumerate(f["examples"]):
            tot += 1
            names = [g["name"] for _, g in
                     idx.search_without_example(i, j, ex)[:dd.TOP_N]]
            ok += f["name"] in names
    quiet = sum(1 for q in NEGS if not idx.search(q))
    return (ok / tot if tot else None), quiet / len(NEGS), tot

print("   N   subsets   recall@3            silence on 33 negatives   examples")
for N in GRID:
    rs, qs, ts = [], [], []
    for _ in range(K if N < len(forms_all) else 1):
        sub = (forms_all if N >= len(forms_all)
               else rng.sample(forms_all, N))
        r, q, t = measure(sub)
        if r is not None:
            rs.append(r); ts.append(t)
        qs.append(q)
    print("  %3d   %5d     %.2f  (%.2f-%.2f)      %.2f  (%.2f-%.2f)          %d"
          % (N, len(qs),
             statistics.mean(rs), min(rs), max(rs),
             statistics.mean(qs), min(qs), max(qs),
             int(statistics.mean(ts))))
