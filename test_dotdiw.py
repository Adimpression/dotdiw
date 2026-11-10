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
import fcntl
import glob
import importlib.machinery
import importlib.util
import io
import json
import os
import py_compile
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
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

        hooks = old.config(HOOKS_KEY)
        code, out = old.dotdiw("check")
        self.assertEqual(code, 1, out)
        self.assertIn(HOOKS_KEY, out)
        self.assertIn("Run dotdiw init once to bring it up to date.", out)
        self.assertEqual(old.config(HOOKS_KEY), hooks, "nothing is put right before init")
        code, out = old.dotdiw("init")
        self.assertEqual(code, 0, out)
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

        code, out = old.dotdiw("init")
        self.assertEqual(code, 0, out)
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

    def test_init_upgrades_an_in_tree_adoption(self):
        """0.2.x let bd commit its files. init adopts under the home; every
        other command says so first and writes nothing.

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

        code, out = old.dotdiw("create", "Before the upgrade")
        self.assertEqual(code, 1, out)
        self.assertIn("the tracker is in the tree", out)
        self.assertIn("Run dotdiw init once to bring it up to date.", out)
        self.assertFalse(old.key(), "nothing is adopted before init")
        code, out = old.dotdiw("init")
        self.assertEqual(code, 0, out)
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

        code, out = old.dotdiw("create", "After the upgrade")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: old-", out, "the prefix is kept")
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

    def test_init_stops_where_the_tree_tracker_cannot_be_adopted(self):
        """With no bd on the machine, the tracker an earlier version kept in the
        tree cannot be adopted under the home: init stops in one line, chooses
        no other tracker and adopts nothing; once bd is back, init adopts."""
        old = Repo()
        self.addCleanup(old.close)
        old.commit("first")
        old.adopt_the_old_way(prefix="old")
        code, out = old.dotdiw("init", env=dict(old.env, PATH="/usr/bin:/bin"))
        self.assertEqual(code, 1, out)
        self.assertIn(
            "init stopped: the tracker kept in the tree could not be adopted under the home", out
        )
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        self.assertEqual(old.config("dotdiw.tracker"), "", "no tracker is chosen")
        code, out = old.dotdiw("create", "Too soon", env=dict(old.env, PATH="/usr/bin:/bin"))
        self.assertEqual(code, 1, out)
        self.assertIn("Run dotdiw init once to bring it up to date.", out)
        code, out = old.dotdiw("init")
        self.assertEqual(code, 0, out)
        code, out = old.dotdiw("create", "After the upgrade")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: old-", out)

    def test_init_upgrades_a_stealth_adoption(self):
        """0.3.0 kept .beads in the tree, excluded. Same upgrade, rm as the command."""
        st = Repo()
        self.addCleanup(st.close)
        st.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        st.commit("first")
        st.adopt_the_old_way(prefix="st", stealth=True)
        self.assertEqual(st.porcelain(), [])

        code, out = st.dotdiw("create", "Before the upgrade")
        self.assertEqual(code, 1, out)
        code, out = st.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertIn("rm -rf .beads .beads.gate.lock", out)
        code, out = st.dotdiw("create", "After the upgrade")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: st-", out)
        self.assertEqual([line for line in st.porcelain() if ".beads" in line], [])
        subprocess.run("rm -rf .beads .beads.gate.lock", shell=True, cwd=st.path)
        code, out = st.dotdiw("create", "Still works")
        self.assertEqual(code, 0, out)

    def test_the_notice_says_who_did_it(self):
        """What 0.1.0 left is 'an earlier version'; a fresh init never says that."""
        old = self.old()
        code, out = old.dotdiw("init")
        self.assertIn("put right what an earlier version of it left here", out)

        fresh = Repo()
        self.addCleanup(fresh.close)
        fresh.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        fresh.commit("first")
        code, out = fresh.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertNotIn("earlier version", out)

    def test_only_init_puts_an_earlier_adoption_right(self):
        """learn and --version run as they are; every other command is refused
        in one line, exits 1 and writes nothing, until init has run."""
        old = self.old()
        hooks = old.config(HOOKS_KEY)
        for args in (("learn",), ("--version",)):
            code, out = old.dotdiw(*args)
            self.assertEqual(code, 0, out)
            self.assertNotIn("earlier version", out)
        for command in (["check"], ["formula", "list"], ["list"], ["create", "Something"]):
            code, out = old.dotdiw(*command)
            self.assertEqual(code, 1, (command, out))
            self.assertEqual(out.count("\n"), 1, (command, out))
            self.assertIn("Run dotdiw init once to bring it up to date.", out)
        self.assertEqual(old.config(HOOKS_KEY), hooks)
        self.assertFalse(old.key())
        code, out = old.dotdiw("init")
        self.assertEqual(code, 0, out)
        code, out = old.dotdiw("list")
        self.assertEqual(code, 0, out)

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
        self.assertNotIn("2.0.0", lines[1], "the tracker underneath, not this tool")

    def test_without_the_tracker_the_message_is_the_install_command(self):
        """Nothing on PATH but the system: one line, the command for the tracker
        this checkout chose, exit 127."""
        self.repo.dotdiw("init", "--prefix", "t")
        code, out = self.repo.dotdiw("list", env=dict(self.repo.env, PATH="/usr/bin:/bin"))
        self.assertEqual(code, 127, out)
        self.assertEqual(out.strip(), "dotdiw: beads is not installed. Run: brew install beads")

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

    def test_an_assignee_reads_back(self):
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        made = self.ask("create-item", title="Theirs")["item"]
        self.assertIsNone(made.get("assignee"))
        out = self.ask("update-item", id=made["id"], assignee="someone")
        self.assertEqual(out["item"]["assignee"], "someone", out)
        self.assertEqual(self.ask("show-item", id=made["id"])["item"]["assignee"], "someone")
        rows = {i["id"]: i for i in self.ask("list-items")["items"]}
        self.assertEqual(rows[made["id"]]["assignee"], "someone")

    def test_steps_that_share_an_id_pour_nothing(self):
        """A pour answers one id per step, so two steps with one id are refused
        before anything is made."""
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        out = self.ask(
            "pour-steps",
            formulaRef="m",
            title="m",
            steps=[
                {"id": "a", "title": "A"},
                {"id": "b", "title": "B"},
                {"id": "a", "title": "A again"},
            ],
        )
        self.assertEqual((out["status"], out["reason"]), ("failed", "duplicate-step"), out)
        self.assertIn("share the id a, so nothing was poured", out["summary"])
        self.assertEqual(self.ask("list-items")["items"], [])

    def test_a_title_that_reads_like_a_flag_is_kept_as_given(self):
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        made = self.ask("create-item", title="--title=Wrong title", description="--type=epic")
        poured = self.ask(
            "pour-steps",
            formulaRef="m",
            title="--priority=0",
            steps=[{"id": "a", "title": "--parent=x"}],
            description="-d",
        )
        for ident, title, description in (
            (made["item"]["id"], "--title=Wrong title", "--type=epic"),
            (poured["rootId"], "--priority=0", "-d"),
            (poured["stepIds"][0], "--parent=x", ""),
        ):
            item = self.ask("show-item", id=ident)["item"]
            self.assertEqual((item["title"], item.get("description") or ""), (title, description))

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

        a = self.ask("create-item", title="First", priority=1)["item"]
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
        self.assertEqual(root["item"]["kind"], "root")
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

    def test_it_says_who_bd_records_and_that_nobody_checked(self):
        self.addCleanup(os.environ.pop, "BEADS_ACTOR", None)
        os.environ.pop("BEADS_ACTOR", None)
        self.assertEqual(self.ask("describe-tracker")["actor"], {"name": "Test", "verified": False})
        os.environ["BEADS_ACTOR"] = "Set By Hand"
        self.assertEqual(self.ask("describe-tracker")["actor"]["name"], "Set By Hand")

    def test_an_assignee_of_me_is_the_name_bd_records(self):
        self.addCleanup(os.environ.pop, "BEADS_ACTOR", None)
        os.environ.pop("BEADS_ACTOR", None)
        self.ask("open-tracker", prefix="w")
        made = self.ask("create-item", title="Mine")["item"]
        out = self.ask("update-item", id=made["id"], assignee="me")
        self.assertEqual(out["item"]["assignee"], "Test", out)

    def test_what_it_says_of_itself(self):
        info = self.ask("describe-tracker")["info"]
        self.assertEqual(info["extras"], ["forward", "metrics-off", "upgrade"])
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


OLD_LOCAL_SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
    priority INTEGER NOT NULL, parent TEXT REFERENCES items(id), description TEXT,
    assignee TEXT, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE TABLE edges (id TEXT NOT NULL, needs TEXT NOT NULL, PRIMARY KEY (id, needs));
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema', '1'), ('prefix', 't');
"""


def a_store_as_2_0_kept_it(path, rows):
    """A local store made before 3.0.0: schema 1, the means kept as the last
    section of each description, under the path given."""
    conn = sqlite3.connect(path)
    with conn:
        conn.executescript(OLD_LOCAL_SCHEMA)
        for ident, kind, description in rows:
            conn.execute(
                "INSERT INTO items (id, title, kind, status, priority, description, created_at, "
                "updated_at) VALUES (?, ?, ?, 'open', 2, ?, '2026-11-09T00:00:00Z', "
                "'2026-11-09T00:00:00Z')",
                (ident, ident, kind, description),
            )
    conn.close()


class TheBeadsMetadata(InterfaceRecords, unittest.TestCase):
    """Under beads, the means to prove a run are the issue's metadata, and a
    workspace an earlier version poured into is brought up to date by the
    upgrade extra, once."""

    ADAPTER = "beads"

    def setUp(self):
        if not have_bd():
            self.skipTest("bd is not installed")
        super().setUp()

    def bd_show(self, ident):
        p = subprocess.run(
            ["bd", "show", ident, "--json"],
            capture_output=True,
            text=True,
            env=dict(os.environ, BEADS_DIR=os.path.join(self.repo.workspace(), ".beads")),
        )
        rows = json.loads(p.stdout)
        return rows[0] if isinstance(rows, list) else rows

    def test_the_means_are_kept_in_the_issues_metadata(self):
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        given = "Ship it.\n\nVerify using:\n- not a means"
        means = ["run:make check", "https://example.invalid/runs/1"]
        poured = self.ask(
            "pour-steps",
            formulaRef="mol-x",
            title="mol-x",
            steps=[{"id": "a", "title": "A"}],
            description=given,
            verifyUsing=means,
        )
        made = self.ask("create-item", title="Moved", description=given, verifyUsing=means)
        for ident in (poured["rootId"], made["item"]["id"]):
            item = self.ask("show-item", id=ident)["item"]
            self.assertEqual((item["description"], item["verifyUsing"]), (given, means))
            raw = self.bd_show(ident)
            self.assertEqual(raw["description"], given)
            self.assertEqual(raw["metadata"]["dotdiw"]["verifyUsing"], means)

    def test_a_workspace_poured_into_before_3_0_is_brought_up_to_date_when_init_asks(self):
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        marker = os.path.join(self.repo.workspace(), "means-in-metadata")
        self.assertTrue(os.path.exists(marker), "a store opened by 3.0.0 starts up to date")
        old = self.ask("create-item", title="Poured by 2.0", description="Ship it.")["item"]["id"]
        p = subprocess.run(
            ["bd", "update", old, "--description", "Ship it.\n\nVerify using:\n- run:make check"],
            capture_output=True,
            text=True,
            env=dict(os.environ, BEADS_DIR=os.path.join(self.repo.workspace(), ".beads")),
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        os.unlink(marker)
        asked = self.m.invoke_extra("upgrade", {"root": self.repo.path, "tracker": "beads"})
        self.assertEqual(len(asked["pending"]), 1)
        self.assertIn("Verify using:", self.bd_show(old)["description"], "nothing moves unasked")
        done = self.m.invoke_extra(
            "upgrade", {"root": self.repo.path, "tracker": "beads", "apply": True}
        )
        self.assertEqual(done["status"], "completed", done)
        self.assertIn("out of 1 description", done["done"][0])
        self.assertTrue(os.path.exists(marker))
        item = self.ask("show-item", id=old)["item"]
        self.assertEqual(
            (item["description"], item["verifyUsing"]), ("Ship it.", ["run:make check"])
        )
        self.assertEqual(self.bd_show(old)["metadata"]["dotdiw"]["verifyUsing"], ["run:make check"])

    def test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is(self):
        """Issues an earlier version left with dotdiw in their metadata as a
        value of their own, null included, read back, and the upgrade passes
        them: each keeps that value and its description as given, those whose
        means stay in their descriptions are named, and every other issue is
        brought up to date."""
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        marker = os.path.join(self.repo.workspace(), "means-in-metadata")
        env = dict(os.environ, BEADS_DIR=os.path.join(self.repo.workspace(), ".beads"))
        theirs = '{"dotdiw": "customer value"}'
        given = "Ship that.\n\nVerify using:\n- run:make check"
        plain = self.ask("create-item", title="Kept by 2.0", description="Ship it.")["item"]["id"]
        owned = self.ask("create-item", title="Theirs", description="x")["item"]["id"]
        moved = self.ask("create-item", title="Poured by 2.0", description="x")["item"]["id"]
        nulled = self.ask("create-item", title="Nulled", description="x")["item"]["id"]
        for args in (
            [plain, "--metadata", theirs],
            [owned, "--description", given, "--metadata", theirs],
            [nulled, "--description", given, "--metadata", '{"dotdiw": null}'],
            [moved, "--description", "Ship them.\n\nVerify using:\n- run:make test"],
        ):
            p = subprocess.run(["bd", "update", *args], capture_output=True, text=True, env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
        os.unlink(marker)
        done = self.m.invoke_extra(
            "upgrade", {"root": self.repo.path, "tracker": "beads", "apply": True}
        )
        self.assertEqual(done["status"], "completed", done)
        self.assertIn("out of 1 description", done["done"][0])
        self.assertIn(
            done["done"][1],
            [
                "%s and %s keep the means in their descriptions, since their metadata holds "
                "dotdiw as a value of their own" % pair
                for pair in ((owned, nulled), (nulled, owned))
            ],
        )
        self.assertTrue(os.path.exists(marker))
        for ident in (plain, owned):
            self.assertEqual(self.bd_show(ident)["metadata"]["dotdiw"], "customer value")
        self.assertEqual(self.bd_show(nulled)["metadata"], {"dotdiw": None})
        for ident in (owned, nulled):
            self.assertEqual(self.bd_show(ident)["description"], given)
        shown = {}
        for ident in (plain, owned, moved, nulled):
            item = self.ask("show-item", id=ident)["item"]
            shown[ident] = (item["description"], item.get("verifyUsing") or [])
        self.assertEqual(
            shown,
            {
                plain: ("Ship it.", []),
                owned: (given, []),
                moved: ("Ship them.", ["run:make test"]),
                nulled: (given, []),
            },
        )
        listed = self.ask("list-items")
        self.assertEqual(listed["status"], "completed", listed)
        self.assertEqual(len(listed["items"]), 4)

    def test_an_upgrade_cut_short_is_taken_up_where_it_stopped(self):
        """bd refuses the second update: the upgrade fails and the workspace is
        left unmarked. The next moves only the issue still to move; the one
        moved keeps its description, which still reads like the means, and its
        means."""
        self.assertEqual(self.ask("open-tracker", prefix="w")["status"], "completed")
        marker = os.path.join(self.repo.workspace(), "means-in-metadata")
        env = dict(os.environ, BEADS_DIR=os.path.join(self.repo.workspace(), ".beads"))
        made = {}
        for description, means in (
            ("Ship it.\n\nVerify using:\n- run:make lint", ["run:make check"]),
            ("Ship that.\n\nVerify using:\n- run:make test", ["run:make smoke"]),
        ):
            ident = self.ask("create-item", title="Poured by 2.0", description="x")["item"]["id"]
            kept = description + "\n\nVerify using:\n" + "\n".join("- " + m for m in means)
            p = subprocess.run(
                ["bd", "update", ident, "--description", kept],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            made[ident] = (description, means)
        os.unlink(marker)
        shim = tempfile.mkdtemp(prefix="dotdiw-bd-shim-")
        self.addCleanup(shutil.rmtree, shim, True)
        with open(os.path.join(shim, "bd"), "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/sh\n"
                'if [ "$1" = update ]; then\n'
                "  echo x >> %s\n"
                "  n=$(wc -l < %s)\n"
                '  if [ $n -gt %d ]; then echo "refused by the test" >&2; exit 1; fi\n'
                "fi\n"
                'exec %s "$@"\n'
                % (
                    shlex.quote(os.path.join(shim, "updates")),
                    shlex.quote(os.path.join(shim, "updates")),
                    1,
                    shlex.quote(shutil.which("bd") or "bd"),
                )
            )
        os.chmod(os.path.join(shim, "bd"), 0o755)
        path = os.environ["PATH"]
        os.environ["PATH"] = shim + os.pathsep + path
        try:
            cut = self.m.invoke_extra(
                "upgrade", {"root": self.repo.path, "tracker": "beads", "apply": True}
            )
        finally:
            os.environ["PATH"] = path
        self.assertEqual(cut["status"], "failed", cut)
        self.assertIn("refused by the test", cut["summary"])
        self.assertFalse(os.path.exists(marker))

        def held(ident):
            item = self.ask("show-item", id=ident)["item"]
            return item["description"], item.get("verifyUsing") or []

        self.assertEqual(len([i for i in made if held(i) == made[i]]), 1, "one moved")
        done = self.m.invoke_extra(
            "upgrade", {"root": self.repo.path, "tracker": "beads", "apply": True}
        )
        self.assertEqual(done["status"], "completed", done)
        self.assertIn("out of 1 description", done["done"][0])
        self.assertTrue(os.path.exists(marker))
        for ident, want in made.items():
            self.assertEqual(held(ident), want)


class TheLocalAdapter(InterfaceRecords, unittest.TestCase):
    """The local adapter answers the interface in records from one sqlite
    file under the home, runs nothing, and closes a poured root itself when
    its last step closes."""

    ADAPTER = "local"

    def test_it_names_nobody(self):
        self.assertIsNone(self.ask("describe-tracker").get("actor"))

    def test_what_it_says_of_itself(self):
        info = self.ask("describe-tracker")["info"]
        self.assertEqual(info["extras"], ["upgrade"])
        opened = self.ask("open-tracker", prefix="t")
        self.assertTrue(opened["path"].endswith("dotdiw.sqlite"))
        self.assertEqual(sorted(os.listdir(self.repo.workspace())), ["dotdiw.sqlite"])
        out = self.m.invoke_extra(
            "forward", {"root": self.repo.path, "tracker": "local", "arguments": ["list"]}
        )
        self.assertEqual((out["status"], out["reason"]), ("failed", "unsupported"))

    def test_a_store_made_before_1_0_reads_its_molecule_roots_as_root(self):
        self.ask("open-tracker", prefix="t")
        poured = self.ask(
            "pour-steps", formulaRef="mol-x", title="mol-x", steps=[{"id": "a", "title": "A"}]
        )
        root, (step,) = poured["rootId"], poured["stepIds"]
        conn = sqlite3.connect(os.path.join(self.repo.workspace(), "dotdiw.sqlite"))
        with conn:
            conn.execute("UPDATE items SET kind = 'molecule' WHERE id = ?", (root,))
            conn.execute("UPDATE items SET kind = 'epic' WHERE id = ?", (step,))
        conn.close()
        self.assertEqual(self.ask("show-item", id=root)["item"]["kind"], "root")
        self.assertEqual(self.ask("show-item", id=step)["item"]["kind"], "task")
        self.assertEqual(
            self.ask("close-item", id=step, closeReason="done")["closedIds"],
            [step, root],
            "a root kept as molecule still closes with its last step",
        )

    def test_the_means_are_kept_in_a_column_of_their_own(self):
        """A description that reads like the means is a description, kept and
        returned as given, and the means are a column's, not a section's."""
        self.ask("open-tracker", prefix="t")
        given = "Ship it.\n\nVerify using:\n- not a means"
        means = ["run:make check", "https://example.invalid/runs/1"]
        poured = self.ask(
            "pour-steps",
            formulaRef="mol-x",
            title="mol-x",
            steps=[{"id": "a", "title": "A"}],
            description=given,
            verifyUsing=means,
        )
        made = self.ask("create-item", title="Moved", description=given, verifyUsing=means)
        for ident in (poured["rootId"], made["item"]["id"]):
            item = self.ask("show-item", id=ident)["item"]
            self.assertEqual((item["description"], item["verifyUsing"]), (given, means))
            conn = sqlite3.connect(os.path.join(self.repo.workspace(), "dotdiw.sqlite"))
            row = conn.execute(
                "SELECT description, verify_using FROM items WHERE id = ?", (ident,)
            ).fetchone()
            conn.close()
            self.assertEqual(row, (given, json.dumps(means)))

    def test_a_store_made_before_3_0_is_brought_up_to_date_when_init_asks(self):
        a_store_as_2_0_kept_it(
            os.path.join(self.repo.workspace(), "dotdiw.sqlite"),
            [
                ("t-a", "root", "Ship it.\n\nVerify using:\n- run:make check"),
                ("t-b", "root", "Verify using:\n- run:make check"),
                ("t-c", "task", "Looks like one.\n\nVerify using:\n- x\n\nVerify using:"),
                ("t-d", "task", "Plain."),
                ("t-e", "task", None),
            ],
        )
        asked = self.m.invoke_extra("upgrade", {"root": self.repo.path, "tracker": "local"})
        self.assertEqual(asked["status"], "completed")
        self.assertEqual(len(asked["pending"]), 1)
        self.assertEqual(asked["done"], [])
        conn = sqlite3.connect(os.path.join(self.repo.workspace(), "dotdiw.sqlite"))
        columns = [r[1] for r in conn.execute("PRAGMA table_info(items)")]
        conn.close()
        self.assertNotIn("verify_using", columns, "nothing is changed without apply")
        done = self.m.invoke_extra(
            "upgrade", {"root": self.repo.path, "tracker": "local", "apply": True}
        )
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["pending"], [])
        self.assertIn("out of 3 descriptions", done["done"][0])
        expect = {
            "t-a": ("Ship it.", ["run:make check"]),
            "t-b": (None, ["run:make check"]),
            "t-c": ("Looks like one.\n\nVerify using:\n- x", None),
            "t-d": ("Plain.", None),
            "t-e": (None, None),
        }
        for ident, (description, means) in expect.items():
            item = self.ask("show-item", id=ident)["item"]
            self.assertEqual(
                (item.get("description"), item.get("verifyUsing")), (description, means)
            )
        again = self.m.invoke_extra(
            "upgrade", {"root": self.repo.path, "tracker": "local", "apply": True}
        )
        self.assertEqual((again["pending"], again["done"]), ([], []), "once")

    def test_the_notice_the_past_titles_and_from_read_every_item(self):
        """Past the 300th item, a procedure built by hand is noticed, its steps
        are read for --from, and its title counts among the past ones. It is
        done, and the store lists open items first, so 305 open ones put it
        past the 300th whatever their ids."""
        self.ask("open-tracker", prefix="t")
        parent = self.ask("create-item", title="Rotate the signing keys by hand")["item"]["id"]
        kids = [
            self.ask("create-item", title="Step %d" % n, parent=parent)["item"]["id"]
            for n in range(3)
        ]
        self.ask("add-need", id=kids[1], needs=kids[0])
        self.ask("add-need", id=kids[2], needs=kids[1])
        for ident in kids + [parent]:
            self.assertEqual(self.ask("close-item", id=ident)["status"], "completed")
        for n in range(305):
            self.ask("create-item", title="Item %d" % n)
        found = self.m.invoke(
            "operation.notice-handmade-procedures", {"root": self.repo.path, "tracker": "local"}
        )
        self.assertIn(parent, [u["workRef"] for u in found["undeclared"]])
        self.assertIsNotNone(self.m.steps_from(self.repo.path, "local", parent))
        self.assertIn(
            "Rotate the signing keys by hand", self.m.past_titles(self.repo.path, "local")
        )

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

    def test_init_brings_a_store_an_earlier_version_kept_up_to_date(self):
        """A local store kept before 3.0.0 refuses every command but init, and
        init moves its means into their column, once."""
        self.adopted()
        store = os.path.join(self.repo.workspace(), "dotdiw.sqlite")
        os.unlink(store)
        a_store_as_2_0_kept_it(store, [("t-a", "root", "Ship it.\n\nVerify using:\n- run:x")])
        code, out = self.dotdiw("list")
        self.assertEqual(code, 1, out)
        self.assertIn("its store keeps the means to prove a run inside descriptions", out)
        self.assertIn("Run dotdiw init once to bring it up to date.", out)
        code, out = self.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertIn("put right what an earlier version of it left here", out)
        self.assertIn("kept in a column of their own, out of 1 description", out)
        code, out = self.dotdiw("list")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertNotIn("earlier version", out)

    def test_create_pour_and_init_read_their_own_flags(self):
        """create, formula pour and init take dotdiw's own flags, and refuse
        any other in one line, naming it, before anything is done, as they
        refuse a flag of their own given no value; --description=<text> gives
        a value that starts with a dash."""
        self.adopted()
        for args, said in (
            (("create", "Named", "--label", "x"), "--label is not one of its flags"),
            (("create", "Named", "-d"), "-d needs a value"),
            (("create", "Named", "-d", "--not-a-flag"), "-d needs a value"),
            (("create", "Named", "--description", "--json"), "--description needs a value"),
            (("init", "--prefix", "--json"), "--prefix needs a value"),
            (("create", "Named", "--tracker="), "--tracker needs a value"),
            (("create", "Named", "--tracker"), "--tracker needs a value"),
            (("create", "Named", "--tracker", "--json"), "--tracker needs a value"),
            (("create", "Two", "words"), "words is one word too many"),
            (("create",), "a title is needed"),
            (("create", "Named", "-p", "high"), "the priority is 0 to 4"),
            (("formula", "pour", "mol-release-through-tap", "--var", "a=b"), "--var is not one"),
            (("init", "--force"), "--force is not one of its flags"),
        ):
            with self.subTest(args=args):
                code, out = self.dotdiw(*args)
                self.assertEqual(code, 2, out)
                self.assertIn(said, out)
                self.assertEqual(len(out.strip().splitlines()), 1, out)
        code, out = self.dotdiw("list", "--json")
        self.assertNotIn("Named", out)
        code, out = self.dotdiw(
            "create", "Named", "-p", "P1", "--description=--not-a-flag", "--json"
        )
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        self.assertEqual((made["priority"], made["description"]), (1, "--not-a-flag"))
        code, out = self.dotdiw("create", "Release v0.3.0 through the tap")
        self.assertIn("Formulas that may apply", out)
        code, out = self.dotdiw("create", "Release v0.4.0 through the tap", "-q")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue:", out)
        self.assertNotIn("Formulas that may apply", out)

    def test_show_says_who_an_item_is_assigned_to(self):
        self.adopted()
        ident = self.made("Theirs")
        code, out = self.dotdiw("show", ident)
        self.assertEqual(code, 0, out)
        self.assertNotIn("Assignee", out)
        code, out = self.dotdiw("update", ident, "-a", "me")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("show", ident)
        self.assertEqual(code, 0, out)
        self.assertIn("Assignee: me\n", out)
        code, out = self.dotdiw("show", ident, "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["assignee"], "me")
        code, out = self.dotdiw("list", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([i["assignee"] for i in json.loads(out)], ["me"])

    def test_init_names_nobody_here(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Acting as", out)

    def test_learn_claims_only_the_trackers_own_name(self):
        """A worker types git to commit a formula, as formula new tells them, so
        what dotdiw spares them is the tracker's name."""
        code, taught = self.dotdiw("learn")
        self.assertEqual(code, 0, taught)
        self.assertIn("so you never type the\ntracker's own name.", taught)
        self.assertNotIn("anything else", taught)

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

    def test_the_notice_names_a_parent_built_by_hand_and_never_a_root(self):
        """A parent of kind task with ordered children is a procedure carried out
        by hand; the root a pour made is of kind root, and never named."""
        self.adopted()
        parent = self.made("Handle the webhook backlog")
        steps = [
            self.made(title, "--parent", parent)
            for title in ("Drain the queue", "Replay the failures", "Reconcile the ledger")
        ]
        for i in range(1, len(steps)):
            self.assertEqual(self.dotdiw("dep", "add", steps[i], steps[i - 1])[0], 0)
        # An id no formula's words reach, so that only the kind keeps the root
        # out of the notice.
        self.repo.write(
            "ops/rotate.formula.toml",
            FORMULA_A.replace('formula = "mol-release-through-tap"', 'formula = "mol-q7x"'),
        )
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "a formula with an id of its own")
        code, out = self.dotdiw("formula", "pour", "mol-q7x")
        self.assertEqual(code, 0, out)
        root = group1(r"Root issue: (\S+)", out)
        code, out = self.dotdiw("check")
        self.assertIn("--from %s" % parent, out)
        self.assertNotIn("--from %s" % root, out)

    def test_the_notice_quotes_the_title_it_prints(self):
        """A title is the tracker's text: in the line printed to be copied, a
        shell reads it as one word and nothing in it as a command."""
        self.adopted()
        title = 'Handle the "webhook" backlog $(touch PWNED)'
        parent = self.made(title)
        steps = [
            self.made(t, "--parent", parent)
            for t in ("Drain the queue", "Replay the failures", "Reconcile the ledger")
        ]
        for i in range(1, len(steps)):
            self.assertEqual(self.dotdiw("dep", "add", steps[i], steps[i - 1])[0], 0)
        code, out = self.dotdiw("check")
        line = next(x for x in out.splitlines() if "--from %s" % parent in x)
        self.assertEqual(shlex.split(line), ["dotdiw", "formula", "new", title, "--from", parent])

    def test_the_nudge_quotes_the_text_it_prints(self):
        module = load_module("dotdiw_nudge")
        text = 'First bump "the formula", then install $(touch PWNED), then announce'
        said = module.invoke("operation.nudge-towards-a-formula", {"root": HERE, "text": text})
        self.assertTrue(said["nudged"])
        words = shlex.split(said["command"])
        self.assertEqual(words[:3], ["dotdiw", "formula", "new"])
        self.assertEqual(len(words), 4)
        self.assertTrue(text.startswith(words[3]), words)

    def test_formula_new_seeds_named_work_and_never_a_root(self):
        """A new formula's examples start from the titles of work named here
        before; a root a pour made is titled with a formula's id, and is never
        one of them."""
        self.adopted()
        self.made("Release v0.3 through the tap")
        code, out = self.dotdiw("formula", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, out)
        os.mkdir(os.path.join(self.repo.path, "seeded"))
        code, out = self.dotdiw("formula", "new", "Release through tap", "--at", "seeded")
        self.assertEqual(code, 0, out)
        with open(
            os.path.join(self.repo.path, group1(r"Wrote (\S+)", out)), encoding="utf-8"
        ) as fh:
            written = fh.read()
        self.assertIn('  "Release v0.3 through the tap",\n', written)
        self.assertNotIn('  "mol-release-through-tap",\n', written)

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
        self.assertEqual(out.strip().split("\n")[1], "  tracker local 2.0.0", out)

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
TRACKER = {"info": {"name": "boom", "version": "0", "interface": 3, "checkTarget": "scratch"},
           "operations": {"operation.open-tracker": open_tracker, "operation.describe-tracker": describe,
                          "operation.create-item": create, "operation.add-need": ok,
                          "operation.pour-steps": ok, "operation.close-item": ok, "operation.show-item": ok,
                          "operation.list-items": none, "operation.update-item": ok, "operation.ready-items": none},
           "extras": {}, "store": store}
"""


# A small adapter that passes the scenario: the operations as impl_<name>, so
# that a test can pour them into the file `tracker new` writes.
ACME_BODIES = """import json
import os


def _ok(**kw):
    return dict({"status": "completed", "summary": "ok", "exitCode": 0}, **kw)


def _no(reason):
    return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 1}


def acme_store(root):
    return os.path.join(dotdiw_workspace(root), "acme.json")


def _load(root):
    with open(acme_store(root), encoding="utf-8") as fh:
        return json.load(fh)


def _save(root, data):
    with open(acme_store(root), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make(data, title, **given):
    data["count"] += 1
    ident = given.pop("id", None) or "%s-%d" % (data["prefix"], data["count"])
    item = {"id": ident, "title": title, "kind": "task", "status": "open", "priority": 2,
            "parent": None, "reason": None, "needs": []}
    item.update({k: v for k, v in given.items() if v is not None})
    data["items"][ident] = item
    return item


def _reaches(data, start, goal):
    seen, todo = set(), [start]
    while todo:
        at = todo.pop()
        if at == goal:
            return True
        if at not in seen:
            seen.add(at)
            todo.extend(data["items"][at]["needs"])
    return False


def _open(data, ids):
    return [i for i in ids if data["items"][i]["status"] != "closed"]


def impl_open_tracker(request):
    path = acme_store(request["root"])
    made = not os.path.exists(path)
    if made:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _save(request["root"], {"prefix": request.get("prefix") or "acme", "count": 0, "items": {}})
    return _ok(created=made, path=path)


def impl_describe_tracker(request):
    path = acme_store(request["root"]) if request.get("root") else None
    info = {"name": "acme", "version": "1.0.0", "origin": "loaded"}
    return _ok(info=info, path=path if path and os.path.exists(path) else None)


def impl_create_item(request):
    data = _load(request["root"])
    parent = request.get("parent")
    if parent and parent not in data["items"]:
        return _no("parent-not-found")
    item = _make(data, request["title"], id=request.get("id"), priority=request.get("priority"),
                 parent=parent, description=request.get("description"),
                 verifyUsing=list(request.get("verifyUsing") or []) or None)
    _save(request["root"], data)
    return _ok(item=item)


def impl_add_need(request):
    data = _load(request["root"])
    ident, needs = request["id"], request["needs"]
    if ident not in data["items"] or needs not in data["items"]:
        return _no("item-not-found")
    if _reaches(data, needs, ident):
        return _no("cycle")
    if needs not in data["items"][ident]["needs"]:
        data["items"][ident]["needs"].append(needs)
        _save(request["root"], data)
    return _ok(edge={"id": ident, "needs": needs})


def impl_show_item(request):
    data = _load(request["root"])
    item = data["items"].get(request["id"])
    if item is None:
        return _no("item-not-found")
    kids = [i for i in data["items"].values() if i["parent"] == request["id"]]
    return _ok(item=item, children=kids)


def impl_list_items(request):
    data = _load(request["root"])
    items = list(data["items"].values())
    if request.get("scope") != "all":
        items = [i for i in items if i["status"] != "closed"]
    if request.get("parent"):
        items = [i for i in items if i["parent"] == request["parent"]]
    return _ok(items=items[: request.get("limit") or len(items)])


def impl_ready_items(request):
    data = _load(request["root"])
    return _ok(items=[i for i in data["items"].values()
                      if i["status"] != "closed" and not _open(data, i["needs"])])


def impl_close_item(request):
    data = _load(request["root"])
    item = data["items"].get(request["id"])
    if item is None:
        return _no("item-not-found")
    kids = [i["id"] for i in data["items"].values() if i["parent"] == item["id"]]
    blockers = _open(data, item["needs"] + kids)
    if blockers:
        return {"status": "blocked", "summary": "blocked", "blockedBy": blockers, "exitCode": 1}
    item.update(status="closed", reason=request.get("closeReason"))
    _save(request["root"], data)
    return _ok(item=item, closedIds=[item["id"]])


def impl_update_item(request):
    if request.get("status") == "closed":
        return _no("close-through-update")
    if request.get("status") not in (None, "open", "in_progress", "blocked"):
        return _no("bad-status")
    data = _load(request["root"])
    item = data["items"].get(request["id"])
    if item is None:
        return _no("item-not-found")
    for key in ("title", "status", "priority", "parent"):
        if request.get(key) is not None:
            item[key] = request[key]
    _save(request["root"], data)
    return _ok(item=item)


def impl_pour_steps(request):
    steps = request.get("steps") or []
    if not steps:
        return _no("no-steps")
    known = {s["id"] for s in steps}
    needs = {s["id"]: list(s.get("needs") or []) for s in steps}
    if any(n not in known for ns in needs.values() for n in ns):
        return _no("step-not-found")
    left = set(known)
    while left:
        free = {s for s in left if not set(needs[s]) & left}
        if not free:
            return _no("cycle")
        left -= free
    data = _load(request["root"])
    root = _make(data, request["title"], kind="root", description=request.get("description"),
                 verifyUsing=request.get("verifyUsing"))
    made = {s["id"]: _make(data, s["title"], parent=root["id"]) for s in steps}
    for s in steps:
        made[s["id"]]["needs"] = [made[n]["id"] for n in needs[s["id"]]]
    _save(request["root"], data)
    return _ok(rootId=root["id"], stepIds=[made[s["id"]]["id"] for s in steps])


"""
ACME = (
    ACME_BODIES
    + """TRACKER = {
    "info": {"name": "acme", "version": "1.0.0", "interface": 3, "checkTarget": "scratch", "extras": []},
    "operations": {
        "operation.%s" % name.replace("_", "-"): globals()["impl_" + name]
        for name in ("open_tracker", "describe_tracker", "create_item", "add_need", "pour_steps",
                     "close_item", "show_item", "list_items", "update_item", "ready_items")
    },
    "extras": {},
    "store": acme_store,
}
"""
)


class TheWordFormulaPour(unittest.TestCase):
    """dotdiw formula pour is what dotdiw teaches for running a formula, and mol
    pour the older spelling of it: one operation, one answer, and nothing new
    printed for whoever still types the old one."""

    IDS = r"\bw-[a-z0-9.\-]+\b"

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.env = dict(self.repo.env, PATH="/usr/bin:/bin")
        self.repo.write("release-through-tap.formula.toml", FORMULA_A)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the project as it stands")

    def dotdiw(self, *args):
        return self.repo.dotdiw(*args, env=self.env)

    def adopted(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)

    def test_it_pours_the_formula(self):
        self.adopted()
        code, out = self.dotdiw("formula", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol: created 4 issues", out)
        root = group1("Root issue: (\\S+)", out)
        code, out = self.dotdiw("list", "--all", "--json")
        self.assertEqual(code, 0, out)
        steps = [r for r in json.loads(out) if r.get("parent") == root]
        self.assertEqual(len(steps), 3)

    def test_both_spellings_print_the_same(self):
        self.adopted()
        code, new = self.dotdiw("formula", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, new)
        code, older = self.dotdiw("mol", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, older)
        self.assertEqual(re.sub(self.IDS, "<id>", new), re.sub(self.IDS, "<id>", older))

    def test_json_after_the_formula_prints_the_record(self):
        self.adopted()
        code, out = self.dotdiw("formula", "pour", "mol-release-through-tap", "--json")
        self.assertEqual(code, 0, out)
        poured = json.loads(out)
        self.assertTrue(poured["rootId"] and poured["stepIds"], poured)

    def test_it_takes_the_file_name_and_the_path_too(self):
        self.adopted()
        for ident in (
            "release-through-tap",
            "release-through-tap.formula.toml",
            "./release-through-tap.formula.toml",
        ):
            with self.subTest(ident=ident):
                code, out = self.dotdiw("formula", "pour", ident)
                self.assertEqual(code, 0, out)
                self.assertIn("Poured mol: created 4 issues", out)

    def test_with_no_formula_it_says_how_it_is_used(self):
        self.adopted()
        for args in (("formula", "pour"), ("formula", "pour", "--json")):
            with self.subTest(args=args):
                code, out = self.dotdiw(*args)
                self.assertEqual(code, 2, out)
                self.assertEqual(out.strip(), "dotdiw formula pour <formula>")
        code, out = self.dotdiw("list", "--all", "--json")
        self.assertEqual(json.loads(out), [])

    def test_a_formula_nobody_holds_is_refused_the_same(self):
        self.adopted()
        code, out = self.dotdiw("formula", "pour", "mol-nothing")
        self.assertNotEqual(code, 0, out)
        self.assertEqual((code, out), self.dotdiw("mol", "pour", "mol-nothing"))
        code, out = self.dotdiw("list", "--all", "--json")
        self.assertEqual(json.loads(out), [])

    def test_a_repository_not_adopted_is_told_so(self):
        code, out = self.dotdiw("formula", "pour", "mol-release-through-tap")
        self.assertEqual(code, 1, out)
        self.assertIn("this repository is not adopted", out)

    def test_what_dotdiw_prints_teaches_it(self):
        self.adopted()
        code, created = self.dotdiw("create", "Release v0.3.0 through the tap")
        self.assertEqual(code, 0, created)
        self.assertIn("Run it: dotdiw formula pour mol-release-through-tap", created)
        code, listed = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, listed)
        self.assertIn("Run one: dotdiw formula pour <id>", listed)
        code, taught = self.dotdiw("learn")
        self.assertEqual(code, 0, taught)
        self.assertIn("Run a formula:  dotdiw formula pour <formula-id>", taught)
        for said in (created, listed, taught):
            self.assertNotIn("mol pour", said)

    def test_the_declaration_stays_as_0_7_0_wrote_it(self):
        """An adopted checkout rewrites its copy on its next create, as a change
        in its own tree, so a new word there reaches every repository at once.
        2.0.0 changes one sentence on purpose: an uncommitted formula is found
        on its holder's file system, where 0.7.0 said nothing finds it."""
        before = dotdiw_at("v0.7.0")
        if before is None:
            self.skipTest("v0.7.0 is not in this clone's history")
        then = load_module("dotdiw_declared_at_v0_7_0", before).CONVENTIONS
        unfound = (
            "hold: it does\nnot appear in `formula list`, nothing matches it against a "
            "title, and `check`\n"
        )
        found = (
            "hold: it is\nfound on your file system alone, nobody else's `create` reaches "
            "it, and `check`\n"
        )
        self.assertIn(unfound, then)
        self.assertEqual(
            load_module("dotdiw_declared_now").CONVENTIONS, then.replace(unfound, found)
        )

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_under_beads_both_spellings_print_the_same(self):
        repo = Repo()
        self.addCleanup(repo.close)
        repo.write("release-through-tap.formula.toml", FORMULA_A)
        repo.git("add", "-A")
        repo.git("commit", "-qm", "the project as it stands")
        code, out = repo.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, new = repo.dotdiw("formula", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, new)
        self.assertIn("Root issue: ", new)
        code, older = repo.dotdiw("mol", "pour", "mol-release-through-tap")
        self.assertEqual(code, 0, older)
        self.assertEqual(re.sub(self.IDS, "<id>", new), re.sub(self.IDS, "<id>", older))
        code, out = repo.dotdiw("formula", "pour", "mol-release-through-tap", "--json")
        self.assertEqual(code, 0, out)
        json.loads(out)


PROVED = """formula = "mol-ship-the-package"
description = "Ship the package to the registry: build it, publish it, and install the published version to prove it went out. Use when releasing a new version."
examples = [
  "Ship the package",
  "Publish the new version to the registry",
  "Release the package",
]
verify-using = [
  "run:make smoke-test",
  "git+https://example.invalid/acme/shop.git#RELEASING.md",
  "https://status.example.invalid/registry",
]
version = 1
type = "workflow"

[[steps]]
id = "build"
title = "Build the package"

[[steps]]
id = "publish"
title = "Publish it"
needs = ["build"]
"""


SIX_STEPS = """formula = "mol-six-steps"
description = "Six steps one after another, declared last first, poured to see that their ids come back in the order the formula gives them and not the order they were made. Use when checking a pour."
examples = ["Pour six steps", "Six steps in order", "Check the order of a pour"]
version = 1
type = "workflow"

[[steps]]
id = "six"
title = "Step six"
needs = ["five"]

[[steps]]
id = "five"
title = "Step five"
needs = ["four"]

[[steps]]
id = "four"
title = "Step four"
needs = ["three"]

[[steps]]
id = "three"
title = "Step three"
needs = ["two"]

[[steps]]
id = "two"
title = "Step two"
needs = ["one"]

[[steps]]
id = "one"
title = "Step one"
"""


class TheMeansToProveARun(unittest.TestCase):
    """A formula's verify-using: read with it and never matched, carried in its
    records, held to being well formed by check, handed to the tracker with the
    root and shown after a pour, and never run, opened or fetched by dotdiw."""

    MEANS = [
        "run:make smoke-test",
        "git+https://example.invalid/acme/shop.git#RELEASING.md",
        "https://status.example.invalid/registry",
    ]

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.env = dict(self.repo.env, PATH="/usr/bin:/bin")
        self.repo.write("ship-the-package.formula.toml", PROVED)
        self.repo.write("RELEASING.md", "# Releasing\n\nHow a release is proved.\n")
        self.repo.git("remote", "add", "origin", "git@example.invalid:acme/shop.git")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the project as it stands")
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)

    def dotdiw(self, *args):
        return self.repo.dotdiw(*args, env=self.env)

    def formula(self, means):
        """The formula again, naming these means, committed."""
        lines = PROVED.split("\n")
        start = lines.index("verify-using = [")
        end = lines.index("]", start)
        lines[start : end + 1] = ["verify-using = %s" % means]
        self.repo.write("ship-the-package.formula.toml", "\n".join(lines))
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the means changed")

    def test_a_pour_shows_the_means_and_the_root_keeps_them(self):
        code, out = self.dotdiw("formula", "pour", "mol-ship-the-package")
        self.assertEqual(code, 0, out)
        self.assertIn("Verify using:\n" + "".join("  %s\n" % m for m in self.MEANS), out)
        root = group1("Root issue: (\\S+)", out)
        code, out = self.dotdiw("show", root, "--json")
        self.assertEqual(code, 0, out)
        shown = json.loads(out)
        self.assertEqual(shown["kind"], "root")
        self.assertEqual(shown["verifyUsing"], self.MEANS)
        self.assertTrue(shown["description"].startswith("Ship the package to the registry"))
        code, out = self.dotdiw("formula", "pour", "mol-ship-the-package", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["verifyUsing"], self.MEANS)

    def test_formula_list_carries_them_in_json_and_keeps_its_line(self):
        code, out = self.dotdiw("formula", "list", "--json")
        self.assertEqual(code, 0, out)
        held = [f for f in json.loads(out) if f["formula"] == "mol-ship-the-package"]
        self.assertEqual(held[0]["verifyUsing"], self.MEANS)
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertNotIn("run:make smoke-test", out)

    def test_the_means_are_never_run_or_matched(self):
        self.formula('["run:touch ran", "run:zanzibar quokka", "https://example.invalid/ran"]')
        for args in (
            ("create", "Zanzibar quokka"),
            ("create", "Ship the package"),
            ("formula", "pour", "mol-ship-the-package"),
            ("check",),
            ("formula", "show", "mol-ship-the-package"),
            ("formula", "list"),
        ):
            code, out = self.dotdiw(*args)
            if args == ("create", "Zanzibar quokka"):
                self.assertNotIn("ship-the-package", out, "verify-using is never matched")
        self.assertFalse(os.path.exists(os.path.join(self.repo.path, "ran")), "nothing ran")

    def test_check_names_a_value_it_cannot_read(self):
        self.formula(
            '["make test", "run:", "one\\ntwo", 3, "git+https://example.invalid/acme/shop.git"]'
        )
        code, out = self.dotdiw("check")
        self.assertEqual(code, 1, out)
        for said in (
            'verify-using value "make test" is in none of the forms',
            'verify-using value "run:" names no command',
            'verify-using value "one" is longer than one line',
            "verify-using holds a value that is not text",
            'verify-using value "git+https://example.invalid/acme/shop.git" names a repository'
            " and no file",
        ):
            self.assertIn(said, out)

    def test_check_holds_a_file_of_this_repository_to_being_tracked(self):
        self.formula(
            '["git+https://example.invalid/acme/shop.git#GONE.md",'
            ' "git+ssh://git@example.invalid/acme/shop.git#RELEASING.md",'
            ' "git+https://example.invalid/other/thing.git#elsewhere.md"]'
        )
        code, out = self.dotdiw("check")
        self.assertEqual(code, 1, out)
        self.assertIn("verify-using names GONE.md, which git does not track here", out)
        self.assertNotIn("RELEASING.md, which", out, "a tracked file is held")
        self.assertNotIn("elsewhere.md", out, "another repository's file is shown as it is")
        self.repo.write("GONE.md", "Here after all.\n")
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the file")
        code, out = self.dotdiw("check")
        self.assertNotIn("GONE.md", out)

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_under_beads_the_means_follow_its_own_output(self):
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        repo.write("ship-the-package.formula.toml", PROVED)
        repo.git("add", "-A")
        repo.git("commit", "-qm", "the project as it stands")
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("formula", "pour", "mol-ship-the-package")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol", out)
        self.assertTrue(
            out.rstrip("\n").endswith(
                "\n".join(["Verify using:"] + ["  %s" % m for m in self.MEANS])
            ),
            out,
        )
        root = group1("Root issue: (\\S+)", out)
        code, out = repo.dotdiw("show", root, "--json")
        self.assertEqual(code, 0, out)
        shown = json.loads(out)
        shown = shown[0] if isinstance(shown, list) else shown
        self.assertNotIn("Verify using:", shown.get("description") or "")
        self.assertEqual(shown["metadata"]["dotdiw"]["verifyUsing"], self.MEANS)
        # Under --json the answer is bd's own, and the means stay out of it;
        # the root it names keeps them all the same.
        code, out = repo.dotdiw("formula", "pour", "mol-ship-the-package", "--json")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Verify using:", out)
        root = json.loads(out)["rootId"]
        code, out = repo.dotdiw("show", root, "--json")
        self.assertEqual(code, 0, out)
        shown = json.loads(out)
        shown = shown[0] if isinstance(shown, list) else shown
        self.assertEqual(shown["metadata"]["dotdiw"]["verifyUsing"], self.MEANS)
        self.assertNotIn("Verify using:", shown.get("description") or "")

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_under_beads_a_pour_answers_its_steps_in_the_formulas_order(self):
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        repo.write("six.formula.toml", SIX_STEPS)
        repo.git("add", "-A")
        repo.git("commit", "-qm", "the project as it stands")
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("formula", "pour", "mol-six-steps", "--json")
        self.assertEqual(code, 0, out)
        steps = json.loads(out)["stepIds"]
        titles = []
        for ident in steps:
            code, shown = repo.dotdiw("show", ident, "--json")
            self.assertEqual(code, 0, shown)
            rows = json.loads(shown)
            titles.append((rows[0] if isinstance(rows, list) else rows)["title"])
        self.assertEqual(
            titles, ["Step six", "Step five", "Step four", "Step three", "Step two", "Step one"]
        )

    def test_under_beads_a_pour_that_fails_after_its_root_names_it(self):
        """The pour made its root and a step, and bd refused the next: the pour
        is a failure, and the line said names the root and what it made; with
        --json, the record of what it made is printed, and the line said."""
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        repo.write("ship-the-package.formula.toml", PROVED)
        repo.git("add", "-A")
        repo.git("commit", "-qm", "the project as it stands")
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        shim = tempfile.mkdtemp(prefix="dotdiw-bd-shim-")
        self.addCleanup(shutil.rmtree, shim, True)
        with open(os.path.join(shim, "bd"), "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/sh\n"
                'if [ "$1" = create ]; then for a in "$@"; do\n'
                '  case "$a" in --deps=*) echo "refused by the test" >&2; exit 1;; esac\n'
                "done; fi\n"
                'exec %s "$@"\n' % shlex.quote(shutil.which("bd") or "bd")
            )
        os.chmod(os.path.join(shim, "bd"), 0o755)
        env = dict(repo.env, PATH=shim + os.pathsep + repo.env["PATH"])
        code, out = repo.dotdiw("formula", "pour", "mol-ship-the-package", env=env)
        self.assertEqual(code, 1, out)
        self.assertRegex(
            out,
            r"Poured 1 of 2 steps under w-[a-z0-9]+ \(w-[a-z0-9.]+\), "
            r"and the next failed: refused by the test",
        )
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "formula", "pour", "mol-ship-the-package", "--json"],
            cwd=repo.path,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        record = json.loads(p.stdout)
        self.assertEqual(len(record["stepIds"]), 1, record)
        self.assertEqual(
            p.stderr,
            "dotdiw: Poured 1 of 2 steps under %s (%s), and the next failed: refused by the test\n"
            % (record["rootId"], record["stepIds"][0]),
        )

    def test_a_pour_prints_the_same_under_beads_as_under_local(self):
        said = []
        for tracker in ("beads", "local"):
            repo = Repo(tracker=None)
            self.addCleanup(repo.close)
            repo.write("release-through-tap.formula.toml", FORMULA_A)
            repo.git("add", "-A")
            repo.git("commit", "-qm", "the project as it stands")
            code, out = repo.dotdiw("init", "--tracker", tracker, "--prefix", "w")
            self.assertEqual(code, 0, out)
            code, out = repo.dotdiw("formula", "pour", "mol-release-through-tap")
            self.assertEqual(code, 0, out)
            said.append(re.sub(r"w-[a-z0-9.]+", "<id>", out))
        self.assertEqual(said[0], said[1])

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_init_stops_where_the_beads_store_cannot_be_brought_up_to_date(self):
        """bd refuses the upgrade's update: init stops in one line naming it,
        every other command is still refused, and the next init finishes."""
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("create", "Poured by 2.0", "--json")
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        ident = (made[0] if isinstance(made, list) else made)["id"]
        code, out = repo.bd(
            "update", ident, "--description", "Ship it.\n\nVerify using:\n- run:make check"
        )
        self.assertEqual(code, 0, out)
        os.unlink(os.path.join(repo.workspace(), "means-in-metadata"))
        shim = tempfile.mkdtemp(prefix="dotdiw-bd-shim-")
        self.addCleanup(shutil.rmtree, shim, True)
        with open(os.path.join(shim, "bd"), "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/sh\n"
                'if [ "$1" = update ]; then\n'
                "  echo x >> %s\n"
                "  n=$(wc -l < %s)\n"
                '  if [ $n -gt %d ]; then echo "refused by the test" >&2; exit 1; fi\n'
                "fi\n"
                'exec %s "$@"\n'
                % (
                    shlex.quote(os.path.join(shim, "updates")),
                    shlex.quote(os.path.join(shim, "updates")),
                    0,
                    shlex.quote(shutil.which("bd") or "bd"),
                )
            )
        os.chmod(os.path.join(shim, "bd"), 0o755)
        env = dict(repo.env, PATH=shim + os.pathsep + repo.env["PATH"])
        code, out = repo.dotdiw("init", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn(
            "init stopped: the store an earlier version kept could not be brought up to date: ",
            out,
        )
        self.assertIn("refused by the test", out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        code, out = repo.dotdiw("list")
        self.assertEqual(code, 1, out)
        self.assertIn("Run dotdiw init once to bring it up to date.", out)
        code, out = repo.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertIn("out of 1 description", out)
        code, out = repo.dotdiw("list")
        self.assertEqual(code, 0, out)

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_init_passes_an_issue_whose_metadata_holds_dotdiw_of_its_own(self):
        """An issue an earlier version made with dotdiw in its metadata as a
        value of its own: init brings the store up to date, and every command
        runs again."""
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("create", "Theirs", "--json")
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        ident = (made[0] if isinstance(made, list) else made)["id"]
        code, out = repo.bd("update", ident, "--metadata", '{"dotdiw": "customer value"}')
        self.assertEqual(code, 0, out)
        os.unlink(os.path.join(repo.workspace(), "means-in-metadata"))
        code, out = repo.dotdiw("list")
        self.assertEqual(code, 1, out)
        code, out = repo.dotdiw("init")
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("list")
        self.assertEqual(code, 0, out)
        self.assertIn(ident, out)

    def test_learn_teaches_it(self):
        code, out = self.dotdiw("learn")
        self.assertEqual(code, 0, out)
        self.assertIn("A formula may also name the means to prove that its run", out)
        self.assertIn('"run:make smoke-test",', out)


class TheArgumentsBeadsIsGiven(unittest.TestCase):
    """Under beads, create reads dotdiw's own flags, a value never taken for an
    option, and what is typed through the pass-through reaches bd read option
    by option, a type that makes a root refused, since only a pour makes one."""

    def setUp(self):
        if not have_bd():
            self.skipTest("bd is not installed")
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        code, out = self.repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)

    def test_a_value_is_never_read_as_an_option(self):
        code, out = self.repo.dotdiw("create", "Quoted", "--description=--assignee=me", "--json")
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        made = made[0] if isinstance(made, list) else made
        self.assertEqual(made.get("description"), "--assignee=me")
        self.assertFalse(made.get("assignee"))
        # And through the pass-through, which reads bd's own flags.
        code, out = self.repo.dotdiw("update", made["id"], "-d", "--assignee=me")
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("show", made["id"], "--json")
        shown = json.loads(out)
        shown = shown[0] if isinstance(shown, list) else shown
        self.assertEqual(shown.get("description"), "--assignee=me")
        self.assertFalse(shown.get("assignee"))

    def test_a_typed_description_reads_back_as_typed(self):
        """A description typed with -d that reads like the means is kept so
        that the interface gives it back as typed, with no means."""
        typed = "Verify using:\n- a line of this description, not a means"
        code, out = self.repo.dotdiw("create", "Described", "--json")
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        ident = (made[0] if isinstance(made, list) else made)["id"]
        code, out = self.repo.dotdiw("update", ident, "-d", typed)
        self.assertEqual(code, 0, out)
        m = load_module("dotdiw_typed_description")
        saved = {k: os.environ.get(k) for k in ("HOME", "DOTDIW_TRACKER", "BEADS_DIR")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        self.addCleanup(restore)
        os.environ["HOME"] = self.repo.home
        for k in ("DOTDIW_TRACKER", "BEADS_DIR"):
            os.environ.pop(k, None)
        item = m.invoke_tracker(
            "operation.show-item", {"root": self.repo.path, "tracker": "beads", "id": ident}
        )["item"]
        self.assertEqual((item.get("description"), item.get("verifyUsing")), (typed, None))

    def test_only_a_pour_makes_a_root(self):
        refused = "Only formula pour makes a root, so a type of molecule is refused."
        for typed in (["-t", "molecule"], ["--type", "molecule"], ["--type=molecule"]):
            with self.subTest(typed=typed):
                code, out = self.repo.dotdiw("create", "A root by hand", *typed)
                self.assertEqual(code, 2, out)
                self.assertIn("is not one of its flags", out)
                self.assertEqual(len(out.strip().splitlines()), 1, out)
        code, out = self.repo.dotdiw("list", "--json")
        self.assertNotIn("A root by hand", out)
        code, out = self.repo.dotdiw("create", "A task", "--json")
        self.assertEqual(code, 0, out)
        made = json.loads(out)
        ident = (made[0] if isinstance(made, list) else made)["id"]
        code, out = self.repo.dotdiw("update", ident, "--type", "molecule")
        self.assertEqual(code, 1, out)
        self.assertIn(refused, out)
        code, out = self.repo.dotdiw("show", ident, "--json")
        shown = json.loads(out)
        self.assertEqual((shown[0] if isinstance(shown, list) else shown)["issue_type"], "task")


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

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_an_assignee_of_me_under_beads_is_the_name_bd_records(self):
        repo = self.repo
        code, out = repo.dotdiw("init", "--prefix", "w", "--tracker", "beads")
        self.assertEqual(code, 0, out)
        ident = group1("Created issue: (\\S+)", repo.dotdiw("create", "Mine")[1])

        def assignee():
            code, out = repo.dotdiw("show", ident, "--json")
            self.assertEqual(code, 0, out)
            shown = json.loads(out)
            return (shown[0] if isinstance(shown, list) else shown).get("assignee")

        for flags in (("-a", "me"), ("--assignee", "me"), ("--assignee=me",), ("-a=me",)):
            with self.subTest(flags=flags):
                self.assertEqual(repo.dotdiw("update", ident, "-a", "other")[0], 0)
                code, out = repo.dotdiw("update", ident, *flags)
                self.assertEqual(code, 0, out)
                self.assertEqual(assignee(), "Test")
        env = dict(repo.env, BEADS_ACTOR="Set By Hand")
        self.assertEqual(repo.dotdiw("update", ident, "-a", "me", env=env)[0], 0)
        self.assertEqual(assignee(), "Set By Hand")
        code, out = repo.dotdiw("create", "Mine too", "-a", "me")
        self.assertEqual(code, 2, out)
        self.assertIn("-a is not one of its flags", out)
        code, out = repo.dotdiw("create", "Mine too")
        self.assertEqual(code, 0, out)
        ident = group1("Created issue: (\\S+)", out)
        self.assertEqual(repo.dotdiw("update", ident, "-a", "me")[0], 0)
        self.assertEqual(assignee(), "Test")
        self.assertEqual(repo.dotdiw("update", ident, "-a", "someone")[0], 0)
        self.assertEqual(assignee(), "someone")

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
        self.assertRegex(lines[1], r"^  local\s+2\.0\.0\s+shipped\s+\(this checkout\)$")
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
        self.assertIn(
            "tracker list | use <name> | check <name or path> | new <name> | migrate <from> <to>",
            out,
        )
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
        # A root moves as a task until question.how-migrate-copies-a-root is settled.
        self.assertEqual(moved[root]["kind"], "task")
        self.assertEqual(
            repo.dotdiw("--version")[1].strip().split("\n")[1], "  tracker local 2.0.0"
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
class PrefixCase(unittest.TestCase):
    """A copy of the tool installed in a temporary prefix laid out as Homebrew
    lays one out, with a home directory and a repository of its own."""

    def setUp(self):
        self.top = tempfile.mkdtemp(prefix="dotdiw-prefix-")
        self.addCleanup(shutil.rmtree, self.top, True)
        self.home = os.path.join(self.top, "home")
        self.repo = os.path.join(self.top, "repo")
        self.prefix = os.path.join(self.top, "prefix")
        self.homed = os.path.join(self.home, ".dotdiw", "trackers")
        self.shared = os.path.join(self.prefix, "share", "dotdiw", "trackers")
        os.makedirs(self.repo)
        os.makedirs(self.home)
        for args in (["init", "-q", "."], ["config", "user.email", "t@example.invalid"]):
            subprocess.run(["git"] + args, cwd=self.repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, capture_output=True)
        self.tool = self.install(os.path.join(self.prefix, "bin", "dotdiw"))

    def install(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy(DOTDIW, path)
        return path

    def module(self, directory, name, text):
        os.makedirs(directory, exist_ok=True)
        # Bytecode is matched by size and second: a same-sized edit could run the old file.
        shutil.rmtree(os.path.join(directory, "__pycache__"), ignore_errors=True)
        path = os.path.join(directory, name + ".py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_tool(self, *args, tool=None, cwd=None, env=None, flags=("-I",)):
        p = subprocess.run(
            [sys.executable, *flags, tool or self.tool] + list(args),
            cwd=cwd or self.repo,
            env=dict({"HOME": self.home, "PATH": "/usr/bin:/bin"}, **(env or {})),
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def line_of(self, name, out):
        return [line for line in out.splitlines() if line.startswith("  %s " % name)]

    def left_in_the_home_directory(self):
        try:
            return os.listdir(os.path.join(self.home, ".dotdiw"))
        except OSError:
            return []


# A check by path and then ordinary work in one process, as the bindings allow.
IN_ONE_PROCESS = """
import json
import sys

sys.path.insert(0, %(here)r)
import promise_bindings as bound

dotdiw = bound.load_dotdiw()
root, path, first = %(root)r, %(path)r, %(first)r


def who():
    out = bound.DescribeTracker({"tracker": "acme"})
    module = sys.modules.get("dotdiw_tracker_acme")
    return {
        "version": (out.get("info") or {}).get("version"),
        "reason": out.get("reason"),
        "module": module.__file__ if module else None,
        "tried": "acme" in dotdiw.LOAD_TRIED,
        "failed": dotdiw.LOAD_FAILED.get("acme"),
    }


before = who() if first else None
checked = bound.CheckTracker({"root": root, "name": "acme", "path": path})
print(
    json.dumps(
        {
            "before": before,
            "summary": checked["summary"],
            "passed": checked.get("passed"),
            "after": who(),
            "bytecode": sys.dont_write_bytecode,
        }
    )
)
"""


class ACheckByPathLeavesTheProcessAsItWas(PrefixCase):
    """Through the bindings a process outlives a check. Whatever a file checked by
    path did to the registry would go on answering ordinary work."""

    def candidate(self, text=None):
        return self.module(
            os.path.join(self.repo, "sub"), "acme", text or ACME.replace("1.0.0", "9.9.9")
        )

    def in_one_process(self, path, first=True):
        p = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                IN_ONE_PROCESS
                % {
                    "here": os.path.dirname(DOTDIW),
                    "root": self.repo,
                    "path": path,
                    "first": first,
                },
            ],
            cwd=self.repo,
            env={"HOME": self.home, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        ran = json.loads(p.stdout.splitlines()[-1])
        self.assertFalse(ran["bytecode"], "writing bytecode comes back on")
        return ran

    def assert_the_installed_file_answers(self, who):
        self.assertEqual(who["version"], "1.0.0", who)
        self.assertEqual(who["module"], os.path.realpath(os.path.join(self.homed, "acme.py")), who)
        self.assertFalse(who["tried"], who)
        self.assertIsNone(who["failed"], who)

    def test_the_adapter_that_was_answering_answers_again(self):
        self.module(self.homed, "acme", ACME)
        ran = self.in_one_process(self.candidate())
        self.assert_the_installed_file_answers(ran["before"])
        self.assertTrue(ran["passed"], ran)
        self.assert_the_installed_file_answers(ran["after"])

    def test_an_adapter_not_loaded_yet_still_loads_from_its_own_file(self):
        self.module(self.homed, "acme", ACME)
        ran = self.in_one_process(self.candidate(), first=False)
        self.assertTrue(ran["passed"], ran)
        self.assert_the_installed_file_answers(ran["after"])

    def test_a_file_that_failed_the_scenario_is_gone_too(self):
        self.module(self.homed, "acme", ACME)
        start = "def impl_create_item(request):\n"
        ran = self.in_one_process(
            self.candidate(ACME.replace(start, start + '    raise RuntimeError("no")\n'))
        )
        self.assertFalse(ran["passed"], ran)
        self.assert_the_installed_file_answers(ran["after"])

    def test_a_file_that_did_not_load_takes_nothing_away(self):
        self.module(self.homed, "acme", ACME)
        ran = self.in_one_process(self.candidate("def broken(:\n"))
        self.assertIn("did not load", ran["summary"])
        self.assert_the_installed_file_answers(ran["after"])

    def test_a_file_that_did_not_load_counts_against_nothing(self):
        self.module(self.homed, "acme", ACME)
        ran = self.in_one_process(self.candidate("def broken(:\n"), first=False)
        self.assertIn("did not load", ran["summary"])
        self.assert_the_installed_file_answers(ran["after"])

    def test_with_nothing_installed_no_adapter_is_left_under_that_name(self):
        ran = self.in_one_process(self.candidate(), first=False)
        self.assertTrue(ran["passed"], ran)
        self.assertEqual(ran["after"]["reason"], "tracker-unknown", ran)
        self.assertIsNone(ran["after"]["module"], ran)

    def test_a_failure_already_recorded_is_still_said(self):
        self.module(self.homed, "acme", "def broken(:\n")
        ran = self.in_one_process(self.candidate())
        self.assertEqual(ran["before"]["reason"], "adapter-failed", ran)
        self.assertTrue(ran["passed"], ran)
        self.assertEqual(ran["after"], ran["before"])


class ThePlanFormula(PrefixCase):
    """What track-items-plan-file.formula.toml promises about a plan's order and its
    text. The walk is the layout its steps name, on each tracker at hand."""

    def steps(self):
        path = os.path.join(os.path.dirname(DOTDIW), "track-items-plan-file.formula.toml")
        with open(path, "rb") as fh:
            return {step["id"]: step["title"] for step in tomllib.load(fh)["steps"]}

    def made(self, title, *args, env=None):
        code, out = self.run_tool("create", title, *args, env=env)
        self.assertEqual(code, 0, out)
        return group1(r"Created issue: (\S+)", out)

    def refused(self, ident, env=None):
        code, out = self.run_tool("close", ident, env=env)
        self.assertNotEqual(code, 0, out)

    def closed(self, ident, env=None):
        code, out = self.run_tool("close", ident, env=env)
        self.assertEqual(code, 0, out)

    def ready(self, env=None):
        code, out = self.run_tool("ready", env=env)
        self.assertEqual(code, 0, out)
        return out

    def walk(self, tracker, env=None):
        code, out = self.run_tool("init", "--tracker", tracker, env=env)
        self.assertEqual(code, 0, out)
        root = self.made("The plan", env=env)
        first = self.made("Phase one", "--parent", root, env=env)
        second = self.made("Phase two", "--parent", root, env=env)
        code, out = self.run_tool("dep", "add", second, first, env=env)
        self.assertEqual(code, 0, out)
        sooner = self.made("Build the worker", "--parent", first, env=env)
        later = self.made("Ship the worker", "--parent", second, env=env)
        code, out = self.run_tool("dep", "add", later, first, env=env)
        self.assertEqual(code, 0, out)
        out = self.ready(env)
        self.assertIn(sooner, out)
        self.assertNotIn(later, out)
        self.refused(later, env)
        self.refused(first, env)  # a phase does not close over its open items
        self.closed(sooner, env)
        self.closed(first, env)
        self.assertIn(later, self.ready(env))
        self.closed(later, env)
        self.closed(second, env)
        self.closed(root, env)

    def test_the_layout_keeps_the_order_under_local(self):
        self.walk("local")

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_the_layout_keeps_the_order_under_beads(self):
        self.walk("beads", {"PATH": "%s:/usr/bin:/bin" % os.path.dirname(shutil.which("bd") or "")})

    def test_a_child_does_not_take_on_its_parents_needs_under_local(self):
        """Why the formula writes the edge. Should this change, the formula can drop it."""
        code, out = self.run_tool("init", "--tracker", "local")
        self.assertEqual(code, 0, out)
        before = self.made("Phase one")
        parent = self.made("Phase two")
        code, out = self.run_tool("dep", "add", parent, before)
        self.assertEqual(code, 0, out)
        self.assertIn(self.made("Ship the worker", "--parent", parent), self.ready())

    def test_the_formula_writes_the_edge_and_verifies_it(self):
        steps = self.steps()
        self.assertIn("`dep add` each item of a later phase", steps["items"])
        self.assertIn("`dotdiw ready` lists no item of a later phase", steps["verify"])
        self.assertIn("`dotdiw close` on one is refused", steps["verify"])

    def test_the_plan_file_keeps_each_items_text(self):
        steps = self.steps()
        self.assertIn("keep the item's full text where it is", steps["point"])
        self.assertIn("every item's full text", steps["verify"])


class ThePlacesAModuleIsFound(PrefixCase):
    """A package cannot write to a home directory, so a module is also found in
    share/dotdiw/trackers beside the tool. A shipped name comes first, then the
    home directory, then share."""

    def test_a_module_beside_bin_is_found_and_answers(self):
        path = self.module(self.shared, "acme", ACME)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("loaded, from %s" % path, self.line_of("acme", out)[0])
        code, out = self.run_tool("tracker", "check", "acme")
        self.assertEqual(code, 0, out)
        self.assertIn("✓ acme passed 10 of 10.", out)
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("create", "Work on acme")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("list")
        self.assertEqual(code, 0, out)
        self.assertIn("Work on acme", out)

    def test_the_home_directory_comes_first(self):
        self.module(self.shared, "acme", ACME.replace('"1.0.0"', '"1.0.0-shared"'))
        path = self.module(self.homed, "acme", ACME.replace('"1.0.0"', '"1.0.0-home"'))
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        lines = self.line_of("acme", out)
        self.assertEqual(len(lines), 1, out)
        self.assertIn("1.0.0-home", lines[0])
        self.assertIn(path, lines[0])

    def test_a_shipped_name_comes_before_both(self):
        for directory in (self.homed, self.shared):
            self.module(directory, "local", 'raise RuntimeError("never run")\n')
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(self.line_of("local", out)[0], r"shipped")
        self.assertNotIn("did not load", out)

    def test_a_keg_reads_the_directory_above_cellar(self):
        keg = self.install(os.path.join(self.prefix, "Cellar", "dotdiw", "9.9", "bin", "dotdiw"))
        os.makedirs(os.path.join(self.prefix, "opt"))
        os.symlink(
            os.path.join("..", "Cellar", "dotdiw", "9.9"),
            os.path.join(self.prefix, "opt", "dotdiw"),
        )
        os.remove(self.tool)
        os.symlink(os.path.join("..", "Cellar", "dotdiw", "9.9", "bin", "dotdiw"), self.tool)
        path = self.module(self.shared, "acme", ACME)
        for tool in (keg, self.tool, os.path.join(self.prefix, "opt", "dotdiw", "bin", "dotdiw")):
            with self.subTest(tool=tool):
                code, out = self.run_tool("tracker", "list", tool=tool)
                self.assertEqual(code, 0, out)
                self.assertIn(path, self.line_of("acme", out)[0])

    def test_a_tool_outside_a_bin_directory_reads_only_the_home_directory(self):
        checkout = self.install(os.path.join(self.top, "checkout", "dotdiw"))
        self.module(os.path.join(self.top, "share", "dotdiw", "trackers"), "acme", ACME)
        code, out = self.run_tool("tracker", "list", tool=checkout)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.line_of("acme", out), [], out)

    def test_a_broken_module_does_not_fall_through_to_a_later_directory(self):
        self.module(self.homed, "acme", "def broken(:\n")
        self.module(self.shared, "acme", ACME)
        code, out = self.run_tool("tracker", "use", "acme")
        self.assertEqual(code, 1, out)
        self.assertIn("dotdiw: acme did not load from %s" % self.homed, out)
        self.assertNotIn("Traceback", out)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("did not load", self.line_of("acme", out)[0])

    def test_a_store_that_raises_is_no_traceback(self):
        """Asking which adapter holds a store reaches every registered adapter,
        when a checkout has no choice written, so one module's mistake there must
        not stop another answering."""
        boom = ACME.replace(
            'return os.path.join(dotdiw_workspace(root), "acme.json")',
            'raise RuntimeError("the store has a bug")',
        )
        self.module(self.homed, "acme", boom)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("(this checkout)", self.line_of("local", out)[0])

    def test_another_interface_is_one_line_from_the_command_line(self):
        self.module(
            self.shared,
            "acme",
            ACME.replace('"checkTarget": "scratch",', '"checkTarget": "scratch", "interface": 99,'),
        )
        code, out = self.run_tool("tracker", "use", "acme")
        self.assertEqual(code, 1, out)
        self.assertIn("written for tracker interface 99; this dotdiw supports interface 3", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len([s for s in out.splitlines() if s.strip()]), 1, out)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("did not load", self.line_of("acme", out)[0])

    def test_a_file_is_checked_by_path_without_installing_it(self):
        path = self.module(os.path.join(self.repo, "sub"), "acme", ACME)
        code, out = self.run_tool("tracker", "check", "./sub/acme.py")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("  pass  operation."), 10, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)
        self.assertEqual(self.left_in_the_home_directory(), [], "nothing is installed")
        self.assertEqual(os.listdir(os.path.dirname(path)), ["acme.py"], "nothing beside it")

    def test_a_check_by_path_reads_the_file_and_not_its_bytecode(self):
        """Bytecode is matched by size and second, so a same-sized edit within one
        second still looks current. The file is what gets checked, and what is
        cached beside it stays as it was."""
        start = "def impl_create_item(request):\n"
        broken = '    raise RuntimeError("edited")\n'
        working = "    pass".ljust(len(broken) - 1) + "\n"
        path = self.module(self.repo, "acme", ACME.replace(start, start + working))
        cached = importlib.util.cache_from_source(path)
        py_compile.compile(
            path,
            cfile=cached,
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
        )
        with open(cached, "rb") as fh:
            held = fh.read()
        when = os.stat(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ACME.replace(start, start + broken))
        os.utime(path, ns=(when.st_atime_ns, when.st_mtime_ns))
        self.assertEqual(os.stat(path).st_size, when.st_size)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL  operation.create-item", out)
        self.assertIn("edited", out)
        with open(cached, "rb") as fh:
            self.assertEqual(fh.read(), held)

    def test_what_a_checked_file_imports_leaves_no_bytecode_beside_it(self):
        """While the file loads, and while the scenario runs."""
        directory = os.path.join(self.repo, "sub")
        for name in ("helper_at_load", "helper_later"):
            self.module(directory, name, "VALUE = 1\n")
        start = "def impl_create_item(request):\n"
        self.module(
            directory,
            "acme",
            "import os\nimport sys\n\n"
            "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            "import helper_at_load\n\n" + ACME.replace(start, start + "    import helper_later\n"),
        )
        code, out = self.run_tool("tracker", "check", "./sub/acme.py")
        self.assertEqual(code, 0, out)
        self.assertEqual(
            sorted(os.listdir(directory)), ["acme.py", "helper_at_load.py", "helper_later.py"]
        )

    def test_a_word_ending_in_py_is_a_file_in_the_current_directory(self):
        self.module(self.repo, "acme", ACME)
        code, out = self.run_tool("tracker", "check", "acme.py")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)

    def test_a_file_is_checked_outside_any_repository(self):
        outside = os.path.join(self.top, "outside")
        self.module(outside, "acme", ACME)
        code, out = self.run_tool("tracker", "check", "./acme.py", cwd=outside)
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)

    def test_a_path_is_what_is_checked_when_the_name_is_also_installed(self):
        self.module(self.homed, "acme", "def broken(:\n")
        self.module(self.repo, "acme", ACME)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)

    def test_a_file_whose_operations_all_raise_gets_a_line_each(self):
        raising = "OPERATIONS = %r\n" % sorted(
            "operation.%s" % n
            for n in (
                "open-tracker",
                "describe-tracker",
                "create-item",
                "add-need",
                "pour-steps",
                "close-item",
                "show-item",
                "list-items",
                "update-item",
                "ready-items",
            )
        )
        raising += (
            "def _raises(request):\n"
            '    raise NotImplementedError("not yet")\n'
            'TRACKER = {"info": {"name": "acme", "version": "0", "interface": 3, "checkTarget": "scratch"},\n'
            '           "operations": {op: _raises for op in OPERATIONS}}\n'
        )
        self.module(self.repo, "acme", raising)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("  FAIL  operation."), 10, out)
        self.assertIn("\u2717 acme failed at operation.open-tracker", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(self.left_in_the_home_directory(), [])

    def test_a_file_that_cannot_be_checked_is_one_line(self):
        self.module(self.repo, "broken", "def broken(:\n")
        self.module(self.repo, "notatracker", "VALUE = 1\n")
        self.module(self.repo, "Bad_Name", ACME)
        self.module(self.repo, "local", ACME)
        for word, says in (
            ("./gone.py", "is not a file"),
            ("./broken.py", "broken did not load from "),
            ("./notatracker.py", "holds no TRACKER table"),
            ("./Bad_Name.py", "lowercase letters, digits and hyphens"),
            ("./local.py", "is the name of an adapter built into dotdiw"),
        ):
            with self.subTest(word=word):
                code, out = self.run_tool("tracker", "check", word)
                self.assertEqual(code, 1, out)
                self.assertIn(says, out)
                self.assertNotIn("Traceback", out)
                self.assertEqual(len([s for s in out.splitlines() if s.strip()]), 1, out)

    def test_a_name_outside_the_rule_stays_refused(self):
        self.module(self.shared, "acme", ACME)
        code, out = self.run_tool("tracker", "use", "../trackers/acme")
        self.assertEqual(code, 1, out)
        self.assertIn("is not a tracker here", out)

    def test_a_package_leaves_nothing_in_the_directory_packages_share(self):
        keg = os.path.join(self.prefix, "Cellar", "dotdiw-tracker-acme", "1", "share", "trackers")
        real = self.module(keg, "acme", ACME)
        os.makedirs(self.shared)
        os.symlink(real, os.path.join(self.shared, "acme.py"))
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertIn(os.path.join(self.shared, "acme.py"), self.line_of("acme", out)[0])
        self.assertEqual(os.listdir(self.shared), ["acme.py"])


class WhoATrackerActsAs(PrefixCase):
    """init names who a tracker acts as, once, and tracker use each time, where
    the tracker checked; a name anyone could give is not shown. A move says how
    many assignees it left."""

    DESCRIBE = "    return _ok(info=info, path=path if path and os.path.exists(path) else None)\n"

    def answering(self, actor):
        self.assertEqual(ACME.count(self.DESCRIBE), 1)
        return ACME.replace(
            self.DESCRIBE,
            "    return _ok(info=info, actor=%s, path=path if path and os.path.exists(path) else None)\n"
            % actor,
        )

    def test_a_checked_name_is_said_once_at_init(self):
        self.module(
            self.homed, "acme", self.answering('{"name": "Priya", "id": "p-1", "verified": True}')
        )
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("  Acting as Priya.\n"), 1, out)
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Acting as", out)

    def test_a_name_nobody_checked_is_not_said(self):
        self.module(self.homed, "acme", self.answering('{"name": "Priya", "verified": False}'))
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Acting as", out)

    def test_an_adapter_with_nothing_to_say_is_not_asked_to(self):
        self.module(self.homed, "acme", ACME)
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertIn("Adopted. The tracker is acme", out)
        self.assertNotIn("Acting as", out)

    def test_an_actor_outside_its_type_does_not_stop_the_adoption(self):
        self.module(self.homed, "acme", self.answering('{"name": "Priya"}'))
        code, out = self.run_tool("init", "--tracker", "acme", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertIn("Adopted. The tracker is acme", out)
        self.assertNotIn("Acting as", out)

    def test_a_checked_name_is_said_each_time_a_tracker_is_chosen(self):
        self.module(
            self.homed, "acme", self.answering('{"name": "Priya", "id": "p-1", "verified": True}')
        )
        code, out = self.run_tool("init", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Acting as", out)
        for _ in range(2):  # the first opens acme's store, the second finds it open
            code, out = self.run_tool("tracker", "use", "acme")
            self.assertEqual(code, 0, out)
            self.assertIn("tracker is acme.\n  Acting as Priya.\n", out)

    def made(self, *args):
        code, out = self.run_tool("create", *args, "-q")
        self.assertEqual(code, 0, out)
        return group1(r"Created issue: (\S+)", out)

    def test_a_move_says_how_many_assignees_it_left(self):
        self.module(self.homed, "acme", ACME)
        code, out = self.run_tool("init", "--prefix", "a")
        self.assertEqual(code, 0, out)
        for title in ("One", "Two"):
            code, out = self.run_tool("update", self.made(title), "-a", "someone")
            self.assertEqual(code, 0, out)
        self.made("Nobody's")
        code, out = self.run_tool("tracker", "migrate", "local", "acme")
        self.assertEqual(code, 0, out)
        self.assertIn("Moved 3 items", out)
        self.assertIn("  Assignees do not carry over: 2 items had one.\n", out)

    def test_a_move_with_one_assignee_says_one(self):
        self.module(self.homed, "acme", ACME)
        code, out = self.run_tool("init", "--prefix", "a")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("update", self.made("One"), "-a", "me")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("tracker", "migrate", "local", "acme")
        self.assertEqual(code, 0, out)
        self.assertIn("  Assignees do not carry over: 1 item had one.\n", out)

    def test_a_move_with_no_assignee_says_nothing_of_them(self):
        self.module(self.homed, "acme", ACME)
        code, out = self.run_tool("init", "--prefix", "a")
        self.assertEqual(code, 0, out)
        self.made("Nobody's")
        code, out = self.run_tool("tracker", "migrate", "local", "acme")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Assignees", out)


class TheFileATrackerStartsFrom(PrefixCase):
    """dotdiw tracker new writes one file: the ten operations raising until
    they are filled, and the table that declares them. The check says which are
    left, and filled in it passes."""

    OPERATIONS = (
        "open_tracker",
        "describe_tracker",
        "create_item",
        "add_need",
        "pour_steps",
        "close_item",
        "show_item",
        "list_items",
        "update_item",
        "ready_items",
    )

    def written(self, *where):
        with open(os.path.join(self.repo, *where), encoding="utf-8") as fh:
            return fh.read()

    def test_its_helper_keeps_the_means_in_the_description(self):
        """A tracker with a title and a description and nothing more keeps the
        means to prove a run with the helper the file holds, and reads back
        what it was given."""
        code, out = self.run_tool("tracker", "new", "acme")
        self.assertEqual(code, 0, out)
        written = load_module("acme_started", os.path.join(self.repo, "acme.py"))
        means = [
            "run:make check",
            "git+ssh://git@example.invalid/a/b.git#c.md",
            "https://example.invalid/r",
        ]
        for description in ("Two lines.\nOf it.", None):
            kept = written.keep_verify_using(description, means)
            self.assertEqual(written.read_verify_using(kept), (description, means))
        self.assertEqual(
            written.read_verify_using("Only a description."), ("Only a description.", [])
        )
        self.assertEqual(written.keep_verify_using("Unchanged.", []), "Unchanged.")

    def test_it_is_written_and_fails_one_line_per_operation(self):
        code, out = self.run_tool("tracker", "new", "acme")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 Wrote acme.py", out)
        self.assertIn("dotdiw tracker check ./acme.py", out)
        self.assertEqual(self.left_in_the_home_directory(), [], "only the file is written")
        self.assertEqual(os.listdir(self.repo).count("acme.py"), 1)
        text = self.written("acme.py")
        self.assertIn('"name": "acme"', text)
        self.assertIn('"interface": 3', text)
        self.assertNotIn("<NAME>", text)
        for internal in ("correlationId", "trackerRef", "terminal", "printed", "resultRefs"):
            self.assertNotIn(internal, text)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("  FAIL  operation."), 10, out)
        self.assertNotIn("Traceback", out)

    def test_filled_in_it_passes(self):
        code, out = self.run_tool("tracker", "new", "acme")
        self.assertEqual(code, 0, out)
        text = self.written("acme.py")
        for name in self.OPERATIONS:
            raising = 'raise NotImplementedError("%s")' % name
            self.assertEqual(text.count(raising), 1, name)
            text = text.replace(raising, "return impl_%s(request)" % name)
        first = text.index("def open_tracker")
        filled = text[:first] + ACME_BODIES + text[first:]
        with open(os.path.join(self.repo, "acme.py"), "w", encoding="utf-8") as fh:
            fh.write(filled)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)
        self.module(self.shared, "acme", filled)
        code, out = self.run_tool("tracker", "check", "acme")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 acme passed 10 of 10.", out)

    def test_it_goes_where_it_is_told(self):
        os.makedirs(os.path.join(self.repo, "one"))
        os.makedirs(os.path.join(self.repo, "two"))
        for args, where in ((("--at", "one"), "one"), (("--at=two",), "two")):
            with self.subTest(args=args):
                code, out = self.run_tool("tracker", "new", "acme", *args)
                self.assertEqual(code, 0, out)
                self.assertIn("\u2713 Wrote %s" % os.path.join(where, "acme.py"), out)
                self.assertIn("dotdiw tracker check ./%s/acme.py" % where, out)
                self.assertTrue(os.path.isfile(os.path.join(self.repo, where, "acme.py")))

    def test_a_file_elsewhere_is_named_by_its_whole_path(self):
        elsewhere = os.path.join(self.top, "elsewhere")
        os.makedirs(elsewhere)
        code, out = self.run_tool("tracker", "new", "acme", "--at", elsewhere)
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 Wrote %s" % os.path.join(elsewhere, "acme.py"), out)
        self.assertIn("dotdiw tracker check %s says" % os.path.join(elsewhere, "acme.py"), out)
        self.assertNotIn("..", out)

    def test_at_with_nothing_after_it_is_refused(self):
        for args in (("foo", "--at"), ("foo", "--at=")):
            with self.subTest(args=args):
                code, out = self.run_tool("tracker", "new", *args)
                self.assertEqual(code, 2, out)
                self.assertIn("tracker list | use", out)
                self.assertEqual(os.listdir(self.repo), [".git"])

    def test_it_needs_no_repository(self):
        outside = os.path.join(self.top, "outside")
        os.makedirs(outside)
        code, out = self.run_tool("tracker", "new", "acme", cwd=outside)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(outside, "acme.py")))

    def test_what_it_refuses_is_one_line_and_writes_nothing(self):
        with open(os.path.join(self.repo, "taken.py"), "w", encoding="utf-8") as fh:
            fh.write("# already here\n")
        for args, says in (
            (("taken",), "already exists"),
            (("Bad_Name",), "lowercase letters, digits and hyphens"),
            (("../acme",), "lowercase letters, digits and hyphens"),
            (("local",), "is the name of an adapter built into dotdiw"),
            (("beads",), "is the name of an adapter built into dotdiw"),
            (("acme", "--at", "nowhere"), "nowhere"),
        ):
            with self.subTest(args=args):
                before = sorted(os.listdir(self.repo))
                code, out = self.run_tool("tracker", "new", *args)
                self.assertEqual(code, 1, out)
                self.assertIn(says, out)
                self.assertNotIn("Traceback", out)
                self.assertEqual(len([s for s in out.splitlines() if s.strip()]), 1, out)
                self.assertEqual(sorted(os.listdir(self.repo)), before)
        self.assertEqual(self.written("taken.py"), "# already here\n")
        code, out = self.run_tool("tracker", "new")
        self.assertEqual(code, 2, out)
        self.assertIn("new <name>", out)


class WithoutTheBeadsBinary(unittest.TestCase):
    """Beads is optional. With no binary a new adoption and a day's work pass
    under the store dotdiw brings, and a checkout that chose beads is told the
    one command, in one line, whatever it asked for."""

    SAID = "dotdiw: beads is not installed. Run: brew install beads"

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.env = dict(self.repo.env, PATH="/usr/bin:/bin")

    def on_beads_with_the_binary_gone(self):
        code, out = self.repo.dotdiw("init", "--tracker", "beads", "--prefix", "b")
        self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("create", "Before it went away")
        self.assertEqual(code, 0, out)
        return group1(r"Created issue: (\S+)", out)

    def test_a_day_of_work_needs_no_binary(self):
        code, out = self.repo.dotdiw("init", "--prefix", "w", env=self.env)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.repo.config("dotdiw.tracker"), "local")
        code, out = self.repo.dotdiw("create", "A piece of work", env=self.env)
        self.assertEqual(code, 0, out)
        ident = group1(r"Created issue: (\S+)", out)
        for args in (("list",), ("ready",), ("show", ident), ("close", ident)):
            code, out = self.repo.dotdiw(*args, env=self.env)
            self.assertEqual(code, 0, out)
        code, out = self.repo.dotdiw("tracker", "list", env=self.env)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^  beads\s+not installed\s+shipped$")
        code, out = self.repo.dotdiw("--version", env=self.env)
        self.assertEqual(code, 0, out)
        self.assertIn("tracker local", out)
        self.assertNotIn("not installed", out)

    def test_choosing_beads_with_no_binary_writes_nothing(self):
        for args in (("init", "--tracker", "beads", "--prefix", "b"), ("tracker", "use", "beads")):
            with self.subTest(args=args):
                code, out = self.repo.dotdiw(*args, env=self.env)
                self.assertNotEqual(code, 0, out)
                self.assertEqual(out.strip(), self.SAID)
                self.assertEqual(self.repo.config("dotdiw.tracker"), "")
                self.assertEqual(os.listdir(self.repo.path), [".git"], "nothing in the tree")

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_a_checkout_on_beads_is_told_the_one_command(self):
        ident = self.on_beads_with_the_binary_gone()
        for args in (
            ("create", "After it went away"),
            ("list",),
            ("ready",),
            ("show", ident),
            ("close", ident),
            ("update", ident, "--title", "New"),
            ("dep", "add", ident, ident),
            ("mol", "pour", "mol-anything"),
            ("formula", "pour", "mol-anything"),
            ("update", ident, "-a", "me"),
            ("frobnicate",),
            ("tracker", "check", "beads"),
        ):
            with self.subTest(args=args):
                code, out = self.repo.dotdiw(*args, env=self.env)
                self.assertNotEqual(code, 0, out)
                self.assertEqual(out.strip(), self.SAID)
        code, out = self.repo.dotdiw("tracker", "list", env=self.env)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^  beads\s+not installed\s+shipped\s+\(this checkout\)$")
        code, out = self.repo.dotdiw("--version", env=self.env)
        self.assertEqual(code, 0, out)

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_steps_from_work_on_a_tracker_that_is_gone_says_so(self):
        ident = self.on_beads_with_the_binary_gone()
        code, out = self.repo.dotdiw("formula", "new", "Repeat it", "--from", ident, env=self.env)
        self.assertEqual(code, 127, out)
        self.assertEqual(out.strip(), self.SAID)
        self.assertNotIn("repeat-it.formula.toml", os.listdir(self.repo.path))

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_the_work_is_there_when_the_binary_comes_back(self):
        self.on_beads_with_the_binary_gone()
        code, out = self.repo.dotdiw("list", env=self.env)
        self.assertNotEqual(code, 0, out)
        code, out = self.repo.dotdiw("list")
        self.assertEqual(code, 0, out)
        self.assertIn("Before it went away", out)


class TheScenarioOnAnAdapterThatFails(PrefixCase):
    """An operation that could not be tried says why, in words."""

    def test_a_later_operation_says_an_earlier_one_did_not_pass(self):
        code, out = self.run_tool("tracker", "new", "acme")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("tracker", "check", "./acme.py")
        self.assertEqual(code, 1, out)
        self.assertNotIn("KeyError", out)
        self.assertIn("create-item", [s for s in out.splitlines() if "add-need" in s][0])


class TheCommandsPrinted(PrefixCase):
    """A printed command is there to be run, whatever a directory is called."""

    def test_the_check_after_tracker_new_runs_as_printed(self):
        for at in ("new adapters", "it's $HOME; (a)", os.path.join(self.top, "out side")):
            with self.subTest(at=at):
                directory = os.path.join(self.repo, at)
                os.makedirs(directory)
                code, out = self.run_tool("tracker", "new", "acme", "--at", at)
                self.assertEqual(code, 0, out)
                line = next(line for line in out.splitlines() if "tracker check" in line)
                words = shlex.split(line.split(" says which")[0])
                self.assertEqual(words[:3], ["dotdiw", "tracker", "check"], line)
                self.assertEqual(len(words), 4, line)
                self.assertTrue(
                    os.path.samefile(
                        os.path.join(self.repo, words[3]), os.path.join(directory, "acme.py")
                    ),
                    line,
                )
                code, out = self.run_tool(*words[1:])
                self.assertEqual(code, 1, out)  # 2 would be the usage error
                self.assertIn("FAIL  operation.", out)

    def test_the_git_add_after_formula_new_runs_as_printed(self):
        for at in ("my procedures", "it's $HOME; (a)"):
            with self.subTest(at=at):
                os.makedirs(os.path.join(self.repo, at))
                code, out = self.run_tool("formula", "new", "Cut a release", "--at", at)
                self.assertEqual(code, 0, out)
                line = next(line for line in out.splitlines() if "git add" in line)
                words = shlex.split(line.split("Then:")[1])
                self.assertEqual(words[:2], ["git", "add"], line)
                self.assertEqual(words[3], "&&", line)
                added = subprocess.run(words[:3], cwd=self.repo, capture_output=True, text=True)
                self.assertEqual(added.returncode, 0, added.stderr)


class WhatAModuleGetsWrong(PrefixCase):
    """A module is someone else's code. Whatever it gets wrong is said in one
    line, the command's exit says so, and the worker's checkout stays as it was."""

    ELSEWHERE = (
        (
            'return os.path.join(dotdiw_workspace(root), "acme.json")',
            'return os.path.join(os.path.expanduser("~"), "acme-elsewhere.json")',
        ),
        ('    "store": acme_store,\n', ""),
    )

    def acme(self, *changes, directory=None, name="acme"):
        text = ACME
        for old, new in changes:
            self.assertIn(old, text)
            text = text.replace(old, new)
        return self.module(directory or self.homed, name, text)

    def key(self, name="dotdiw.workspace"):
        return subprocess.run(
            ["git", "config", "--local", "--get", name],
            cwd=self.repo,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def in_the_tree(self):
        return sorted(os.listdir(self.repo))

    def test_the_check_leaves_the_checkout_alone_when_git_dir_is_set(self):
        """A hook runs with GIT_DIR exported, and the scratch repository is
        still the scratch one."""
        code, out = self.run_tool("init", "--tracker", "local")
        self.assertEqual(code, 0, out)
        key = self.key()
        code, out = self.run_tool("create", "Work that must stay found")
        self.assertEqual(code, 0, out)
        path = self.acme(directory=self.top)
        git_dir = os.path.join(self.repo, ".git")
        for args in (("tracker", "check", path), ("tracker", "check", "local")):
            with self.subTest(args=args):
                code, out = self.run_tool(*args, env={"GIT_DIR": git_dir})
                self.assertEqual(code, 0, out)
                self.assertIn("passed 10 of 10", out)
                self.assertEqual(self.key(), key)
                self.assertEqual(self.key("dotdiw.tracker"), "local")
        code, out = self.run_tool("list")
        self.assertEqual(code, 0, out)
        self.assertIn("Work that must stay found", out)

    def test_a_module_that_exits_on_load_is_refused(self):
        path = self.module(self.homed, "quitter", "import sys\nsys.exit(0)\n")
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn("quitter did not load from", out)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("did not load", self.line_of("quitter", out)[0])
        self.assertTrue(self.line_of("local", out), out)

    def test_an_operation_that_exits_fails_the_check(self):
        path = self.acme(
            (
                "def impl_create_item(request):\n",
                "def impl_create_item(request):\n    raise SystemExit(0)\n",
            ),
            directory=self.top,
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"FAIL  operation.create-item: .*SystemExit")
        self.assertEqual(len(re.findall(r"(?m)^  (?:pass|FAIL)  ", out)), 10, out)

    def test_a_chosen_module_that_exits_does_not_silence_a_command(self):
        self.acme()
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        self.module(self.homed, "acme", "import sys\nsys.exit(0)\n")
        for args in (("create", "Named"), ("list",), ("tracker", "new", "other", "--at", self.top)):
            with self.subTest(args=args):
                code, out = self.run_tool(*args)
                if args[0] != "tracker":
                    self.assertEqual(code, 1, out)
                    self.assertIn("acme did not load from", out)
                else:
                    self.assertEqual(code, 0, out)

    def test_a_metrics_extra_that_exits_does_not_stop_the_work(self):
        self.acme(
            ('"extras": {},', '"extras": {"metrics-off": quit_now},'),
            ("TRACKER = {", "def quit_now(request):\n    raise SystemExit(0)\n\n\nTRACKER = {"),
        )
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        code, out = self.run_tool("create", "Named")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue", out)

    def test_init_says_why_the_store_did_not_open_and_stops(self):
        stop = (
            "def impl_open_tracker(request):\n",
            "def impl_open_tracker(request):\n    return %s\n",
        )
        for answer, said in (
            ('_no("store-unwritable")', "store-unwritable"),
            (
                '{"status": "failed", "summary": "the site is down", "exitCode": 1}',
                "the site is down",
            ),
        ):
            with self.subTest(said=said):
                self.acme((stop[0], stop[1] % answer))
                code, out = self.run_tool("init", "--tracker", "acme")
                self.assertEqual(code, 1, out)
                self.assertIn(said, out)
                self.assertNotIn("\u2713", out)
                self.assertEqual(self.in_the_tree(), [".git"])
                self.assertEqual(self.key("dotdiw.tracker"), "")
                code, out = self.run_tool("tracker", "use", "acme")
                self.assertEqual(code, 1, out)
                self.assertIn(said, out)

    def test_init_stops_at_a_name_nothing_answers_to(self):
        code, out = self.run_tool("init", "--tracker", "typo")
        self.assertEqual(code, 1, out)
        self.assertIn("typo is not a tracker here", out)
        self.assertNotIn("\u2713", out)
        self.assertEqual(self.in_the_tree(), [".git"])

    def test_an_exit_code_left_out_is_read_from_the_status(self):
        ok = 'return dict({"status": "completed", "summary": "ok", "exitCode": 0}, **kw)'
        no = 'return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 1}'
        for extra in ("", ', "exitCode": None'):
            with self.subTest(extra=extra):
                path = self.acme(
                    (ok, 'return dict({"status": "completed", "summary": "ok"%s}, **kw)' % extra),
                    (
                        no,
                        'return {"status": "failed", "summary": reason, "reason": reason%s}'
                        % extra,
                    ),
                )
                code, out = self.run_tool("tracker", "check", path)
                self.assertEqual(code, 0, out)
                self.assertIn("acme passed 10 of 10", out)
                code, out = self.run_tool("init", "--tracker", "acme")
                self.assertEqual(code, 0, out)
                code, out = self.run_tool("create", "Named")
                self.assertEqual(code, 0, out)
                self.assertIn("Created issue", out)
                code, out = self.run_tool("create", "Orphan", "--parent", "nowhere")
                self.assertEqual(code, 1, out)
                self.assertNotIn("Traceback", out)

    def test_an_exit_code_against_the_status_is_refused(self):
        said = "a failed answer cannot exit 0"
        path = self.acme(
            (
                'return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 1}',
                'return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 0}',
            )
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn(said, out)
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        code, out = self.run_tool("create", "Orphan", "--parent", "nowhere")
        self.assertEqual(code, 1, out)
        self.assertIn(said, out)
        self.acme(
            (
                'return dict({"status": "completed", "summary": "ok", "exitCode": 0}, **kw)',
                'return dict({"status": "completed", "summary": "ok", "exitCode": 3}, **kw)',
            )
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn("a completed answer cannot exit 3", out)

    def test_a_forward_extra_is_held_to_the_same_rule(self):
        for answer, code_wanted in (
            ('{"status": "completed", "summary": "did"}', 0),
            ('{"status": "failed", "summary": "no", "exitCode": None}', 1),
            ('{"status": "failed", "summary": "no", "exitCode": 0}', 1),
            ('{"status": "failed", "summary": "no", "exitCode": "2"}', 1),
        ):
            with self.subTest(answer=answer):
                self.acme(
                    ('"extras": {},', '"extras": {"forward": forward},'),
                    (
                        "TRACKER = {",
                        "def forward(request):\n    return %s\n\n\nTRACKER = {" % answer,
                    ),
                )
                self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
                code, out = self.run_tool("frobnicate")
                self.assertEqual(code, code_wanted, out)
                self.assertNotIn("Traceback", out)

    def test_a_module_that_keeps_nothing_under_the_workspace_is_adopted(self):
        self.acme(*self.ELSEWHERE)
        code, out = self.run_tool("init", "--tracker", "acme")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("create", "Named")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue", out)
        code, out = self.run_tool("list")
        self.assertEqual(code, 0, out)
        self.assertIn("Named", out)
        self.module(self.homed, "acme", "def broken(:\n")
        code, out = self.run_tool("list")
        self.assertEqual(code, 1, out)
        self.assertIn("acme did not load from", out)

    def test_a_shipped_tracker_with_no_store_is_still_not_adopted(self):
        code, out = self.run_tool("init", "--tracker", "local")
        self.assertEqual(code, 0, out)
        shutil.rmtree(os.path.join(self.home, ".dotdiw", self.key()))
        code, out = self.run_tool("list")
        self.assertEqual(code, 1, out)
        self.assertIn("not adopted", out)

    def test_use_says_when_the_choice_could_not_be_written(self):
        self.acme()
        self.assertEqual(self.run_tool("init", "--tracker", "local")[0], 0)
        lock = os.path.join(self.repo, ".git", "config.lock")
        with open(lock, "w", encoding="utf-8"):
            pass
        code, out = self.run_tool("tracker", "use", "acme")
        os.unlink(lock)
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.strip(), "dotdiw: could not write dotdiw.tracker into this repository's git config."
        )
        self.assertEqual(self.key("dotdiw.tracker"), "local")

    def test_a_store_that_answers_no_path_is_no_traceback(self):
        self.acme(
            ('    "store": acme_store,\n', '    "store": odd_store,\n'),
            (
                "TRACKER = {",
                'def odd_store(root):\n    return ["not", "a", "path"]\n\n\nTRACKER = {',
            ),
        )
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertTrue(self.line_of("acme", out), out)

    def test_a_module_cannot_say_it_shipped(self):
        """The loader says where a module came from, whatever the module says:
        its mistakes stay its own, and the list prints where it really is."""
        path = self.acme(
            (
                '"info": {"name": "acme", "version": "1.0.0", "interface": 3, "checkTarget": "scratch", "extras": []},',
                '"info": {"name": "acme", "version": "1.0.0", "interface": 3, "checkTarget": "scratch", "extras": [],'
                ' "origin": "shipped", "source": "/nowhere"},',
            ),
            (
                'info = {"name": "acme", "version": "1.0.0", "origin": "loaded"}',
                'info = {"name": "acme", "version": "1.0.0", "origin": "shipped", "source": "/nowhere"}',
            ),
            (
                "def impl_create_item(request):\n",
                'def impl_create_item(request):\n    raise RuntimeError("a bug")\n',
            ),
        )
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        code, out = self.run_tool("create", "Named")
        self.assertEqual(code, 1, out)
        self.assertIn("acme failed inside create-item: RuntimeError: a bug", out)
        self.assertNotIn("Traceback", out)
        code, out = self.run_tool("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(self.line_of("acme", out)[0], r"loaded, from %s" % re.escape(path))

    def test_a_failed_create_says_why(self):
        self.assertEqual(self.run_tool("init")[0], 0)
        code, out = self.run_tool("create", "Orphan", "--parent", "nowhere")
        self.assertEqual(code, 1, out)
        self.assertIn("nowhere", out)

    def test_a_module_may_use_the_whole_standard_library(self):
        """A dataclass looks its module up by name while the module loads."""
        path = self.module(
            self.top,
            "acme",
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n\n\n"
            "@dataclass\nclass Held:\n    count: int = 0\n\n\n" + ACME,
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 0, out)
        self.assertIn("acme passed 10 of 10", out)

    def test_the_check_with_nowhere_to_work_is_one_line(self):
        path = self.acme(directory=self.top)
        with open(os.path.join(self.home, ".dotdiw"), "w", encoding="utf-8"):
            pass
        scratch = os.path.join(self.top, "tmp")
        os.makedirs(scratch)
        code, out = self.run_tool("tracker", "check", path, env={"TMPDIR": scratch})
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        self.assertEqual(os.listdir(scratch), [])

    def test_the_check_is_not_fooled_under_optimisation(self):
        path = self.acme(
            (
                "def impl_ready_items(request):\n",
                "def impl_ready_items(request):\n    return _ok(items=[])\n",
            ),
            directory=self.top,
        )
        code, out = self.run_tool("tracker", "check", path, flags=("-I", "-O"))
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL  operation.ready-items", out)

    def test_a_file_that_is_no_adapter_runs_once_in_a_command(self):
        ran = os.path.join(self.top, "ran")
        run_it = "with open(%r, 'a') as fh:\n    fh.write('x')\n" % ran
        for name, tail in (("raises", "raise RuntimeError('no')\n"), ("tableless", "")):
            for args in (("tracker", "list"), ("list",), ("--version",)):
                with self.subTest(name=name, args=args):
                    if os.path.exists(ran):
                        os.unlink(ran)
                    self.module(self.homed, name, run_it + tail)
                    self.run_tool(*args, env={"DOTDIW_TRACKER": name})
                    with open(ran, encoding="utf-8") as fh:
                        self.assertEqual(fh.read(), "x")
            os.unlink(os.path.join(self.homed, name + ".py"))

    def test_glob_characters_in_the_home_hide_nothing(self):
        home = os.path.join(self.top, "ho[me]")
        self.acme(directory=os.path.join(home, ".dotdiw", "trackers"))
        code, out = self.run_tool("tracker", "list", env={"HOME": home})
        self.assertEqual(code, 0, out)
        self.assertTrue(self.line_of("acme", out), out)

    def test_a_number_that_is_not_a_number_says_so(self):
        path = self.acme(
            (
                '"info": {"name": "acme", "version": "1.0.0", "interface": 3, "checkTarget": "scratch", "extras": []},',
                '"info": {"name": "acme", "version": "1.0.0", "interface": 3, "checkTarget": "scratch", "extras": [],'
                ' "interface": "1"},',
            ),
            directory=self.top,
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn("written for tracker interface '1'; this dotdiw supports interface 3", out)
        self.assertNotIn("DoorError", out)

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_an_old_tree_does_not_move_a_checkout_off_its_module(self):
        self.acme(*self.ELSEWHERE)
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        os.makedirs(os.path.join(self.repo, ".beads"))
        code, out = self.run_tool("create", "Named", env={"PATH": os.environ["PATH"]})
        self.assertEqual(code, 0, out)
        self.assertEqual(self.key("dotdiw.tracker"), "acme")
        self.assertNotIn("earlier version", out)

    @unittest.skipUnless(have_bd(), "needs the tracker")
    def test_the_check_of_beads_leaves_the_checkout_as_it_was(self):
        self.assertEqual(self.run_tool("init", "--tracker", "local")[0], 0)

        def what_git_holds():
            held = []
            for rel in ("config", os.path.join("info", "exclude")):
                with open(os.path.join(self.repo, ".git", rel), encoding="utf-8") as fh:
                    held.append(fh.read())
            return held

        before = what_git_holds()
        for env in ({}, {"GIT_DIR": os.path.join(self.repo, ".git")}):
            with self.subTest(env=env):
                code, out = self.run_tool(
                    "tracker", "check", "beads", env=dict(env, PATH=os.environ["PATH"])
                )
                self.assertEqual(code, 0, out)
                self.assertEqual(what_git_holds(), before)

    def test_a_failed_create_says_what_the_adapter_said(self):
        self.acme(
            (
                "def impl_create_item(request):\n",
                "def impl_create_item(request):\n"
                '    return {"status": "failed", "summary": "quota exceeded", "exitCode": 1}\n',
            )
        )
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        code, out = self.run_tool("create", "Named")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.strip(), "dotdiw: quota exceeded")

    def test_a_forward_extra_that_prints_nothing_is_shown(self):
        for answer, code_wanted, said in (
            (
                '{"status": "failed", "summary": "the forward failed", "exitCode": 4}',
                4,
                "the forward failed",
            ),
            ('{"status": "completed", "summary": "ok", "output": "its answer"}', 0, "its answer"),
        ):
            with self.subTest(said=said):
                self.acme(
                    ('"extras": {},', '"extras": {"forward": forward},'),
                    (
                        "TRACKER = {",
                        "def forward(request):\n    return %s\n\n\nTRACKER = {" % answer,
                    ),
                )
                self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
                code, out = self.run_tool("frobnicate")
                self.assertEqual(code, code_wanted, out)
                self.assertIn(said, out)

    def test_a_failure_of_use_is_said_once(self):
        self.acme(
            (
                "def impl_open_tracker(request):\n",
                'def impl_open_tracker(request):\n    raise RuntimeError("no")\n',
            )
        )
        code, out = self.run_tool("tracker", "use", "acme")
        self.assertEqual(code, 1, out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        self.assertIn("acme failed inside open-tracker", out)

    def test_the_conventions_are_checked_under_a_module_that_keeps_nothing(self):
        self.acme(*self.ELSEWHERE)
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        for rel in ("CLAUDE.md", "AGENTS.md"):
            os.unlink(os.path.join(self.repo, rel))
        code, out = self.run_tool("check")
        self.assertEqual(code, 1, out)
        self.assertIn("CLAUDE.md", out)

    def test_steps_from_work_are_refused_when_the_tracker_cannot_answer(self):
        code, out = self.run_tool("--tracker", "typo", "formula", "new", "Repeat it", "--from", "x")
        self.assertEqual(code, 1, out)
        self.assertIn("typo is not a tracker here", out)
        self.assertEqual(os.listdir(self.repo), [".git"])

    def test_a_name_only_asked_for_does_not_adopt_a_checkout(self):
        self.acme()
        self.run_tool("init", "--tracker", "typo")
        self.assertNotEqual(self.key(), "")
        code, out = self.run_tool("--tracker", "acme", "list")
        self.assertEqual(code, 1, out)
        self.assertIn("not adopted", out)

    def test_an_exit_code_git_would_read_as_zero_is_refused(self):
        path = self.acme(
            (
                'return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 1}',
                'return {"status": "failed", "summary": reason, "reason": reason, "exitCode": 256}',
            ),
            directory=self.top,
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn("a failed answer cannot exit 256", out)

    def test_a_second_init_keeps_the_prefix_under_local(self):
        self.assertEqual(self.run_tool("init", "--tracker", "local", "--prefix", "aaa")[0], 0)
        self.assertEqual(self.run_tool("init", "--prefix", "bbb")[0], 0)
        code, out = self.run_tool("create", "Named")
        self.assertEqual(code, 0, out)
        self.assertIn("Created issue: aaa-", out)

    def test_a_pour_hands_the_tracker_the_formula_and_no_file(self):
        """The tracker is handed the steps, the description and the means to
        prove that the pour read, and no path; nothing is written under the
        workspace for it."""
        self.acme(
            (
                "def impl_pour_steps(request):\n",
                "def impl_pour_steps(request):\n"
                "    with open(os.path.join(request['root'], '.asked.json'), 'w') as fh:\n"
                "        json.dump(sorted(k for k, v in request.items() if v is not None), fh)\n",
            )
        )
        self.assertEqual(self.run_tool("init", "--tracker", "acme")[0], 0)
        with open(os.path.join(self.repo, "ship.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(PROVED)
        code, out = self.run_tool("formula", "pour", "mol-ship-the-package")
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.repo, ".asked.json"), encoding="utf-8") as fh:
            asked = json.load(fh)
        self.assertIn("steps", asked)
        self.assertIn("verifyUsing", asked)
        self.assertNotIn("path", asked)
        ws = os.path.join(self.home, ".dotdiw", self.key())
        self.assertFalse(os.path.exists(os.path.join(ws, "pours")))

    def test_a_choice_that_could_not_be_pinned_is_not_said_to_be(self):
        self.assertEqual(self.run_tool("init", "--tracker", "local")[0], 0)
        subprocess.run(["git", "config", "--unset", "dotdiw.tracker"], cwd=self.repo)
        lock = os.path.join(self.repo, ".git", "config.lock")
        with open(lock, "w", encoding="utf-8"):
            pass
        code, out = self.run_tool("init")
        os.unlink(lock)
        self.assertNotIn("is written in .git/config", out)
        code, out = self.run_tool("init")
        self.assertEqual(code, 0, out)
        self.assertIn("is written in .git/config", out)
        code, out = self.run_tool("list")
        self.assertEqual(code, 0, out)

    def test_formula_new_with_a_flag_and_nothing_after_it_is_refused(self):
        self.assertEqual(self.run_tool("init")[0], 0)
        for flag in ("--at", "--from"):
            with self.subTest(flag=flag):
                code, out = self.run_tool("formula", "new", "Repeat it", flag)
                self.assertEqual(code, 2, out)
                self.assertNotIn("repeat-it.formula.toml", os.listdir(self.repo))

    def test_a_priority_that_is_no_number_is_one_line(self):
        self.assertEqual(self.run_tool("init", "--prefix", "w")[0], 0)
        code, out = self.run_tool("create", "Named")
        ident = group1(r"Created issue: (\S+)", out)
        code, out = self.run_tool("update", ident, "-p", "high")
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        self.assertIn("high", out)

    def test_a_failed_close_does_not_read_as_a_failed_list(self):
        path = self.acme(
            (
                "def impl_close_item(request):\n",
                'def impl_close_item(request):\n    return _no("nope")\n',
            ),
            directory=self.top,
        )
        code, out = self.run_tool("tracker", "check", path)
        self.assertEqual(code, 1, out)
        self.assertIn(
            "FAIL  operation.list-items: cannot be tried until operation.close-item passes", out
        )

    def test_the_scenario_holds_what_the_other_commands_rely_on(self):
        """Ten of ten is what compatible means, so what `migrate`, `list` and
        `mol pour` rely on is in it."""
        for why, old, new, operation in (
            (
                "a need already there is refused",
                '    if needs not in data["items"][ident]["needs"]:\n',
                '    if needs in data["items"][ident]["needs"]:\n'
                '        return _no("cycle")\n'
                '    if needs not in data["items"][ident]["needs"]:\n',
                "add-need",
            ),
            (
                "scope is read only under a parent",
                '    if request.get("scope") != "all":\n',
                '    if request.get("scope") != "all" and request.get("parent"):\n',
                "list-items",
            ),
            (
                "parent is read only with scope all",
                '    if request.get("parent"):\n'
                '        items = [i for i in items if i["parent"] == request["parent"]]\n',
                '    if request.get("parent") and request.get("scope") == "all":\n'
                '        items = [i for i in items if i["parent"] == request["parent"]]\n',
                "list-items",
            ),
            (
                "limit is ignored",
                'return _ok(items=items[: request.get("limit") or len(items)])',
                "return _ok(items=items)",
                "list-items",
            ),
            (
                "any status is taken",
                '    if request.get("status") == "closed":\n'
                '        return _no("close-through-update")\n'
                '    if request.get("status") not in (None, "open", "in_progress", "blocked"):\n'
                '        return _no("bad-status")\n',
                '    if request.get("status") == "closed":\n'
                '        return _no("close-through-update")\n',
                "update-item",
            ),
            (
                "a poured root is not of kind root",
                'kind="root", ',
                "",
                "pour-steps",
            ),
            (
                "a root forgets the means to prove its run",
                'verifyUsing=request.get("verifyUsing")',
                "verifyUsing=None",
                "pour-steps",
            ),
            (
                "a step is not of kind task",
                'made = {s["id"]: _make(data, s["title"], parent=root["id"]) for s in steps}',
                'made = {s["id"]: _make(data, s["title"], parent=root["id"], kind="root")'
                " for s in steps}",
                "pour-steps",
            ),
            (
                "a created item forgets the means a move carries",
                'verifyUsing=list(request.get("verifyUsing") or []) or None',
                "verifyUsing=None",
                "create-item",
            ),
            (
                "a created item is a root",
                '"kind": "task", ',
                '"kind": "root", ',
                "create-item",
            ),
        ):
            with self.subTest(why=why):
                path = self.acme((old, new), directory=self.top)
                code, out = self.run_tool("tracker", "check", path)
                self.assertEqual(code, 1, out)
                self.assertIn("FAIL  operation.%s" % operation, out)


class TheUpgradePin(unittest.TestCase):
    """A workspace adopted before there was a choice of tracker holds one
    adapter's store and no choice: every command but init says so, and init
    writes the choice once and says so once."""

    def test_the_choice_is_written_once_and_said_once(self):
        repo = Repo(tracker=None)
        self.addCleanup(repo.close)
        code, out = repo.dotdiw("init", "--tracker", "beads", "--prefix", "w")
        self.assertEqual(code, 0, out)
        self.assertEqual(repo.config("dotdiw.tracker"), "beads")
        repo.git("config", "--local", "--unset", "dotdiw.tracker")
        self.assertEqual(repo.config("dotdiw.tracker"), "")
        code, out = repo.dotdiw("create", "Work from before")
        self.assertEqual(code, 1, out)
        self.assertIn("no tracker is chosen for this checkout", out)
        self.assertEqual(repo.config("dotdiw.tracker"), "")
        code, out = repo.dotdiw("init")
        self.assertEqual(code, 0, out)
        self.assertIn("dotdiw.tracker = beads is written in .git/config", out)
        code, out = repo.dotdiw("create", "Work from before")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"Created issue: w-[a-z0-9]{3,}")
        # A quiet create, as the tracker underneath allows, still names the
        # work in the record where it can and exits 0 where it cannot.
        code, out = repo.dotdiw("create", "Quietly", "-q")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"^\u2713 Created issue: w-[a-z0-9]{3,} \u2014 Quietly\n")
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

    def __init__(self, script, learn_tracker="", learn_verify="", learn_providers=""):
        self.script = script
        self.learn_tracker = learn_tracker
        self.learn_verify = learn_verify
        self.learn_providers = learn_providers
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
        text = text.replace(self.learn_verify, "")
        text = text.replace(self.learn_providers, "")
        # Since 3.0.0 the header of formula list counts the formulas without
        # saying where they are kept; each formula's own lines say that.
        text = re.sub(r"(?m)^(\d+ formulas?) in this repo:$", r"\1:", text)
        # And the three hints for running a formula say formula pour, where they
        # said mol pour; those three are read as the same.
        text = re.sub(
            r"(Run it: |Run one: |Run a formula:  )dotdiw mol pour\b",
            r"\1dotdiw formula pour",
            text,
        )
        # So is the opening of learn, which now claims only the tracker's own name.
        text = text.replace(
            "adds the fourth and puts all of them under one name, so you never type\n"
            "anything else.\n",
            "adds the fourth and puts the tracker behind one command, so you never type the\n"
            "tracker's own name.\n",
        )
        return text.replace("\u2514\u2500\u2500", "\u251c\u2500\u2500")


# The seventeen commands a worker types in a day, in the order a day goes,
# and two more beyond them. Where an output lists items by their random ids,
# its lines are compared as a set.
SEVENTEEN = [
    ("init --prefix w", "own"),
    ("init",),
    ("--version",),
    ("learn",),
    ("check",),
    ("formula list",),
    ("formula show mol-release-through-tap",),
    ("create", "Release v0.3.0 through the tap"),
    ("create", "Fix the login redirect", "-d", "The redirect after login loops."),
    ("mol pour mol-release-through-tap", "own"),
    ("list --all", "unordered", "own"),
    ("show {root}", "unordered", "own"),
    ("ready", "unordered", "own"),
    ("close {step1}", "own"),
    ("doctor",),
    ("remember", "Every release: first bump the formula, then install cleanly, then announce"),
    ("dep tree {root}", "unordered", "own"),
]
BEYOND = [
    ("frobnicate --now",),
    ("list", "clone"),
    ("formula new", "Rotate the signing keys", "--from", "{work1}"),
]


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheBytesUnderBeads(unittest.TestCase):
    """Under the beads adapter, the seventeen commands print what an earlier
    version printed, byte for byte once the random parts are named: the promise
    that nothing a worker sees changes with the tracker behind its door. Since
    3.0.0 the adoption and a pour under beads are dotdiw's own, as under every
    tracker, so init, the pour and the commands that read the run it made,
    marked own, are run on both and not compared."""

    def test_the_seventeen_commands_print_what_0_5_0_printed(self):
        self.prints_what("v0.5.0")

    def test_the_seventeen_commands_print_what_0_6_0_printed(self):
        self.prints_what("v0.6.0")

    def prints_what(self, tag):
        before = dotdiw_at(tag)
        if before is None:
            self.skipTest("%s is not in this clone's history" % tag)
        had = getattr(
            load_module("dotdiw_at_" + tag.replace(".", "_"), before), "LEARN_TRACKER", ""
        )
        now = load_module("dotdiw_learn_tracker")
        twins = [
            Twin(before, learn_tracker=had),
            Twin(
                DOTDIW,
                learn_tracker=now.LEARN_TRACKER,
                learn_verify=now.LEARN_VERIFY,
                learn_providers=now.LEARN_PROVIDERS,
            ),
        ]
        for t in twins:
            self.addCleanup(t.close)
        differences = []
        for entry in SEVENTEEN + BEYOND:
            words, flags = entry[0].split(), [e for e in entry[1:]]
            args = words + [f for f in flags if f not in ("unordered", "clone", "own")]
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
            if "own" in flags:
                continue
            if got[0] != got[1]:
                differences.append(
                    "%s:\n--- %s ---\n%s%s\n--- now ---\n%s%s"
                    % (" ".join(args), tag, got[0][1], got[0][2], got[1][1], got[1][2])
                )
        self.assertEqual(differences, [], "\n\n".join(differences))


PROVIDED = """formula = "mol-ship-a-release"
description = "Ship a release of the service: tag it, build it, publish it to the registry."
examples = ["Ship the 4.0 release", "Release the service", "Publish the new version"]
version = 1
type = "workflow"

[[steps]]
id = "tag"
title = "Tag the release"

[[steps]]
id = "publish"
title = "Publish it"
needs = ["tag"]
"""

HALF_A_PROVIDER = """PROVIDER = {
    "info": {"name": "half", "version": "0.1", "interface": 2},
    "operations": {"describe": lambda r: {"answers": ["list"]}, "list": lambda r: {"formulas": []}},
}
"""

SHY_PROVIDER = """def show(request):
    return {}


PROVIDER = {
    "info": {"name": "shy", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list"]},
        "list": lambda r: {"formulas": []},
        "show": show,
    },
}
"""

COUNTING_PROVIDER = """import os

CALLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calls.log")


def note(what):
    with open(CALLS, "a", encoding="utf-8") as fh:
        fh.write(what + " ")


def listing(request):
    note("list")
    return {"formulas": [{"id": "mol-ship", "description": "Ship it.", "examples": []}]}


def show(request):
    note("show")
    return {
        "formula": {
            "description": "Ship a release of the service: tag it, build it, publish it.",
            "steps": [{"id": "tag", "title": "Tag it"}],
        }
    }


PROVIDER = {
    "info": {"name": "counting", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": listing,
        "show": show,
    },
}
"""

HOSTILE_PROVIDER = """import os

TARGET = os.environ.get("DOTDIW_TEST_TARGET", "")


def listing(request):
    return {
        "formulas": [
            {"id": TARGET, "description": "Overwrite a formula in the checkout.", "examples": []},
            {
                "id": "mol-$(touch PWNED)",
                "description": "Ship a release of the service: tag it, build it, publish it.",
                "examples": ["Ship the 4.0 release"],
            },
        ]
    }


def show(request):
    return {"formula": {"description": "Written by a provider.", "steps": []}}


PROVIDER = {
    "info": {"name": "hostile", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": listing,
        "show": show,
    },
}
"""

MALFORMED_PROVIDER = """PROVIDER = {
    "info": {"name": "malformed", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": lambda r: {
            "formulas": [
                {
                    "id": "mol-good",
                    "description": "Ship a release of the service: tag it, build it, publish it.",
                    "examples": ["Ship the 4.0 release"],
                },
                {"id": "mol-broken", "description": "Broken.", "examples": 42},
            ]
        },
        "show": lambda r: {},
    },
}
"""

SLOW_PROVIDER = """import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def describe(request):
    open(os.path.join(HERE, "waiting"), "w").close()
    for _ in range(1200):
        if os.path.exists(os.path.join(HERE, "go")):
            break
        time.sleep(0.05)
    return {"answers": ["list", "show"]}


PROVIDER = {
    "info": {"name": "slow", "version": "0.1", "interface": 2},
    "operations": {"describe": describe, "list": lambda r: {"formulas": []}, "show": lambda r: {}},
}
"""

QUOTED = """formula = "mol-keys-$(touch PWNED)"
description = "Rotate the signing keys: revoke the old pair, generate a new one, and publish it. Use when a key is due or exposed."
examples = ["Rotate the signing keys", "Replace the exposed key", "Generate a new signing key"]
version = 1
type = "workflow"

[[steps]]
id = "revoke"
title = "Revoke the old pair"
"""

CASED_PROVIDER = """def show(request):
    return {
        "formula": {
            "description": "The formula listed as %s." % request["id"],
            "steps": [{"id": "one", "title": "One"}],
        }
    }


PROVIDER = {
    "info": {"name": "cased", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": lambda r: {
            "formulas": [
                {"id": "mol-ship", "description": "Lower.", "examples": []},
                {"id": "Mol-Ship", "description": "Upper.", "examples": []},
            ]
        },
        "show": show,
    },
}
"""

GARBLED_PROVIDER = """PROVIDER = {
    "info": {"name": "garbled", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": lambda r: {
            "formulas": [{"id": "mol-ship", "description": "Ship it.", "examples": []}]
        },
        "show": lambda r: {"formula": {"description": "Ship it.", "steps": [{"id": "tag"}]}},
    },
}
"""

FAILING_PROVIDER = """def fail(request):
    raise RuntimeError("the endpoint is down")


PROVIDER = {
    "info": {"name": "failing", "version": "0.1", "interface": 2},
    "operations": {
        "describe": lambda r: {"answers": ["list", "show"]},
        "list": fail,
        "show": fail,
    },
}
"""


class TheFormulaProviders(unittest.TestCase):
    """Local storage is the file system, and a formula management provider,
    registered under a name, serves its formulas with that name as their
    suffix: they surface, list, show and pour as local ones do."""

    def setUp(self):
        self.repo = Repo(tracker=None)
        self.addCleanup(self.repo.close)
        self.env = dict(self.repo.env, PATH="/usr/bin:/bin")
        self.repo.write("release-through-tap.formula.toml", FORMULA_A)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "the project as it stands")
        self.kept = tempfile.mkdtemp(prefix="dotdiw-provider-")
        self.addCleanup(shutil.rmtree, self.kept, True)
        with open(os.path.join(self.kept, "ship.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(PROVIDED)

    def dotdiw(self, *args):
        return self.repo.dotdiw(*args, env=self.env)

    def adopted(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)

    def registered(self):
        code, out = self.dotdiw(
            "formula", "provider", "register", "acme", "directory", "--at", self.kept
        )
        self.assertEqual(code, 0, out)
        self.assertIn("Registered acme", out)

    def module(self, name, text):
        directory = os.path.join(self.repo.home, ".dotdiw", "formula-providers")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, name + ".py"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_an_uncommitted_formula_is_found_and_named_as_unshared(self):
        self.adopted()
        self.repo.write(
            "deploy.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-deploy")
        )
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-deploy", out)
        code, out = self.dotdiw("check")
        self.assertIn("deploy.formula.toml", out)
        self.assertIn("not committed, so nobody else can see it", out)

    def test_local_storage_leaves_out_dot_directories_and_symbolic_links(self):
        self.adopted()
        self.repo.write(
            ".hidden/deploy.formula.toml",
            FORMULA_A.replace("mol-release-through-tap", "mol-hidden"),
        )
        os.symlink(
            os.path.join(self.kept, "ship.formula.toml"),
            os.path.join(self.repo.path, "linked.formula.toml"),
        )
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-release-through-tap", out)
        self.assertNotIn("mol-hidden", out)
        self.assertNotIn("mol-ship-a-release", out)

    def test_a_list_of_local_formulas_has_the_one_header(self):
        self.adopted()
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^1 formula:$")
        self.assertNotIn("in this repo", out)

    def test_a_provider_formula_carries_its_suffix_and_says_where_it_comes_from(self):
        self.adopted()
        self.registered()
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-ship-a-release-acme", out)
        self.assertIn("from the acme provider", out)
        self.assertIn("mol-release-through-tap", out)
        self.assertRegex(out, r"(?m)^2 formulas:$")
        code, out = self.dotdiw("formula", "show", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["formula"], "mol-ship-a-release-acme")
        code, out = self.dotdiw("formula", "list", "--json")
        self.assertEqual(code, 0, out)
        held = {f["formula"]: f for f in json.loads(out)}
        self.assertEqual(held["mol-ship-a-release-acme"]["provider"], "acme")
        self.assertNotIn("provider", held["mol-release-through-tap"])

    def test_a_provider_formula_surfaces_when_work_starts_and_pours(self):
        self.adopted()
        self.registered()
        code, out = self.dotdiw("create", "Ship the 4.0 release")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-ship-a-release-acme", out)
        code, out = self.dotdiw("formula", "pour", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol: created 3 issues", out)
        root = group1("Root issue: (\\S+)", out)
        code, out = self.dotdiw("show", root, "--json")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-ship-a-release-acme", out)

    def test_registration_refuses_in_one_line_and_registers_nothing(self):
        self.adopted()
        self.module("half", HALF_A_PROVIDER)
        self.module("shy", SHY_PROVIDER)
        for args, said in (
            (("a-b", "directory"), "letters and digits"),
            (("zed", "nosuch"), "No formula management provider module named nosuch"),
            (("zed", "half"), "not a formula management provider"),
            (("zed", "shy"), "a formula management provider answers list and show"),
        ):
            with self.subTest(args=args):
                code, out = self.dotdiw("formula", "provider", "register", *args)
                self.assertEqual(code, 1, out)
                self.assertIn(said, out)
        code, out = self.dotdiw("formula", "provider", "list")
        self.assertIn("No formula management provider is registered.", out)
        self.registered()
        code, out = self.dotdiw(
            "formula", "provider", "register", "acme", "directory", "--at", self.kept
        )
        self.assertEqual(code, 1, out)
        self.assertIn("already registered as acme", out)

    def test_registration_waits_for_a_clashing_local_formula_to_migrate(self):
        self.adopted()
        self.repo.write(
            "tap.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-tap-acme")
        )
        code, out = self.dotdiw(
            "formula", "provider", "register", "acme", "directory", "--at", self.kept
        )
        self.assertEqual(code, 1, out)
        self.assertIn("tap.formula.toml", out)
        code, out = self.dotdiw("formula", "provider", "list")
        self.assertIn("No formula management provider is registered.", out)

    def test_check_names_a_local_formula_that_reads_like_a_provider_formula(self):
        self.adopted()
        self.registered()
        self.repo.write(
            "tap.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-tap-acme")
        )
        code, out = self.dotdiw("check")
        self.assertIn("reads like a formula of the acme provider", out)

    def test_a_failing_provider_is_left_out_in_one_line(self):
        self.adopted()
        self.module("failing", FAILING_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "down", "failing")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        self.assertIn("mol-release-through-tap", out)
        left = [line for line in out.splitlines() if "left out of this run" in line]
        self.assertEqual(len(left), 1, out)
        self.assertIn("the endpoint is down", left[0])

    def test_each_provider_is_asked_once_in_a_run(self):
        """One list in a run, and a formula's text only when it is shown or
        poured: a lookup reads one formula, never the provider's catalog."""
        self.adopted()
        self.module("counting", COUNTING_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "cnt", "counting")
        self.assertEqual(code, 0, out)
        calls = os.path.join(self.repo.home, ".dotdiw", "formula-providers", "calls.log")
        for args, asked in (
            (("create", "Ship the 4.0 release"), ["list"]),
            (("formula", "show", "mol-ship-cnt"), ["list", "show"]),
            (("formula", "pour", "mol-ship-cnt"), ["list", "show"]),
        ):
            with self.subTest(args=args):
                if os.path.exists(calls):
                    os.remove(calls)
                code, out = self.dotdiw(*args)
                self.assertEqual(code, 0, out)
                if args[1] != "pour":
                    self.assertIn("mol-ship-cnt", out)
                with open(calls, encoding="utf-8") as fh:
                    self.assertEqual(sorted(fh.read().split()), asked)

    def test_learn_names_the_provider_commands(self):
        code, out = self.dotdiw("learn")
        self.assertEqual(code, 0, out)
        for line in (
            "dotdiw formula provider register <name> <module> [--at <location>]",
            "dotdiw formula provider list",
            "dotdiw formula provider remove <name>",
        ):
            self.assertIn(line, out)

    def test_the_conventions_say_where_an_uncommitted_formula_is_found(self):
        self.adopted()
        with open(os.path.join(self.repo.path, "CLAUDE.md"), encoding="utf-8") as fh:
            said = " ".join(fh.read().split())
        self.assertIn(
            "A formula you have not committed is one only you hold: it is found on your "
            "file system alone, nobody else's `create` reaches it, and `check` says so.",
            said,
        )

    def registry(self):
        with open(
            os.path.join(self.repo.home, ".dotdiw", "formula-providers.json"), encoding="utf-8"
        ) as fh:
            return json.load(fh)

    def test_a_provider_id_outside_its_shape_leaves_the_provider_out(self):
        """An id is the provider's text: one that is a path, or that a shell
        reads, never names a file and never reaches a printed command."""
        self.adopted()
        victim = FORMULA_A.replace("mol-release-through-tap", "mol-victim")
        self.repo.write("victim-hostile.formula.toml", victim)
        self.repo.git("add", "-A")
        self.repo.git("commit", "-qm", "a formula a provider must never touch")
        self.module("hostile", HOSTILE_PROVIDER)
        self.env["DOTDIW_TEST_TARGET"] = os.path.join(self.repo.path, "victim")
        code, out = self.dotdiw("formula", "provider", "register", "hostile", "hostile")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("formula", "list")
        self.assertEqual(code, 0, out)
        left = [line for line in out.splitlines() if "left out of this run" in line]
        self.assertEqual(len(left), 1, out)
        self.assertIn("not an id of letters, digits", left[0])
        with open(
            os.path.join(self.repo.path, "victim-hostile.formula.toml"), encoding="utf-8"
        ) as fh:
            self.assertEqual(fh.read(), victim)
        code, out = self.dotdiw("create", "Ship the 4.0 release")
        self.assertEqual(code, 0, out)
        self.assertNotIn("$(touch PWNED)", out)
        self.assertEqual(glob.glob(os.path.join(self.repo.path, "**", "PWNED"), recursive=True), [])

    def test_the_command_printed_to_pour_quotes_the_id(self):
        self.adopted()
        self.repo.write("ops/keys.formula.toml", QUOTED)
        code, out = self.dotdiw("create", "Rotate the signing keys")
        self.assertEqual(code, 0, out)
        line = next(x for x in out.splitlines() if "Run it:" in x)
        self.assertEqual(shlex.split(line.split("Run it:", 1)[1])[-1], "mol-keys-$(touch PWNED)")
        self.assertIn("formula pour 'mol-keys-$(touch PWNED)'", line)

    def test_an_exact_id_comes_before_a_file_name(self):
        """A file name is an alias: a local file named like a provider's
        suffixed id, declaring an id of its own, never shadows the provider."""
        self.adopted()
        self.repo.write(
            "mol-ship-a-release-acme.formula.toml",
            FORMULA_A.replace("mol-release-through-tap", "mol-calibrate"),
        )
        self.registered()
        code, out = self.dotdiw("formula", "show", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["formula"], "mol-ship-a-release-acme")
        self.assertIn("Publish it", out)
        code, out = self.dotdiw("formula", "pour", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol: created 3 issues", out)

    def test_two_formulas_under_one_id_are_refused(self):
        self.adopted()
        twin = FORMULA_A.replace("mol-release-through-tap", "mol-twin")
        self.repo.write("one/twin.formula.toml", twin)
        self.repo.write("two/twin.formula.toml", twin)
        said = (
            "dotdiw: mol-twin names more than one formula: "
            "one/twin.formula.toml, two/twin.formula.toml."
        )
        for args in (("formula", "show", "mol-twin"), ("formula", "pour", "mol-twin")):
            with self.subTest(args=args):
                code, out = self.dotdiw(*args)
                self.assertEqual(code, 1, out)
                self.assertEqual(out.strip(), said)

    def test_a_name_differing_only_in_case_is_taken(self):
        self.adopted()
        self.registered()
        code, out = self.dotdiw(
            "formula", "provider", "register", "Acme", "directory", "--at", self.kept
        )
        self.assertEqual(code, 1, out)
        self.assertIn("already registered as acme", out)

    def test_a_removed_providers_formula_is_never_handed_to_the_tracker(self):
        self.adopted()
        self.registered()
        code, out = self.dotdiw("formula", "pour", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("formula", "provider", "remove", "acme")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.registry()["removed"], ["acme"])
        code, out = self.dotdiw("formula", "pour", "mol-ship-a-release-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula: the acme provider is removed", out)
        self.registered()
        self.assertEqual(self.registry()["removed"], [])
        code, out = self.dotdiw("formula", "pour", "mol-gone-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula the acme provider serves", out)

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_under_beads_a_removed_providers_formula_pours_no_copy(self):
        repo = Repo()
        self.addCleanup(repo.close)
        env = dict(repo.env, PATH=os.environ.get("PATH", "/usr/bin:/bin"))
        self.assertEqual(repo.dotdiw("init", "--prefix", "w", env=env)[0], 0)
        code, out = repo.dotdiw(
            "formula", "provider", "register", "acme", "directory", "--at", self.kept, env=env
        )
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("formula", "pour", "mol-ship-a-release-acme", env=env)
        self.assertEqual(code, 0, out)
        code, out = repo.dotdiw("formula", "provider", "remove", "acme", env=env)
        self.assertEqual(code, 0, out)
        code, listed = repo.dotdiw("list", "--all", "--json", env=env)
        before = len(json.loads(listed))
        code, out = repo.dotdiw("formula", "pour", "mol-ship-a-release-acme", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("the acme provider is removed", out)
        code, listed = repo.dotdiw("list", "--all", "--json", env=env)
        self.assertEqual(len(json.loads(listed)), before)

    def test_one_run_forgets_its_index_when_the_registry_changes(self):
        """Through the operations in one process: what a registration or a
        removal changes is in the very next answer, and a name registered again
        is listed from where it points now."""
        self.adopted()
        module, root = self.in_process("dotdiw_one_run")

        def listed():
            out = module.invoke("operation.list-formulas", {"root": root})
            return {f["formulaRef"] for f in out["formulas"]}

        self.assertNotIn("mol-ship-a-release-acme", listed())
        done = module.invoke(
            "operation.register-provider",
            {"root": root, "name": "acme", "module": "directory", "location": self.kept},
        )
        self.assertEqual(done["status"], "completed", done)
        self.assertIn("mol-ship-a-release-acme", listed())
        self.assertEqual(
            module.invoke("operation.remove-provider", {"name": "acme"})["status"], "completed"
        )
        self.assertNotIn("mol-ship-a-release-acme", listed())
        elsewhere = tempfile.mkdtemp(prefix="dotdiw-provider-")
        self.addCleanup(shutil.rmtree, elsewhere, True)
        with open(os.path.join(elsewhere, "calibrate.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(PROVIDED.replace('"mol-ship-a-release"', '"mol-calibrate"'))
        done = module.invoke(
            "operation.register-provider",
            {"root": root, "name": "acme", "module": "directory", "location": elsewhere},
        )
        self.assertEqual(done["status"], "completed", done)
        now = listed()
        self.assertIn("mol-calibrate-acme", now)
        self.assertNotIn("mol-ship-a-release-acme", now)

    def test_a_malformed_list_leaves_the_provider_out_and_create_succeeds(self):
        self.adopted()
        self.module("malformed", MALFORMED_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "bad", "malformed")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("create", "Ship the 4.0 release")
        self.assertEqual(code, 0, out)
        left = [line for line in out.splitlines() if "left out of this run" in line]
        self.assertEqual(len(left), 1, out)
        self.assertIn("the examples of mol-broken are not a list of text", left[0])
        self.assertNotIn("mol-good-bad", out)
        code, listed = self.dotdiw("list", "--all", "--json")
        self.assertEqual(
            [r["title"] for r in json.loads(listed)].count("Ship the 4.0 release"), 1, listed
        )

    def test_check_names_a_formula_head_does_not_hold(self):
        self.adopted()
        self.repo.write(".gitignore", "ignored/\n")
        self.repo.git("add", ".gitignore")
        self.repo.git("commit", "-qm", "ignore a directory")
        self.repo.write(
            "ignored/deploy.formula.toml",
            FORMULA_A.replace("mol-release-through-tap", "mol-ignored"),
        )
        self.repo.write(
            "staged.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-staged")
        )
        self.repo.git("add", "staged.formula.toml")
        code, out = self.dotdiw("check")
        for rel in ("ignored/deploy.formula.toml", "staged.formula.toml"):
            self.assertRegex(out, r"%s\s+not committed, so nobody else can see it" % re.escape(rel))
        self.assertNotIn("release-through-tap.formula.toml  not committed", out)

    def test_a_registration_waits_for_the_registry_lock(self):
        self.adopted()
        lock = os.path.join(self.repo.home, ".dotdiw", "formula-providers.lock")
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        with open(lock, "a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            p = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    DOTDIW,
                    "formula",
                    "provider",
                    "register",
                    "acme",
                    "directory",
                    "--at",
                    self.kept,
                ],
                cwd=self.repo.path,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.addCleanup(p.kill)
            time.sleep(2)
            self.assertIsNone(p.poll())
            self.assertFalse(
                os.path.exists(os.path.join(self.repo.home, ".dotdiw", "formula-providers.json"))
            )
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        out, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out)
        self.assertIn("acme", self.registry()["providers"])
        with open(lock, "a", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            q = subprocess.Popen(
                [sys.executable, "-I", DOTDIW, "formula", "provider", "remove", "acme"],
                cwd=self.repo.path,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.addCleanup(q.kill)
            time.sleep(2)
            self.assertIsNone(q.poll())
            self.assertIn("acme", self.registry()["providers"])
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        out, _ = q.communicate(timeout=60)
        self.assertEqual(q.returncode, 0, out)
        self.assertNotIn("acme", self.registry()["providers"])

    def test_two_registrations_at_once_keep_both(self):
        """A registration reads the registry it writes under its lock, so one
        that began first and finishes last keeps what the other wrote."""
        self.adopted()
        self.module("slow", SLOW_PROVIDER)
        here = os.path.join(self.repo.home, ".dotdiw", "formula-providers")
        p = subprocess.Popen(
            [sys.executable, "-I", DOTDIW, "formula", "provider", "register", "late", "slow"],
            cwd=self.repo.path,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.addCleanup(p.kill)
        for _ in range(600):
            if os.path.exists(os.path.join(here, "waiting")):
                break
            time.sleep(0.05)
        self.registered()
        open(os.path.join(here, "go"), "w").close()
        out, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out)
        self.assertEqual(sorted(self.registry()["providers"]), ["acme", "late"])

    def test_a_directory_store_is_resolved_at_registration(self):
        self.adopted()
        os.makedirs(os.path.join(self.repo.path, "sub"))
        relative = os.path.relpath(self.kept, self.repo.path)
        code, out = self.dotdiw(
            "formula", "provider", "register", "acme", "directory", "--at", relative
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(
            self.registry()["providers"]["acme"]["location"], os.path.realpath(self.kept)
        )
        code, out = self.repo.dotdiw(
            "formula", "list", cwd=os.path.join(self.repo.path, "sub"), env=self.env
        )
        self.assertEqual(code, 0, out)
        self.assertIn("mol-ship-a-release-acme", out)
        gone = self.kept + "-moved"
        os.rename(self.kept, gone)
        self.addCleanup(shutil.rmtree, gone, True)
        code, out = self.dotdiw("formula", "list")
        left = [line for line in out.splitlines() if "left out of this run" in line]
        self.assertEqual(len(left), 1, out)
        self.assertIn("no directory at", left[0])
        code, out = self.dotdiw(
            "formula", "provider", "register", "zed", "directory", "--at", self.kept
        )
        self.assertEqual(code, 1, out)
        self.assertIn("no directory at", out)

    def test_a_registration_that_cannot_answer_is_listed(self):
        self.adopted()
        self.module("counting", COUNTING_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "cnt", "counting")
        self.assertEqual(code, 0, out)
        os.remove(os.path.join(self.repo.home, ".dotdiw", "formula-providers", "counting.py"))
        code, out = self.dotdiw("formula", "provider", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(
            out,
            r"cnt\s+counting\s+unavailable: No formula management provider module named counting",
        )

    def test_local_storage_reads_regular_files_alone(self):
        self.adopted()
        os.mkfifo(os.path.join(self.repo.path, "pipe.formula.toml"))
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "formula", "list"],
            cwd=self.repo.path,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("mol-release-through-tap", p.stdout)

    def in_process(self, name):
        """dotdiw as a module in this process, under the repo's home."""
        home = os.environ.get("HOME")
        os.environ["HOME"] = self.repo.home
        self.addCleanup(os.environ.__setitem__, "HOME", home or "")
        return load_module(name), os.path.realpath(self.repo.path)

    def test_a_rebuilt_index_asks_no_provider_again(self):
        """An index built for a lookup and built again with the project's text
        asks each provider for its list once in the run."""
        self.adopted()
        self.module("counting", COUNTING_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "cnt", "counting")
        self.assertEqual(code, 0, out)
        calls = os.path.join(self.repo.home, ".dotdiw", "formula-providers", "calls.log")
        if os.path.exists(calls):
            os.remove(calls)
        module, root = self.in_process("dotdiw_rebuilt")
        found = module.invoke("operation.resolve-formula", {"root": root, "ident": "mol-ship-cnt"})
        self.assertEqual(found["status"], "completed", found)
        matched = module.invoke(
            "operation.match-formulas",
            {"root": root, "title": "Ship the 4.0 release", "surface": False},
        )
        self.assertEqual(matched["status"], "completed", matched)
        with open(calls, encoding="utf-8") as fh:
            self.assertEqual(sorted(fh.read().split()), ["list", "show"])

    def test_a_provider_formula_is_data_and_nothing_is_written_for_it(self):
        """show answers the formula as data; formula show prints it as a
        .formula.json file would hold it, a pour pours its steps, and nothing
        is written under the workspace for it."""
        self.adopted()
        self.registered()
        code, out = self.dotdiw("formula", "show", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertEqual(
            json.loads(out),
            {
                "formula": "mol-ship-a-release-acme",
                "description": "Ship a release of the service: tag it, build it, publish it to "
                "the registry.",
                "verify-using": [],
                "steps": [
                    {"id": "tag", "title": "Tag the release", "needs": []},
                    {"id": "publish", "title": "Publish it", "needs": ["tag"]},
                ],
            },
        )
        code, out = self.dotdiw("formula", "pour", "mol-ship-a-release-acme")
        self.assertEqual(code, 0, out)
        self.assertIn("Poured mol: created 3 issues", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo.workspace(), "formula-providers")))

    def test_ids_that_differ_in_case_are_their_own_formulas(self):
        self.adopted()
        self.module("cased", CASED_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "cs", "cased")
        self.assertEqual(code, 0, out)
        module, root = self.in_process("dotdiw_cased")
        for ident, listed in (("mol-ship-cs", "mol-ship"), ("Mol-Ship-cs", "Mol-Ship")):
            found = module.invoke("operation.resolve-formula", {"root": root, "ident": ident})
            self.assertEqual(found["status"], "completed", found)
            self.assertEqual(found["formula"]["description"], "The formula listed as %s." % listed)

    def test_a_provider_written_for_another_interface_is_refused(self):
        self.adopted()
        self.module("older", SHY_PROVIDER.replace(', "interface": 2}', "}"))
        code, out = self.dotdiw("formula", "provider", "register", "old", "older")
        self.assertEqual(code, 1, out)
        self.assertIn("is not a formula management provider of interface 2", out)
        code, out = self.dotdiw("formula", "provider", "list")
        self.assertNotIn("old", out.split())

    def test_the_lookup_answers_a_providers_formula_as_resolve_does(self):
        """find-a-held-procedure, asked to resolve a provider's formula, answers
        it as data, as resolve-formula answered it."""
        self.adopted()
        self.registered()
        module, root = self.in_process("dotdiw_lookup")
        found = module.invoke(
            "operation.find-a-held-procedure",
            {"root": root, "ask": "resolve", "ident": "mol-ship-a-release-acme"},
        )
        self.assertEqual(found["status"], "completed", found)
        self.assertEqual(found["formulaRef"], "mol-ship-a-release-acme")
        self.assertEqual([s["id"] for s in found["formula"]["steps"]], ["tag", "publish"])

    def test_nothing_a_provider_gives_is_replaced_by_a_default(self):
        """A field given outside its shape is refused, however falsy; only the
        means to prove and a step's needs may be left out."""
        module, _ = self.in_process("dotdiw_shape")
        step = {"id": "tag", "title": "Tag it"}
        for body, said in (
            ({"steps": [step]}, "its description is not text"),
            ({"description": 0, "steps": [step]}, "its description is not text"),
            ({"description": "Ship it."}, "its steps are not a list"),
            ({"description": "Ship it.", "steps": {}}, "its steps are not a list"),
            (
                {"description": "Ship it.", "steps": [step], "verifyUsing": False},
                "its verifyUsing is not a list",
            ),
            (
                {"description": "Ship it.", "steps": [dict(step, needs=0)]},
                "the needs of tag are not a list of step ids",
            ),
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValueError) as refused:
                    module.formula_body({"formula": body})
                self.assertEqual(str(refused.exception), said)
        self.assertEqual(
            module.formula_body({"formula": {"description": "", "steps": [step]}}),
            {"description": "", "verifyUsing": [], "steps": [dict(step, needs=[])]},
        )

    def test_a_provider_formula_outside_its_shape_is_refused(self):
        self.adopted()
        self.module("garbled", GARBLED_PROVIDER)
        code, out = self.dotdiw("formula", "provider", "register", "gb", "garbled")
        self.assertEqual(code, 0, out)
        for args in (("formula", "show", "mol-ship-gb"), ("formula", "pour", "mol-ship-gb")):
            with self.subTest(args=args):
                code, out = self.dotdiw(*args)
                self.assertEqual(code, 1, out)
                self.assertIn("The gb provider failed to show mol-ship", out)
        code, listed = self.dotdiw("list", "--all", "--json")
        self.assertEqual(json.loads(listed), [])

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_a_providers_suffix_never_falls_back_to_a_file_name(self):
        """A local file named like a provider's suffixed id, declaring an id
        of its own, never answers to that suffixed id."""
        self.adopted()
        self.repo.write(
            "mol-calibrate-acme.formula.toml",
            FORMULA_A.replace("mol-release-through-tap", "mol-other"),
        )
        self.registered()
        code, out = self.dotdiw("formula", "pour", "mol-calibrate-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula the acme provider serves", out)
        self.assertEqual(self.dotdiw("formula", "provider", "remove", "acme")[0], 0)
        code, out = self.dotdiw("formula", "pour", "mol-calibrate-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula: the acme provider is removed", out)
        for ident in ("mol-other", "mol-calibrate-acme.formula.toml"):
            with self.subTest(ident=ident):
                code, out = self.dotdiw("formula", "show", ident)
                self.assertEqual(code, 0, out)
                self.assertIn('formula = "mol-other"', out)

    def test_an_exact_path_comes_before_a_file_name(self):
        self.adopted()
        self.repo.write(
            "docs/release.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-docs")
        )
        self.repo.write(
            "tools/release.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-tools")
        )
        for ident, said in (
            ("tools/release.formula.toml", 'formula = "mol-tools"'),
            (os.path.join(self.repo.path, "docs", "release.formula.toml"), 'formula = "mol-docs"'),
        ):
            with self.subTest(ident=ident):
                code, out = self.dotdiw("formula", "show", ident)
                self.assertEqual(code, 0, out)
                self.assertIn(said, out)
        code, out = self.dotdiw("formula", "show", "release")
        self.assertEqual(code, 1, out)
        self.assertIn("names more than one formula", out)

    def test_check_names_a_formula_that_does_not_parse(self):
        self.adopted()
        self.repo.write("broken.formula.toml", 'formula = "mol-broken"\ndescription =\n')
        code, out = self.dotdiw("check")
        self.assertNotEqual(code, 0, out)
        self.assertRegex(out, r"broken\.formula\.toml\s+not committed, so nobody else can see it")
        self.assertRegex(out, r"broken\.formula\.toml\s+does not parse, so nothing can find it")
        code, out = self.dotdiw("create", "Rotate the signing keys")
        self.assertEqual(code, 0, out)
        self.assertIn("does not parse, so nothing can find it", out)
        self.repo.git("add", "broken.formula.toml")
        self.repo.git("commit", "-qm", "a formula that does not parse")
        code, out = self.dotdiw("check")
        self.assertNotIn("broken.formula.toml  not committed", out)
        self.assertRegex(out, r"broken\.formula\.toml\s+does not parse, so nothing can find it")

    def test_a_local_formula_never_takes_a_providers_suffix(self):
        """A provider's suffix is reserved: a local formula that declares an id
        with it is never reached by that id, and check says to rename it."""
        self.adopted()
        self.registered()
        self.repo.write(
            "zed.formula.toml", FORMULA_A.replace("mol-release-through-tap", "mol-zed-acme")
        )
        code, out = self.dotdiw("formula", "pour", "mol-zed-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula the acme provider serves", out)
        self.assertEqual(self.dotdiw("formula", "provider", "remove", "acme")[0], 0)
        code, out = self.dotdiw("formula", "pour", "mol-zed-acme")
        self.assertEqual(code, 1, out)
        self.assertIn("names no formula: the acme provider is removed", out)
        code, out = self.dotdiw("check")
        self.assertIn("its id carries the suffix of the removed acme provider -- rename it", out)
        code, out = self.dotdiw("formula", "show", "zed.formula.toml")
        self.assertEqual(code, 0, out)
        self.assertIn('formula = "mol-zed-acme"', out)

    def test_the_pour_hint_pours_the_formula_it_shows(self):
        """The command create prints to pour the first formula resolves to
        that formula: by its path when its id is a provider's, or is shared."""
        self.adopted()
        self.registered()
        self.repo.write(
            "zed.formula.toml", QUOTED.replace("mol-keys-$(touch PWNED)", "mol-ship-a-release-acme")
        )
        twin = QUOTED.replace("mol-keys-$(touch PWNED)", "mol-twin").replace(
            "Rotate the signing keys", "Renew the release certificates"
        )
        self.repo.write("one/twin.formula.toml", twin)
        self.repo.write("two/twin.formula.toml", twin.replace("Revoke the old pair", "Revoke it"))
        for title, path in (
            ("Rotate the signing keys", "zed.formula.toml"),
            ("Renew the release certificates", None),
        ):
            with self.subTest(title=title):
                code, out = self.dotdiw("create", title)
                self.assertEqual(code, 0, out)
                line = next(x for x in out.splitlines() if "Run it:" in x)
                ref = shlex.split(line.split("Run it:", 1)[1])[-1]
                self.assertTrue(ref.endswith(".formula.toml"), line)
                if path:
                    self.assertEqual(ref, path)
                code, out = self.dotdiw("formula", "pour", ref)
                self.assertEqual(code, 0, out)
                self.assertIn("Poured mol: created 2 issues", out)
        self.assertEqual(self.dotdiw("formula", "provider", "remove", "acme")[0], 0)
        code, out = self.dotdiw("create", "Rotate the signing keys")
        line = next(x for x in out.splitlines() if "Run it:" in x)
        self.assertEqual(shlex.split(line.split("Run it:", 1)[1])[-1], "zed.formula.toml")

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_the_pour_hint_is_never_read_as_an_option(self):
        """A reference that starts with a hyphen would be read as an option:
        an id like that gives way to the path, and a path like that is
        written from ./."""
        self.adopted()
        self.registered()
        self.repo.write(
            "-flight-check.formula.toml",
            QUOTED.replace("mol-keys-$(touch PWNED)", "mol-flight-acme"),
        )
        self.repo.write(
            "preflight.formula.toml",
            QUOTED.replace("mol-keys-$(touch PWNED)", "-preflight").replace(
                "Rotate the signing keys", "Renew the release certificates"
            ),
        )
        for title, ref in (
            ("Rotate the signing keys", "./-flight-check.formula.toml"),
            ("Renew the release certificates", "preflight.formula.toml"),
        ):
            with self.subTest(title=title):
                code, out = self.dotdiw("create", title)
                self.assertEqual(code, 0, out)
                line = next(x for x in out.splitlines() if "Run it:" in x)
                self.assertEqual(shlex.split(line.split("Run it:", 1)[1])[-1], ref)
                code, out = self.dotdiw("formula", "pour", ref)
                self.assertEqual(code, 0, out)
                self.assertIn("Poured mol: created 2 issues", out)

    @unittest.skipUnless(have_bd(), "bd is not installed")
    def test_the_providers_list_and_remove(self):
        self.adopted()
        self.registered()
        code, out = self.dotdiw("formula", "provider", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"acme\s+directory\s+list, show")
        code, out = self.dotdiw("formula", "provider", "remove", "acme")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("formula", "list")
        self.assertNotIn("mol-ship-a-release-acme", out)
        code, out = self.dotdiw("formula", "provider", "remove", "acme")
        self.assertEqual(code, 1, out)
        self.assertIn("No formula management provider is registered as acme.", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
