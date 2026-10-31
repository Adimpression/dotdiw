"""Ground truth for round three. Reads the invocation log and the repo diffs,
never what an agent said it did."""
import json, os, subprocess, sys

S = os.environ.get("DOTDIW_SIM_ROOT",
    "./sim-root")
REAL = "/opt/homebrew/Cellar/dotdiw/0.1.0/bin/dotdiw"

def sh(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout

def log_for(path):
    out = []
    try:
        for line in open(S + "/invocations3.log", encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3 and (parts[1] == path or parts[1].startswith(path + "/")):
                out.append(parts[2])
    except OSError:
        pass
    return out

def base_commit(d, state):
    want = ("formulas for the things we repeat" if state == "live"
            else "the project as it stands")
    _, o = sh(["git", "log", "--format=%H", "--grep", want, "-1"], d)
    return o.strip()

def formulas_now(d):
    _, a = sh(["git", "ls-files", "*.formula.toml"], d)
    _, b = sh(["git", "ls-files", "-o", "--exclude-standard", "*.formula.toml"], d)
    if a or b:
        return sorted(set(x for x in (a + b).split("\n") if x))
    out = []
    for dp, _, ns in os.walk(d):
        if ".git" in dp:
            continue
        out += [os.path.relpath(os.path.join(dp, n), d)
                for n in ns if n.endswith(".formula.toml")]
    return sorted(out)

def formulas_at_base(d, base):
    if not base:
        return []
    _, o = sh(["git", "ls-tree", "-r", "--name-only", base], d)
    return sorted(x for x in o.split("\n") if x.endswith(".formula.toml"))

def issues(d):
    if not os.path.isdir(os.path.join(d, ".beads")):
        return None
    c, o = sh([REAL, "list", "--all", "--json", "--brief", "-n", "300"], d)
    if c != 0:
        return None
    try:
        return json.loads(o)
    except ValueError:
        return None

def handmade_dag(rows):
    if not rows:
        return 0
    byid = {r.get("id"): r for r in rows}
    kids = {}
    for r in rows:
        if r.get("parent"):
            kids.setdefault(r["parent"], []).append(r)
    n = 0
    for pid, ks in kids.items():
        p = byid.get(pid) or {}
        if p.get("issue_type") in ("molecule", "epic") or len(ks) < 3:
            continue
        if any(x.get("type") == "blocks" for k in ks
               for x in (k.get("dependencies") or [])):
            n += 1
    return n

def files_touched(d, base):
    if not base:
        n = 0
        for dp, _, ns in os.walk(d):
            if ".git" in dp or ".beads" in dp:
                continue
            n += len(ns)
        return n
    _, a = sh(["git", "diff", "--name-only", base, "--"], d)
    _, b = sh(["git", "ls-files", "-o", "--exclude-standard"], d)
    skip = (".beads/", ".agents/", ".claude/", ".codex/", ".cursor/")
    keep = set()
    for x in (a + b).split("\n"):
        if not x or x.startswith(skip) or x in ("AGENTS.md", "CLAUDE.md", ".gitignore", ".beads.gate.lock"):
            continue
        keep.add(x)
    return len(keep)

ROWS = []
for line in open(S + "/runmap3.tsv", encoding="utf-8"):
    rid, proj, state, d = line.rstrip("\n").split("\t")
    inv = log_for(d)
    base = base_commit(d, state) if os.path.isdir(os.path.join(d, ".git")) else ""
    now, was = formulas_now(d), formulas_at_base(d, base)
    authored = [f for f in now if f not in was]
    rows = issues(d)
    first = inv[0].split()[0] if inv else "-"
    fl = [i for i, c in enumerate(inv) if c.startswith("formula list")]
    cr = [i for i, c in enumerate(inv) if c.startswith("create")]
    ROWS.append({
      "id": rid, "project": proj, "state": state,
      "inv": len(inv), "first": first,
      "create": len(cr),
      "create_first": bool(cr) and cr[0] == 0,
      "browse_before_create": bool(fl) and bool(cr) and fl[0] < cr[0],
      "check": sum(1 for c in inv if c.startswith("check")),
      # `formula new --help` is reading the manual, not writing a formula.
      "formula_new": sum(1 for c in inv if c.startswith("formula new")
                         and c.split()[2:3] not in ([], ["--help"], ["-h"])),
      "formula_new_help": sum(1 for c in inv if c.startswith("formula new")
                              and c.split()[2:3] in ([], ["--help"], ["-h"])),
      "pour": sum(1 for c in inv if c.startswith("mol pour")),
      "formula_list": len(fl),
      "authored": authored,
      "relocated": [f for f in now if f.startswith(".beads/formulas")],
      "issues": (len(rows) if rows is not None else None),
      "handmade": handmade_dag(rows),
      "files": files_touched(d, base),
      "calls": inv,
    })

json.dump(ROWS, open(S + "/score3.json", "w"), indent=1)

def grp(st):
    return [r for r in ROWS if r["state"] == st]

print("round 3 -- 11 projects x 3 states, %d runs, %d invocations logged\n"
      % (len(ROWS), sum(r["inv"] for r in ROWS)))
for st in ("cold", "warm", "live"):
    g = grp(st)
    print("%-5s n=%-3d invoked:%-3d  create:%-3d create-first:%-3d  check:%-3d  "
          "formula-new:%-3d  authored:%-3d  relocated:%-3d  browse-first:%d"
          % (st, len(g), sum(1 for r in g if r["inv"]),
             sum(1 for r in g if r["create"]),
             sum(1 for r in g if r["create_first"]),
             sum(1 for r in g if r["check"]),
             sum(1 for r in g if r["formula_new"]),
             sum(1 for r in g if r["authored"]),
             sum(1 for r in g if r["relocated"]),
             sum(1 for r in g if r["browse_before_create"])))
print()
for r in ROWS:
    print("%-4s %-14s %-5s inv:%-3s first:%-13s cr:%-2d chk:%-2d fnew:%-2d pour:%-2d "
          "iss:%-4s hand:%-2d auth:%-2d files:%-3d" % (
      r["id"], r["project"], r["state"], r["inv"], r["first"], r["create"],
      r["check"], r["formula_new"], r["pour"],
      "-" if r["issues"] is None else r["issues"],
      r["handmade"], len(r["authored"]), r["files"]))
    if r["authored"]:
        for f in r["authored"]:
            print("       + %s" % f)
