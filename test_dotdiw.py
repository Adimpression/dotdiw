#!/usr/bin/env python3
"""What adoption does to a repository, and what it must not do.

v0.1.0 passed `init` straight through to `bd init` without checking what bd
changes in a repository. Two of those changes were wrong to inherit, and the
claim made about one of them was itself wrong: bd copies the hooks already in
`.git/hooks` into its own directory, so hooks present at adoption keep running.
What stops running is anything added afterwards, because `core.hooksPath` names
one directory and from adoption onward it is bd's snapshot.

0.2.x let bd commit its own files into the repository; 0.3.0 kept them in the
tree, local. From 0.4.0 the tracker's state lives under the user's home, in a
directory keyed to the checkout by one line in its own .git/config, and bd runs
there in its stealth mode with hooks and agent files declined. What init leaves
in the repository is dotdiw's own declaration, named as the worker's to commit;
the printed command leaves the tree clean. A repository adopted by an earlier
version is adopted under the home by its first command, keeping its prefix;
its tasks are not carried over, and the in-tree copy is the worker's to remove.

Every test that adopts runs with HOME isolated, because that is where the state
goes.

Every assertion here was first run by hand, which is exactly why it is now a
file: a shell command in a transcript is not evidence anyone else can check.

    python3 -I test_dotdiw.py

Each test builds a real git repository in a temporary directory and runs the
real `dotdiw` against it, because the behaviour under test is the interaction
with git and bd and nothing else. `bd init` takes a few seconds, so the whole
suite is slower than a unit test and that is the price of testing the thing
itself.
"""

import json
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTDIW = os.path.join(HERE, "dotdiw")
HOOKS_KEY = "core.hooksPath"

# A hook that leaves a trace on disk rather than on stdout: git routes hook
# output in ways that differ between versions, a file does not.
HOOK = "#!/bin/sh\necho ran >> \"$(git rev-parse --show-toplevel)/%s\"\n"


def have_bd():
    return shutil.which("bd") is not None


class Repo:
    """A real git repository in a temporary directory, with a home of its own."""

    def __init__(self, home=None):
        self.path = tempfile.mkdtemp(prefix="dotdiw-test-")
        self.home = home or tempfile.mkdtemp(prefix="dotdiw-home-")
        self.env = dict(os.environ, HOME=self.home)
        self.env.pop("BEADS_DIR", None)
        self.env.pop("DOTDIW_WITNESS", None)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        # bd asks for one, and warns on every command without it.
        self.git("config", "beads.role", "maintainer")

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def key(self):
        return self.git("config", "--local", "--get", "dotdiw.workspace")[1].strip()

    def workspace(self):
        return os.path.join(self.home, ".dotdiw", self.key()) if self.key() else None

    def trackers(self):
        try:
            return sorted(os.listdir(os.path.join(self.home, ".dotdiw")))
        except OSError:
            return []

    def bd(self, *args):
        """bd itself, pointed at this repository's tracker under the home."""
        env = dict(self.env, BEADS_DIR=os.path.join(self.workspace(), ".beads"))
        p = subprocess.run([shutil.which("bd")] + list(args), cwd=self.path, env=env,
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def git(self, *args):
        p = subprocess.run(["git"] + list(args), cwd=self.path,
                           capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def config(self, key):
        return self.git("config", "--get", key)[1].strip()

    def dotdiw(self, *args, cwd=None, env=None):
        p = subprocess.run([sys.executable, "-I", DOTDIW] + list(args),
                           cwd=cwd or self.path, env=env or self.env,
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def write(self, rel, text, executable=False):
        path = os.path.join(self.path, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if executable:
            os.chmod(path, 0o755)

    @classmethod
    def clone_of(cls, other):
        """A clone in the same home, so that its tracker must be a second one."""
        repo = cls.__new__(cls)
        repo.path = tempfile.mkdtemp(prefix="dotdiw-clone-")
        repo.home, repo.env = other.home, other.env
        subprocess.run(["git", "clone", "-q", other.path, repo.path], capture_output=True)
        repo.git("config", "user.email", "test@example.invalid")
        repo.git("config", "user.name", "Test")
        repo.git("config", "beads.role", "maintainer")
        return repo

    def hook(self, name, marker):
        """Install a hook in the repository's own .git/hooks."""
        self.write(os.path.join(".git", "hooks", name), HOOK % marker,
                   executable=True)

    def commit(self, name):
        self.write(name, name)
        self.git("add", name)
        return self.git("commit", "-m", name)

    def ran(self, marker):
        return os.path.exists(os.path.join(self.path, marker))

    def porcelain(self):
        return [l for l in self.git("status", "--porcelain")[1].split("\n") if l.strip()]

    def commits(self):
        return len([l for l in self.git("log", "--oneline")[1].split("\n") if l.strip()])

    def tracked(self, *paths):
        return [p for p in self.git("ls-files", "--", *paths)[1].split("\n") if p.strip()]

    def excluded(self):
        try:
            with open(os.path.join(self.path, ".git", "info", "exclude"), encoding="utf-8") as fh:
                return [l for l in fh.read().split("\n") if l and not l.startswith("#")]
        except OSError:
            return []

    def adopt_the_old_way(self, prefix="t", stealth=False):
        """Adopt as 0.2.x did (bd's default init, which commits its own files),
        or as 0.3.0 did (stealth: in the tree, local and excluded)."""
        args = [shutil.which("bd"), "init", "--skip-hooks", "--prefix", prefix]
        if stealth:
            args.insert(2, "--stealth")
        p = subprocess.run(args, cwd=self.path, env=self.env, capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr

    def dolt_remotes(self):
        out = []
        for f in glob.glob(os.path.join(self.path, ".beads", "embeddeddolt",
                                        "*", ".dolt", "repo_state.json")):
            with open(f, encoding="utf-8") as fh:
                out += list(json.load(fh).get("remotes") or {})
        return sorted(out)

    def beads_config(self):
        try:
            with open(os.path.join(self.path, ".beads", "config.yaml"),
                      encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def adopt_as_v0_1_0(self):
        """Put the repository in the state v0.1.0 left it in.

        `init` now declines both of these, so the damage has to be recreated to
        test that it is repaired. This is what bd did and what v0.1.0 kept:
        hooksPath aimed at bd's snapshot, and a Dolt remote aimed at the
        repository's git remote.
        """
        self.git("config", HOOKS_KEY,
                 os.path.join(self.path, ".beads", "hooks"))
        cfg = os.path.join(self.path, ".beads", "config.yaml")
        with open(cfg, "a", encoding="utf-8") as fh:
            fh.write('\nsync:\n    remote: "git+ssh://git@example.invalid/x.git"\n')
        for f in glob.glob(os.path.join(self.path, ".beads", "embeddeddolt",
                                        "*", ".dolt", "repo_state.json")):
            with open(f, encoding="utf-8") as fh:
                state = json.load(fh)
            state["remotes"] = {"origin": {"name": "origin",
                                           "url": "git+ssh://git@example.invalid/x.git",
                                           "fetch_specs": [], "params": {}}}
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)


@unittest.skipUnless(have_bd(), "bd is not installed")
class Adoption(unittest.TestCase):
    """What `dotdiw init` may and may not change."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_init_leaves_the_tree_clean(self):
        """Two files in the repository, one directory under the home.

        The key is one line in the checkout's own git config; the tracker is
        ~/.dotdiw/<key>/.beads with no sync remote; the hooks path is unset;
        nothing of bd's is in the tree; and the command init prints leaves
        the tree clean.
        """
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.commits(), 1, "bd must not commit")
        self.assertEqual(sorted(l[3:] for l in self.repo.porcelain()), ["AGENTS.md", "CLAUDE.md"])
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, ".beads")))
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, ".beads.gate.lock")))
        self.assertRegex(self.repo.key(), r"^[0-9a-f]{16}$")
        cfg = os.path.join(self.repo.workspace(), ".beads", "config.yaml")
        self.assertTrue(os.path.exists(cfg), "the tracker lives under the home")
        with open(cfg, encoding="utf-8") as fh:
            self.assertNotIn("\nsync:", fh.read())
        self.assertEqual(self.repo.config(HOOKS_KEY), "")
        self.assertIn("yours to commit", out)
        self.assertNotIn("an earlier version", out)
        command = [l.strip() for l in out.split("\n") if l.strip().startswith("git add ")]
        self.assertEqual(len(command), 1, out)
        p = subprocess.run(command[0], shell=True, cwd=self.repo.path, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.repo.porcelain(), [], "the printed command must leave the tree clean")

    def test_the_tracker_is_under_the_home(self):
        """What dotdiw creates, bd sees only through that directory."""
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("create", "Under the home")
        self.assertEqual(code, 0, out)
        code, listing = self.repo.bd("list", "--json")
        self.assertIn("Under the home", listing)
        p = subprocess.run([shutil.which("bd"), "list"], cwd=self.repo.path, env=self.repo.env,
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0, "plain bd in the repository finds no tracker")
        self.assertTrue(os.path.exists(os.path.join(self.repo.workspace(), ".beads.gate.lock")))

    def test_two_repositories_under_one_home_stay_apart(self):
        other = Repo(home=self.repo.home)
        self.addCleanup(lambda: shutil.rmtree(other.path, ignore_errors=True))
        for r, prefix in ((self.repo, "a"), (other, "b")):
            r.commit("first")
            code, out = r.dotdiw("init", "--prefix", prefix)
            self.assertEqual(code, 0, out)
        self.assertNotEqual(self.repo.key(), other.key())
        procs = [subprocess.Popen([sys.executable, "-I", DOTDIW, "create", "At once in %s" % n],
                                  cwd=r.path, env=r.env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for r, n in ((self.repo, "a"), (other, "b"))]
        for p in procs:
            p.communicate()
            self.assertEqual(p.returncode, 0)
        self.assertIn("At once in a", self.repo.bd("list", "--json")[1])
        self.assertNotIn("At once in b", self.repo.bd("list", "--json")[1])
        self.assertIn("At once in b", other.bd("list", "--json")[1])

    def test_a_worktree_shares_the_tracker(self):
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        wt = tempfile.mkdtemp(prefix="dotdiw-wt-")
        self.addCleanup(shutil.rmtree, wt, True)
        shutil.rmtree(wt)
        self.repo.git("worktree", "add", "-q", wt, "-b", "wt")
        code, out = self.repo.dotdiw("create", "From the worktree", cwd=wt)
        self.assertEqual(code, 0, out)
        self.assertIn("From the worktree", self.repo.bd("list", "--json")[1])
        self.assertEqual(len(self.repo.trackers()), 1)

    def test_init_twice_is_a_sentence_not_a_reinit(self):
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        before = self.repo.bd("list", "--json")[1]
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertIn("is adopted", out)
        self.assertEqual(len(self.repo.trackers()), 1)
        self.assertEqual(self.repo.bd("list", "--json")[1], before)

    def test_an_unadopted_repository_is_told_in_one_line(self):
        self.repo.commit("first")
        code, out = self.repo.dotdiw("create", "x")
        self.assertEqual(code, 1)
        self.assertIn("not adopted", out)
        self.assertIn("dotdiw init", out)
        self.assertNotIn("no beads database found", out)
        code, out = self.repo.dotdiw("formula", "list")
        self.assertEqual(code, 0, "listing formulas needs no tracker")

    def test_init_does_not_take_over_the_hooks(self):
        """The repository's own hook directory stays the one git reads.

        bd installs its hooks by pointing core.hooksPath at its own directory.
        Hooks already present are copied across, so they keep running -- but
        anything added later is then invisible to git. `init` declines the
        whole arrangement instead.
        """
        self.repo.hook("pre-commit", "own-hook-ran")
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")

        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.config(HOOKS_KEY), "",
                         "init must not point git at bd's hook directory")
        self.repo.commit("second")
        self.assertTrue(self.repo.ran("own-hook-ran"),
                        "the repository's own hook must still run")

    def test_init_leaves_no_dolt_remote(self):
        """The issue database does not get a route into the repository.

        bd aims a Dolt remote at whatever the git remote is, which pushes the
        database into the repository, where it keeps its full history and never
        shrinks.
        """
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")

        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.dolt_remotes(), [])
        self.assertNotIn("\nsync:", self.repo.beads_config())

    def test_init_refuses_outside_a_git_repository(self):
        """bd's stealth init would run git init on the worker's behalf; dotdiw does not let it."""
        plain = tempfile.mkdtemp(prefix="dotdiw-nogit-")
        self.addCleanup(shutil.rmtree, plain, True)
        p = subprocess.run([sys.executable, "-I", DOTDIW, "init", "--prefix", "n"],
                           cwd=plain, capture_output=True, text=True)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("needs a git repository", p.stdout + p.stderr)
        self.assertEqual(sorted(os.listdir(plain)), [], "nothing may be created")

    def test_a_clone_is_told_to_init_and_then_works(self):
        """A clone has no key, so no tracker until init; its tracker is its own."""
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.repo.git("add", "AGENTS.md", "CLAUDE.md")
        self.repo.git("commit", "-qm", "Declare where work starts")

        clone = Repo.clone_of(self.repo)
        self.addCleanup(lambda: shutil.rmtree(clone.path, ignore_errors=True))
        code, out = clone.dotdiw("create", "In the clone")
        self.assertEqual(code, 1)
        self.assertIn("not adopted", out)

        code, out = clone.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertEqual(clone.commits(), 2)
        self.assertEqual(clone.porcelain(), [], "the clone already carries the declaration")
        self.assertNotEqual(clone.key(), self.repo.key())
        self.assertEqual(len(self.repo.trackers()), 2)
        code, out = clone.dotdiw("create", "In the clone")
        self.assertEqual(code, 0, out)

    def test_init_writes_nothing_global_but_its_own_directory(self):
        """Outside the repository: ~/.dotdiw/<key> and bd's three per-machine files."""
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        written = sorted(os.path.relpath(os.path.join(d, f), self.repo.home)
                         for d, _, fs in os.walk(self.repo.home) for f in fs)
        allowed = {".beads/machine-id", ".dolt/config_global.json", ".config/bd/config.yaml"}
        own = os.path.join(".dotdiw", self.repo.key())
        stray = [w for w in written if w not in allowed and not w.startswith(own + os.sep)]
        self.assertEqual(stray, [], written)

@unittest.skipUnless(have_bd(), "bd is not installed")
class Repair(unittest.TestCase):
    """Undoing what v0.1.0 did to repositories that already ran it."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

    def old(self):
        """A repository as 0.1.0 left it: tracker in the tree, hooks taken over, a remote."""
        old = Repo()
        self.addCleanup(old.close)
        old.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        old.commit("first")
        old.adopt_the_old_way()
        old.adopt_as_v0_1_0()
        return old

    def test_repair_hands_the_hooks_back(self):
        """A hook added after adoption was being skipped, and runs again.

        This is the actual defect, and it is narrower than it first looked:
        hooks that existed at adoption were copied into bd's directory and kept
        running. A hook added afterwards went to .git/hooks, which git was no
        longer reading.
        """
        old = self.old()
        old.hook("pre-commit", "added-later")

        old.commit("while-adopted")
        self.assertFalse(old.ran("added-later"),
                         "a hook added after adoption should be skipped, or "
                         "there is nothing here to repair")

        code, out = old.dotdiw("check")
        self.assertIn(HOOKS_KEY, out)
        self.assertEqual(old.config(HOOKS_KEY), "")

        old.commit("after-repair")
        self.assertTrue(old.ran("added-later"),
                        "the hook must run once the override is gone")

    def test_an_old_remote_stays_in_the_unused_tree_copy(self):
        """The in-tree tracker is left as it is; no bd runs there any more.

        0.2.x stripped the Dolt remote out of it. Now the tracker under the
        home has no remote, and the copy in the tree is the worker's to
        remove, so nothing in it is edited -- a remote in an abandoned
        directory reaches nothing.
        """
        old = self.old()
        self.assertEqual(old.dolt_remotes(), ["origin"])

        code, out = old.dotdiw("check")
        self.assertEqual(old.dolt_remotes(), ["origin"], "the in-tree copy is not edited")
        self.assertIn("\nsync:", old.beads_config())
        self.assertIn("not carried over", out)
        self.assertIn("git rm -r -q .beads", out)
        cfg = os.path.join(old.workspace(), ".beads", "config.yaml")
        with open(cfg, encoding="utf-8") as fh:
            self.assertNotIn("\nsync:", fh.read(), "the tracker under the home has no remote")

    def test_repair_says_nothing_when_there_is_nothing_to_undo(self):
        """Silence in a repository this never touched.

        A repair that announces itself every time teaches people to ignore it.
        """
        code, out = self.repo.dotdiw("check")
        self.assertEqual(code, 0, out)
        self.assertNotIn("put right", out)

    def test_upgrade_from_an_in_tree_adoption_is_seamless(self):
        """0.2.x let bd commit its files. The first command adopts under the home.

        The prefix is kept, the in-tree copy is not touched, tasks are not
        carried over and that is said once, with the one command that removes
        the copy; after that command the tree is clean.
        """
        old = Repo()
        self.addCleanup(old.close)
        old.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        old.commit("first")
        old.adopt_the_old_way(prefix="old")
        self.assertEqual(len(old.tracked(".beads")), 4)
        before = {}
        for d, _, fs in os.walk(os.path.join(old.path, ".beads")):
            for f in fs:
                with open(os.path.join(d, f), "rb") as fh:
                    before[os.path.join(d, f)] = fh.read()

        code, out = old.dotdiw("create", "After the upgrade")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: old-", out, "the prefix is kept")
        self.assertIn("not carried over", out)
        self.assertIn("git rm -r -q .beads", out)
        command = [l.strip() for l in out.split("\n") if l.strip().startswith("git rm -r")]
        self.assertEqual(len(command), 1, out)
        self.assertTrue(old.key())
        self.assertTrue(os.path.isdir(os.path.join(old.workspace(), ".beads")))
        self.assertEqual(len(old.tracked(".beads")), 4, "dotdiw never changes the index")
        for path, data in before.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), data, "%s was touched" % path)

        code, out = old.dotdiw("create", "Second create")
        self.assertEqual(code, 0, out)
        self.assertNotIn("not carried over", out, "said once")
        code, out = old.dotdiw("check")
        self.assertIn("left by an adoption before 0.4.0", out)

        p = subprocess.run(command[0], shell=True, cwd=old.path, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(old.path, ".beads")))
        # What stays modified is bd's agent files from 0.2.x, now carrying the
        # declaration: the worker's to commit, as init's report says.
        self.assertEqual([l for l in old.porcelain() if ".beads" in l], [])
        code, out = old.dotdiw("check")
        self.assertNotIn("left by an adoption", out, "the notice stops once it is done")
        code, out = old.dotdiw("create", "Still works")
        self.assertEqual(code, 0, out)

    def test_upgrade_from_a_stealth_adoption_is_seamless(self):
        """0.3.0 kept .beads in the tree, excluded. Same upgrade, rm as the command."""
        st = Repo()
        self.addCleanup(st.close)
        st.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        st.commit("first")
        st.adopt_the_old_way(prefix="st", stealth=True)
        self.assertEqual(st.porcelain(), [])

        code, out = st.dotdiw("create", "After the upgrade")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: st-", out)
        self.assertIn("rm -rf .beads .beads.gate.lock", out)
        self.assertEqual([l for l in st.porcelain() if ".beads" in l], [])
        subprocess.run("rm -rf .beads .beads.gate.lock", shell=True, cwd=st.path)
        code, out = st.dotdiw("create", "Still works")
        self.assertEqual(code, 0, out)

    def test_the_notice_says_who_did_it(self):
        """What 0.1.0 left is 'an earlier version'; a fresh init never says that."""
        old = self.old()
        code, out = old.dotdiw("check")
        self.assertIn("put right what an earlier version of it left here", out)

        fresh = Repo()
        self.addCleanup(fresh.close)
        fresh.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        fresh.commit("first")
        code, out = fresh.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertNotIn("earlier version", out)

    def test_repair_leaves_a_hooks_path_the_user_chose(self):
        """Someone else's hooksPath is not ours to unset.

        Projects point core.hooksPath at a directory of their own. Unsetting
        that would break the very thing this repair exists to protect, so only
        a path inside .beads is touched.
        """
        mine = os.path.join(self.repo.path, "myhooks")
        os.makedirs(mine, exist_ok=True)
        self.repo.git("config", HOOKS_KEY, mine)

        code, out = self.repo.dotdiw("check")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.config(HOOKS_KEY), mine)
        self.assertNotIn("put right", out)


@unittest.skipUnless(have_bd(), "bd is not installed")
class Metrics(unittest.TestCase):
    """bd's usage metrics are off before this tool runs anything else.

    bd ships them on. These tests run against an empty HOME, which is what a
    machine looks like the day bd is installed, so nothing here touches the
    config of the machine running the suite.
    """

    OFF = "turned the tracker's anonymous usage metrics off"

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dotdiw-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = dict(os.environ, HOME=self.home)

    def dotdiw(self, *args):
        p = subprocess.run([sys.executable, "-I", DOTDIW] + list(args),
                           cwd=self.home, env=self.env,
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def config(self):
        try:
            with open(os.path.join(self.home, ".config", "bd", "config.yaml"),
                      encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""

    def queued(self):
        """Events bd has queued to send: the proof of whether metrics ran."""
        return glob.glob(os.path.join(self.home, ".beads", "eventsData",
                                      "*.evtq"))

    def test_first_run_turns_them_off_before_anything_is_queued(self):
        """The first command, whatever it is, turns them off before bd runs.

        `--version` runs bd. Had metrics still been on at that moment, bd
        would have queued an event for it; the empty queue is the evidence.
        """
        self.assertEqual(self.config(), "")
        code, out = self.dotdiw("--version")
        self.assertEqual(code, 0, out)
        self.assertIn(self.OFF, out)
        self.assertRegex(self.config(), r"(?m)^metrics:\n(?:[ \t]+.*\n)*?[ \t]+disabled: true")
        self.assertEqual(self.queued(), [])

    def test_silent_once_they_are_off(self):
        self.dotdiw("--version")
        code, out = self.dotdiw("--version")
        self.assertEqual(code, 0, out)
        self.assertNotIn(self.OFF, out)
        self.assertEqual(self.queued(), [])

    def test_turned_back_on_they_are_turned_off_again(self):
        """Every run, not only the first: `bd metrics on` does not hold."""
        self.dotdiw("--version")
        subprocess.run([shutil.which("bd"), "metrics", "on"], cwd=self.home,
                       env=self.env, capture_output=True)
        self.assertNotRegex(self.config(), r"disabled: true")
        code, out = self.dotdiw("learn")
        self.assertEqual(code, 0, out)
        self.assertIn(self.OFF, out)
        self.assertRegex(self.config(), r"disabled: true")


class Version(unittest.TestCase):
    def test_version_is_its_own(self):
        """`--version` reports this tool's version, not the one it wraps."""
        p = subprocess.run([sys.executable, "-I", DOTDIW, "--version"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("dotdiw "), p.stdout)


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheName(unittest.TestCase):
    """What dotdiw says names the tracker and never bd (invariant.one-name-for-all-four)."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_version_reports_the_trackers_number_only(self):
        p = subprocess.run([sys.executable, "-I", DOTDIW, "--version"], cwd=self.repo.path,
                           env=self.repo.env, capture_output=True, text=True)
        lines = p.stdout.strip().split("\n")
        self.assertEqual(len(lines), 2, p.stdout)
        self.assertRegex(lines[1], r"^  tracker \d+(\.\d+)+$")

    def test_without_the_tracker_the_message_is_the_install_command(self):
        """Nothing on PATH but the system: one line, Day 0's command, exit 127."""
        self.repo.dotdiw("init", "--prefix", "t")
        code, out = self.repo.dotdiw("list", env=dict(self.repo.env, PATH="/usr/bin:/bin"))
        self.assertEqual(code, 127, out)
        self.assertIn("dotdiw is not fully installed. Run: brew install adimpression/tap/dotdiw", out)
        self.assertNotRegex(out, r"(?<![\w./-])(bd|beads)(?![\w-])")

    def test_the_rename_says_what_is_now_true(self):
        """A file an earlier version's tracker wrote for agents names dotdiw afterwards, and the line says how many."""
        self.repo.write(".cursor/rules/beads.mdc", "Use bd create first.\n")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertIn("1 agent instruction file now names dotdiw", out)
        self.assertNotIn("Renamed bd", out)
        with open(os.path.join(self.repo.path, ".cursor", "rules", "beads.mdc"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "Use dotdiw create first.\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
