"""Silence has to be judged against the competition, not against a constant.

A fixed fraction cannot hold as a project grows: with N formulas there are N
chances for one of them to clear it by coincidence, so the chance that
something surfaces goes to one. Measured: 0.84 of uncovered titles silent at
three formulas, 0.03 at fifty-six.

The quantity that does not drift is whether the best match stands out from the
others. For a title the project really holds a procedure for, one formula
should score far above the rest; for a title it holds nothing for, they should
all score alike. Test that: keep a formula only when its coverage is an
outlier in the distribution of coverages for this title.
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

def covers(idx, text):
    """Every formula's coverage of this title, not just the ones over a floor."""
    words = dd.toks(text)
    if not words:
        return []
    total = sum(idx.weight(w) for w in words)
    if not total:
        return []
    out = []
    for rowid in range(1, len(idx.forms) + 1):
        held = sum(idx.weight(w) for w in words
                   if rowid in idx.spread(w)[0])
        out.append((held / total, idx.forms[rowid - 1]))
    out.sort(key=lambda r: -r[0])
    return out

def rule_abs(cs, floor=0.15):
    return [f for c, f in cs if c >= floor]

def rule_z(cs, floor=0.15, z=2.0, minn=8):
    """An outlier against the other formulas' coverages for this same title."""
    if len(cs) < minn:
        return rule_abs(cs, floor)
    vals = [c for c, _ in cs]
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) or 1e-9
    return [f for c, f in cs if c >= floor and (c - mu) / sd >= z]

GRID = [3, 8, 12, 20, 30, 44, 56]
K = 6
rng = random.Random(56)

def run(rule, label):
    print("\n%s" % label)
    print("   N    recall@3    silence on 33 negatives")
    for N in GRID:
        rs, qs = [], []
        for _ in range(K if N < len(forms_all) else 1):
            sub = forms_all if N >= len(forms_all) else rng.sample(forms_all, N)
            idx = dd.Index(sub, bg)
            ok = tot = 0
            for i, f in enumerate(sub):
                for j, ex in enumerate(f["examples"]):
                    tot += 1
                    before = " ".join(f["examples"])
                    kept = " ".join(e for k, e in enumerate(f["examples"]) if k != j)
                    idx.db.execute("UPDATE f SET cases=? WHERE rowid=?", (kept, i + 1))
                    idx._spread_cache.clear()
                    keep = rule(covers(idx, ex))
                    idx.db.execute("UPDATE f SET cases=? WHERE rowid=?", (before, i + 1))
                    idx._spread_cache.clear()
                    ok += f["name"] in [g["name"] for g in keep[:dd.TOP_N]]
            if tot:
                rs.append(ok / tot)
            qs.append(sum(1 for q in NEGS if not rule(covers(idx, q))) / len(NEGS))
        print("  %3d     %.2f        %.2f  (%.2f-%.2f)"
              % (N, statistics.mean(rs), statistics.mean(qs), min(qs), max(qs)))

run(rule_abs, "coverage >= 0.15 (what ships)")
for z in (1.5, 2.0, 2.5):
    run(lambda cs, z=z: rule_z(cs, z=z), "outlier: >= 0.15 and z >= %.1f" % z)
