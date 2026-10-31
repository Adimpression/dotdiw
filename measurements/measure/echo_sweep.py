"""Sweep ECHO: how close two titles must be to count as the same work.

Positives: two example titles from the SAME formula -- by construction two
phrasings of one procedure, which is exactly the population the nudge is for.
Negatives: two example titles from DIFFERENT formulas in the same project.
Word weights come from each project's own background, as at runtime.
"""
import importlib.util, importlib.machinery, os, sys, glob

spec = importlib.util.spec_from_loader(
    "dd", importlib.machinery.SourceFileLoader("dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
PROJECTS = [S + "/sim/acme-api"] + sorted(glob.glob(S + "/matrix/*/live"))

GRID = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]

pairs = []   # (threshold-independent) (cover, same_formula)
fires = []   # (title, n_hits_at_threshold...) for the ECHO_MIN rule
for root in PROJECTS:
    if not os.path.isdir(root):
        continue
    forms = dd.load_formulas(root)
    if len(forms) < 2:
        continue
    idx = dd.Index(forms, dd.background(root))
    allex = [(i, e) for i, f in enumerate(forms) for e in f["examples"]]
    for i, e in allex:
        others = [(j, t) for j, t in allex if t != e]
        T = dd.Titles([t for _, t in others], idx)
        # raw coverage for every candidate, threshold applied later
        words = dd.toks(e)
        total = sum(idx.weight(w) for w in words) or 1.0
        covs = []
        for k, (j, t) in enumerate(others):
            held = sum(idx.weight(w) for w in words if (k + 1) in T.holders(w))
            covs.append((held / total, j == i))
        pairs.extend(covs)
        fires.append(covs)

print("%d pairs: %d same-formula, %d different"
      % (len(pairs), sum(1 for _, s in pairs if s), sum(1 for _, s in pairs if not s)))
print()
print(" ECHO   pair-recall  pair-FP   fires-correctly  fires-wrongly")
for th in GRID:
    tp = sum(1 for c, s in pairs if s and c >= th)
    pos = sum(1 for _, s in pairs if s)
    fp = sum(1 for c, s in pairs if not s and c >= th)
    neg = len(pairs) - pos
    # operational: with ECHO_MIN=2, does the nudge fire, and is it right?
    good = bad = 0
    for covs in fires:
        hits = [s for c, s in covs if c >= th]
        if len(hits) >= dd.ECHO_MIN:
            if sum(1 for s in hits if s) >= dd.ECHO_MIN:
                good += 1
            else:
                bad += 1
    print(" %.2f    %3d/%-3d      %3d/%-4d   %2d/%-2d            %d"
          % (th, tp, pos, fp, neg, good, len(fires), bad))
