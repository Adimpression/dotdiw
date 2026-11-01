#!/usr/bin/env python3
"""What adoption does to a repository, and what it must not do.

v0.1.0 passed `init` straight through to `bd init` without checking what bd
changes in a repository. Two of those changes were wrong to inherit, and the
claim made about one of them was itself wrong: bd copies the hooks already in
`.git/hooks` into its own directory, so hooks present at adoption keep running.
What stops running is anything added afterwards, because `core.hooksPath` names
one directory and from adoption onward it is bd's snapshot.

0.2.x then let bd commit its own files into the repository and repaired what
it had committed, which left one file modified and unexplained. From 0.3.0
`init` runs bd in its stealth mode: bd commits nothing, writes nothing for
agents, configures no remote, and keeps `.beads/` local to the checkout. What
init leaves behind is dotdiw's own declaration, named as the worker's to
commit, and the printed command leaves the tree clean. Repositories adopted
earlier are told the one command that does the same for them.

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
    """A real git repository in a temporary directory."""

    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="dotdiw-test-")
        self.git("init", "-q", ".")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        # bd asks for one, and warns on every command without it.
        self.git("config", "beads.role", "maintainer")

    def close(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def git(self, *args):
        p = subprocess.run(["git"] + list(args), cwd=self.path,
                           capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def config(self, key):
        return self.git("config", "--get", key)[1].strip()

    def dotdiw(self, *args):
        p = subprocess.run([sys.executable, "-I", DOTDIW] + list(args),
                           cwd=self.path, capture_output=True, text=True)
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
        repo = cls.__new__(cls)
        repo.path = tempfile.mkdtemp(prefix="dotdiw-clone-")
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

    def adopt_the_old_way(self, prefix="t"):
        """Adopt as 0.2.x did: bd's default init, which commits its own files."""
        p = subprocess.run([shutil.which("bd"), "init", "--skip-hooks", "--prefix", prefix],
                           cwd=self.path, capture_output=True, text=True)
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

    def test_init_commits_nothing_and_names_what_is_yours(self):
        """bd commits nothing; what is left is dotdiw's declaration, and one command.

        Under bd's stealth mode .beads/ is local to the checkout, so nothing of
        bd's enters git. The two instruction files dotdiw wrote are the
        worker's to commit, the report says so, and the command it prints
        leaves the tree clean. Committing is not this tool's to do, but saying
        exactly what to commit is.
        """
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.commits(), 1, "bd must not commit")
        self.assertEqual(sorted(l[3:] for l in self.repo.porcelain()),
                         ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(self.repo.tracked(".beads"), [])
        self.assertIn(".beads/", self.repo.excluded())
        self.assertIn("yours to commit", out)
        self.assertIn("AGENTS.md", out)
        self.assertIn("CLAUDE.md", out)
        self.assertNotIn("an earlier version", out)
        command = [l.strip() for l in out.split("\n") if l.strip().startswith("git add ")]
        self.assertEqual(len(command), 1, out)
        p = subprocess.run(command[0], shell=True, cwd=self.repo.path,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.repo.porcelain(), [], "the printed command must leave the tree clean")

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
        """The tracker is local to each checkout, so a clone has none until init.

        This was already true before 0.3.0 -- bd's database was never in git --
        and nothing said so. Now create says so, and init in the clone commits
        nothing.
        """
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.repo.git("add", "AGENTS.md", "CLAUDE.md")
        self.repo.git("commit", "-qm", "Declare where work starts")

        clone = Repo.clone_of(self.repo)
        self.addCleanup(clone.close)
        code, out = clone.dotdiw("create", "In the clone")
        self.assertNotEqual(code, 0)
        self.assertIn("no tracker database yet", out)
        self.assertIn("dotdiw init once", out)

        code, out = clone.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)
        self.assertEqual(clone.commits(), 2)
        self.assertIn(".beads/", clone.excluded())
        self.assertEqual(clone.porcelain(), [], "the clone already carries the declaration")
        code, out = clone.dotdiw("create", "In the clone")
        self.assertEqual(code, 0, out)

    def test_init_over_an_old_adoption_does_not_reinitialise(self):
        """A repository where 0.2.x let bd commit: no second init, the one command instead."""
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        self.repo.adopt_the_old_way()
        before = self.repo.commits()
        self.assertEqual(len(self.repo.tracked(".beads")), 4)

        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(self.repo.commits(), before)
        self.assertEqual(len(self.repo.tracked(".beads")), 4, "dotdiw never changes the index")
        self.assertTrue(os.path.exists(os.path.join(self.repo.path, ".beads", "config.yaml")))
        self.assertIn("git rm -r --cached .beads", out)
        self.assertIn(".beads/", self.repo.excluded())

    def test_init_writes_nothing_global(self):
        """Outside the repository: bd's three per-machine files and nothing else.

        bd's help says stealth mode writes a global gitignore and
        gitattributes. bd 1.3.2 does not. The day a bd does, this fails before
        a release instead of after.
        """
        home = tempfile.mkdtemp(prefix="dotdiw-home-")
        self.addCleanup(shutil.rmtree, home, True)
        self.repo.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        self.repo.commit("first")
        p = subprocess.run([sys.executable, "-I", DOTDIW, "init", "--prefix", "t"],
                           cwd=self.repo.path, env=dict(os.environ, HOME=home),
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        written = sorted(os.path.relpath(os.path.join(d, f), home)
                         for d, _, fs in os.walk(home) for f in fs)
        allowed = {".beads/machine-id", ".dolt/config_global.json", ".config/bd/config.yaml"}
        self.assertTrue(set(written) <= allowed, written)


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

    def test_repair_hands_the_hooks_back(self):
        """A hook added after adoption was being skipped, and runs again.

        This is the actual defect, and it is narrower than it first looked:
        hooks that existed at adoption were copied into bd's directory and kept
        running. A hook added afterwards went to .git/hooks, which git was no
        longer reading.
        """
        self.repo.adopt_as_v0_1_0()
        self.repo.hook("pre-commit", "added-later")

        self.repo.commit("while-adopted")
        self.assertFalse(self.repo.ran("added-later"),
                         "a hook added after adoption should be skipped, or "
                         "there is nothing here to repair")

        code, out = self.repo.dotdiw("check")
        self.assertEqual(code, 0, out)
        self.assertIn(HOOKS_KEY, out)
        self.assertEqual(self.repo.config(HOOKS_KEY), "")

        self.repo.commit("after-repair")
        self.assertTrue(self.repo.ran("added-later"),
                        "the hook must run once the override is gone")

    def test_repair_removes_the_dolt_remote(self):
        self.repo.adopt_as_v0_1_0()
        self.assertEqual(self.repo.dolt_remotes(), ["origin"])

        code, out = self.repo.dotdiw("check")
        self.assertEqual(code, 0, out)

        self.assertEqual(self.repo.dolt_remotes(), [])
        self.assertNotIn("\nsync:", self.repo.beads_config())
        self.assertIn("Dolt remote", out)

    def test_repair_says_nothing_when_there_is_nothing_to_undo(self):
        """Silence in a repository this never touched.

        A repair that announces itself every time teaches people to ignore it.
        """
        code, out = self.repo.dotdiw("check")
        self.assertEqual(code, 0, out)
        self.assertNotIn("undid", out)

    def test_an_old_adoption_is_told_how_to_keep_the_tracker_local(self):
        """0.2.x let bd commit its files. dotdiw names the one command and never runs it.

        The exclude is written so that once the files leave the index they
        stay out; running the printed command leaves the tree clean and the
        files on disk.
        """
        old = Repo()
        self.addCleanup(old.close)
        old.git("remote", "add", "origin", "git@example.invalid:x/y.git")
        old.commit("first")
        old.adopt_the_old_way()
        self.assertEqual(len(old.tracked(".beads")), 4)

        code, out = old.dotdiw("check")
        self.assertIn("tracked in git, from an adoption before 0.3.0", out)
        self.assertIn("git rm -r --cached .beads", out)
        self.assertIn(".beads/", old.excluded())
        self.assertEqual(len(old.tracked(".beads")), 4, "dotdiw never changes the index")

        p = subprocess.run("git rm -r --cached .beads && git commit -qm \"Keep the tracker local\"",
                           shell=True, cwd=old.path, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(old.tracked(".beads"), [])
        self.assertTrue(os.path.exists(os.path.join(old.path, ".beads", "config.yaml")))
        self.assertEqual(old.porcelain(), [], "excluded, so not even untracked")
        code, out = old.dotdiw("check")
        self.assertNotIn("tracked in git", out, "the notice stops once it is done")

    def test_the_notice_says_who_did_it(self):
        """What 0.1.0 left is 'an earlier version'; a fresh init never says that."""
        self.repo.adopt_as_v0_1_0()
        code, out = self.repo.dotdiw("check")
        self.assertIn("undid what an earlier version of it did here", out)

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
        self.assertNotIn("undid", out)


@unittest.skipUnless(have_bd(), "bd is not installed")
class Metrics(unittest.TestCase):
    """bd's usage metrics are off before this tool runs anything else.

    bd ships them on. These tests run against an empty HOME, which is what a
    machine looks like the day bd is installed, so nothing here touches the
    config of the machine running the suite.
    """

    OFF = "turned bd's anonymous usage metrics off"

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
