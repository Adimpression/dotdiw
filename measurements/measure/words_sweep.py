"""One shared word is a coincidence; two is a topic.

A higher COVERAGE cannot separate the real matches from the coincidences -- at
0.40, 32 of 33 uncovered titles go quiet but 41 of 128 examples stop finding
their own formula. Test a second condition instead: how many of the title's
own distinctive words the formula actually has to hold.
"""
import os
import importlib.util, importlib.machinery, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)
S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
sys.path.insert(0, S)
from cover_sweep import NEG

def search(idx, text, floor, minw):
    """idx.search, plus a floor on how many query words are held."""
    words = dd.toks(text)
    if not words or not idx.forms:
        return []
    match = " OR ".join('"%s"' % w for w in words)
    try:
        rows = idx.db.execute(idx.sql, (match, len(idx.forms))).fetchall()
    except Exception:
        return []
    total = sum(idx.weight(w) for w in words)
    if not total:
        return []
    out = []
    for rowid, score in rows:
        hit = [w for w in words if rowid in idx.spread(w)[0]]
        if len(hit) < minw:
            continue
        if sum(idx.weight(w) for w in hit) / total >= floor:
            out.append((score, idx.forms[rowid - 1]))
    out.sort(key=lambda r: (-r[0], r[1]["name"]))
    return out

runs = [l.rstrip("\n").split("\t") for l in open(S + "/runmap4.tsv")]
FIX = [(S + "/sim/acme-api", "acme"), (S + "/stress", "stress")]

print("  minwords  COVERAGE   examples retrieving   uncovered titles silent")
best = []
for minw in (1, 2, 3):
    for th in (0.10, 0.15, 0.20, 0.25, 0.30):
        ok = tot = quiet = qtot = 0
        for rid, proj, st, d in runs:
            forms = dd.load_formulas(d); bg = dd.background(d)
            idx = dd.Index(forms, bg)
            for i, f in enumerate(forms):
                for j, ex in enumerate(f["examples"]):
                    tot += 1
                    ex_f = f["name"]
                    before = " ".join(f["examples"])
                    kept = " ".join(e for k, e in enumerate(f["examples"]) if k != j)
                    idx.db.execute("UPDATE f SET cases = ? WHERE rowid = ?", (kept, i + 1))
                    idx._spread_cache.clear()
                    names = [g["name"] for _, g in search(idx, ex, th, minw)[:dd.TOP_N]]
                    idx.db.execute("UPDATE f SET cases = ? WHERE rowid = ?", (before, i + 1))
                    idx._spread_cache.clear()
                    ok += ex_f in names
            for q in NEG[proj]:
                qtot += 1
                quiet += not search(idx, q, th, minw)
        print("    %d       %.2f        %3d/%-3d               %3d/%-3d"
              % (minw, th, ok, tot, quiet, qtot))
        best.append((minw, th, ok, tot, quiet, qtot))

print("\nthe original fixtures, to check nothing regressed:")
from importlib.machinery import SourceFileLoader
CASES = [("cut-release","Release 1.9 of the billing service"),("cut-release","Get auth out to prod this afternoon"),
 ("cut-release","Tag and ship the current main"),("migrate-schema","We need a new column on customers"),
 ("migrate-schema","Add an index, invoice lookups are slow"),("migrate-schema","Rename the status field in orders"),
 ("incident-response","Checkout is failing for everyone"),("incident-response","Pager fired at 3am, auth is throwing 500s"),
 ("incident-response","Site is down"),("rotate-secrets","The Stripe key is in a public gist"),
 ("rotate-secrets","Offboard Priya and revoke her access"),("rotate-secrets","Time for the quarterly key rotation"),
 (None,"Fix the typo in the README"),(None,"Upgrade the Go version to 1.23"),
 (None,"Write unit tests for the parser"),(None,"Refactor the config loader"),(None,"Update the nginx read timeout")]
for d, label in FIX:
    forms = dd.load_formulas(d); idx = dd.Index(forms, dd.background(d))
    for minw, th in ((1, 0.15), (2, 0.15), (2, 0.10)):
        p = n = pt = nt = 0
        for want, q in CASES:
            names = [g["name"] for _, g in search(idx, q, th, minw)[:dd.TOP_N]]
            if want:
                pt += 1; p += want in names
            else:
                nt += 1; n += not names
        print("  %-7s minwords=%d cover=%.2f  positives %d/%d  negatives quiet %d/%d"
              % (label, minw, th, p, pt, n, nt))
