"""Pool every real formula into one project, to measure above four.

Everything measured so far used two to four formulas. The design is for
hundreds. This collects the 56 distinct formulas written across the trials --
the eleven domains' fixtures, the ones blind agents authored, acme's, and
trial1's example-less ones as distractors -- into a single repository, with
every domain's prose as one fixed background corpus so that formula count is
the only thing that varies.
"""
import glob, os, shutil, subprocess, sys, tomllib

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
POOL = S + "/pool"

FORMULA_SRC = (
    glob.glob(S + "/matrix/*/formulas/**/*.formula.toml", recursive=True)
    + glob.glob(S + "/runs4/*/*/**/*.formula.toml", recursive=True)
    + glob.glob(S + "/sim/acme-api/**/*.formula.toml", recursive=True)
    + glob.glob("../trial1/formulas/*.formula.toml")
)
PROSE_SRC = (
    glob.glob(S + "/matrix/*/base/**/*.md", recursive=True)
    + glob.glob(S + "/runs4/*/*/*.md", recursive=True)
    + glob.glob(S + "/runs4/*/*/*/*.md", recursive=True)
    + glob.glob(S + "/sim/acme-api/**/*.md", recursive=True)
)

def domain_of(p):
    for marker in ("/matrix/", "/runs4/", "/sim/"):
        if marker in p:
            return p.split(marker, 1)[1].split("/")[0]
    return "trial1"

def build():
    shutil.rmtree(POOL, ignore_errors=True)
    os.makedirs(POOL)
    subprocess.run(["git", "init", "-q", "."], cwd=POOL)
    subprocess.run(["git", "config", "user.email", "p@p"], cwd=POOL)
    subprocess.run(["git", "config", "user.name", "P"], cwd=POOL)

    seen, nf = set(), 0
    for p in sorted(FORMULA_SRC):
        try:
            d = tomllib.load(open(p, "rb"))
        except Exception:
            continue
        fid = str(d.get("formula") or os.path.basename(p).split(".")[0])
        if fid in seen:
            continue
        seen.add(fid)
        # keep each formula under its own domain, at the depth it really sat at
        sub = os.path.dirname(p).split("/")
        tail = "/".join(sub[-2:]) if len(sub) > 1 else ""
        rel = os.path.join(domain_of(p), os.path.basename(p))
        dst = os.path.join(POOL, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(p, dst)
        nf += 1

    np_ = 0
    for p in sorted(set(PROSE_SRC)):
        if ".beads" in p or "/.git/" in p:
            continue
        rel = os.path.join("prose", domain_of(p),
                           os.path.basename(os.path.dirname(p)) + "-"
                           + os.path.basename(p))
        dst = os.path.join(POOL, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copyfile(p, dst)
        except OSError:
            continue
        np_ += 1

    subprocess.run(["git", "add", "-A"], cwd=POOL, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "pooled"], cwd=POOL, capture_output=True)
    print("pool: %d formulas, %d prose documents" % (nf, np_))

if __name__ == "__main__":
    build()
