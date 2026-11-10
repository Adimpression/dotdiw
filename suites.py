#!/usr/bin/env python3
"""The tests, in suites by what they run beyond Python and git.

    fast  nothing more
    bd    the beads tracker's own binary, bd
    poa   POA, at ~/poa
    all   all three

    python3 -I suites.py fast

A test says what it runs with uses("bd") or uses("poa") on its class or on
itself; a test that says nothing is fast. A test that runs both is in bd.
TheMarks, in the fast suite, holds every test that skips without bd, or that
runs POA, to saying so.

The suites that run bd -- bd and all -- keep every temp directory of the run
on a RAM disk made for it (on_a_ram_disk), since bd opens its store on each
command and a store in memory opens in about half the time: on macOS one
hdiutil makes, on Linux one under /dev/shm, and the disk where neither can be
had or DOTDIW_TEST_ON_DISK is set. Nothing of it is left after the run.
"""

import ast
import contextlib
import importlib.machinery
import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from types import ModuleType
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ("test_dotdiw.py", "test_promise.py", "test_jira.py", "test_tracker.py")
SUITES = ("fast", "bd", "poa")
RAM_SUITES = ("bd", "all")  # the runs that reach bd, kept in memory
RAM_MB = 2048  # room for the stores of a run, and a copy of the tree for each break
ON_DISK = "DOTDIW_TEST_ON_DISK"  # set, a run keeps its temp directories on the disk


def load(name: str) -> ModuleType:
    """A test file as a module, loaded by its path, as the tests load dotdiw."""
    loader = importlib.machinery.SourceFileLoader(name[:-3], os.path.join(HERE, name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def flatten(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def suite_of(test: unittest.TestCase) -> str:
    """The suite a test is in, by what its method and its class say they run."""
    method = getattr(type(test), test._testMethodName, None)
    runs = set(getattr(method, "uses", ())) | set(getattr(type(test), "uses", ()))
    return "bd" if "bd" in runs else "poa" if "poa" in runs else "fast"


class TempPlace:
    """Where a run keeps its temp directories: the path, whether it is in
    memory, and, where it is not, why."""

    def __init__(self, path: str, ram: bool, why: str = "") -> None:
        self.path, self.ram, self.why = path, ram, why


def ram_directory() -> tuple[str | None, str | None, str]:
    """A directory in memory, where one can be had: on macOS a RAM disk
    hdiutil makes, on Linux one under /dev/shm. The RAM disk's device, to be
    detached after, else None; the directory, else None; and, where there is
    none, why."""
    if shutil.which("hdiutil") and shutil.which("diskutil"):  # macOS
        made = subprocess.run(
            ["hdiutil", "attach", "-nomount", "ram://%d" % (RAM_MB * 2048)],
            capture_output=True,
            text=True,
        )
        words = made.stdout.split()
        if made.returncode != 0 or not words:
            said = " ".join((made.stderr or made.stdout).split())
            return None, None, "hdiutil made no RAM disk: %s" % (said or made.returncode)
        device, name = words[0], "dotdiw-tests-%d-%s" % (os.getpid(), os.urandom(3).hex())
        # Attached, the RAM disk is this run's to take away, whatever stops
        # its making after: a step that fails, or ^C or SIGTERM as it runs.
        try:
            mount = os.path.join("/Volumes", name)
            erased = subprocess.run(
                ["diskutil", "erasevolume", "APFS", name, device], capture_output=True, text=True
            )
            if erased.returncode != 0 or not os.path.isdir(mount):
                said = " ".join((erased.stderr or erased.stdout).split())
                why = "diskutil made no volume on the RAM disk: %s" % said
            else:
                # Spotlight leaves alone a volume that holds this file at its root.
                open(os.path.join(mount, ".metadata_never_index"), "w").close()
                path = os.path.join(mount, "tmp")
                os.mkdir(path)
                return device, path, ""
        except OSError as e:
            why = "the RAM disk could not be readied: %s" % e
        except BaseException:
            subprocess.run(["hdiutil", "detach", device, "-force"], capture_output=True)
            raise
        subprocess.run(["hdiutil", "detach", device, "-force"], capture_output=True)
        return None, None, why
    shm = "/dev/shm"
    if os.path.isdir(shm) and os.access(shm, os.W_OK | os.X_OK):
        room = os.statvfs(shm)
        if room.f_bavail * room.f_frsize >= RAM_MB // 4 * 1024 * 1024:
            return None, tempfile.mkdtemp(prefix="dotdiw-tests-", dir=shm), ""
        return None, None, "%s has less than %d MB free" % (shm, RAM_MB // 4)
    return None, None, "this machine offers no RAM disk a run can make"


@contextlib.contextmanager
def on_a_ram_disk() -> Iterator[TempPlace]:
    """The length of a run, with every temp directory it makes in memory: the
    directory ram_directory makes is the temp directory of this process, and
    of every process it starts, through TMPDIR, so that each store a test
    makes for bd is there. Where none can be had, or ON_DISK is set, the
    run is where it was. After it, TMPDIR is as it was, and the directory,
    and the RAM disk under it, are gone."""
    before = os.environ.get("TMPDIR"), tempfile.tempdir
    device: str | None = None
    path: str | None = None
    why = "%s is set" % ON_DISK if os.environ.get(ON_DISK) else ""
    if not why:
        device, path, why = ram_directory()
    try:
        if path is None:
            yield TempPlace(tempfile.gettempdir(), False, why)
            return
        os.environ["TMPDIR"] = path
        tempfile.tempdir = path
        yield TempPlace(path, True)
    finally:
        if before[0] is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = before[0]
        tempfile.tempdir = before[1]
        if device is not None:
            subprocess.run(["hdiutil", "detach", device, "-force"], capture_output=True)
        elif path is not None:
            shutil.rmtree(path, ignore_errors=True)


def tests(name: str) -> unittest.TestSuite:
    """The tests of one suite, or of all."""
    out = unittest.TestSuite()
    loader = unittest.TestLoader()
    found = [loader.loadTestsFromModule(load(f)) for f in FILES]
    found.append(loader.loadTestsFromTestCase(TheMarks))
    found.append(loader.loadTestsFromTestCase(TheRamDisk))
    for test in flatten(unittest.TestSuite(found)):
        if name == "all" or suite_of(test) == name:
            out.addTest(test)
    return out


class TheMarks(unittest.TestCase):
    """Every test that skips without bd says it runs bd, and every test that
    runs POA says so, so that no slow test sits in the fast suite unseen."""

    def marked(self, node: ast.ClassDef | ast.FunctionDef, what: str) -> bool:
        return any(
            isinstance(d, ast.Call)
            and getattr(d.func, "id", None) == "uses"
            and what in [getattr(a, "value", None) for a in d.args]
            for d in node.decorator_list
        )

    def test_a_test_that_skips_without_bd_says_it_runs_bd(self) -> None:
        for name in FILES:
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                skips = any("have_bd" in ast.unparse(d) for d in node.decorator_list)
                if isinstance(node, ast.ClassDef):
                    setup = [
                        m
                        for m in node.body
                        if isinstance(m, ast.FunctionDef) and m.name in ("setUp", "setUpClass")
                    ]
                    skips = skips or any("have_bd" in ast.unparse(m) for m in setup)
                with self.subTest(file=name, name=node.name):
                    self.assertTrue(
                        not skips or self.marked(node, "bd"),
                        '%s skips without bd and does not say uses("bd")' % node.name,
                    )

    def test_a_test_that_runs_poa_says_so(self) -> None:
        for name in FILES:
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
                for method in [m for m in cls.body if isinstance(m, ast.FunctionDef)]:
                    if not method.name.startswith("test") or "POA" not in ast.unparse(method):
                        continue
                    with self.subTest(file=name, test="%s.%s" % (cls.name, method.name)):
                        self.assertTrue(
                            self.marked(method, "poa") or self.marked(cls, "poa"),
                            '%s.%s runs POA and does not say uses("poa")' % (cls.name, method.name),
                        )


class TheRamDisk(unittest.TestCase):
    """A run that reaches bd keeps its temp directories in memory, for this
    process and every one it starts, and leaves nothing of it behind."""

    def test_a_run_keeps_its_temp_directories_in_memory_and_takes_them_away(self) -> None:
        was = tempfile.gettempdir(), os.environ.get("TMPDIR")
        with on_a_ram_disk() as place:
            self.assertEqual(tempfile.gettempdir(), place.path)
            told = subprocess.run(
                [sys.executable, "-I", "-c", "import tempfile; print(tempfile.gettempdir())"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(os.path.realpath(told), os.path.realpath(place.path))
            if place.ram:
                self.assertNotEqual(
                    os.stat(place.path).st_dev, os.stat(was[0]).st_dev, "a file system apart"
                )
            else:
                self.assertEqual(place.path, was[0], place.why)
        self.assertEqual((tempfile.gettempdir(), os.environ.get("TMPDIR")), was)
        self.assertFalse(place.ram and os.path.exists(place.path), "the RAM disk is gone")

    def readied(self, fails: BaseException) -> tuple[list[list[str]], object]:
        """ram_directory on a macOS whose RAM disk attaches and takes a
        volume, and whose making then fails as given, past the attach: the
        commands run, and what it answered or raised."""
        ran: list[list[str]] = []

        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            ran.append(list(argv))
            made = "/dev/disk99\n" if argv[:2] == ["hdiutil", "attach"] else ""
            return subprocess.CompletedProcess(argv, 0, made, "")

        with (
            mock.patch.object(shutil, "which", lambda name: "/usr/bin/" + name),
            mock.patch.object(subprocess, "run", run),
            mock.patch.object(os.path, "isdir", lambda _: True),
            mock.patch("builtins.open", mock.mock_open()),
            mock.patch.object(os, "mkdir", side_effect=fails),
        ):
            try:
                return ran, ram_directory()
            except BaseException as e:  # noqa: BLE001 -- the test reads what it raised
                return ran, e

    def test_a_ram_disk_whose_making_fails_is_taken_away(self) -> None:
        """A RAM disk attached and given a volume, whose directory cannot be
        made, is detached, and the run keeps its temp directories on the
        disk, saying why."""
        ran, answer = self.readied(OSError("no room"))
        self.assertIn(["hdiutil", "detach", "/dev/disk99", "-force"], ran)
        self.assertEqual(answer, (None, None, "the RAM disk could not be readied: no room"))

    def test_a_ram_disk_stopped_as_it_is_made_is_taken_away(self) -> None:
        """A run stopped as its RAM disk is made -- ^C, or SIGTERM read as ^C --
        detaches the RAM disk before it stops."""
        ran, answer = self.readied(KeyboardInterrupt())
        self.assertIn(["hdiutil", "detach", "/dev/disk99", "-force"], ran)
        self.assertIsInstance(answer, KeyboardInterrupt)

    def test_a_run_told_to_stay_on_the_disk_stays(self) -> None:
        with mock.patch.dict(os.environ, {ON_DISK: "1"}):
            with on_a_ram_disk() as place:
                self.assertFalse(place.ram)
                self.assertEqual(place.path, tempfile.gettempdir())
                self.assertIn(ON_DISK, place.why)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in SUITES + ("all",):
        sys.stderr.write("usage: suites.py fast|bd|poa|all\n")
        return 2
    # A run stopped by SIGTERM takes its RAM disk away too, as one stopped by ^C.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    with contextlib.ExitStack() as stack:
        if argv[0] in RAM_SUITES:
            place = stack.enter_context(on_a_ram_disk())
            sys.stderr.write(
                "suites.py: temp directories %s\n"
                % ("on a RAM disk, %s" % place.path if place.ram else "on the disk: %s" % place.why)
            )
        result = unittest.TextTestRunner(verbosity=2).run(tests(argv[0]))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
