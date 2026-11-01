#!/usr/bin/env python3
"""What adoption does to a repository, and what it must not do.

v0.1.0 passed `init` straight through to `bd init` without checking what bd
changes in a repository. Two of those changes were wrong to inherit, and the
claim made about one of them was itself wrong: bd copies the hooks already in
`.git/hooks` into its own directory, so hooks present at adoption keep running.
What stops running is anything added afterwards, because `core.hooksPath` names
one directory and from adoption onward it is bd's snapshot.

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

    def test_init_says_what_it_left_uncommitted(self):
        """bd commits its files, then init edits some of them.

        That left the repository dirty and the committed copies stale -- naming
        bd, carrying no declaration -- so a clone at that commit got neither.
        Committing is not this tool's to do, but saying so is.
        """
        self.repo.commit("first")
        code, out = self.repo.dotdiw("init", "--prefix", "t")
        self.assertEqual(code, 0, out)

        dirty = self.repo.git("diff", "--name-only")[1].split()
        if not dirty:
            self.skipTest("this bd did not commit its own files")
        self.assertIn("uncommitted", out)
        self.assertIn("CLAUDE.md", out)
        self.assertIn("git add", out)


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


class Version(unittest.TestCase):
    def test_version_is_its_own(self):
        """`--version` reports this tool's version, not the one it wraps."""
        p = subprocess.run([sys.executable, "-I", DOTDIW, "--version"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("dotdiw "), p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
