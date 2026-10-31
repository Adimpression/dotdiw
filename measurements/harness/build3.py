"""Build the eleven-project matrix: 33 repos, one per parent directory.

State never appears in a path, and the (project, state) -> run number mapping
is shuffled under a fixed seed so adjacent run directories are unrelated
projects. An agent that walks up one level sees r01..r33 and learns nothing.
"""
import os, random, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import domains3

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
OLD = ["ramen-shop", "paws-shelter", "tinybill", "edgeops", "corpsec"]
DOTDIW = "../dotdiw"
RUNS = S + "/runs3"

JOBS = {
 "ramen-shop": "Add a new dish, a yuzu shio bowl, to the autumn menu.",
 "paws-shelter": "A stray collie was found on Quarry Rise and brought in this morning. Take her in.",
 "tinybill": "Cut the 0.3 release.",
 "edgeops": "Patch the kernel on the us-west-2 node without dropping traffic.",
 "corpsec": "Record the transfer of 500 ordinary shares from R. Osei to M. Lindqvist, approved by the board on 2026-05-13.",
}
for k, v in domains3.NEW.items():
    JOBS[k] = v["job"]

def sh(args, cwd, quiet=True):
    return subprocess.run(args, cwd=cwd, capture_output=quiet, text=True)

def read_old(proj):
    """Base files and formulas from the first matrix, read off disk."""
    files, forms = {}, {}
    b = "%s/matrix/%s/base" % (S, proj)
    for dirpath, _, names in os.walk(b):
        for n in names:
            p = os.path.join(dirpath, n)
            files[os.path.relpath(p, b)] = open(p, encoding="utf-8").read()
    f = "%s/matrix/%s/formulas" % (S, proj)
    for dirpath, _, names in os.walk(f):
        for n in names:
            p = os.path.join(dirpath, n)
            forms[os.path.relpath(p, f)] = open(p, encoding="utf-8").read()
    return files, forms

def write(root, rel, body):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p) or root, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)

def build(root, state, files, forms):
    os.makedirs(root, exist_ok=True)
    if state == "cold":
        return                                  # the project has not started
    sh(["git", "init", "-q", "."], root)
    sh(["git", "config", "user.email", "team@example.invalid"], root)
    sh(["git", "config", "user.name", "The team"], root)
    for rel, body in sorted(files.items()):
        write(root, rel, body)
    sh(["git", "add", "-A"], root)
    sh(["git", "commit", "-qm", "the project as it stands"], root)
    if state == "warm":
        return
    r = sh([DOTDIW, "init"], root)
    sh(["git", "add", "-A"], root)
    sh(["git", "commit", "-qm", "dotdiw init: workflow discovery and tracking"], root)
    for rel, body in sorted(forms.items()):
        write(root, rel, body)
    sh(["git", "add", "-A"], root)
    sh(["git", "commit", "-qm", "formulas for the things we repeat"], root)

if __name__ == "__main__":
    projects = OLD + list(domains3.NEW)
    assert len(projects) == 11, projects
    cells = [(p, st) for p in projects for st in ("cold", "warm", "live")]
    random.Random(1131).shuffle(cells)
    shutil.rmtree(RUNS, ignore_errors=True)
    os.makedirs(RUNS)
    rows = []
    for i, (proj, state) in enumerate(cells, 1):
        if proj in OLD:
            files, forms = read_old(proj)
        else:
            d = domains3.NEW[proj]
            files, forms = dict(d["files"]), dict(d["formulas"])
        rid = "r%02d" % i
        root = "%s/%s/%s" % (RUNS, rid, proj)
        build(root, state, files, forms)
        rows.append((rid, proj, state, root))
    with open(S + "/runmap3.tsv", "w") as fh:
        for r in rows:
            fh.write("\t".join(r) + "\n")
    with open(S + "/jobs3.tsv", "w") as fh:
        for p in projects:
            fh.write("%s\t%s\n" % (p, JOBS[p]))
    print("built %d repos" % len(rows))
    for st in ("cold", "warm", "live"):
        print("  %s: %s" % (st, " ".join(r[0] for r in rows if r[2] == st)))
