#!/usr/bin/env python3
"""Does the hosted adapter keep to the tracker interface?

trackers/jira.py is the proof that the interface fits a tracker that is not
on this machine. It is never run against a live account here: these tests
stand up a stub of Jira Cloud's REST API, standard library http.server and
nothing else, with enough of the API for the conformance scenario, install
the adapter under a temporary home by name, and run dotdiw against it --
`tracker list`, `tracker check jira`, and a checkout adopted on it.

    python3 -I test_jira.py

The stub holds projects, issues, links, comments and three statuses in
memory, answers only to Basic auth, and says what it was asked, so a test
can prove that nothing left the declared project and no credential was
printed.
"""

import base64
import glob
import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
DOTDIW = os.path.join(HERE, "dotdiw")
ADAPTER = os.path.join(HERE, "trackers", "jira.py")
TOKEN = "stub-token-for-tests-only"
STATUSES = {"To Do": "new", "In Progress": "indeterminate", "Done": "done"}
MYSELF = {
    "accountId": "5c0a1b2c3d4e5f6a7b8c9d0e",
    "displayName": "Stub Person",
    "emailAddress": "stub.person@example.invalid",
}
ACCOUNTS = {MYSELF["accountId"]: MYSELF["displayName"], "5b10ac8d82e05b22cc7d4ef5": "Some Body"}


class StubJira:
    """Jira Cloud's REST API v3, the parts the adapter calls, in memory."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Empty, as at the start: what a test does between adapters."""
        self.projects = {}  # key -> next issue number
        self.issues = {}  # key -> fields
        self.links = []  # (outward, inward)
        self.comments = {}  # key -> [text]
        self.requests = []  # (method, path)
        self.page_size = 100  # the most a search answers with, whatever is asked
        self.tokens = []  # the nextPageToken of each search that sent one
        self.no_way_to = set()  # status categories no transition reaches
        self.refuse_children = False  # whether a create under a parent is refused
        self.refuse_properties = False  # whether an issue property is refused
        self.cut = None  # a function of a property's method, name and body: True answers 503
        self.unreadable = None  # "all" or "children": issues made then answer 503 when read
        self.unread = set()  # the keys of the issues that answer 503 when read
        self.properties = {}  # key -> {property: value}, as Jira keeps entity properties
        self.no_myself = False  # whether the site will say who the token is
        self.no_issues = False  # whether a search answers without its list of issues

    def issue(self, key, wanted="", props=""):
        fields = self.issues.get(key)
        if fields is None:
            return None
        links = []
        for n, (outward, inward) in enumerate(self.links):
            if outward == key:
                links.append(
                    {"id": str(n), "type": {"name": "Blocks"}, "outwardIssue": {"key": inward}}
                )
            if inward == key:
                links.append(
                    {"id": str(n), "type": {"name": "Blocks"}, "inwardIssue": {"key": outward}}
                )
        shown = dict(
            fields,
            issuelinks=links,
            status={
                "name": fields["_status"],
                "statusCategory": {"key": STATUSES[fields["_status"]]},
            },
            comment={
                "comments": [
                    {
                        "body": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {"type": "paragraph", "content": [{"type": "text", "text": t}]}
                            ],
                        }
                    }
                    for t in self.comments.get(key, [])
                ]
            },
        )
        if fields.get("assignee"):
            who = fields["assignee"].get("accountId")
            shown["assignee"] = dict(fields["assignee"], displayName=ACCOUNTS.get(who))
        kept = {k: v for k, v in shown.items() if not k.startswith("_")}
        # A site answers with the fields asked for and no others.
        answer = {
            "key": key,
            "fields": {k: v for k, v in kept.items() if not wanted or k in wanted.split(",")},
        }
        held = self.properties.get(key) or {}
        asked = list(held) if props == "*all" else [p for p in props.split(",") if p in held]
        if asked:
            answer["properties"] = {p: held[p] for p in asked}
        return answer

    def handle(self, method, path, query, body):
        self.requests.append((method, path))
        parts = path.strip("/").split("/")
        if parts[:3] != ["rest", "api", "3"]:
            return 404, {"errorMessages": ["no such resource"]}
        rest = parts[3:]
        if rest == ["myself"]:
            if self.no_myself:
                return 401, {"errorMessages": ["You are not logged in."]}
            return 200, dict(MYSELF)
        if rest == ["serverInfo"]:
            return 200, {"version": "1001.0.0-stub", "deploymentType": "Cloud"}
        if rest[:1] == ["project"] and len(rest) == 2:
            self.projects.setdefault(rest[1], 1)
            return 200, {"key": rest[1], "name": "Project %s" % rest[1]}
        if rest == ["search"]:
            # What a site answers once the legacy endpoint has been removed.
            return 410, {
                "errorMessages": [
                    "The requested API has been removed. Please migrate to /rest/api/3/search/jql."
                ]
            }
        if rest == ["search", "jql"] and method == "GET":
            jql = query.get("jql", [""])[0]
            m = re.search(r"project = (\w+)", jql)
            if not m:
                return 400, {"errorMessages": ["Unbounded JQL queries are not allowed here."]}
            parent = re.search(r"parent = ([\w-]+)", jql)
            keys = [
                k
                for k, f in self.issues.items()
                if m
                and f["project"]["key"] == m.group(1)
                and (not parent or (f.get("parent") or {}).get("key") == parent.group(1))
            ]
            keys.sort(key=lambda k: self.issues[k]["created"])
            if self.no_issues:
                return 200, {}
            token = query.get("nextPageToken", [""])[0]
            if token:
                self.tokens.append(token)
            start = int(token[1:]) if token else 0
            size = min(int(query.get("maxResults", ["50"])[0]), self.page_size)
            page = keys[start : start + size]
            answer = {
                "issues": [
                    self.issue(k, query.get("fields", [""])[0], query.get("properties", [""])[0])
                    for k in page
                ],
                "isLast": start + size >= len(keys),
            }
            if not answer["isLast"]:
                answer["nextPageToken"] = "t%d" % (start + size)
            return 200, answer
        if rest == ["issue"] and method == "POST" and self.refuse_children:
            if body["fields"].get("parent"):
                return 400, {"errors": {"parent": "That parent cannot have children."}}
        if rest == ["issue"] and method == "POST":
            fields = (body or {}).get("fields") or {}
            project = (fields.get("project") or {}).get("key")
            if not project:
                return 400, {"errors": {"project": "project is required"}}
            parent = (fields.get("parent") or {}).get("key")
            if parent and parent not in self.issues:
                return 400, {"errors": {"parent": "Parent issue %s does not exist" % parent}}
            n = self.projects.setdefault(project, 1)
            self.projects[project] = n + 1
            key = "%s-%d" % (project, n)
            stamp = "2026-11-03T00:00:%02d.000+0000" % (len(self.issues) % 60)
            self.issues[key] = {
                "project": {"key": project},
                "summary": fields.get("summary", ""),
                "issuetype": {"name": (fields.get("issuetype") or {}).get("name", "Task")},
                "priority": {"name": (fields.get("priority") or {}).get("name", "Medium")},
                "labels": list(fields.get("labels") or []),
                "parent": {"key": parent} if parent else None,
                "description": fields.get("description"),
                "created": stamp,
                "updated": stamp,
                "_status": "To Do",
                "_order": len(self.issues),
            }
            self.issues[key]["created"] = "2026-11-03T00:%02d:%02d.000+0000" % divmod(
                self.issues[key]["_order"], 60
            )
            self.issues[key]["updated"] = self.issues[key]["created"]
            if self.unreadable == "all" or (self.unreadable == "children" and parent):
                self.unread.add(key)
            return 201, {"id": str(len(self.issues)), "key": key}
        if rest[:1] == ["issue"] and len(rest) == 2:
            key = rest[1]
            if key not in self.issues:
                return 404, {
                    "errorMessages": [
                        "Issue does not exist or you do not have permission to see it."
                    ]
                }
            if method == "GET" and key in self.unread:
                return 503, {"errorMessages": ["The service is unavailable."]}
            if method == "GET":
                return 200, self.issue(
                    key, query.get("fields", [""])[0], query.get("properties", [""])[0]
                )
            if method == "PUT":
                fields = (body or {}).get("fields") or {}
                for k, v in fields.items():
                    if k == "parent" and v and v.get("key") not in self.issues:
                        return 400, {"errors": {"parent": "no such parent"}}
                    if k == "assignee" and "name" in (v or {}):
                        return 400, {"errors": {"assignee": "name was removed; use accountId"}}
                    self.issues[key][k] = v
                return 204, None
        if rest[:1] == ["issue"] and len(rest) == 4 and rest[2] == "properties":
            key = rest[1]
            if key not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist"]}
            if method == "PUT" and self.refuse_properties:
                return 400, {"errorMessages": ["Properties are turned off here."]}
            if self.cut and self.cut(method, rest[3], body or {}):
                return 503, {"errorMessages": ["The service is unavailable."]}
            if method == "PUT":
                self.properties.setdefault(key, {})[rest[3]] = body
                return 200, None
            if method == "DELETE":
                if rest[3] not in self.properties.get(key, {}):
                    return 404, {"errorMessages": ["The property does not exist."]}
                del self.properties[key][rest[3]]
                return 204, None
        if rest[:1] == ["issue"] and len(rest) == 3 and rest[2] == "assignee" and method == "PUT":
            key = rest[1]
            if key not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist"]}
            if not (body or {}).get("accountId"):
                return 400, {"errorMessages": ["accountId is required"]}
            if body["accountId"] not in ACCOUNTS:
                return 404, {"errorMessages": ["The user does not exist."]}
            self.issues[key]["assignee"] = {"accountId": body["accountId"]}
            return 204, None
        if rest[:1] == ["issue"] and len(rest) == 3 and rest[2] == "transitions":
            key = rest[1]
            if key not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist"]}
            if method == "GET":
                return 200, {
                    "transitions": [
                        {
                            "id": str(i + 11),
                            "name": name,
                            "to": {"name": name, "statusCategory": {"key": cat}},
                        }
                        for i, (name, cat) in enumerate(STATUSES.items())
                        if cat not in self.no_way_to and name != self.issues[key]["_status"]
                    ]
                }
            if method == "POST":
                wanted = (body or {}).get("transition", {}).get("id")
                for i, name in enumerate(STATUSES):
                    if str(i + 11) == wanted:
                        self.issues[key]["_status"] = name
                        return 204, None
                return 400, {"errorMessages": ["no such transition"]}
        if rest[:1] == ["issue"] and len(rest) == 3 and rest[2] == "comment" and method == "POST":
            key = rest[1]
            if key not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist"]}
            doc = (body or {}).get("body") or {}
            text = "".join(
                leaf.get("text", "")
                for node in doc.get("content") or []
                for leaf in node.get("content") or []
            )
            self.comments.setdefault(key, []).append(text)
            return 201, {"id": str(len(self.comments[key]))}
        if rest == ["issueLink"] and method == "POST":
            outward = ((body or {}).get("outwardIssue") or {}).get("key")
            inward = ((body or {}).get("inwardIssue") or {}).get("key")
            if outward not in self.issues or inward not in self.issues:
                return 404, {"errorMessages": ["No issue could be found"]}
            if (outward, inward) not in self.links:
                self.links.append((outward, inward))
            return 201, None
        return 404, {"errorMessages": ["no such resource: %s %s" % (method, path)]}


class Handler(http.server.BaseHTTPRequestHandler):
    stub: StubJira

    def _answer(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return self._send(401, {"errorMessages": ["Basic auth required"]})
        who = base64.b64decode(auth[6:]).decode("utf-8", "replace")
        if not who.endswith(":" + TOKEN):
            return self._send(401, {"errorMessages": ["bad token"]})
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else None
        url = urllib.parse.urlsplit(self.path)
        status, answer = self.stub.handle(
            self.command, url.path, urllib.parse.parse_qs(url.query), body
        )
        self._send(status, answer)

    def _send(self, status, answer):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if answer is not None:
            self.wfile.write(json.dumps(answer).encode("utf-8"))

    do_GET = do_POST = do_PUT = do_DELETE = _answer

    def log_message(self, *args):
        pass


class Site:
    """The stub served on a loopback port, for one test."""

    def __init__(self):
        self.stub = StubJira()
        handler = type("StubHandler", (Handler,), {"stub": self.stub})
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Home:
    """A temporary home with the adapter installed by name, and a repository."""

    def __init__(self, site, project="CHK"):
        self.home = tempfile.mkdtemp(prefix="dotdiw-jira-home-")
        self.path = tempfile.mkdtemp(prefix="dotdiw-jira-repo-")
        os.makedirs(os.path.join(self.home, ".dotdiw", "trackers"))
        shutil.copy(ADAPTER, os.path.join(self.home, ".dotdiw", "trackers", "jira.py"))
        self.env = dict(
            os.environ,
            HOME=self.home,
            PATH="/usr/bin:/bin",
            JIRA_SITE=site.url,
            JIRA_EMAIL="tester@example.invalid",
            JIRA_API_TOKEN=TOKEN,
            JIRA_CHECK_PROJECT=project,
        )
        for k in ("BEADS_DIR", "DOTDIW_WITNESS", "DOTDIW_TRACKER"):
            self.env.pop(k, None)
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "Test"],
        ):
            subprocess.run(["git"] + args, cwd=self.path, capture_output=True)

    def close(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.path, ignore_errors=True)

    def dotdiw(self, *args, env=None):
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW] + list(args),
            cwd=self.path,
            env=env or self.env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr


def load_adapter():
    """The adapter as a module of this process, for what a test must interfere with."""
    loader = importlib.machinery.SourceFileLoader("jira_under_test", ADAPTER)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise ImportError(ADAPTER)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TheTable(unittest.TestCase):
    def test_it_says_which_interface_it_was_written_for(self):
        self.assertEqual(load_adapter().TRACKER["info"]["interface"], 4)

    def test_steps_that_share_an_id_pour_nothing(self):
        """Refused before Jira is asked: a pour answers one id per step."""
        pour = load_adapter().TRACKER["operations"]["operation.pour-steps"]
        out = pour(
            {
                "root": tempfile.gettempdir(),
                "formulaRef": "m",
                "title": "m",
                "steps": [{"id": "a", "title": "A"}, {"id": "a", "title": "A again"}],
            }
        )
        self.assertEqual((out["status"], out["reason"]), ("failed", "duplicate-step"), out)
        self.assertEqual(out["summary"], "Two steps share the id a, so nothing was poured.")


class TheHostedAdapter(unittest.TestCase):
    """Loaded by name from the home, checked against its declared project,
    and a checkout adopted on it; the stub sees only that project and no
    output carries the token."""

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)

    def installed_by_a_package(self):
        """The tool and the adapter laid out as Homebrew lays them out, with
        nothing under the home directory."""
        prefix = tempfile.mkdtemp(prefix="dotdiw-jira-prefix-")
        self.addCleanup(shutil.rmtree, prefix, True)
        tool = os.path.join(prefix, "bin", "dotdiw")
        shared = os.path.join(prefix, "share", "dotdiw", "trackers")
        os.makedirs(os.path.dirname(tool))
        os.makedirs(shared)
        shutil.copy(DOTDIW, tool)
        shutil.copy(ADAPTER, os.path.join(shared, "jira.py"))
        shutil.rmtree(os.path.join(self.home.home, ".dotdiw"))
        return tool, os.path.join(shared, "jira.py")

    def run_tool(self, tool, *args, env=None):
        p = subprocess.run(
            [sys.executable, "-I", tool] + list(args),
            cwd=self.home.path,
            env=env or self.home.env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def test_it_passes_the_check_from_where_a_package_puts_it(self):
        tool, path = self.installed_by_a_package()
        code, out = self.run_tool(tool, "tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^  jira\s+.*loaded, from %s$" % re.escape(path))
        code, out = self.run_tool(tool, "tracker", "check", "jira")
        self.assertEqual(code, 0, out)
        self.assertIn("\u2713 jira passed 11 of 11.", out)

    def test_it_is_listed_with_no_credentials_and_no_network(self):
        """What a package's test block sees under `brew test`."""
        tool, path = self.installed_by_a_package()
        env = {"HOME": self.home.home, "PATH": "/usr/bin:/bin"}
        before = len(self.site.stub.requests)
        code, out = self.run_tool(tool, "tracker", "list", env=env)
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"(?m)^  jira\s+.*loaded, from %s$" % re.escape(path))
        self.assertNotIn("did not load", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len(self.site.stub.requests), before, "nothing reached the site")

    def test_it_is_listed_from_the_home_and_passes_the_check(self):
        code, out = self.home.dotdiw("tracker", "list")
        self.assertEqual(code, 0, out)
        self.assertRegex(
            out,
            r"(?m)^  jira\s+0\.1, site 1001\.0\.0-stub\s+loaded, from .*/\.dotdiw/trackers/jira\.py$",
        )
        self.assertRegex(out, r"(?m)^  local\s+4\.0\.0\s+shipped\s+\(this checkout\)$")
        code, out = self.home.dotdiw("tracker", "check", "jira")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("  pass  operation."), 11, out)
        self.assertIn("✓ jira passed 11 of 11.", out)
        projects = {f["project"]["key"] for f in self.site.stub.issues.values()}
        self.assertEqual(projects, {"CHK"}, "the check fills its declared project and nothing else")
        self.assertNotIn(TOKEN, out)
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.home.home, ".dotdiw"))),
            ["trackers"],
            "the scratch workspace is gone",
        )

    def test_without_credentials_nothing_is_sent(self):
        env = dict(self.home.env)
        del env["JIRA_API_TOKEN"]
        code, out = self.home.dotdiw("tracker", "check", "jira", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn(
            "FAIL  operation.open-tracker: the first open makes the store: JIRA_SITE, JIRA_EMAIL and JIRA_API_TOKEN are not set",
            out,
        )
        self.assertEqual(self.site.stub.requests, [], "nothing left the machine")
        env["JIRA_API_TOKEN"] = "wrong"
        code, out = self.home.dotdiw("tracker", "check", "jira", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("Jira answered 401", out)
        self.assertNotIn("wrong", out)

    def test_a_checkout_on_jira(self):
        home, stub = self.home, self.site.stub
        env = dict(home.env, JIRA_CHECK_PROJECT="OTHER")
        code, out = home.dotdiw("init", "--tracker", "jira", "--prefix", "demo", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("✓ Adopted. The tracker is jira, under", out)
        self.assertEqual(sorted(os.listdir(home.path)), [".git", "AGENTS.md", "CLAUDE.md"])
        code, out = home.dotdiw("--version", env=env)
        self.assertEqual(out.strip().split("\n")[1], "  tracker jira 0.1, site 1001.0.0-stub")
        code, out = home.dotdiw("create", "Release v0.3.0 through the tap", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("✓ Created issue: DEMO-1 — Release v0.3.0 through the tap", out)
        code, out = home.dotdiw("create", "Fix the login redirect", "-p", "1", env=env)
        self.assertIn("DEMO-2", out)
        self.assertEqual(home.dotdiw("dep", "add", "DEMO-2", "DEMO-1", env=env)[0], 0)
        code, out = home.dotdiw("show", "DEMO-2", "--json", env=env)
        item = json.loads(out)
        self.assertEqual((item["needs"], item["priority"], item["status"]), (["DEMO-1"], 1, "open"))
        code, out = home.dotdiw("close", "DEMO-2", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("cannot close blocked issue: DEMO-2 is blocked by [DEMO-1]", out)
        code, out = home.dotdiw("close", "DEMO-1", "--reason", "shipped", env=env)
        self.assertEqual(code, 0, out)
        self.assertIn("✓ Closed DEMO-1 — Release v0.3.0 through the tap: shipped", out)
        self.assertEqual(stub.issues["DEMO-1"]["_status"], "Done")
        self.assertEqual(stub.comments["DEMO-1"], ["closed: shipped"])
        code, out = home.dotdiw("ready", env=env)
        self.assertIn("DEMO-2", out)
        self.assertIn("Ready: 1 issue with no active blockers", out)
        code, out = home.dotdiw("frobnicate", env=env)
        self.assertEqual(code, 1, out)
        self.assertIn("frobnicate is not a command of this tracker", out)
        self.assertEqual({f["project"]["key"] for f in stub.issues.values()}, {"DEMO"})
        self.assertNotIn(TOKEN, out)

    def adopted(self):
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)

    def made(self, *args):
        code, out = self.home.dotdiw("create", *args, "-q")
        self.assertEqual(code, 0, out)
        found = re.search(r"Created issue: (\S+)", out)
        assert found is not None, out
        return found.group(1)

    def test_a_search_uses_the_endpoint_jira_keeps_and_its_tokens(self):
        """The legacy search answers 410 on the stub, as on a site where it
        has been removed; a list longer than a page is read through tokens."""
        self.adopted()
        stub = self.site.stub
        stub.page_size = 2
        keys = [self.made("Work %d" % n) for n in range(5)]
        stub.requests.clear()
        code, out = self.home.dotdiw("list", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([i["id"] for i in json.loads(out)], keys)
        self.assertEqual(stub.tokens, ["t2", "t4"])
        self.assertIn(("GET", "/rest/api/3/search/jql"), stub.requests)
        self.assertNotIn(("GET", "/rest/api/3/search"), stub.requests)

    def test_a_second_open_changes_nothing(self):
        self.adopted()
        store = glob.glob(os.path.join(self.home.home, ".dotdiw", "*", "jira.json"))[0]
        code, out = self.home.dotdiw("init", "--prefix", "other")
        self.assertEqual(code, 0, out)
        with open(store, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["project"], "DEMO")
        self.assertIn("DEMO-1", self.made("Still here"))

    def test_formula_pour_pours_on_the_site(self):
        self.adopted()
        formula = "pour-new.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-pour-new"\n'
                'description = "Pour it. Use when testing formula pour on a hosted tracker."\n'
                '[[steps]]\nid = "one"\ntitle = "One"\n'
                '[[steps]]\nid = "two"\ntitle = "Two"\nneeds = ["one"]\n'
            )
        subprocess.run(["git", "add", formula], cwd=self.home.path, env=self.home.env)
        subprocess.run(["git", "commit", "-qm", "f"], cwd=self.home.path, env=self.home.env)
        code, out = self.home.dotdiw("formula", "pour", "mol-pour-new")
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"Root issue: DEMO-\d+")

    def test_a_pour_jira_refuses_partway_is_one_line(self):
        self.adopted()
        formula = "pour-it.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-pour-it"\n'
                'description = "Pour it. Use when testing a refusal partway through a pour."\n'
                '[[steps]]\nid = "one"\ntitle = "One"\n'
                '[[steps]]\nid = "two"\ntitle = "Two"\nneeds = ["one"]\n'
            )
        subprocess.run(["git", "add", formula], cwd=self.home.path, env=self.home.env)
        subprocess.run(["git", "commit", "-qm", "f"], cwd=self.home.path, env=self.home.env)
        stub = self.site.stub
        stub.refuse_children = True
        code, out = self.home.dotdiw("mol", "pour", "mol-pour-it")
        stub.refuse_children = False
        self.assertEqual(code, 1, out)
        self.assertIn("That parent cannot have children", out)
        self.assertRegex(out, r"Poured 0 of 2 steps under DEMO-\d+, and the next failed: ")
        self.assertNotIn("DoorError", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)

    def test_a_pour_names_what_jira_made_and_could_not_read_back(self):
        """Jira makes the root, or then a step, and answers 503 when it is read
        back: the pour fails, and its record and its line name what Jira made."""
        self.adopted()
        formula = "pour-unread.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-pour-unread"\n'
                'description = "Pour it. Use when testing a read that fails after a create."\n'
                '[[steps]]\nid = "one"\ntitle = "One"\n'
                '[[steps]]\nid = "two"\ntitle = "Two"\nneeds = ["one"]\n'
            )
        subprocess.run(["git", "add", formula], cwd=self.home.path, env=self.home.env)
        subprocess.run(["git", "commit", "-qm", "f"], cwd=self.home.path, env=self.home.env)
        stub = self.site.stub
        for unreadable, made in (("all", 0), ("children", 1)):
            with self.subTest(unreadable=unreadable):
                stub.unreadable = unreadable
                p = subprocess.run(
                    [sys.executable, "-I", DOTDIW, "formula", "pour", "mol-pour-unread", "--json"],
                    cwd=self.home.path,
                    env=self.home.env,
                    capture_output=True,
                    text=True,
                )
                stub.unreadable = None
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                record = json.loads(p.stdout)
                self.assertRegex(record["rootId"], r"^DEMO-\d+$")
                self.assertEqual(len(record["stepIds"]), made, record)
                last = (record["stepIds"] or [record["rootId"]])[-1]
                self.assertIn("Jira made %s and could not read it back" % last, p.stderr)
                self.assertIn(record["rootId"], p.stderr)

    def test_a_pour_whose_claim_jira_cannot_keep_names_what_it_made(self):
        """Jira makes a claimed step and refuses its property: the pour fails,
        and its record and its line name the root and the step Jira made."""
        self.adopted()
        formula = "pour-claimed.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-pour-claimed"\n'
                'description = "Pour it. Use when testing a claim Jira cannot keep."\n'
                '[[steps]]\nid = "count"\ntitle = "Count"\n'
                '[steps.claim]\nstatement = "Counted {{ n }}."\n"n:" = {}\n'
            )
        subprocess.run(["git", "add", formula], cwd=self.home.path, env=self.home.env)
        subprocess.run(["git", "commit", "-qm", "f"], cwd=self.home.path, env=self.home.env)
        stub = self.site.stub
        stub.refuse_properties = True
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "formula", "pour", "mol-pour-claimed", "--json"],
            cwd=self.home.path,
            env=self.home.env,
            capture_output=True,
            text=True,
        )
        stub.refuse_properties = False
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        record = json.loads(p.stdout)
        self.assertEqual(len(record["stepIds"]), 1, record)
        self.assertIn("Jira made %s and could not keep its claim" % record["stepIds"][0], p.stderr)
        self.assertIn(record["rootId"], p.stderr)

    def test_a_create_names_what_jira_made_and_could_not_read_back(self):
        self.adopted()
        stub = self.site.stub
        stub.unreadable = "all"
        code, out = self.home.dotdiw("create", "Made and not read back")
        stub.unreadable = None
        self.assertEqual(code, 1, out)
        self.assertRegex(out, r"Jira made DEMO-\d+ and could not read it back: Jira answered 503")
        self.assertEqual(len(out.strip().splitlines()), 1, out)

    def test_a_close_with_no_way_to_done_is_refused(self):
        """No transition reaches done: nothing is reported closed, the issue
        keeps its status, and no reason is written on it."""
        self.adopted()
        stub = self.site.stub
        key = self.made("Stuck")
        stub.no_way_to = {"done"}
        code, out = self.home.dotdiw("close", key, "--reason", "tried")
        self.assertEqual(code, 1, out)
        self.assertNotIn("Closed", out)
        self.assertIn("%s has no transition to done" % key, out)
        self.assertEqual(stub.issues[key]["_status"], "To Do")
        self.assertEqual(stub.comments.get(key), None)
        stub.no_way_to = set()
        code, out = self.home.dotdiw("close", key, "--reason", "tried")
        self.assertEqual(code, 0, out)
        self.assertEqual(stub.issues[key]["_status"], "Done")
        self.assertEqual(stub.comments[key], ["closed: tried"])

    def test_a_step_closes_though_its_root_has_no_way_to_done(self):
        """The step closed; the root is the one left open, and is not named."""
        self.adopted()
        stub = self.site.stub
        patcher = mock.patch.dict(
            os.environ,
            {k: self.home.env[k] for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN", "HOME")},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        ask = load_adapter()
        poured = ask.jira_pour(
            {
                "root": self.home.path,
                "formulaRef": "mol-x",
                "title": "mol-x",
                "steps": [{"id": "a", "title": "A"}],
            }
        )
        self.assertEqual(poured["status"], "completed", poured)
        real = ask.transition_to

        def only_the_step(key, category):
            return real(key, category) if key != poured["rootId"] else False

        ask.transition_to = only_the_step
        closed = ask.jira_close({"root": self.home.path, "id": poured["stepIds"][0]})
        self.assertEqual(closed["status"], "completed", closed)
        self.assertEqual(closed["closedIds"], [poured["stepIds"][0]])
        self.assertEqual(stub.issues[poured["rootId"]]["_status"], "To Do")

    def test_a_writer_of_other_labels_keeps_what_it_recorded(self):
        """One writer reads the step, another records a different label, then
        the first records its own: both labels are kept."""
        self.adopted()
        patcher = mock.patch.dict(
            os.environ,
            {k: self.home.env[k] for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN", "HOME")},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        ask = load_adapter()
        claim = {"statement": "{{ n }} {{ m }}", "slots": ["n", "m"]}
        poured = ask.jira_pour(
            {
                "root": self.home.path,
                "formulaRef": "mol-x",
                "title": "mol-x",
                "steps": [{"id": "a", "title": "A", "claim": claim}],
            }
        )
        self.assertEqual(poured["status"], "completed", poured)
        step = poured["stepIds"][0]
        real = ask.fetch
        done: list[int] = []

        def read_then_the_other_writes(key):
            issue = real(key)
            if not done:
                done.append(key)
                other = ask.jira_record_values(
                    {"root": self.home.path, "id": step, "values": [{"label": "m", "text": "2"}]}
                )
                self.assertEqual(other["status"], "completed", other)
            return issue

        ask.fetch = read_then_the_other_writes
        out = ask.jira_record_values(
            {"root": self.home.path, "id": step, "values": [{"label": "n", "text": "1"}]}
        )
        ask.fetch = real
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual(sorted(v["label"] for v in out["item"]["values"]), ["m", "n"])

    ROSTER = (
        'formula = "mol-roster"\n'
        'description = "Check a roster. Use when testing a write Jira cuts short."\n'
        'verify-using = ["run:check-roster {{ count.roster-id }} {{ count.capacity }}"]\n'
        '[[steps]]\nid = "count"\ntitle = "Count"\n'
        '[steps.claim]\nstatement = "Roster {{ roster-id }} covers {{ capacity }}."\n'
        '"roster-id:" = {}\n"capacity:" = {}\n'
    )

    def claim(self, *args):
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "claim"] + list(args),
            cwd=self.home.path,
            env=self.home.env,
            input="",
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout, p.stderr

    def roster(self):
        """A run of one claimed step, roster 42 covering 80 recorded whole."""
        self.adopted()
        with open(os.path.join(self.home.path, "roster.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(self.ROSTER)
        subprocess.run(["git", "add", "-A"], cwd=self.home.path, env=self.home.env)
        subprocess.run(["git", "commit", "-qm", "f"], cwd=self.home.path, env=self.home.env)
        code, out = self.home.dotdiw("formula", "pour", "mol-roster")
        self.assertEqual(code, 0, out)
        step = re.search(r"dotdiw claim (\S+) ", out)
        assert step is not None, out
        code, out, err = self.claim(step.group(1), "roster-id: 42", "capacity: 80")
        self.assertEqual(code, 0, out + err)
        return step.group(1)

    def cut_short(self, step, cut, *lines):
        """The run as read after a claim Jira cut short where cut says."""
        self.site.stub.cut = cut
        code, out, err = self.claim(step, *lines)
        self.site.stub.cut = None
        self.assertEqual(code, 1, out + err)
        code, out, err = self.claim(step, "--json")
        self.assertEqual(code, 0, out + err)
        run = json.loads(out)
        return run["steps"][0]["values"], run["open"]

    def test_a_write_jira_refuses_reads_as_it_was(self):
        """Jira answers 503 for a write of roster 7 covering 65: the run reads
        roster 42 covering 80, whole, as it was."""
        step = self.roster()
        self.assertEqual(
            self.cut_short(
                step,
                lambda method, name, body: (
                    {"label": "capacity", "text": "65"} in (body.get("values") or [])
                ),
                "roster-id: 7",
                "capacity: 65",
            ),
            ([{"label": "roster-id", "text": "42"}, {"label": "capacity", "text": "80"}], []),
        )

    def in_process(self):
        """The adapter in this process, and a step of roster and capacity
        poured through it, for a test that must interleave two writers."""
        self.adopted()
        patcher = mock.patch.dict(
            os.environ,
            {k: self.home.env[k] for k in ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN", "HOME")},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        ask = load_adapter()
        claim = {"statement": "{{ roster-id }} {{ capacity }}", "slots": ["roster-id", "capacity"]}
        poured = ask.jira_pour(
            {
                "root": self.home.path,
                "formulaRef": "mol-x",
                "title": "mol-x",
                "steps": [{"id": "a", "title": "A", "claim": claim}],
            }
        )
        self.assertEqual(poured["status"], "completed", poured)
        return ask, poured["stepIds"][0]

    def recorded(self, ask, step, roster, capacity):
        return ask.jira_record_values(
            {
                "root": self.home.path,
                "id": step,
                "values": [
                    {"label": "roster-id", "text": roster},
                    {"label": "capacity", "text": capacity},
                ],
            }
        )

    def overlapped(self, ask, step, first, second):
        """The second write read, then the first written whole, then the
        second: what the item holds after."""
        real = ask.fetch
        done: list[str] = []

        def read_then_the_other_writes(key):
            issue = real(key)
            if not done:
                done.append(key)
                self.assertEqual(self.recorded(ask, step, *first)["status"], "completed")
            return issue

        ask.fetch = read_then_the_other_writes
        try:
            out = self.recorded(ask, step, *second)
        finally:
            ask.fetch = real
        return out, [v["text"] for v in ask.record(real(step)).get("values") or []]

    def test_a_write_cut_short_beside_another_leaves_that_one_whole(self):
        """One writer records roster 9 covering 90 while another, overlapping
        it, fails recording 7 covering 65: the step reads 9 and 90, never 7
        beside 90."""
        ask, step = self.in_process()
        self.site.stub.cut = lambda method, name, body: (
            {"label": "capacity", "text": "65"} in (body.get("values") or [])
        )
        out, held = self.overlapped(ask, step, ("9", "90"), ("7", "65"))
        self.site.stub.cut = None
        self.assertEqual(out["status"], "failed", out)
        self.assertEqual(held, ["9", "90"])

    def test_writes_of_the_same_labels_at_once_leave_one_whole(self):
        ask, step = self.in_process()
        out, held = self.overlapped(ask, step, ("9", "90"), ("7", "65"))
        self.assertEqual(out["status"], "completed", out)
        self.assertIn(held, (["9", "90"], ["7", "65"]))

    def test_the_last_step_closes_the_root_of_its_run_wherever_it_stands(self):
        """A step moved under another run's root closes its own run's root
        when it is that run's last open step, and leaves the other open."""
        ask, step = self.in_process()
        root = ask.record(ask.fetch(step))["run"]
        other = ask.jira_pour(
            {
                "root": self.home.path,
                "formulaRef": "mol-y",
                "title": "mol-y",
                "steps": [{"id": "b", "title": "B"}],
            }
        )
        self.assertEqual(other["status"], "completed", other)
        moved = ask.jira_update({"root": self.home.path, "id": step, "parent": other["rootId"]})
        self.assertEqual(moved["status"], "completed", moved)
        closed = ask.jira_close({"root": self.home.path, "id": step})
        self.assertEqual(closed["closedIds"], [step, root])
        self.assertEqual(ask.record(ask.fetch(other["rootId"]))["status"], "open")

    def test_a_search_that_answers_no_list_of_issues_is_no_empty_one(self):
        """What stands open under a root is read from Jira's search. An answer
        without its list of issues is a failed read, not a project holding
        nothing: the root is not closed over its open step, and the listing
        fails."""
        ask, step = self.in_process()
        root = ask.record(ask.fetch(step))["run"]
        self.site.stub.no_issues = True
        try:
            closed = ask.jira_close({"root": self.home.path, "id": root})
            listed = ask.jira_list({"root": self.home.path, "scope": "all"})
        finally:
            self.site.stub.no_issues = False
        self.assertEqual((closed["status"], closed.get("closedIds")), ("failed", None), closed)
        self.assertIn("no list of issues", closed["summary"])
        self.assertEqual(listed["status"], "failed", listed)
        self.assertEqual(ask.record(ask.fetch(root))["status"], "open")
        self.assertEqual(
            [i["id"] for i in ask.jira_list({"root": self.home.path, "scope": "all"})["items"]],
            [root, step],
        )

    def test_a_write_is_read_after_every_write_the_step_held(self):
        """A write named for a moment ahead of this clock is still read before
        the one made after it."""
        ask, step = self.in_process()
        ahead = 32503680000 * 1000000  # 3000-01-01, in microseconds
        self.site.stub.properties.setdefault(step, {})["dotdiw.write.%020d.ffffffff" % ahead] = {
            "values": [{"label": "roster-id", "text": "1"}]
        }
        out = self.recorded(ask, step, "2", "20")
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual([v["text"] for v in out["item"]["values"]], ["2", "20"])

    def test_an_update_with_no_way_to_the_status_is_refused(self):
        self.adopted()
        stub = self.site.stub
        key = self.made("Stuck")
        stub.no_way_to = {"indeterminate"}
        code, out = self.home.dotdiw("update", key, "-s", "in_progress", "--title", "Renamed")
        self.assertEqual(code, 1, out)
        self.assertIn("%s has no transition to in_progress" % key, out)
        self.assertEqual(stub.issues[key]["_status"], "To Do")
        self.assertEqual(stub.issues[key]["summary"], "Stuck", "nothing else changed either")
        stub.requests.clear()
        code, out = self.home.dotdiw("update", key, "-s", "open")
        self.assertEqual(code, 0, out)
        self.assertNotIn(("POST", "/rest/api/3/issue/%s/transitions" % key), stub.requests)

    def test_priority_zero_is_kept(self):
        self.adopted()
        key = self.made("Urgent", "-p", "0")
        self.assertEqual(self.site.stub.issues[key]["priority"], {"name": "Highest"})
        code, out = self.home.dotdiw("show", key, "--json")
        self.assertEqual(json.loads(out)["priority"], 0)

    def test_an_assignee_is_an_account_id(self):
        self.adopted()
        stub = self.site.stub
        key = self.made("Theirs")
        code, out = self.home.dotdiw("update", key, "-a", "5b10ac8d82e05b22cc7d4ef5")
        self.assertEqual(code, 0, out)
        self.assertEqual(stub.issues[key]["assignee"], {"accountId": "5b10ac8d82e05b22cc7d4ef5"})
        self.assertIn(("PUT", "/rest/api/3/issue/%s/assignee" % key), stub.requests)

    def test_an_assignee_of_me_is_the_account_behind_the_token(self):
        self.adopted()
        stub = self.site.stub
        key = self.made("Mine")
        code, out = self.home.dotdiw("update", key, "-a", "me")
        self.assertEqual(code, 0, out)
        self.assertEqual(stub.issues[key]["assignee"], {"accountId": MYSELF["accountId"]})
        code, out = self.home.dotdiw("show", key)
        self.assertEqual(code, 0, out)
        self.assertIn("Assignee: Stub Person\n", out)
        code, out = self.home.dotdiw("list", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([i["assignee"] for i in json.loads(out)], ["Stub Person"])

    def test_an_id_it_does_not_know_is_one_line_and_changes_nothing(self):
        self.adopted()
        stub = self.site.stub
        key = self.made("Theirs")
        code, out = self.home.dotdiw("update", key, "-a", "alice")
        self.assertEqual(code, 1, out)
        self.assertIn("The user does not exist", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(len(out.strip().splitlines()), 1, out)
        self.assertNotIn("assignee", stub.issues[key])

    def test_init_names_the_account_once_and_never_its_email(self):
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)
        self.assertIn("  Acting as Stub Person.\n", out)
        self.assertNotIn(MYSELF["emailAddress"], out)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)
        self.assertNotIn("Acting as", out)

    def test_tracker_use_names_the_account_and_never_its_email(self):
        self.adopted()
        code, out = self.home.dotdiw("tracker", "use", "jira")
        self.assertEqual(code, 0, out)
        self.assertIn("tracker is jira.\n  Acting as Stub Person.\n", out)
        self.assertNotIn(MYSELF["emailAddress"], out)

    def test_a_site_that_will_not_say_who_leaves_the_line_out(self):
        self.site.stub.no_myself = True
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)
        self.assertIn("Adopted. The tracker is jira", out)
        self.assertNotIn("Acting as", out)
        code, out = self.home.dotdiw("--version")
        self.assertEqual(code, 0, out)
        self.assertIn("tracker jira", out)

    def test_a_description_reaches_the_issue(self):
        self.adopted()
        key = self.made("Described", "-d", "Why this work exists")
        self.assertIn("Why this work exists", json.dumps(self.site.stub.issues[key]["description"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
