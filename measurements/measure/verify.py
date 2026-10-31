"""The shipped rule, untouched, on every fixture."""
import os, sys
from importlib.machinery import SourceFileLoader
m = SourceFileLoader("d", "../dotdiw").load_module()
CASES = [
    ("cut-release","Release 1.9 of the billing service"),("cut-release","Get auth out to prod this afternoon"),
    ("cut-release","Tag and ship the current main"),("migrate-schema","We need a new column on customers"),
    ("migrate-schema","Add an index, invoice lookups are slow"),("migrate-schema","Rename the status field in orders"),
    ("incident-response","Checkout is failing for everyone"),("incident-response","Pager fired at 3am, auth is throwing 500s"),
    ("incident-response","Site is down"),("rotate-secrets","The Stripe key is in a public gist"),
    ("rotate-secrets","Offboard Priya and revoke her access"),("rotate-secrets","Time for the quarterly key rotation"),
    (None,"Fix the typo in the README"),(None,"Upgrade the Go version to 1.23"),
    (None,"Write unit tests for the parser"),(None,"Refactor the config loader"),(None,"Update the nginx read timeout"),
]
TINY = [("cut-release","Cut the 2.4 release"),("cut-release","Ship v3 to production"),
        ("cut-release","Release the billing service"),("cut-release","Tag and ship the current main"),
        ("cut-release","Publish the next version"),(None,"Fix a typo"),(None,"Order more cups")]
os.chdir(sys.argv[1]); root = m.repo_root()
forms = m.load_formulas(root); bg = m.background(root)
idx = m.Index(forms, bg)
hit = miss = fp = quiet = 0
for want, title in (TINY if sys.argv[1] == "tiny" else CASES):
    names = [f["name"] for _, f in idx.search(title)][:3]
    if want is None:
        quiet += not names; fp += bool(names)
        if names: print("     NOISE %-34s -> %s" % (title[:34], names))
    else:
        if want in names: hit += 1
        else: miss += 1; print("     MISS  %-34s -> %s" % (title[:34], names or "-"))
print("  formulas=%d background=%d   positives %d/%d   negatives quiet %d/%d"
      % (len(forms), len(bg), hit, hit + miss, quiet, quiet + fp))
print("  self-test:", m.problems(root, forms, idx) or "clean")
