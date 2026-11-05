#!/usr/bin/env python3
"""Does every adapter present answer the tracker interface the same way?

The scenario that defines an adapter lives in dotdiw, as the helper of
check-tracker that `dotdiw tracker check <name>` runs: open, describe,
create, need, show, list, ready, the blocked close, the close, update and a
composed pour, one result per operation. These tests run it through the
door against every adapter present on this machine -- local always, beads
when bd is on PATH, jira against the stub in test_jira.py -- and then move a
workspace between each ordered pair of them and back, holding titles,
kinds, statuses, reasons, parents and needs across the move, with the source
unchanged and a second run moving nothing.

    python3 -I test_tracker.py
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTDIW = os.path.join(HERE, "dotdiw")
sys.path.insert(0, HERE)
import test_jira  # noqa: E402  the stub Jira, so that jira counts as present


def load_module(name, path=DOTDIW):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def have_bd():
    return shutil.which("bd") is not None


class Present:
    """A home with every adapter present installed, a stub Jira up, and a
    repository keyed to a workspace under that home; dotdiw loaded once."""

    def __init__(self):
        self.home = tempfile.mkdtemp(prefix="dotdiw-tracker-home-")
        self.site = test_jira.Site()
        os.makedirs(os.path.join(self.home, ".dotdiw", "trackers"))
        shutil.copy(test_jira.ADAPTER, os.path.join(self.home, ".dotdiw", "trackers", "jira.py"))
        self.before = {
            k: os.environ.get(k)
            for k in (
                "HOME",
                "JIRA_SITE",
                "JIRA_EMAIL",
                "JIRA_API_TOKEN",
                "JIRA_CHECK_PROJECT",
                "JIRA_PROJECT",
                "BEADS_DIR",
                "DOTDIW_TRACKER",
            )
        }
        # The project a move onto jira writes into: a hosted tracker opens no
        # store without a project named, by prefix or by this.
        os.environ.update(
            HOME=self.home,
            JIRA_SITE=self.site.url,
            JIRA_EMAIL="tester@example.invalid",
            JIRA_API_TOKEN=test_jira.TOKEN,
            JIRA_CHECK_PROJECT="CHK",
            JIRA_PROJECT="MV",
        )
        for k in ("BEADS_DIR", "DOTDIW_TRACKER"):
            os.environ.pop(k, None)
        self.m = load_module("dotdiw_for_trackers")
        self.names = ["local"] + (["beads"] if have_bd() else []) + ["jira"]
        for name in self.names:
            if name not in self.m.TRACKERS:
                self.m.load_tracker(name)
        self.repo = tempfile.mkdtemp(prefix="dotdiw-tracker-repo-")
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "Test"],
            ["config", "beads.role", "maintainer"],
            ["config", "--local", "dotdiw.workspace", "t" * 16],
        ):
            subprocess.run(["git"] + args, cwd=self.repo, capture_output=True)
        os.makedirs(os.path.join(self.home, ".dotdiw", "t" * 16))

    def close(self):
        self.site.close()
        for k, v in self.before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.repo, ignore_errors=True)

    def ask(self, tracker, operation, **request):
        return self.m.invoke_tracker(
            "operation." + operation, dict(request, root=self.repo, tracker=tracker)
        )


class EveryAdapterPresent(unittest.TestCase):
    """The scenario, through the door, against each adapter here."""

    present: Present

    @classmethod
    def setUpClass(cls):
        cls.present = Present()

    @classmethod
    def tearDownClass(cls):
        cls.present.close()

    def test_the_scenario_passes_on_every_adapter(self):
        m = self.present.m
        for name in self.present.names:
            with self.subTest(adapter=name):
                out = m.invoke("operation.check-tracker", {"root": self.present.repo, "name": name})
                self.assertEqual(out["status"], "completed", out["summary"])
                self.assertEqual(
                    [r["operation"] for r in out["results"]],
                    sorted(
                        m.TRACKER_DOOR,
                        key=lambda op: [
                            "operation.open-tracker",
                            "operation.describe-tracker",
                            "operation.create-item",
                            "operation.add-need",
                            "operation.show-item",
                            "operation.ready-items",
                            "operation.close-item",
                            "operation.list-items",
                            "operation.update-item",
                            "operation.pour-steps",
                        ].index(op),
                    ),
                )
                for r in out["results"]:
                    with self.subTest(adapter=name, operation=r["operation"]):
                        self.assertEqual(r["status"], "pass", r.get("detail"))
        # Jira's check filled its declared project and nothing else.
        self.assertEqual(
            {f["project"]["key"] for f in self.present.site.stub.issues.values()}, {"CHK"}
        )

    def test_the_scenario_says_what_fails(self):
        """The scenario is only a proof if it fails on an adapter that drops a
        rule: one that closes a blocked item is named at close-item."""
        m = self.present.m
        lax = {
            "info": {"name": "lax", "version": "0", "origin": "shipped", "checkTarget": "lax"},
            "operations": dict(m.TRACKERS["local"]["operations"]),
            "extras": {},
            "store": m.TRACKERS["local"]["store"],
        }
        real_close = lax["operations"]["operation.close-item"]

        def closes_anything(request):
            out = real_close(request)
            if out["status"] == "blocked":
                return {
                    "status": "completed",
                    "summary": "closed anyway",
                    "closedIds": [request["id"]],
                    "exitCode": 0,
                }
            return out

        lax["operations"]["operation.close-item"] = closes_anything
        m.register_tracker("lax", lax)
        self.addCleanup(m.TRACKERS.pop, "lax", None)
        out = m.invoke("operation.check-tracker", {"root": self.present.repo, "name": "lax"})
        self.assertEqual(out["status"], "failed")
        failed = [r["operation"] for r in out["results"] if r["status"] != "pass"]
        self.assertIn("operation.close-item", failed)
        self.assertIn("refused while an open need exists", out["summary"])


class Memory:
    """A tracker in memory, in the registry's shape, that gives ids of its own,
    refuses a write when told to, and remembers every write it took."""

    def __init__(self, name):
        self.name = name
        self.items = {}
        self.refuse = {}  # (operation, title) -> how many times
        self.kill = set()  # titles whose create dies with the process
        self.writes = []

    def add(self, title, status="open", needs=(), parent=None, reason=None):
        ident = "%s-%d" % (self.name, len(self.items) + 1)
        self.items[ident] = {
            "id": ident,
            "title": title,
            "kind": "task",
            "status": status,
            "priority": 2,
            "parent": parent,
            "reason": reason,
            "needs": list(needs),
        }
        return ident

    def named(self, title):
        return next(i for i in self.items.values() if i["title"] == title)

    def refused(self, operation, title):
        if self.refuse.get((operation, title), 0) > 0:
            self.refuse[(operation, title)] -= 1
            return {"status": "failed", "exitCode": 1, "summary": "told to refuse %s" % title}
        return None

    def table(self):
        def open_tracker(request):
            return {"status": "completed", "summary": "open", "created": False, "exitCode": 0}

        def describe(request):
            return {
                "status": "completed",
                "summary": "memory",
                "info": {"name": self.name, "version": "0", "origin": "loaded"},
                "exitCode": 0,
            }

        def create(request):
            title = request["title"]
            if title in self.kill:
                raise Killed(title)
            no = self.refused("create", title)
            if no:
                return no
            ident = self.add(title, parent=request.get("parent"))
            self.writes.append(("create", title))
            return {"status": "completed", "summary": "made", "item": self.items[ident]}

        def need(request):
            item = self.items[request["id"]]
            no = self.refused("need", item["title"])
            if no:
                return no
            if request["needs"] not in item["needs"]:
                item["needs"].append(request["needs"])
            self.writes.append(("need", item["title"]))
            return {
                "status": "completed",
                "summary": "linked",
                "edge": {"id": request["id"], "needs": request["needs"]},
            }

        def update(request):
            item = self.items[request["id"]]
            no = self.refused("update", item["title"])
            if no:
                return no
            item["status"] = request.get("status") or item["status"]
            self.writes.append(("update", item["title"]))
            return {"status": "completed", "summary": "updated", "item": item}

        def close(request):
            item = self.items[request["id"]]
            no = self.refused("close", item["title"])
            if no:
                return no
            if item["status"] == "closed":
                return {"status": "completed", "summary": "already", "item": item, "closedIds": []}
            blocked = [n for n in item["needs"] if self.items[n]["status"] != "closed"]
            blocked += [
                i["id"]
                for i in self.items.values()
                if i["parent"] == item["id"] and i["status"] != "closed"
            ]
            if blocked:
                return {
                    "status": "blocked",
                    "reason": "blocked",
                    "blockedBy": blocked,
                    "exitCode": 1,
                    "summary": "%s is blocked by %s." % (item["id"], ", ".join(blocked)),
                }
            item["status"], item["reason"] = "closed", request.get("closeReason")
            self.writes.append(("close", item["title"]))
            return {
                "status": "completed",
                "summary": "closed",
                "item": item,
                "closedIds": [item["id"]],
            }

        def show(request):
            return {"status": "completed", "summary": "x", "item": self.items[request["id"]]}

        def listing(request):
            return {"status": "completed", "summary": "x", "items": list(self.items.values())}

        def pour(request):
            return {"status": "failed", "reason": "no-steps", "exitCode": 1, "summary": "none"}

        return {
            "info": {
                "name": self.name,
                "version": "0",
                "origin": "loaded",
                "checkTarget": "scratch",
            },
            "operations": {
                "operation.open-tracker": open_tracker,
                "operation.describe-tracker": describe,
                "operation.create-item": create,
                "operation.add-need": need,
                "operation.pour-steps": pour,
                "operation.close-item": close,
                "operation.show-item": show,
                "operation.list-items": listing,
                "operation.update-item": update,
                "operation.ready-items": listing,
            },
            "extras": {},
        }


class Killed(BaseException):
    """The process dying: not an adapter's failure, nothing catches it."""


class AnInterruptedMove(unittest.TestCase):
    """A move that a target refused part of says so and keeps what was
    written, and the next run finishes every phase of it, nothing twice."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="dotdiw-resume-home-")
        self.repo = tempfile.mkdtemp(prefix="dotdiw-resume-repo-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.addCleanup(shutil.rmtree, self.repo, True)
        before = {k: os.environ.get(k) for k in ("HOME", "DOTDIW_TRACKER")}

        def restore():
            for k, v in before.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        self.addCleanup(restore)
        os.environ["HOME"] = self.home
        os.environ.pop("DOTDIW_TRACKER", None)
        for args in (["init", "-q", "."], ["config", "--local", "dotdiw.workspace", "m" * 16]):
            subprocess.run(["git"] + args, cwd=self.repo, capture_output=True)
        self.ws = os.path.join(self.home, ".dotdiw", "m" * 16)
        os.makedirs(self.ws)
        self.m = load_module("dotdiw_for_moves")
        self.src, self.dst = Memory("src"), Memory("dst")
        self.m.register_tracker("src", self.src.table())
        self.m.register_tracker("dst", self.dst.table())

    def move(self):
        return self.m.invoke(
            "operation.migrate-workspace",
            {"root": self.repo, "fromTracker": "src", "toTracker": "dst"},
        )

    def needs_of(self, title):
        return sorted(self.dst.items[n]["title"] for n in self.dst.named(title)["needs"])

    def test_a_refused_item_leaves_the_earlier_ones_to_be_finished(self):
        """A needs B and is in progress; B is refused once. The retry writes
        B, and A's need and status, which the first run never reached."""
        b = self.src.add("B")
        a = self.src.add("A", status="in_progress", needs=[b])
        self.src.items = {a: self.src.items[a], b: self.src.items[b]}  # A goes first
        self.dst.refuse[("create", "B")] = 1
        first = self.move()
        self.assertEqual((first["status"], first["reason"]), ("failed", "item-refused"), first)
        self.assertEqual(first["exitCode"], 1)
        self.assertEqual(first["moved"], 1)
        self.assertEqual(self.dst.named("A")["status"], "open")
        second = self.move()
        self.assertEqual(second["status"], "completed", second)
        self.assertEqual((second["moved"], second["resumed"]), (1, 1))
        self.assertEqual(self.dst.named("A")["status"], "in_progress")
        self.assertEqual(self.needs_of("A"), ["B"])

    def test_a_refused_need_is_reported_and_written_by_the_next_run(self):
        b = self.src.add("B")
        a = self.src.add("A", needs=[b])
        self.dst.refuse[("need", "A")] = 1
        first = self.move()
        self.assertEqual((first["status"], first["reason"]), ("failed", "item-refused"), first)
        self.assertEqual(first["exitCode"], 1)
        self.assertIn("the need of %s on %s" % (a, b), first["summary"])
        self.assertEqual(self.needs_of("A"), [], "the need is missing, and the move says so")
        second = self.move()
        self.assertEqual(second["status"], "completed", second)
        self.assertEqual((second["moved"], second["resumed"]), (0, 2))
        self.assertEqual(self.needs_of("A"), ["B"])

    def test_a_refused_status_is_reported_and_written_by_the_next_run(self):
        self.src.add("A", status="in_progress")
        self.dst.refuse[("update", "A")] = 1
        first = self.move()
        self.assertEqual((first["status"], first["reason"]), ("failed", "item-refused"), first)
        self.assertEqual(self.dst.named("A")["status"], "open")
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual(self.dst.named("A")["status"], "in_progress")

    def test_a_refused_close_is_reported_and_written_by_the_next_run(self):
        self.src.add("A", status="closed", reason="shipped")
        self.dst.refuse[("close", "A")] = 1
        first = self.move()
        self.assertEqual((first["status"], first["reason"]), ("failed", "item-refused"), first)
        self.assertEqual(self.dst.named("A")["status"], "open")
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual(
            (self.dst.named("A")["status"], self.dst.named("A")["reason"]), ("closed", "shipped")
        )

    def test_a_close_that_stays_blocked_is_not_a_completed_move(self):
        """Closed in the source with a need still open, which a target that
        holds to the rule will not close: the move says which, and why."""
        b = self.src.add("B")
        a = self.src.add("A", status="closed", reason="forced", needs=[b])
        first = self.move()
        self.assertEqual((first["status"], first["reason"]), ("failed", "item-refused"), first)
        self.assertIn("the close of %s" % a, first["summary"])
        self.assertIn("is blocked by", first["summary"])
        self.assertEqual(self.dst.named("A")["status"], "open")
        self.dst.named("B")["status"] = "closed"  # the worker closes it there
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual(self.dst.named("A")["status"], "closed")

    def test_a_finished_move_writes_nothing_again(self):
        b = self.src.add("B")
        self.src.add("A", status="in_progress", needs=[b])
        self.src.add("C", status="closed", reason="done")
        self.assertEqual(self.move()["status"], "completed")
        writes = list(self.dst.writes)
        again = self.move()
        self.assertEqual((again["status"], again["moved"], again["resumed"]), ("completed", 0, 0))
        self.assertEqual(self.dst.writes, writes)

    def test_the_mapping_is_saved_as_each_item_is_made(self):
        """The process dies between two creates: the next run does not make
        the first one twice."""
        self.src.add("A")
        self.src.add("B")
        self.dst.kill = {"B"}
        with self.assertRaises(Killed):
            self.move()
        self.assertEqual([i["title"] for i in self.dst.items.values()], ["A"])
        self.dst.kill = set()
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual(sorted(i["title"] for i in self.dst.items.values()), ["A", "B"])

    def test_a_run_that_only_finishes_says_so(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.m.show_migrate(
                {},
                {
                    "status": "completed",
                    "summary": "Finished 2 items an earlier run left from src to dst.",
                    "moved": 0,
                    "resumed": 2,
                },
            )
        self.assertEqual(
            buffer.getvalue(), "\u2713 Finished 2 items an earlier run left from src to dst.\n"
        )


class MovingBetweenAdapters(unittest.TestCase):
    """A workspace's work moves from each adapter present to each other one
    with everything intact, the source unchanged, and nothing twice."""

    present: Present

    @classmethod
    def setUpClass(cls):
        cls.present = Present()

    @classmethod
    def tearDownClass(cls):
        cls.present.close()

    def fill(self, tracker):
        """A few items with everything the records carry, in one adapter."""

        def ask(op, **r):
            return self.present.ask(tracker, op, **r)

        self.assertEqual(ask("open-tracker", prefix="mv")["status"], "completed")
        a = ask("create-item", title="Alpha", kind="task", priority=1)["item"]["id"]
        b = ask("create-item", title="Beta", parent=a)["item"]["id"]
        c = ask("create-item", title="Gamma", priority=3)["item"]["id"]
        self.assertEqual(ask("add-need", id=c, needs=b)["status"], "completed")
        poured = ask(
            "pour-steps",
            formulaRef="mol-mv",
            title="mol-mv",
            steps=[{"id": "x", "title": "Step X"}, {"id": "y", "title": "Step Y", "needs": ["x"]}],
        )
        self.assertEqual(poured["status"], "completed", poured)
        self.assertEqual(ask("close-item", id=b, closeReason="beta done")["status"], "completed")
        self.assertEqual(ask("update-item", id=c, status="in_progress")["status"], "completed")
        self.assertEqual(
            ask("close-item", id=poured["stepIds"][0], closeReason="x done")["status"], "completed"
        )
        return ask("list-items", scope="all")["items"]

    @staticmethod
    def shape(items):
        """What a move must keep, keyed by title: kind, status, reason, the
        parent's title and the needs' titles."""
        title = {i["id"]: i["title"] for i in items}
        return {
            i["title"]: (
                i["kind"] in ("molecule", "epic"),
                i["status"],
                i.get("reason"),
                title.get(i.get("parent")),
                sorted(title[n] for n in i["needs"] if n in title),
            )
            for i in items
        }

    def test_every_pair_and_back(self):
        m, present = self.present.m, self.present
        for src in present.names:
            for dst in present.names:
                if src == dst:
                    continue
                with self.subTest(move="%s to %s" % (src, dst)):
                    home = tempfile.mkdtemp(prefix="dotdiw-move-")
                    shutil.copytree(
                        os.path.join(present.home, ".dotdiw", "trackers"),
                        os.path.join(home, ".dotdiw", "trackers"),
                    )
                    os.makedirs(os.path.join(home, ".dotdiw", "t" * 16))
                    os.environ["HOME"] = home
                    try:
                        before = self.fill(src)
                        moved = m.invoke(
                            "operation.migrate-workspace",
                            {"root": present.repo, "fromTracker": src, "toTracker": dst},
                        )
                        self.assertEqual(moved["status"], "completed", moved["summary"])
                        self.assertEqual(moved["moved"], len(before))
                        after = present.ask(dst, "list-items", scope="all")["items"]
                        self.assertEqual(self.shape(after), self.shape(before))
                        self.assertEqual(
                            present.ask(src, "list-items", scope="all")["items"],
                            before,
                            "the source is unchanged",
                        )
                        if dst == "local":
                            self.assertEqual(moved["mapped"], 0, "local keeps every id")
                            self.assertEqual({i["id"] for i in after}, {i["id"] for i in before})
                        else:
                            self.assertEqual(
                                moved["mapped"], len(before), "%s assigns its own ids" % dst
                            )
                        again = m.invoke(
                            "operation.migrate-workspace",
                            {"root": present.repo, "fromTracker": src, "toTracker": dst},
                        )
                        self.assertEqual((again["status"], again["moved"]), ("completed", 0))
                        self.assertEqual(
                            len(present.ask(dst, "list-items", scope="all")["items"]),
                            len(before),
                            "a second run moves nothing",
                        )
                    finally:
                        os.environ["HOME"] = present.home
                        m.forget_workspace(present.repo)
                        shutil.rmtree(home, ignore_errors=True)
                        present.site.stub.reset()


if __name__ == "__main__":
    unittest.main(verbosity=2)
