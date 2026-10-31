"""Re-bracket COVERAGE on eleven projects instead of one.

Positives: each formula's own example titles, under leave-one-out -- these must
keep retrieving or discovery is broken.
Negatives: a title per project naming real work the formula set does not cover.
Also reports the background corpus size, because that is the suspected cause:
0.15 was calibrated where the project had 22 documents of its own prose, and
these projects have six.
"""
import os
import importlib.util, importlib.machinery

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")

NEG = {
 "ramen-shop":    ["Hire and train a new kitchen hand", "Fix the leaking tap in the prep sink", "Renew the food hygiene registration"],
 "paws-shelter":  ["Run a weekend fundraising open day", "Service the van before its MOT", "Rewrite the volunteer handbook"],
 "tinybill":      ["Handle the reported security vulnerability in the amount parser", "Set up a code of conduct", "Move the docs to a new static site generator"],
 "edgeops":       ["Bring eu-central-1 into the fleet", "Negotiate the bandwidth contract renewal", "Write the on-call compensation policy"],
 "corpsec":       ["Change the registered office address", "Open a second bank account", "Renew the directors insurance"],
 "vinyl-press":   ["Take on Coldharbour as a customer", "Replace the roof light over the yard", "Hire a second plating operator"],
 "clinic-rota":   ["Take the written complaint through to a response", "Replace the waiting room chairs", "Renegotiate the cleaning contract"],
 "seed-bank":     ["Regenerate CAL-01882, it is below the distribution threshold", "Fix the freezer alarm wiring", "Apply for the heritage grant"],
 "tidepool":      ["Do the quarterly station data refresh", "Renegotiate the analytics vendor contract", "Hire an Android engineer"],
 "grange-farm":   ["Get the sprayer through NSTS and renew the operator certificates", "Repair the gate into Mill Field", "Sell the old grain trailer"],
 "archive-fonds": ["Answer the FOI request on the 1974 boundary review papers", "Replace the reading room lighting", "Run the volunteer recruitment round"],
}

GRID = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
runs = [l.rstrip("\n").split("\t") for l in open(S + "/runmap4.tsv")]

# raw coverage per (project, query, formula), threshold applied after
pos, neg, sizes = [], [], {}
for rid, proj, st, d in runs:
    forms = dd.load_formulas(d)
    bg = dd.background(d)
    sizes[proj] = (len(forms), len(bg))
    idx = dd.Index(forms, bg, floor=0.0)          # no silence; keep every score
    for i, f in enumerate(forms):
        for j, ex in enumerate(f["examples"]):
            ranked = idx.search_without_example(i, j, ex)
            best = None
            for _, g in ranked[:dd.TOP_N]:
                if g["name"] == f["name"]:
                    best = True
                    break
            # recompute this formula's own coverage for the example
            idx._spread_cache.clear()
            words = dd.toks(ex)
            total = sum(idx.weight(w) for w in words) or 1.0
            pos.append((proj, ex, f["name"], ranked))
    for q in NEG[proj]:
        neg.append((proj, q, idx.search(q)))

def cov_of(idx, rowid, words):
    total = sum(idx.weight(w) for w in words) or 1.0
    held = sum(idx.weight(w) for w in words if rowid in idx.spread(w)[0])
    return held / total

print("project          formulas  background")
for p, (nf, nb) in sorted(sizes.items()):
    print("  %-14s %-9d %d" % (p, nf, nb))
print("  (acme-api, where 0.15 was set: 4 formulas, 22 background)\n")

# rebuild with explicit coverage so a threshold can be applied post hoc
print("COVERAGE  examples retrieving  uncovered titles left silent")
for th in GRID:
    ok = tot = 0
    quiet = qtot = 0
    for rid, proj, st, d in runs:
        forms = dd.load_formulas(d); bg = dd.background(d)
        idx = dd.Index(forms, bg, floor=th)
        for i, f in enumerate(forms):
            for j, ex in enumerate(f["examples"]):
                tot += 1
                names = [g["name"] for _, g in idx.search_without_example(i, j, ex)[:dd.TOP_N]]
                ok += f["name"] in names
        for q in NEG[proj]:
            qtot += 1
            quiet += not idx.search(q)
    print("  %.2f      %3d/%-3d              %3d/%-3d" % (th, ok, tot, quiet, qtot))
