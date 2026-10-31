"""Did the occasion for capture ever arise?

Capture is for work no formula covers. Replay every create title each live run
actually typed, and see which of them surfaced nothing -- those are the only
moments at which authoring a formula was the right move.
"""
import importlib.util, importlib.machinery, json, os, subprocess, sys

spec = importlib.util.spec_from_loader("dd", importlib.machinery.SourceFileLoader(
    "dd", "../dotdiw"))
dd = importlib.util.module_from_spec(spec); spec.loader.exec_module(dd)

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
REAL = "/opt/homebrew/Cellar/dotdiw/0.1.0/bin/dotdiw"

runs = {}
for line in open(S + "/runmap3.tsv", encoding="utf-8"):
    rid, proj, state, d = line.rstrip("\n").split("\t")
    runs[rid] = (proj, state, d)

titles = {}
for line in open(S + "/invocations3.log", encoding="utf-8"):
    t, pwd, cmd = line.rstrip("\n").split("\t")
    if not cmd.startswith("create "):
        continue
    rid = pwd.split("/runs3/")[1].split("/")[0]
    argv = cmd.split()
    title, _ = dd.extract_query(argv)
    # the shim loses quoting, so reconstruct: everything up to the first flag
    words = []
    for a in argv[1:]:
        if a.startswith("-"):
            break
        words.append(a)
    titles.setdefault(rid, []).append(" ".join(words) or title)

covered = uncovered = 0
print("Every create title a live run typed, and what surfaced for it:\n")
for rid in sorted(titles):
    proj, state, d = runs[rid]
    forms = dd.load_formulas(d)
    idx = dd.Index(forms, dd.background(d))
    print("%s %s (%d formulas)" % (rid, proj, len(forms)))
    for t in titles[rid]:
        hits = idx.search(t)
        names = []
        for _, f in hits:
            if f["name"] not in names:
                names.append(f["name"])
        if names:
            covered += 1
            print("   HIT   %-62s -> %s" % (t[:62], names[0]))
        else:
            uncovered += 1
            print("   NONE  %-62s" % t[:62])
print("\n%d create titles: %d a formula covered, %d nothing covered"
      % (covered + uncovered, covered, uncovered))

# and for the uncovered ones, was a DAG built by hand?
print("\nIssue shape in each live run (was any procedure built by hand?):")
for rid in sorted(runs):
    proj, state, d = runs[rid]
    if state != "live":
        continue
    p = subprocess.run([REAL, "list", "--all", "--json", "--brief", "-n", "300"],
                       cwd=d, capture_output=True, text=True)
    try:
        rows = json.loads(p.stdout)
    except ValueError:
        continue
    mol = sum(1 for r in rows if r.get("issue_type") == "molecule")
    kids = sum(1 for r in rows if r.get("parent"))
    flat = len(rows) - mol - kids
    print("  %s %-14s %2d issues: %d poured molecule(s), %d steps under them, "
          "%d flat and unparented" % (rid, proj, len(rows), mol, kids, flat))
