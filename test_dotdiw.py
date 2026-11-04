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

import contextlib
import glob
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from typing import TYPE_CHECKING

HERE = os.path.dirname(os.path.abspath(__file__))
DOTDIW = os.path.join(HERE, "dotdiw")
HOOKS_KEY = "core.hooksPath"

# A hook that leaves a trace on disk rather than on stdout: git routes hook
# output in ways that differ between versions, a file does not.
HOOK = '#!/bin/sh\necho ran >> "$(git rev-parse --show-toplevel)/%s"\n'


def have_bd():
    return shutil.which("bd") is not None


if TYPE_CHECKING:
    _TestBase = unittest.TestCase  # the mixin's assertions, for the type checker
else:
    _TestBase = object


def group1(pattern: str, text: str) -> str:
    """The first group of the match the text must hold."""
    m = re.search(pattern, text)
    assert m is not None, "%r not found in %r" % (pattern, text[-400:])
    return m.group(1)


def load_module(name, path=DOTDIW):
    """dotdiw as a module, loaded by path because it has no .py suffix."""
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def dotdiw_at(tag):
    """The dotdiw of a released tag, from this repository's own history, as a
    file; None where the tag is not here."""
    p = subprocess.run(
        ["git", "-C", HERE, "show", "%s:dotdiw" % tag], capture_output=True, text=True
    )
    if p.returncode != 0:
        return None
    path = os.path.join(tempfile.mkdtemp(prefix="dotdiw-%s-" % tag), "dotdiw")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(p.stdout)
    return path


class Repo:
    """A real git repository in a temporary directory, with a home of its own,
    going through the adapter named -- beads unless said otherwise, since
    most of what is tested here is what that tracker does to a repository."""

    def __init__(self, home=None, tracker="beads"):
        self.path = tempfile.mkdtemp(prefix="dotdiw-test-")
        self.home = home or tempfile.mkdtemp(prefix="dotdiw-home-")
        self.env = dict(os.environ, HOME=self.home)
        self.env.pop("BEADS_DIR", None)
        self.env.pop("DOTDIW_WITNESS", None)
        self.env.pop("DOTDIW_TRACKER", None)
        if tracker:
            self.env["DOTDIW_TRACKER"] = tracker
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
        p = subprocess.run(
            [shutil.which("bd")] + list(args),
            cwd=self.path,
            env=env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def git(self, *args):
        p = subprocess.run(["git"] + list(args), cwd=self.path, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def config(self, key):
        return self.git("config", "--get", key)[1].strip()

    def dotdiw(self, *args, cwd=None, env=None):
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW] + list(args),
            cwd=cwd or self.path,
            env=env or self.env,
            capture_output=True,
            text=True,
        )
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
        self.write(os.path.join(".git", "hooks", name), HOOK % marker, executable=True)

    def commit(self, name):
        self.write(name, name)
        self.git("add", name)
        return self.git("commit", "-m", name)

    def ran(self, marker):
        return os.path.exists(os.path.join(self.path, marker))

    def porcelain(self):
        return [line for line in self.git("status", "--porcelain")[1].split("\n") if line.strip()]

    def commits(self):
        return len([line for line in self.git("log", "--oneline")[1].split("\n") if line.strip()])

    def tracked(self, *paths):
        return [p for p in self.git("ls-files", "--", *paths)[1].split("\n") if p.strip()]

    def excluded(self):
        try:
            with open(os.path.join(self.path, ".git", "info", "exclude"), encoding="utf-8") as fh:
                return [line for line in fh.read().split("\n") if line and not line.startswith("#")]
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
        for f in glob.glob(
            os.path.join(self.path, ".beads", "embeddeddolt", "*", ".dolt", "repo_state.json")
        ):
            with open(f, encoding="utf-8") as fh:
                out += list(json.load(fh).get("remotes") or {})
        return sorted(out)

    def beads_config(self):
        try:
            with open(os.path.join(self.path, ".beads", "config.yaml"), encoding="utf-8") as fh:
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
        self.git("config", HOOKS_KEY, os.path.join(self.path, ".beads", "hooks"))
        cfg = os.path.join(self.path, ".beads", "config.yaml")
        with open(cfg, "a", encoding="utf-8") as fh:
            fh.write('\nsync:\n    remote: "git+ssh://git@example.invalid/x.git"\n')
        for f in glob.glob(
            os.path.join(self.path, ".beads", "embeddeddolt", "*", ".dolt", "repo_state.json")
        ):
            with open(f, encoding="utf-8") as fh:
                state = json.load(fh)
            state["remotes"] = {
                "origin": {
                    "name": "origin",
                    "url": "git+ssh://git@example.invalid/x.git",
                    "fetch_specs": [],
                    "params": {},
                }
            }
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
        self.assertEqual(
            sorted(line[3:] for line in self.repo.porcelain()), ["AGENTS.md", "CLAUDE.md"]
        )
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
        command = [line.strip() for line in out.split("\n") if line.strip().startswith("git add ")]
        self.assertEqual(len(command), 1, out)
        p = subprocess.run(
            command[0], shell=True, cwd=self.repo.path, capture_output=True, text=True
        )
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
        p = subprocess.run(
            [shutil.which("bd") or "bd", "list"],
            cwd=self.repo.path,
            env=self.repo.env,
            capture_output=True,
            text=True,
        )
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
        procs = [
            subprocess.Popen(
                [sys.executable, "-I", DOTDIW, "create", "At once in %s" % n],
                cwd=r.path,
                env=r.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for r, n in ((self.repo, "a"), (other, "b"))
        ]
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

        self.assertEqual(
            self.repo.config(HOOKS_KEY), "", "init must not point git at bd's hook directory"
        )
        self.repo.commit("second")
        self.assertTrue(self.repo.ran("own-hook-ran"), "the repository's own hook must still run")

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
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "init", "--prefix", "n"],
            cwd=plain,
            capture_output=True,
            text=True,
        )
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
        written = sorted(
            os.path.relpath(os.path.join(d, f), self.repo.home)
            for d, _, fs in os.walk(self.repo.home)
            for f in fs
        )
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
        self.assertFalse(
            old.ran("added-later"),
            "a hook added after adoption should be skipped, or there is nothing here to repair",
        )

        code, out = old.dotdiw("check")
        self.assertIn(HOOKS_KEY, out)
        self.assertEqual(old.config(HOOKS_KEY), "")

        old.commit("after-repair")
        self.assertTrue(old.ran("added-later"), "the hook must run once the override is gone")

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
        command = [line.strip() for line in out.split("\n") if line.strip().startswith("git rm -r")]
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
        self.assertEqual([line for line in old.porcelain() if ".beads" in line], [])
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
        self.assertEqual([line for line in st.porcelain() if ".beads" in line], [])
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
        # Outside any repository the default adapter would answer, and it
        # runs no binary; these tests are about the one that does.
        self.env = dict(os.environ, HOME=self.home, DOTDIW_TRACKER="beads")

    def dotdiw(self, *args):
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW] + list(args),
            cwd=self.home,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def config(self):
        try:
            with open(
                os.path.join(self.home, ".config", "bd", "config.yaml"), encoding="utf-8"
            ) as fh:
                return fh.read()
        except OSError:
            return ""

    def queued(self):
        """Events bd has queued to send: the proof of whether metrics ran."""
        return glob.glob(os.path.join(self.home, ".beads", "eventsData", "*.evtq"))

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
        subprocess.run(
            [shutil.which("bd") or "bd", "metrics", "on"],
            cwd=self.home,
            env=self.env,
            capture_output=True,
        )
        self.assertNotRegex(self.config(), r"disabled: true")
        code, out = self.dotdiw("learn")
        self.assertEqual(code, 0, out)
        self.assertIn(self.OFF, out)
        self.assertRegex(self.config(), r"disabled: true")

    FAKE_BD = """#!/bin/sh
echo "$*" >> "$HOME/bd.log"
if [ "$1 $2" = "metrics off" ]; then
    mkdir -p "$HOME/.config/bd"
    printf 'metrics:\\n  disabled: true\\n' > "$HOME/.config/bd/config.yaml"
fi
if [ "$1" = "--version" ]; then
    echo "bd version 1.3.2"
fi
exit 0
"""

    def fake(self):
        """A repository adopted under local, with a stand-in for bd on the
        PATH that writes down every command it is given."""
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        repo.env["PATH"] = os.path.join(repo.home, "bin") + ":/usr/bin:/bin"
        os.makedirs(os.path.join(repo.home, "bin"))
        path = os.path.join(repo.home, "bin", "bd")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.FAKE_BD)
        os.chmod(path, 0o755)
        code, out = repo.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        return repo, os.path.join(repo.home, "bd.log")

    @staticmethod
    def logged(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read().splitlines()
        except OSError:
            return []

    def test_off_before_the_tracker_runs_whichever_adapter_is_chosen(self):
        """A checkout on local still reaches bd through these four commands;
        metrics go off before the first thing bd is asked, and it is said."""
        for args in (
            ("tracker", "list"),
            ("tracker", "check", "beads"),
            ("tracker", "use", "beads"),
            ("tracker", "migrate", "local", "beads"),
        ):
            with self.subTest(command=" ".join(args)):
                repo, log = self.fake()
                self.assertEqual(self.logged(log), [], "init under local never ran it")
                code, out = repo.dotdiw(*args)
                ran = self.logged(log)
                self.assertTrue(ran, out)
                self.assertEqual(ran[0], "metrics off", ran)
                self.assertEqual(out.count(self.OFF), 1, out)

    def test_a_run_that_stays_on_local_never_runs_bd(self):
        repo, log = self.fake()
        code, out = repo.dotdiw("create", "Plain work")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.logged(log), [])
        self.assertNotIn(self.OFF, out)


class Version(unittest.TestCase):
    def test_version_is_its_own(self):
        """`--version` reports this tool's version, not the one it wraps."""
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "--version"], capture_output=True, text=True
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("dotdiw "), p.stdout)


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheName(unittest.TestCase):
    """What dotdiw says names the tracker and never bd (invariant.one-name-for-all-four)."""

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_version_names_the_chosen_adapter_and_its_number(self):
        """The one line where the adapter's name belongs: the tracker line."""
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "--version"],
            cwd=self.repo.path,
            env=self.repo.env,
            capture_output=True,
            text=True,
        )
        lines = p.stdout.strip().split("\n")
        self.assertEqual(len(lines), 2, p.stdout)
        self.assertRegex(lines[1], r"^  tracker beads \d+(\.\d+)+$")
        self.assertNotIn("0.6.0", lines[1], "the tracker underneath, not this tool")

    def test_without_the_tracker_the_message_is_the_install_command(self):
        """Nothing on PATH but the system: one line, Day 0's command, exit 127."""
        self.repo.dotdiw("init", "--prefix", "t")
        code, out = self.repo.dotdiw("list", env=dict(self.repo.env, PATH="/usr/bin:/bin"))
        self.assertEqual(code, 127, out)
        self.assertIn(
            "dotdiw is not fully installed. Run: brew install adimpression/tap/dotdiw", out
        )
        self.assertNotRegex(out, r"(?<![\w./-])(bd|beads)(?![\w-])")

    def test_the_rename_says_what_is_now_true(self):
        """A file an earlier version's tracker wrote for agents names dotdiw afterwards, and the line says how many."""
        self.repo.write(".cursor/rules/beads.mdc", "Use bd create first.\n")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertIn("1 agent instruction file now names dotdiw", out)
        self.assertNotIn("Renamed bd", out)
        with open(
            os.path.join(self.repo.path, ".cursor", "rules", "beads.mdc"), encoding="utf-8"
        ) as fh:
            self.assertEqual(fh.read(), "Use dotdiw create first.\n")


class InterfaceRecords(_TestBase):
    """The records scenario every shipped adapter answers the same way:
    describe, open, create, need, show, list, ready, the blocked close, the
    close, update, and a composed pour. Mixed into one class per adapter."""

    ADAPTER: str

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        home = os.environ.get("HOME", "")
        os.environ["HOME"] = self.repo.home
        self.addCleanup(os.environ.__setitem__, "HOME", home)
        self.addCleanup(os.environ.pop, "BEADS_DIR", None)
        self.m = load_module("dotdiw_adapter_" + self.ADAPTER)
        self.repo.git("config", "--local", "dotdiw.workspace", "k" * 16)
        os.makedirs(self.repo.workspace())

    def ask(self, operation, **request):
        request.setdefault("root", self.repo.path)
        request.setdefault("tracker", self.ADAPTER)
        return self.m.invoke_tracker("operation." + operation, request)

    def test_the_interface_in_records(self):
        out = self.ask("describe-tracker")
        self.assertEqual(out["status"], "completed", out)
        info = out["info"]
        self.assertEqual(
            (info["name"], info["origin"], info["nativeNeeds"]), (self.ADAPTER, "shipped", True)
        )
        self.assertRegex(info["version"], r"^\d+(\.\d+)+$")
        self.assertIsNone(out.get("path"), "unopened: no store yet")
        self.assertEqual(self.ask("create-item", title="Too soon")["reason"], "no-workspace")

        opened = self.ask("open-tracker", prefix="t")
        self.assertEqual((opened["status"], opened["created"]), ("completed", True), opened)
        self.assertTrue(opened["path"].startswith(self.repo.workspace()))
        self.assertTrue(os.path.exists(opened["path"]))
        self.assertEqual(sorted(os.listdir(self.repo.path)), [".git"], "nothing in the tree")
        again = self.ask("open-tracker", prefix="t")
        self.assertEqual((again["status"], again["created"]), ("completed", False))
        self.assertEqual(self.ask("describe-tracker")["path"], opened["path"])

        a = self.ask("create-item", title="First", kind="task", priority=1)["item"]
        self.assertTrue(a["id"].startswith("t-"), a)
        self.assertEqual(
            (a["title"], a["status"], a["kind"], a["priority"]), ("First", "open", "task", 1)
        )
        b = self.ask("create-item", title="Second", parent=a["id"])["item"]
        self.assertEqual(b["parent"], a["id"])
        c = self.ask("create-item", title="Third", description="the third")["item"]
        orphan = self.ask("create-item", title="Orphan", parent="t-nope")
        self.assertEqual(
            (orphan["status"], orphan["reason"]), ("failed", "parent-not-found"), orphan
        )

        edge = self.ask("add-need", id=c["id"], needs=b["id"])
        self.assertEqual(
            (edge["status"], edge["edge"]), ("completed", {"id": c["id"], "needs": b["id"]})
        )
        self.assertEqual(
            self.ask("add-need", id=c["id"], needs="t-zzz")["reason"], "item-not-found"
        )

        shown = self.ask("show-item", id=a["id"])
        self.assertEqual(shown["item"]["id"], a["id"])
        self.assertEqual([k["id"] for k in shown["children"]], [b["id"]])
        self.assertEqual(self.ask("show-item", id=c["id"])["item"]["needs"], [b["id"]])
        self.assertEqual(self.ask("show-item", id="t-zzz")["reason"], "item-not-found")

        ready = {i["id"] for i in self.ask("ready-items")["items"]}
        self.assertIn(a["id"], ready)
        self.assertIn(b["id"], ready)
        self.assertNotIn(c["id"], ready, "blocked by its need")
        listed = self.ask("list-items", scope="all")["items"]
        self.assertEqual({i["id"] for i in listed}, {a["id"], b["id"], c["id"]})
        self.assertEqual(
            [i["id"] for i in self.ask("list-items", parent=a["id"])["items"]], [b["id"]]
        )

        refused = self.ask("close-item", id=c["id"])
        self.assertEqual(
            (refused["status"], refused["reason"], refused["blockedBy"]),
            ("blocked", "blocked", [b["id"]]),
            refused,
        )
        parent = self.ask("close-item", id=a["id"])
        self.assertEqual((parent["status"], parent["blockedBy"]), ("blocked", [b["id"]]), parent)
        closed = self.ask("close-item", id=b["id"], closeReason="done")
        self.assertEqual((closed["status"], closed["closedIds"]), ("completed", [b["id"]]))
        self.assertEqual((closed["item"]["status"], closed["item"]["reason"]), ("closed", "done"))
        self.assertIn(c["id"], {i["id"] for i in self.ask("ready-items")["items"]})

        updated = self.ask(
            "update-item", id=c["id"], title="Third, renamed", status="in_progress", priority=0
        )
        self.assertEqual(
            (updated["item"]["title"], updated["item"]["status"], updated["item"]["priority"]),
            ("Third, renamed", "in_progress", 0),
        )
        self.assertEqual(
            self.ask("update-item", id=c["id"], status="closed")["reason"], "close-through-update"
        )

        steps = [
            {"id": "one", "title": "One"},
            {"id": "two", "title": "Two", "needs": ["one"]},
            {"id": "three", "title": "Three", "needs": ["two"]},
        ]
        poured = self.ask("pour-steps", formulaRef="mol-x", title="mol-x", steps=steps)
        self.assertEqual(poured["status"], "completed", poured)
        self.assertEqual(len(poured["stepIds"]), 3)
        root = self.ask("show-item", id=poured["rootId"])
        self.assertEqual(root["item"]["title"], "mol-x")
        self.assertIn(root["item"]["kind"], ("epic", "molecule"))
        self.assertEqual({k["id"] for k in root["children"]}, set(poured["stepIds"]))
        self.assertEqual(
            self.ask("show-item", id=poured["stepIds"][1])["item"]["needs"], [poured["stepIds"][0]]
        )
        self.assertEqual(
            self.ask(
                "pour-steps",
                formulaRef="mol-y",
                title="mol-y",
                steps=[{"id": "a", "title": "A", "needs": ["zzz"]}],
            )["reason"],
            "step-not-found",
        )
        self.assertEqual(
            self.ask("pour-steps", formulaRef="mol-z", title="mol-z", steps=[])["reason"],
            "no-steps",
        )
        # The steps close in their order and nothing else; the root is the
        # adapter's to close when the last step closes, or the worker's.
        one, two, three = poured["stepIds"]
        self.assertEqual(self.ask("close-item", id=three)["blockedBy"], [two])
        self.assertEqual(self.ask("close-item", id=one, closeReason="did")["closedIds"], [one])
        self.assertEqual(self.ask("close-item", id=two, closeReason="did")["closedIds"], [two])
        last = self.ask("close-item", id=three, closeReason="did")
        self.assertEqual(last["closedIds"][0], three)
        if poured["rootId"] not in last["closedIds"]:
            self.assertEqual(
                self.ask("close-item", id=poured["rootId"])["closedIds"], [poured["rootId"]]
            )
        self.assertEqual(self.ask("show-item", id=poured["rootId"])["item"]["status"], "closed")


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheBeadsAdapter(InterfaceRecords, unittest.TestCase):
    """The beads adapter answers the interface in records, quietly, against
    a real tracker under a temporary home; its two extras answer the
    pass-through and the metrics; without the binary every answer is the
    same one line's reason."""

    ADAPTER = "beads"

    def test_what_it_says_of_itself(self):
        info = self.ask("describe-tracker")["info"]
        self.assertEqual(info["extras"], ["forward", "metrics-off"])
        self.assertTrue(self.ask("open-tracker", prefix="t")["path"].endswith(".beads"))

    def test_the_extras(self):
        m = self.m
        first = m.invoke_extra("metrics-off", {"root": self.repo.path, "tracker": "beads"})
        self.assertEqual((first["status"], first["turnedOff"]), ("completed", True), first)
        self.assertEqual(first["path"], "~/.config/bd/config.yaml")
        second = m.invoke_extra("metrics-off", {"root": self.repo.path, "tracker": "beads"})
        self.assertEqual(second["turnedOff"], False)
        self.ask("open-tracker", prefix="t")
        self.ask("create-item", title="Something to list")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            forwarded = m.invoke_extra(
                "forward",
                {
                    "root": self.repo.path,
                    "tracker": "beads",
                    "arguments": ["list", "--json", "--brief"],
                },
            )
        self.assertEqual(forwarded["status"], "completed", forwarded)
        self.assertIn("Something to list", forwarded["output"])
        self.assertEqual(
            out.getvalue(), forwarded["output"], "the stream went to the terminal as returned"
        )
        self.assertNotIn("bd", out.getvalue().split())
        # The rewrite, on output that names the binary on every line: its
        # own help. Through the pass-through, every "bd" reads dotdiw.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            helped = m.invoke_extra(
                "forward", {"root": self.repo.path, "tracker": "beads", "arguments": ["--help"]}
            )
        self.assertEqual(helped["status"], "completed", helped)
        self.assertIn("dotdiw", helped["output"])
        self.assertNotRegex(helped["output"], r"(?<![\w./-])bd(?![\w-])")
        self.assertRegex(helped["output"], r"dotdiw \[command\]|Usage:")

    def test_the_door_turns_metrics_off_before_it_asks_anything(self):
        """Reached by name, without the run having chosen it: off first, and
        the config says so by the time the first answer comes back."""
        self.assertEqual(self.ask("describe-tracker")["status"], "completed")
        with open(
            os.path.join(self.repo.home, ".config", "bd", "config.yaml"), encoding="utf-8"
        ) as fh:
            self.assertRegex(fh.read(), r"disabled: true")

    def test_without_the_binary_every_answer_says_so(self):
        path = os.environ["PATH"]
        os.environ["PATH"] = "/usr/bin:/bin"
        self.addCleanup(os.environ.__setitem__, "PATH", path)
        for operation, request in (
            ("describe-tracker", {}),
            ("open-tracker", {"prefix": "t"}),
            ("create-item", {"title": "x"}),
            ("list-items", {}),
            ("ready-items", {}),
            ("show-item", {"id": "t-1"}),
        ):
            out = self.ask(operation, **request)
            self.assertEqual(
                (out["status"], out["reason"], out["exitCode"]),
                ("failed", "not-installed", 127),
                operation,
            )
        out = self.m.invoke_extra(
            "forward", {"root": self.repo.path, "tracker": "beads", "arguments": ["list"]}
        )
        self.assertEqual((out["reason"], out["exitCode"]), ("not-installed", 127))
        out = self.m.invoke_extra("metrics-off", {"root": self.repo.path, "tracker": "beads"})
        self.assertEqual((out["status"], out["turnedOff"]), ("completed", False))


class TheLocalAdapter(InterfaceRecords, unittest.TestCase):
    """The local adapter answers the interface in records from one sqlite
    file under the home, runs nothing, and closes a poured root itself when
    its last step closes."""

    ADAPTER = "local"

    def test_what_it_says_of_itself(self):
        info = self.ask("describe-tracker")["info"]
        self.assertEqual(info["extras"], [])
        opened = self.ask("open-tracker", prefix="t")
        self.assertTrue(opened["path"].endswith("dotdiw.sqlite"))
        self.assertEqual(sorted(os.listdir(self.repo.workspace())), ["dotdiw.sqlite"])
        out = self.m.invoke_extra(
            "forward", {"root": self.repo.path, "tracker": "local", "arguments": ["list"]}
        )
        self.assertEqual((out["status"], out["reason"]), ("failed", "unsupported"))

    def test_a_poured_root_closes_with_its_last_step(self):
        self.ask("open-tracker", prefix="t")
        poured = self.ask(
            "pour-steps",
            formulaRef="mol-x",
            title="mol-x",
            steps=[{"id": "a", "title": "A"}, {"id": "b", "title": "B", "needs": ["a"]}],
        )
        a, b = poured["stepIds"]
        self.assertEqual(self.ask("close-item", id=a)["closedIds"], [a])
        self.assertEqual(
            self.ask("close-item", id=b, closeReason="done")["closedIds"], [b, poured["rootId"]]
        )
        root = self.ask("show-item", id=poured["rootId"])["item"]
        self.assertEqual((root["status"], root["reason"]), ("closed", "every step closed"))
        # A plain parent is the worker's to close; a cycle is refused.
        p = self.ask("create-item", title="P")["item"]["id"]
        c = self.ask("create-item", title="C", parent=p)["item"]["id"]
        self.assertEqual(self.ask("close-item", id=p)["blockedBy"], [c])
        self.assertEqual(self.ask("close-item", id=c)["closedIds"], [c])
        self.assertEqual(self.ask("close-item", id=p)["closedIds"], [p])
        x = self.ask("create-item", title="X")["item"]["id"]
        y = self.ask("create-item", title="Y")["item"]["id"]
        self.assertEqual(self.ask("add-need", id=x, needs=y)["status"], "completed")
        self.assertEqual(self.ask("add-need", id=y, needs=x)["reason"], "cycle")
        self.assertEqual(self.ask("add-need", id=x, needs=x)["reason"], "cycle")
        self.assertEqual(self.ask("update-item", id=x, status="nonsense")["reason"], "bad-status")
        self.assertEqual(self.ask("update-item", id=x, parent="t-zzzz")["reason"], "item-not-found")

    def other_connection(self):
        """A second connection to the store, one that will not wait."""
        other = sqlite3.connect(self.ask("describe-tracker")["path"], timeout=0)
        self.addCleanup(other.close)
        return other

    @staticmethod
    def meddle(other, sql, args=()):
        try:
            other.execute(sql, args)
            other.commit()
            return "written"
        except sqlite3.OperationalError as e:
            other.rollback()
            return str(e)

    def test_two_needs_cannot_close_a_cycle_between_them(self):
        """Another writer tries the opposite edge at the moment this one has
        checked for a cycle: it must wait, and then its own check sees this."""
        self.ask("open-tracker", prefix="t")
        a = self.ask("create-item", title="A")["item"]["id"]
        b = self.ask("create-item", title="B")["item"]["id"]
        other, real, seen = self.other_connection(), self.m.local_reaches, []

        def reaches(conn, start, target):
            found = real(conn, start, target)
            sql = "INSERT INTO edges (id, needs) VALUES (?, ?)"
            seen.append(self.meddle(other, sql, (b, a)))
            return found

        self.m.local_reaches = reaches
        self.addCleanup(setattr, self.m, "local_reaches", real)
        out = self.ask("add-need", id=a, needs=b)
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual(seen, ["database is locked"])
        self.m.local_reaches = real
        self.assertEqual(self.ask("add-need", id=b, needs=a)["reason"], "cycle")

    def test_a_need_cannot_slip_in_under_a_close(self):
        """Another writer adds a need at the moment the close has found no
        blockers: it must wait, so the close is not over an open need."""
        self.ask("open-tracker", prefix="t")
        a = self.ask("create-item", title="A")["item"]["id"]
        b = self.ask("create-item", title="B")["item"]["id"]
        other, real, seen = self.other_connection(), self.m.local_blockers, []

        def blockers(conn, ident):
            found = real(conn, ident)
            sql = "INSERT INTO edges (id, needs) VALUES (?, ?)"
            seen.append(self.meddle(other, sql, (a, b)))
            return found

        self.m.local_blockers = blockers
        self.addCleanup(setattr, self.m, "local_blockers", real)
        out = self.ask("close-item", id=a)
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual(seen, ["database is locked"])
        self.assertEqual(self.ask("show-item", id=a)["item"]["needs"], [])

    def test_every_write_holds_the_lock_from_its_first_read(self):
        self.ask("open-tracker", prefix="t")
        p = self.ask("create-item", title="P")["item"]["id"]
        q = self.ask("create-item", title="Q")["item"]["id"]
        other = self.other_connection()
        for name in ("local_fetch", "local_new_id"):
            real = getattr(self.m, name)
            seen: list[str] = []

            def first(*args, real=real, seen=seen):
                seen.append(self.meddle(other, "BEGIN IMMEDIATE"))
                return real(*args)

            setattr(self.m, name, first)
            for operation, request in (
                ("create-item", {"title": "R", "parent": p}),
                ("add-need", {"id": p, "needs": q}),
                ("close-item", {"id": q}),
                ("update-item", {"id": p, "title": "P again"}),
                (
                    "pour-steps",
                    {"formulaRef": "m", "title": "m", "steps": [{"id": "s", "title": "S"}]},
                ),
            ):
                out = self.ask(operation, **request)
                self.assertEqual(out["status"], "completed", (operation, out))
                self.assertEqual(set(seen) - {"database is locked"}, set(), (operation, name))
            setattr(self.m, name, real)

    def test_a_store_another_writer_holds_is_one_line(self):
        self.ask("open-tracker", prefix="t")
        a = self.ask("create-item", title="A")["item"]["id"]
        b = self.ask("create-item", title="B")["item"]["id"]
        other = self.other_connection()
        other.execute("BEGIN IMMEDIATE")
        self.addCleanup(other.rollback)
        self.m.LOCAL_WAIT_SECONDS = 0
        for operation, request in (
            ("create-item", {"title": "C"}),
            ("add-need", {"id": a, "needs": b}),
            ("close-item", {"id": a}),
            ("update-item", {"id": a, "title": "A again"}),
            ("pour-steps", {"formulaRef": "m", "title": "m", "steps": [{"id": "s", "title": "S"}]}),
        ):
            out = self.ask(operation, **request)
            self.assertEqual((out["status"], out["reason"]), ("failed", "adapter-failed"), out)
            self.assertIn("another writer holds", out["summary"])


class TheLocalCommandLine(unittest.TestCase):
    """A repository adopted under the local adapter with no tracker binary on
    the machine: init, create, the formula poured, list, ready, show, close
    and update work through the interface, the tree holds the two
    declaration files only, and a command the tracker does not have is
    refused in one line."""

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.env = dict(self.repo.env, PATH="/usr/bin:/bin")
        self.repo.write("release-through-tap.formula.toml", FORMULA_A)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the project as it stands")

    def dotdiw(self, *args):
        return self.repo.dotdiw(*args, env=self.env)

    def test_help_is_the_conventions_text(self):
        """The tracker's help is the pass-through's to give, and a store has
        none: --help, -h and help print what bare dotdiw prints, and exit 0."""
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, taught = self.dotdiw()
        self.assertEqual(code, 0, taught)
        self.assertIn("how work gets done in this project", taught)
        for word in ("--help", "-h", "help"):
            code, out = self.dotdiw(word)
            self.assertEqual(code, 0, out)
            self.assertEqual(out, taught, word)

    def adopted(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)

    def made(self, *args):
        code, out = self.dotdiw("create", *args, "-q")
        self.assertEqual(code, 0, out)
        return group1(r"Created issue: (\S+)", out)

    def test_a_description_is_saved_on_the_item(self):
        self.adopted()
        ident = self.made("Described", "-d", "Why this work exists")
        store = os.path.join(self.repo.workspace(), "dotdiw.sqlite")
        conn = sqlite3.connect(store)
        self.addCleanup(conn.close)
        row = conn.execute("SELECT description FROM items WHERE id = ?", (ident,)).fetchone()
        self.assertEqual(row, ("Why this work exists",))

    def test_json_is_json(self):
        """A flag the command accepts is a promise about what it prints: what
        each command prints with --json parses, in the shape the tracker's
        own does, one object or a list of the records written."""
        self.adopted()
        code, out = self.dotdiw("create", "Thing", "--json")
        self.assertEqual(code, 0, out)
        thing = json.loads(out)
        self.assertEqual((thing["title"], thing["status"]), ("Thing", "open"))
        other = self.made("Other")
        code, out = self.dotdiw("update", thing["id"], "--title", "Renamed", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([i["title"] for i in json.loads(out)], ["Renamed"])
        code, out = self.dotdiw("dep", "add", other, thing["id"], "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out), {"id": other, "needs": thing["id"]})
        code, out = self.dotdiw("close", thing["id"], "--reason", "done", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([(i["id"], i["reason"]) for i in json.loads(out)], [(thing["id"], "done")])
        code, out = self.dotdiw("mol", "pour", "mol-release-through-tap", "--json")
        self.assertEqual(code, 0, out)
        poured = json.loads(out)
        self.assertTrue(poured["rootId"] and poured["stepIds"], poured)

    def test_a_chain_is_listed_to_its_end(self):
        self.adopted()
        root = self.made("Root")
        child = self.made("Child", "--parent", root)
        grand = self.made("Grandchild", "--parent", child)
        great = self.made("Great-grandchild", "--parent", grand)
        for verb in ("list", "ready"):
            code, out = self.dotdiw(verb)
            self.assertEqual(code, 0, out)
            lines = out.splitlines()
            self.assertEqual(
                lines[:4],
                [
                    "\u25cb %s P2 Root" % root,
                    "\u2514\u2500\u2500 \u25cb %s P2 Child" % child,
                    "    \u2514\u2500\u2500 \u25cb %s P2 Grandchild" % grand,
                    "        \u2514\u2500\u2500 \u25cb %s P2 Great-grandchild" % great,
                ],
                verb,
            )

    def test_a_tree_is_drawn_the_way_the_tracker_draws_one(self):
        """The same lines bd prints for the same tree, and an item in a parent
        loop, which no root reaches, is still printed."""
        m = load_module("dotdiw_for_the_tree")

        def item(ident, parent=None):
            return {
                "id": ident,
                "title": ident.upper(),
                "status": "open",
                "priority": 2,
                "parent": parent,
            }

        items = [
            item("r"),
            item("c1", "r"),
            item("g", "c1"),
            item("c2", "r"),
            item("x", "y"),
            item("y", "x"),
        ]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            m.show_forward(
                {"arguments": ["list"]},
                {
                    "operation": "operation.list-items",
                    "answers": [{"status": "completed", "summary": "x", "items": items}],
                    "printed": False,
                },
            )
        self.assertEqual(
            buffer.getvalue().splitlines()[:6],
            [
                "\u25cb r P2 R",
                "\u251c\u2500\u2500 \u25cb c1 P2 C1",
                "\u2502   \u2514\u2500\u2500 \u25cb g P2 G",
                "\u2514\u2500\u2500 \u25cb c2 P2 C2",
                "\u25cb x P2 X",
                "\u2514\u2500\u2500 \u25cb y P2 Y",
            ],
        )

    FIRST_DECLARED_LAST = """formula = "mol-backwards"
description = "A procedure whose steps are written with the last first."
examples = ["Run the backwards procedure"]
version = 1
type = "workflow"

[[steps]]
id = "second"
title = "The second step"
needs = ["first"]

[[steps]]
id = "first"
title = "The first step"
"""

    def test_a_need_on_a_step_declared_later_pours(self):
        self.adopted()
        self.repo.write("backwards.formula.toml", self.FIRST_DECLARED_LAST)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the backwards one")
        code, out = self.dotdiw("mol", "pour", "mol-backwards")
        self.assertEqual(code, 0, out)
        root = group1(r"Root issue: (\S+)", out)
        code, out = self.dotdiw("list", "--all", "--json")
        rows = {r["title"]: r for r in json.loads(out) if r.get("parent") == root}
        self.assertEqual(rows["The second step"]["needs"], [rows["The first step"]["id"]])

    def test_a_cycle_among_steps_is_refused_and_writes_nothing(self):
        self.adopted()
        self.repo.write(
            "loop.formula.toml",
            self.FIRST_DECLARED_LAST.replace("mol-backwards", "mol-loop").replace(
                'title = "The first step"', 'title = "The first step"\nneeds = ["second"]'
            ),
        )
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the loop")
        code, out = self.dotdiw("mol", "pour", "mol-loop")
        self.assertEqual(code, 1, out)
        self.assertIn("cycle", out)
        self.assertNotIn("Traceback", out)
        code, out = self.dotdiw("list", "--all", "--json")
        self.assertEqual(json.loads(out), [])

    def test_creates_at_once_all_land(self):
        """Eight processes on one store: each waits its turn, and each id is
        one nobody else was given."""
        self.adopted()
        running = [
            subprocess.Popen(
                [sys.executable, "-I", DOTDIW, "create", "Work %d" % n, "-q"],
                cwd=self.repo.path,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for n in range(8)
        ]
        said = [p.communicate()[0] for p in running]
        self.assertEqual([p.returncode for p in running], [0] * 8, said)
        code, out = self.dotdiw("list", "--json")
        self.assertEqual(
            sorted(i["title"] for i in json.loads(out)), ["Work %d" % n for n in range(8)]
        )

    def test_a_switch_that_fails_keeps_the_choice(self):
        """No bd on this PATH: the switch fails, says so, and the checkout
        stays on the tracker that works."""
        self.adopted()
        code, out = self.dotdiw("tracker", "use", "beads")
        self.assertNotEqual(code, 0, out)
        self.assertEqual(self.repo.config("dotdiw.tracker"), "local")
        code, out = self.dotdiw("create", "Still works here")
        self.assertEqual(code, 0, out)

    def test_a_day_without_the_binary(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        self.assertIn("Adopted. The tracker is local, under", out)
        self.assertIn("Declared where work starts", out)
        self.assertEqual(self.repo.config("dotdiw.tracker"), "local")
        self.assertEqual(
            sorted(os.listdir(self.repo.path)),
            [".git", "AGENTS.md", "CLAUDE.md", "release-through-tap.formula.toml"],
        )
        self.assertEqual(sorted(os.listdir(self.repo.workspace())), ["dotdiw.sqlite"])
        code, out = self.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertIn("this repository is adopted; its tracker is", out)

        code, out = self.dotdiw("--version")
        self.assertEqual(out.strip().split("\n")[1], "  tracker local 0.6.0", out)

        code, out = self.dotdiw("create", "Release v0.3.0 through the tap")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"Created issue: w-[a-z0-9]{4} \u2014 Release v0.3.0 through the tap")
        self.assertIn("  Priority: P2\n  Status: open", out)
        self.assertIn("release-through-tap", out, "the formula surfaced")
        work = group1("Created issue: (\\S+)", out)

        code, out = self.dotdiw("mol", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol: created 4 issues", out)
        root = group1("Root issue: (\\S+)", out)

        code, out = self.dotdiw("list", "--all", "--json")
        rows = json.loads(out)
        self.assertEqual(len(rows), 5)
        steps = [r["id"] for r in rows if r.get("parent") == root]
        self.assertEqual(len(steps), 3)
        code, out = self.dotdiw("list")
        self.assertIn(work, out)
        self.assertIn("\u2514\u2500\u2500", out, "the children are drawn under the root")
        self.assertIn("Total: 5 issues (5 open, 0 in progress)", out)

        code, out = self.dotdiw("ready")
        self.assertEqual(code, 0, out)
        self.assertIn("Ready: 3 issues with no active blockers", out)
        first = [r for r in rows if r.get("parent") == root and not r["needs"]][0]["id"]
        last = [
            r
            for r in rows
            if r.get("parent") == root
            and r["needs"]
            and r["needs"][0]
            not in [x["id"] for x in rows if not x["needs"] and x.get("parent") == root]
        ][0]["id"]
        code, out = self.dotdiw("close", last)
        self.assertEqual(code, 1, out)
        self.assertIn("cannot close blocked issue: %s is blocked by [" % last, out)
        code, out = self.dotdiw("close", first, "--reason", "bumped")
        self.assertEqual(code, 0, out)
        self.assertIn(
            "\u2713 Closed %s \u2014 Bump the formula to the new version: bumped" % first, out
        )
        order = [first] + [s for s in steps if s != first and s != last] + [last]
        for step in order[1:]:
            code, out = self.dotdiw("close", step, "-r", "done")
            self.assertEqual(code, 0, out)
        self.assertIn(
            "\u2713 Closed %s: every step closed" % root, out, "the root closed with its last step"
        )

        code, out = self.dotdiw("show", root)
        self.assertEqual(code, 0, out)
        self.assertIn("%s \u00b7 mol-release-through-tap   [P2 \u00b7 CLOSED]" % root, out)
        self.assertIn("Close reason: every step closed", out)
        self.assertIn("CHILDREN", out)
        code, out = self.dotdiw(
            "update", work, "--title", "Release v0.3.1 through the tap", "-p", "1"
        )
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 Updated issue: %s \u2014 Release v0.3.1 through the tap" % work, out)
        other = group1("Created issue: (\\S+)", self.dotdiw("create", "Another", "-q")[1])
        code, out = self.dotdiw("dep", "add", other, work)
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 Added dependency: %s depends on %s" % (other, work), out)
        code, out = self.dotdiw("show", other, "--json")
        self.assertEqual(json.loads(out)["needs"], [work])

        code, out = self.dotdiw("frobnicate", "--now")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.strip(), "dotdiw: frobnicate is not a command of this tracker.")
        code, out = self.dotdiw("show", "w-zzzz")
        self.assertEqual(code, 1, out)
        self.assertIn("w-zzzz names no item here", out)
        self.assertEqual(
            sorted(os.listdir(self.repo.path)),
            [".git", "AGENTS.md", "CLAUDE.md", "release-through-tap.formula.toml"],
        )

    def test_an_unknown_adapter_is_one_line(self):
        code, out = self.dotdiw("init", "--tracker", "nowhere")
        self.assertEqual(code, 1, out)
        self.assertIn("dotdiw: nowhere is not a tracker here; registered: beads, local.", out)
        self.assertEqual(self.repo.config("dotdiw.tracker"), "")
        code, out = self.dotdiw("init", "--tracker=local", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("create", "Something", "--tracker", "nowhere")
        self.assertEqual(code, 1, out)
        self.assertIn("dotdiw: nowhere is not a tracker here", out)


BOOM = """import os
def _ok(**kw):
    d = {"status": "completed", "summary": "ok", "exitCode": 0}
    d.update(kw)
    return d
def store(root):
    return os.path.join(dotdiw_workspace(root), "boom")
def open_tracker(request):
    p = store(request["root"])
    made = not os.path.exists(p)
    os.makedirs(p, exist_ok=True)
    return _ok(created=made, path=p)
def describe(request):
    return _ok(info={"name": "boom", "version": "0", "origin": "loaded"}, path=store(request["root"]))
def create(request):
    raise RuntimeError("the adapter has a bug")
def none(request):
    return _ok(items=[])
def ok(request):
    return _ok()
TRACKER = {"info": {"name": "boom", "version": "0", "checkTarget": "scratch"},
           "operations": {"operation.open-tracker": open_tracker, "operation.describe-tracker": describe,
                          "operation.create-item": create, "operation.add-need": ok,
                          "operation.pour-steps": ok, "operation.close-item": ok, "operation.show-item": ok,
                          "operation.list-items": none, "operation.update-item": ok, "operation.ready-items": none},
           "extras": {}, "store": store}
"""


class TheTrackerCommands(unittest.TestCase):
    """Choosing in the open: list names the adapters and marks the
    checkout's, use writes the choice and opens the store, check proves an
    adapter against the scenario, and migrate moves a workspace's work with
    ids, statuses, reasons and needs intact, the source untouched."""

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.repo.write("release-through-tap.formula.toml", FORMULA_A)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the project as it stands")

    def test_a_loaded_adapter_that_fails_is_one_line(self):
        """An adapter under the home that raises, and a module that does not
        load, reach the worker as one line each, never as a traceback."""
        trackers = os.path.join(self.repo.home, ".dotdiw", "trackers")
        os.makedirs(trackers)
        with open(os.path.join(trackers, "boom.py"), "w", encoding="utf-8") as fh:
            fh.write(BOOM)
        with open(os.path.join(trackers, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def broken(:\n")
        env = dict(self.repo.env, PATH="/usr/bin:/bin")
        code, out = self.repo.dotdiw("init", "--tracker", "boom", "--prefix", "b", env=env)
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("create", "Try the adapter", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn(
            "dotdiw: boom failed inside create-item: RuntimeError: the adapter has a bug", out
        )
        self.assertNotIn("Traceback", out)
        code, out = self.repo.dotdiw("tracker", "list", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("broken   did not load   loaded, from ", out)
        code, out = self.repo.dotdiw("tracker", "use", "broken", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("dotdiw: broken did not load from ", out)
        self.assertIn("SyntaxError", out)
        self.assertNotIn("Traceback", out)

    def test_values_outside_their_type_are_one_line(self):
        """The right field names holding the wrong things: what would raise
        wherever the value is read is refused where it comes in."""
        trackers = os.path.join(self.repo.home, ".dotdiw", "trackers")
        os.makedirs(trackers)
        wrong = BOOM.replace('"boom"', '"wrong"').replace(
            'raise RuntimeError("the adapter has a bug")', 'return _ok(item="not a record")'
        )
        wrong = wrong.replace("return _ok(items=[])", 'return _ok(items="not a list")')
        with open(os.path.join(trackers, "wrong.py"), "w", encoding="utf-8") as fh:
            fh.write(wrong)
        env = dict(self.repo.env, PATH="/usr/bin:/bin")
        code, out = self.repo.dotdiw("init", "--tracker", "wrong", "--prefix", "b", env=env)
        self.assertEqual(code, 0, out)
        for args, operation in (
            (("create", "Try it"), "create-item"),
            (("list",), "list-items"),
            (("ready",), "ready-items"),
            (("show", "b-1"), "show-item"),
            (("update", "b-1", "--title", "New"), "update-item"),
        ):
            with self.subTest(command=args[0]):
                code, out = self.repo.dotdiw(*args, env=env)
                self.assertEqual(code, 1, out)
                self.assertIn("dotdiw: wrong failed inside %s: DoorError:" % operation, out)
                self.assertNotIn("Traceback", out)

    def test_list_use_and_check_under_local(self):
        env = dict(self.repo.env, PATH="/usr/bin:/bin")
        code, out = self.repo.dotdiw("init", "--prefix", "w", env=env)
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("tracker", "list", env=env)
        self.assertEqual(code, 0, out)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2, out)
        self.assertRegex(lines[0], r"^  beads\s+not installed\s+shipped$")
        self.assertRegex(lines[1], r"^  local\s+0\.6\.0\s+shipped\s+\(this checkout\)$")
        code, out = self.repo.dotdiw("tracker", "check", "local", env=env)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("  pass  operation."), 10, out)
        self.assertIn("\u2713 local passed 10 of 10.", out)
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.repo.home, ".dotdiw"))),
            [self.repo.key()],
            "the check's scratch workspace is gone",
        )
        code, out = self.repo.dotdiw("tracker", "use", "nowhere", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("nowhere is not a tracker here; registered: beads, local.", out)
        self.assertEqual(self.repo.config("dotdiw.tracker"), "local")
        code, out = self.repo.dotdiw("tracker", "check", "nowhere", env=env)
        self.assertEqual(code, 1, out)
        code, out = self.repo.dotdiw("tracker", env=env)
        self.assertEqual(code, 2, out)
        self.assertIn("tracker list | use <name> | check <name> | migrate <from> <to>", out)
        code, out = self.repo.dotdiw("tracker", "migrate", "local", "local", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("local is the source and the target both", out)

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_check_beads(self):
        code, out = self.repo.dotdiw("init", "--prefix", "w", "--tracker", "beads")
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("tracker", "check", "beads")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 beads passed 10 of 10.", out)
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.repo.home, ".dotdiw"))), [self.repo.key()]
        )

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_a_workspace_moves_from_beads_to_local_and_back(self):
        repo = self.repo
        code, out = repo.dotdiw("init", "--prefix", "w", "--tracker", "beads")
        self.assertEqual(code, 0, out)
        work = group1(
            "Created issue: (\\S+)", repo.dotdiw("create", "Release v0.3.0 through the tap")[1]
        )
        other = group1(
            "Created issue: (\\S+)", repo.dotdiw("create", "Fix the login redirect", "-p", "1")[1]
        )
        self.assertEqual(repo.dotdiw("dep", "add", other, work)[0], 0)
        root = group1(
            "Root issue: (\\S+)", repo.dotdiw("mol", "pour", "mol-release-through-tap")[1]
        )
        rows = json.loads(repo.dotdiw("list", "--all", "--json")[1])
        steps = {r["title"]: r["id"] for r in rows if r.get("parent") == root}
        bump = steps["Bump the formula to the new version"]
        self.assertEqual(repo.dotdiw("close", bump, "--reason", "bumped")[0], 0)
        self.assertEqual(repo.dotdiw("update", other, "-s", "in_progress")[0], 0)
        before = json.loads(repo.dotdiw("list", "--all", "--json")[1])

        code, out = repo.dotdiw("tracker", "migrate", "beads", "local")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 Moved 6 items from beads to local.", out)
        self.assertNotIn("mapped", out, "local keeps the ids")
        record = os.path.join(repo.workspace(), "migration-beads-to-local.json")
        self.assertTrue(os.path.exists(record))
        with open(record, encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        self.assertEqual(ids, {i: i for i in ids})
        self.assertEqual(
            json.loads(repo.dotdiw("list", "--all", "--json")[1]), before, "the source is unchanged"
        )

        code, out = repo.dotdiw("tracker", "use", "local")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 This checkout's tracker is local.", out)
        self.assertIn("The work in beads stays there", out)
        self.assertEqual(repo.config("dotdiw.tracker"), "local")
        moved = {r["id"]: r for r in json.loads(repo.dotdiw("list", "--all", "--json")[1])}
        self.assertEqual(set(moved), {r["id"] for r in before})
        self.assertEqual((moved[bump]["status"], moved[bump]["reason"]), ("closed", "bumped"))
        self.assertEqual(
            (moved[other]["status"], moved[other]["priority"], moved[other]["needs"]),
            ("in_progress", 1, [work]),
        )
        self.assertEqual(moved[steps["Install cleanly from the tap"]]["needs"], [bump])
        self.assertEqual(moved[steps["Install cleanly from the tap"]]["parent"], root)
        self.assertEqual(moved[root]["kind"], "molecule")
        self.assertEqual(
            repo.dotdiw("--version")[1].strip().split("\n")[1], "  tracker local 0.6.0"
        )

        code, out = repo.dotdiw("tracker", "migrate", "beads", "local")
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing to move", out)
        self.assertEqual(
            {r["id"] for r in json.loads(repo.dotdiw("list", "--all", "--json")[1])},
            {r["id"] for r in before},
            "a second run changes nothing",
        )

        # And back: the tracker underneath assigns its own ids, so they map.
        code, out = repo.dotdiw("tracker", "migrate", "local", "beads", "--tracker", "local")
        self.assertEqual(code, 0, out)
        self.assertIn("Moved 6 items from local to beads; 6 ids mapped.", out)
        self.assertIn("migration-local-to-beads.json", out)
        with open(
            os.path.join(repo.workspace(), "migration-local-to-beads.json"), encoding="utf-8"
        ) as fh:
            back = json.load(fh)["ids"]
        self.assertEqual(set(back), set(ids))
        # Through the pass-through, so these rows are the tracker's own JSON.
        rows = {
            r["id"]: r
            for r in json.loads(repo.dotdiw("list", "--all", "--json", "--tracker", "beads")[1])
        }
        self.assertEqual(len(rows), 12, "the first six and their copies")
        copy = rows[back[bump]]
        self.assertEqual((copy["status"], copy["close_reason"]), ("closed", "bumped"))
        self.assertEqual(
            [
                d["depends_on_id"]
                for d in rows[back[other]].get("dependencies") or []
                if d.get("type") == "blocks"
            ],
            [back[work]],
        )


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheUpgradePin(unittest.TestCase):
    """A workspace adopted before there was a choice of tracker holds one
    adapter's store and no choice: the first command answers through that
    adapter, writes the choice once, and says so once."""

    def test_the_choice_is_written_once_and_said_once(self):
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.config("dotdiw.tracker"), "beads")
        repo.git("config", "--local", "--unset", "dotdiw.tracker")
        self.assertEqual(repo.config("dotdiw.tracker"), "")
        code, out = repo.dotdiw("create", "Work from before")
        self.assertEqual(code, 0, out)
        self.assertIn("dotdiw.tracker = beads is written in .git/config", out)
        self.assertRegex(out, r"Created issue: w-[a-z0-9]{3,}")
        # A quiet create, as the tracker underneath allows, still names the
        # work in the record where it can and exits 0 where it cannot.
        code, out = repo.dotdiw("create", "Quietly", "-q")
        self.assertEqual((code, out), (0, ""))
        code, out = repo.dotdiw("create", "As JSON", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["title"], "As JSON")
        self.assertEqual(repo.config("dotdiw.tracker"), "beads")
        code, out = repo.dotdiw("list")
        self.assertEqual(code, 0, out)
        self.assertNotIn("is written in .git/config", out)
        self.assertIn("Work from before", out)


FORMULA_A = """formula = "mol-release-through-tap"
description = "Release a tagged version of the tool through the Homebrew tap: bump the formula, check the sha, install cleanly, and announce. Use when shipping a version to users."
examples = ["Release v0.2.1 through the tap", "Ship the next version through brew", "Cut a release and update the tap"]
version = 1
type = "workflow"

[[steps]]
id = "bump"
title = "Bump the formula to the new version"

[[steps]]
id = "install"
title = "Install cleanly from the tap"
needs = ["bump"]

[[steps]]
id = "announce"
title = "Announce the release"
needs = ["install"]
"""
FORMULA_B = (
    FORMULA_A.replace("mol-release-through-tap", "mol-rotate-keys")
    .replace(
        "Release a tagged version of the tool through the Homebrew tap: bump the formula, check the sha, install cleanly, and announce. Use when shipping a version to users.",
        "Rotate the signing keys of the build service: revoke the old key, issue the new one, re-sign the artifacts, and tell the team. Use when a key expires or leaks.",
    )
    .replace(
        '"Release v0.2.1 through the tap", "Ship the next version through brew", "Cut a release and update the tap"',
        '"Rotate the signing keys", "Renew the build service keys", "Key rotation for the build"',
    )
)


class Twin:
    """One dotdiw, its own home, its own copy of the same project, and the
    ids its tracker gave, named by title so that two twins compare."""

    def __init__(self, script, learn_tracker=""):
        self.script = script
        self.learn_tracker = learn_tracker
        self.home = tempfile.mkdtemp(prefix="dotdiw-twin-home-")
        self.repo = tempfile.mkdtemp(prefix="dotdiw-twin-")
        # The twin under test goes through beads, named in its environment;
        # 0.5.0 had one tracker and reads no such variable.
        self.env = dict(os.environ, HOME=self.home, DOTDIW_TRACKER="beads")
        for k in ("BEADS_DIR", "DOTDIW_WITNESS", "DOTDIW_NO_HINTS"):
            self.env.pop(k, None)
        self.ids, self.idmap = {}, {}
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "Test"],
            ["config", "beads.role", "maintainer"],
        ):
            subprocess.run(["git"] + args, cwd=self.repo, capture_output=True)
        with open(
            os.path.join(self.repo, "release-through-tap.formula.toml"), "w", encoding="utf-8"
        ) as fh:
            fh.write(FORMULA_A)
        os.makedirs(os.path.join(self.repo, "ops"))
        with open(
            os.path.join(self.repo, "ops", "rotate-keys.formula.toml"), "w", encoding="utf-8"
        ) as fh:
            fh.write(FORMULA_B)
        with open(os.path.join(self.repo, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "# A project\n\nIt releases through a Homebrew tap and rotates signing keys.\n"
            )
        subprocess.run(["git", "add", "-A"], cwd=self.repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "the project as it stands"], cwd=self.repo, capture_output=True
        )
        self.clone = tempfile.mkdtemp(prefix="dotdiw-twin-clone-")
        subprocess.run(["git", "clone", "-q", self.repo, self.clone], capture_output=True)

    def close(self):
        for d in (self.home, self.repo, self.clone):
            shutil.rmtree(d, ignore_errors=True)

    def run(self, args, in_clone=False):
        args = [a.format(**self.ids) for a in args]
        p = subprocess.run(
            [sys.executable, "-I", self.script] + args,
            cwd=self.clone if in_clone else self.repo,
            env=self.env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout, p.stderr

    def learn(self, text):
        m = re.search(r"Created issue:\s+(\S+)", text)
        if m:
            self.ids.setdefault("work1", m.group(1))
        m = re.search(r"Root issue:\s+(\S+)", text)
        if m:
            self.ids["root"] = m.group(1)
        _, listing, _ = self.run(["list", "--all", "--json"])
        try:
            rows = json.loads(listing)
        except ValueError:
            rows = []
        for r in rows:
            title = re.sub(r"[^a-z0-9]+", "-", str(r.get("title") or "").lower()).strip("-")[:40]
            self.idmap[r["id"]] = "<%s>" % title
        if "root" in self.ids and "step1" not in self.ids:
            kids = [r for r in rows if r.get("parent") == self.ids["root"]]
            needs = {
                r["id"]: [
                    d["depends_on_id"]
                    for d in (r.get("dependencies") or [])
                    if d.get("type") == "blocks"
                ]
                for r in kids
            }
            first = sorted(k["id"] for k in kids if not needs[k["id"]])
            if first:
                self.ids["step1"] = first[0]

    def normalise(self, text):
        """What may differ between two runs that print the same thing: the
        paths, the random ids and keys, the dates, the version line, and
        which of a root's children the tree drew last."""
        for path, token in ((self.home, "<HOME>"), (self.repo, "<REPO>"), (self.clone, "<CLONE>")):
            text = text.replace(path, token).replace(os.path.realpath(path), token)
        text = re.sub(
            r"\bw-[a-z0-9][a-z0-9.\-]*\b", lambda m: self.idmap.get(m.group(0), "<id?>"), text
        )
        text = re.sub(r"(Repository ID|Clone ID): [0-9a-f]+", r"\1: <hex>", text)
        text = re.sub(r"/\.dotdiw/[0-9a-f]{16}", "/.dotdiw/<key>", text)
        text = re.sub(r"^dotdiw \d+\.\d+\.\d+$", "dotdiw <version>", text, flags=re.M)
        text = re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", text)
        # Two lines changed on purpose since 0.5.0: the tracker line of
        # --version names the chosen adapter, and learn says how one is
        # chosen. Both are taken out before the rest is compared.
        text = re.sub(r"^  tracker [a-z]+ (\d)", r"  tracker \1", text, flags=re.M)
        text = text.replace(self.learn_tracker, "")
        return text.replace("\u2514\u2500\u2500", "\u251c\u2500\u2500")


# The seventeen commands a worker types in a day, in the order a day goes,
# and two more beyond them. Where an output lists items by their random ids,
# its lines are compared as a set.
SEVENTEEN = [
    ("init --prefix w",),
    ("init",),
    ("--version",),
    ("learn",),
    ("check",),
    ("formula list",),
    ("formula show mol-release-through-tap",),
    ("create", "Release v0.3.0 through the tap"),
    ("create", "Fix the login redirect", "-d", "The redirect after login loops."),
    ("mol pour mol-release-through-tap",),
    ("list --all", "unordered"),
    ("show {root}", "unordered"),
    ("ready", "unordered"),
    ("close {step1}",),
    ("doctor",),
    ("remember", "Every release: first bump the formula, then install cleanly, then announce"),
    ("dep tree {root}", "unordered"),
]
BEYOND = [
    ("frobnicate --now",),
    ("list", "clone"),
    ("formula new", "Rotate the signing keys", "--from", "{work1}"),
]


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheBytesUnderBeads(unittest.TestCase):
    """Under the beads adapter, the seventeen commands print what 0.5.0
    printed, byte for byte once the random parts are named: the promise that
    nothing a worker sees changes with the tracker behind its door."""

    def test_the_seventeen_commands_print_what_0_5_0_printed(self):
        before = dotdiw_at("v0.5.0")
        if before is None:
            self.skipTest("v0.5.0 is not in this clone's history")
        added = load_module("dotdiw_learn_tracker").LEARN_TRACKER
        twins = [Twin(before), Twin(DOTDIW, learn_tracker=added)]
        for t in twins:
            self.addCleanup(t.close)
        differences = []
        for entry in SEVENTEEN + BEYOND:
            words, flags = entry[0].split(), [e for e in entry[1:]]
            args = words + [f for f in flags if f not in ("unordered", "clone")]
            if entry[0] in ("create", "remember", "formula new"):
                args = words + list(entry[1:])
            got = []
            for t in twins:
                code, out, err = t.run(args, in_clone="clone" in flags)
                t.learn(out + err)
                out, err = t.normalise(out), t.normalise(err)
                if "unordered" in flags:
                    out, err = (
                        "\n".join(sorted(out.split("\n"))),
                        "\n".join(sorted(err.split("\n"))),
                    )
                got.append((code, out, err))
            if got[0] != got[1]:
                differences.append(
                    "%s:\n--- 0.5.0 ---\n%s%s\n--- now ---\n%s%s"
                    % (" ".join(args), got[0][1], got[0][2], got[1][1], got[1][2])
                )
        self.assertEqual(differences, [], "\n\n".join(differences))


if __name__ == "__main__":
    unittest.main(verbosity=2)
