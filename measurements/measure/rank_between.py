"""Does a version surface what the version before it surfaced?

A version that adds nothing to what is matched ranks every title as the one
before it did. This ranks the titles verify.py was written against, and every
example of a project's committed formulas, through MatchFormulas under an
earlier version, read from git, and under the tree, and holds each version's
self-test beside the other's: which examples, taken out of the index, still
retrieve their own formula. Whatever differs is printed.

    python3 -I measure/rank_between.py <revision>

Run from `measurements/`. Two projects are ranked: this repository, and a
throwaway checkout of the README's example formula, the one that names the
means to prove its run in all three forms. The home directory is a temporary
one, and nothing is written outside it.
"""

import ast
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SELF_TEST = "does not retrieve it"


def load(path, name):
    """One dotdiw, as a module of its own."""
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def verify_titles():
    """The titles measure/verify.py was written against, read from its source."""
    with open(os.path.join(HERE, "verify.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    titles = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("CASES", "TINY"):
            titles += [title for _, title in ast.literal_eval(node.value)]
    return titles


def examples(root):
    """Every example title of the formulas committed at root."""
    titles = []
    for rel in filter(
        None, git(["ls-files", "-z", "--", "*.formula.toml"], root).stdout.split("\0")
    ):
        with open(os.path.join(root, rel), "rb") as fh:
            titles += [str(e) for e in tomllib.load(fh).get("examples") or []]
    return titles


def readme_checkout(home):
    """A checkout holding the README's example formula, the file its verify-using
    names in this repository, and the remote that makes it this repository."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        found = re.search(r"```toml\n# (\S+\.formula\.toml)\n(.*?)```", fh.read(), re.S)
    rel, text = found.group(1), found.group(2)
    repo = tempfile.mkdtemp(prefix="rank-readme-", dir=home)
    files = {rel: text}
    remote = None
    for value in tomllib.loads(text).get("verify-using") or []:
        if value.startswith("git+"):
            remote, _, path = value[len("git+") :].partition("#")
            files[path] = "Named by the formula's verify-using.\n"
    for path, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
        with open(os.path.join(repo, path), "w", encoding="utf-8") as fh:
            fh.write(body)
    git(["init", "-q"], repo)
    if remote:
        git(["remote", "add", "origin", remote], repo)
    git(["add", "-A"], repo)
    git(
        ["-c", "user.name=rank", "-c", "user.email=rank@example.invalid", "commit", "-qm", "x"],
        repo,
    )
    return repo


def rankings(module, root, titles):
    """What each title surfaces, in order, and the examples the self-test names."""
    surfaced = {}
    for title in titles:
        answer = module.MatchFormulas({"root": root, "title": title})
        ids = [f.get("formulaRef") for f in answer.get("surfaced") or []]
        if not all(isinstance(i, str) and i for i in ids):
            # A ranking of nothing compares equal to any other: refuse it.
            raise SystemExit("%s surfaced a formula with no formulaRef for %r" % (root, title))
        surfaced[title] = ids
    checked = module.DescribeAndCheck({"root": root})
    missed = sorted(
        "%s %s" % (p["where"], p["what"])
        for p in checked.get("problems") or []
        if p["what"].endswith(SELF_TEST)
    )
    return surfaced, missed, checked.get("formulaCount")


def main(argv):
    if len(argv) != 1:
        print("python3 -I measure/rank_between.py <revision>")
        return 2
    revision = argv[0]
    home = tempfile.mkdtemp(prefix="rank-home-")
    os.environ["HOME"] = home
    for name in ("DOTDIW_TRACKER", "DOTDIW_WITNESS"):
        os.environ.pop(name, None)
    differ = 0
    try:
        earlier = os.path.join(home, "dotdiw-" + revision)
        with open(earlier, "w", encoding="utf-8") as fh:
            fh.write(git(["show", revision + ":dotdiw"], ROOT).stdout)
        sys.argv = ["dotdiw"]
        old = load(earlier, "dotdiw_earlier")
        new = load(os.path.join(ROOT, "dotdiw"), "dotdiw_tree")
        print("%s is %s; the tree is %s" % (revision, old.VERSION, new.VERSION))
        for name, root in (
            ("this repository", ROOT),
            ("the README's checkout", readme_checkout(home)),
        ):
            titles = list(dict.fromkeys(verify_titles() + examples(root)))
            before, missed_before, count_before = rankings(old, root, titles)
            after, missed_after, count_after = rankings(new, root, titles)
            moved = [t for t in titles if before[t] != after[t]]
            differ += len(moved) + (missed_before != missed_after)
            print(
                "%s: %s and %s formulas, %d titles, %d ranked differently"
                % (name, count_before, count_after, len(titles), len(moved))
            )
            print(
                "  titles that surfaced a formula: %d under %s, %d under %s"
                % (
                    sum(1 for t in titles if before[t]),
                    old.VERSION,
                    sum(1 for t in titles if after[t]),
                    new.VERSION,
                )
            )
            for title in moved:
                print("  %s: %s, then %s" % (title, before[title], after[title]))
            print("  self-test under %s: %s" % (old.VERSION, "; ".join(missed_before) or "clean"))
            print("  self-test under %s: %s" % (new.VERSION, "; ".join(missed_after) or "clean"))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("%d differences" % differ)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
