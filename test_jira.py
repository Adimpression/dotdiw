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
import contextlib
import datetime
import errno
import glob
import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from typing import TYPE_CHECKING, Any
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


def jql_groups(jql):
    """The groups of a JQL query joined by OR, as Jira reads them: outside a
    quoted value, and before its ORDER BY."""
    groups, start, quoted, i = [], 0, False, 0
    while i < len(jql):
        if quoted and jql[i] == "\\":
            i += 2
            continue
        if jql[i] == '"':
            quoted = not quoted
        elif not quoted and jql.startswith(" OR ", i):
            groups.append(jql[start:i])
            start = i = i + 4
            continue
        elif not quoted and jql.startswith(" ORDER BY ", i):
            break
        i += 1
    groups.append(jql[start:i])
    return groups


def jql_value(field, group):
    """The value a group of a JQL query gives the field, quoted or bare, as
    Jira reads it; None where it gives none."""
    m = re.search(r'\b%s = (?:"((?:[^"\\]|\\.)*)"|([\w-]+))' % field, group)
    if not m:
        return None
    return re.sub(r"\\(.)", r"\1", m.group(1)) if m.group(1) is not None else m.group(2)


class StubJira:
    """Jira Cloud's REST API v3, the parts the adapter calls, in memory."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Empty, as at the start: what a test does between adapters."""
        self.projects = {}  # key -> next issue number
        self.issues = {}  # key -> fields
        self.links = []  # (outward, inward)
        self.link_ids = {}  # (outward, inward) -> the id Jira gives the link, kept while it stands
        self.comments = {}  # key -> [text]
        self.comment_at = {}  # key -> [the moment each comment was written]
        self.ticks = 0  # the moments the stub writes, one apart
        self.changelog = {}  # key -> [each change of status: when, and from and to which]
        self.requests = []  # (method, path)
        self.page_size = 100  # the most a search answers with, whatever is asked
        self.tokens = []  # the nextPageToken of each search that sent one
        self.no_way_to = set()  # status categories no transition reaches
        self.refuse_children = False  # whether a create under a parent is refused
        self.refuse_properties = False  # whether an issue property is refused
        self.cut = None  # a function of a property's method, name and body: True answers 503
        self.unreadable = None  # "all" or "children": issues made then answer 503 when read
        self.unread = set()  # the keys of the issues that answer 503 when read
        # The keys whose lookup answers 404 while a search still finds them, as
        # Jira's does for a while after an issue is deleted, or is no longer
        # the token's to see.
        self.gone = set()
        self.properties = {}  # key -> {property: value}, as Jira keeps entity properties
        self.no_myself = False  # whether the site will say who the token is
        self.no_issues = False  # whether a search answers without its list of issues
        self.held = None  # a function of each request's method and path, run before it is answered
        # What a search is behind on, as Jira's is for a while after a write, a
        # read by key never: an issue's key with None, which no search finds
        # yet, or with the fields a search still shows of it -- its
        # properties among them under _properties.
        self.lagging = {}

    def issue(self, key, wanted="", props="", stale=None):
        fields = self.issues.get(key)
        if fields is None:
            return None
        fields = dict(fields, **(stale or {}))
        links = []
        for outward, inward in self.links:
            n = self.link_ids.setdefault((outward, inward), str(len(self.link_ids) + 1))
            if outward == key:
                links.append({"id": n, "type": {"name": "Blocks"}, "outwardIssue": {"key": inward}})
            if inward == key:
                links.append({"id": n, "type": {"name": "Blocks"}, "inwardIssue": {"key": outward}})
        times = self.comment_at.get(key, [])
        shown = dict(
            fields,
            issuelinks=fields.get("issuelinks", links),  # a search's, where it lags
            status={
                "name": fields["_status"],
                "statusCategory": {"key": STATUSES[fields["_status"]]},
            },
            comment={
                "comments": [
                    dict(
                        {
                            "body": {
                                "type": "doc",
                                "version": 1,
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": t}]}
                                ],
                            }
                        },
                        **(
                            {"created": self.at(times[n])}
                            if n < len(times) and times[n] is not None
                            else {}
                        ),
                    )
                    for n, t in enumerate(self.comments.get(key, []))
                ]
            },
        )
        if "_changed" in fields:
            shown["statuscategorychangedate"] = self.at(fields["_changed"])
        if fields.get("assignee"):
            who = fields["assignee"].get("accountId")
            shown["assignee"] = dict(fields["assignee"], displayName=ACCOUNTS.get(who))
        kept = {k: v for k, v in shown.items() if not k.startswith("_")}
        # A site answers with the fields asked for and no others.
        answer = {
            "key": key,
            "fields": {k: v for k, v in kept.items() if not wanted or k in wanted.split(",")},
        }
        held = (stale or {}).get("_properties", self.properties.get(key)) or {}
        asked = list(held) if props == "*all" else [p for p in props.split(",") if p in held]
        if asked:
            answer["properties"] = {p: held[p] for p in asked}
        return answer

    def tick(self):
        self.ticks += 1
        return self.ticks

    @staticmethod
    def at(tick):
        """A moment as Jira writes one."""
        when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC) + datetime.timedelta(seconds=tick)
        return when.strftime("%Y-%m-%dT%H:%M:%S.000+0000")

    def handle(self, method, path, query, body):
        self.requests.append((method, path))
        if self.held is not None:
            self.held(method, path)
        # Each part of the path as it was sent, a quoted character read back.
        parts = [urllib.parse.unquote(part) for part in path.strip("/").split("/")]
        if parts[:3] != ["rest", "api", "3"]:
            return 404, {"errorMessages": ["no such resource"]}
        rest = parts[3:]
        if rest[:1] == ["issue"] and len(rest) > 1 and rest[1] not in self.issues:
            # Jira reads an issue's key in any case, and answers with the issue's own.
            rest = (
                ["issue"] + [k for k in self.issues if k.lower() == rest[1].lower()][:1] + rest[2:]
            )
            rest = rest if len(rest) > 1 and rest[1] in self.issues else parts[3:]
        if rest == ["myself"]:
            if self.no_myself:
                return 401, {"errorMessages": ["You are not logged in."]}
            return 200, dict(MYSELF)
        if rest == ["user"] and method == "GET":
            who = query.get("accountId", [""])[0]
            if who not in ACCOUNTS:
                return 404, {"errorMessages": ["The user does not exist."]}
            return 200, {"accountId": who, "displayName": ACCOUNTS[who]}
        if rest[:1] == ["status"] and len(rest) == 2 and method == "GET":
            if rest[1] not in STATUSES:
                return 404, {"errorMessages": ["No status with id %s." % rest[1]]}
            return 200, {"name": rest[1], "statusCategory": {"key": STATUSES[rest[1]]}}
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
            groups = [
                (jql_value("project", g), jql_value("parent", g))
                for g in jql_groups(query.get("jql", [""])[0])
            ]
            if not all(project or parent for project, parent in groups):
                # A query needs a restriction of the issues it searches.
                return 400, {"errorMessages": ["Unbounded JQL queries are not allowed here."]}
            # A search finds an issue by what it still shows of it.
            keys = [
                k
                for k, f in (
                    (k, dict(f, **(self.lagging.get(k) or {}))) for k, f in self.issues.items()
                )
                if any(
                    (project is None or f["project"]["key"].lower() == project.lower())
                    and (
                        parent is None
                        or ((f.get("parent") or {}).get("key") or "").lower() == parent.lower()
                    )
                    for project, parent in groups
                )
            ]
            keys = [k for k in keys if self.lagging.get(k, {}) is not None]
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
                    self.issue(
                        k,
                        query.get("fields", [""])[0],
                        query.get("properties", [""])[0],
                        self.lagging.get(k),
                    )
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
        if rest == ["issue"] and method == "POST" and (body or {}).get("update"):
            # Jira takes one link in a create at most, and the stub models
            # none: the adapter links an issue after it is made.
            return 400, {"errors": {"update": "The stub models no update in a create."}}
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
            # Jira's create takes the issue's properties in the same request.
            for prop in (body or {}).get("properties") or []:
                self.properties.setdefault(key, {})[prop["key"]] = prop["value"]
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
            if method == "GET" and key in self.gone:
                return 404, {
                    "errorMessages": [
                        "Issue does not exist or you do not have permission to see it."
                    ]
                }
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
            if "accountId" not in (body or {}):
                return 400, {"errorMessages": ["accountId is required"]}
            if body["accountId"] is None:  # as Jira reads it: no one
                self.issues[key]["assignee"] = None
                return 204, None
            if body["accountId"] not in ACCOUNTS:
                return 404, {"errorMessages": ["The user does not exist."]}
            self.issues[key]["assignee"] = {"accountId": body["accountId"]}
            return 204, None
        if rest[:1] == ["issue"] and len(rest) == 3 and rest[2] == "changelog" and method == "GET":
            if rest[1] not in self.issues:
                return 404, {"errorMessages": ["Issue does not exist"]}
            start = int(query.get("startAt", ["0"])[0])
            values = self.changelog.get(rest[1], [])[start:]
            return 200, {"startAt": start, "values": values, "isLast": True}
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
                        was = self.issues[key]["_status"]
                        now = self.tick()
                        if STATUSES[name] != STATUSES[was]:
                            self.issues[key]["_changed"] = now
                        # A status's id stands for it here, as its name: GET
                        # status reads either.
                        change = {"field": "status", "from": was, "to": name}
                        self.changelog.setdefault(key, []).append(
                            {"created": self.at(now), "items": [change]}
                        )
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
            times = self.comment_at.setdefault(key, [])
            times.extend([None] * (len(self.comments[key]) - 1 - len(times)))
            times.append(self.tick())
            return 201, {"id": str(len(self.comments[key]))}
        if rest == ["issueLink"] and method == "POST":
            outward = ((body or {}).get("outwardIssue") or {}).get("key")
            inward = ((body or {}).get("inwardIssue") or {}).get("key")
            if outward not in self.issues or inward not in self.issues:
                return 404, {"errorMessages": ["No issue could be found"]}
            if (outward, inward) not in self.links:
                self.links.append((outward, inward))
            return 201, None
        if rest[:1] == ["issueLink"] and len(rest) == 2 and method == "DELETE":
            for link in self.links:
                if self.link_ids.get(link) == rest[1]:
                    self.links.remove(link)
                    return 204, None
            return 404, {"errorMessages": ["No issue link with id %s" % rest[1]]}
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

    def test_a_site_spelled_with_the_port_its_scheme_takes_is_the_same_site(self):
        """https://x:443 is https://x, as http://x:80 is http://x, however its
        scheme and host are cased: the site that where the checkout's items
        are (storeId), and what was written there of late, are named by. A
        port of another is another site."""
        adapter = load_adapter()

        def site(spelled):
            env = {"JIRA_SITE": spelled, "JIRA_EMAIL": "e@example.invalid", "JIRA_API_TOKEN": TOKEN}
            with mock.patch.dict(os.environ, env):
                cfg = adapter.config()
            assert cfg is not None
            return cfg[0]

        for spelled, wanted in (
            ("https://jira.invalid:443", "https://jira.invalid"),
            ("HTTPS://JIRA.invalid:443/", "https://jira.invalid"),
            ("http://jira.invalid:80", "http://jira.invalid"),
            ("https://jira.invalid:8443", "https://jira.invalid:8443"),
            ("http://jira.invalid:443", "http://jira.invalid:443"),
        ):
            self.assertEqual(site(spelled), wanted, spelled)


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
        self.assertRegex(out, r"(?m)^  local\s+4\.2\.1\s+shipped\s+\(this checkout\)$")
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

    def test_an_update_refused_for_its_status_keeps_the_needs_it_was_to_take_off(self):
        """A needs B, and a workflow has no way to in progress: an update to
        in progress that would take the need off is refused for its status,
        writes nothing to Jira, and A needs B still."""
        ask, _ = self.in_process()
        root = self.home.path
        a, b = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("A", "B"))
        self.assertEqual(ask.jira_need({"root": root, "id": a, "needs": b})["status"], "completed")
        stub = self.site.stub
        stub.no_way_to = {"indeterminate"}
        stub.requests.clear()
        out = ask.jira_update({"root": root, "id": a, "status": "in_progress", "dropNeeds": [b]})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "bad-status"), out)
        self.assertEqual([r for r in stub.requests if r[0] != "GET"], [])
        self.assertEqual(ask.record(ask.fetch(a))["needs"], [b])

    def test_a_parent_that_waits_on_the_issue_is_refused_unless_the_need_it_waits_through_comes_off(
        self,
    ):
        """B stands under A, so A waits on B: A under B is refused as a cycle,
        and nothing is written. X needs P: X under P is refused too, but
        given with the need taken off, nothing waits on itself, and X stands
        under P waiting on nothing."""
        ask, _ = self.in_process()
        root = self.home.path
        a = ask.jira_create({"root": root, "title": "A"})["item"]["id"]
        b = ask.jira_create({"root": root, "title": "B", "parent": a})["item"]["id"]
        stub = self.site.stub
        stub.requests.clear()
        out = ask.jira_update({"root": root, "id": a, "parent": b})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)
        self.assertEqual([r for r in stub.requests if r[0] != "GET"], [])
        self.assertIsNone(ask.record(ask.fetch(a))["parent"])
        p, x = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("P", "X"))
        self.assertEqual(ask.jira_need({"root": root, "id": x, "needs": p})["status"], "completed")
        out = ask.jira_update({"root": root, "id": x, "parent": p})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)
        out = ask.jira_update({"root": root, "id": x, "parent": p, "dropNeeds": [p]})
        self.assertEqual(out["status"], "completed", out)
        shown = ask.record(ask.fetch(x))
        self.assertEqual((shown["parent"], shown["needs"]), (p, []))

    def test_an_issue_taken_from_under_its_parent_stands_under_none(self):
        """dropParent takes an issue from under its parent: Jira is written
        no parent, and the issue reads back under none. A parent given empty
        is none given, and a parent given with dropParent is refused, nothing
        written."""
        ask, _ = self.in_process()
        root = self.home.path
        top = ask.jira_create({"root": root, "title": "Top"})["item"]["id"]
        child = ask.jira_create({"root": root, "title": "Child", "parent": top})["item"]["id"]
        stub = self.site.stub
        stub.requests.clear()
        out = ask.jira_update({"root": root, "id": child, "parent": top, "dropParent": True})
        self.assertEqual(out["status"], "failed", out)
        self.assertEqual([r for r in stub.requests if r[0] != "GET"], [])
        out = ask.jira_update({"root": root, "id": child, "parent": "", "title": "Child"})
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual(ask.record(ask.fetch(child))["parent"], top)
        out = ask.jira_update({"root": root, "id": child, "dropParent": True})
        self.assertEqual(out["status"], "completed", out)
        self.assertIsNone(ask.record(ask.fetch(child))["parent"])
        self.assertIsNone(stub.issues[child]["parent"])

    def wrapped(self, answer):
        """The stub, answering as answer(method, path, body, real) does,
        where real answers as the stub would."""
        stub = self.site.stub
        real = stub.handle

        def handle(method, path, query, body):
            return answer(method, path, body, lambda: real(method, path, query, body))

        return mock.patch.object(stub, "handle", handle)

    def test_an_update_refused_writes_none_of_what_it_was_given(self):
        """An update Jira refuses part of writes none of the rest: a person
        Jira knows nothing of, asked with a new title; a parent Jira will not
        take the issue from, asked with a status, a need to take off and a
        person, whom it puts back; and a parent Jira keeps though it answers
        as if it took it off, asked with a new title. Each is refused, and
        the issue stands as it was."""
        ask, _ = self.in_process()
        root = self.home.path
        top = ask.jira_create({"root": root, "title": "Top"})["item"]["id"]
        n = ask.jira_create({"root": root, "title": "N"})["item"]["id"]
        c = ask.jira_create({"root": root, "title": "C", "parent": top})["item"]["id"]
        self.assertEqual(ask.jira_need({"root": root, "id": c, "needs": n})["status"], "completed")
        stub = self.site.stub

        def as_it_was():
            shown = ask.record(ask.fetch(c))
            return (
                shown["title"],
                shown["status"],
                shown["parent"],
                shown["needs"],
                shown["assignee"],
            )

        was = as_it_was()
        stub.requests.clear()
        out = ask.jira_update({"root": root, "id": c, "title": "C v2", "assignee": "nobody"})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "assignee-not-found"), out)
        self.assertEqual(
            [r for r in stub.requests if r[0] != "GET"],
            [("PUT", "/rest/api/3/issue/%s/assignee" % c)],
        )
        self.assertEqual(as_it_was(), was)

        def no_parent_off(method, path, body, real):
            fields = (body or {}).get("fields") or {}
            if method == "PUT" and "parent" in fields and fields["parent"] is None:
                return 400, {"errors": {"parent": "A sub-task must have a parent."}}
            return real()

        with self.wrapped(no_parent_off):
            out = ask.jira_update(
                {
                    "root": root,
                    "id": c,
                    "dropParent": True,
                    "status": "in_progress",
                    "dropNeeds": [n],
                    "assignee": "5b10ac8d82e05b22cc7d4ef5",
                }
            )
        self.assertEqual((out["status"], out.get("reason")), ("failed", "unsupported"), out)
        self.assertEqual(as_it_was(), was)

        def parent_kept(method, path, body, real):
            fields = (body or {}).get("fields") or {}
            if method == "PUT" and "parent" in fields and fields["parent"] is None:
                return 204, None
            return real()

        with self.wrapped(parent_kept):
            out = ask.jira_update({"root": root, "id": c, "dropParent": True, "title": "C v2"})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "unsupported"), out)
        self.assertEqual(as_it_was(), was)

    def test_a_need_that_would_wait_on_itself_through_another_projects_subtask_is_refused(self):
        """CHK-2 needs OTH-1, a Task of another project, whose sub-task OTH-2
        needs CHK-1. CHK-1 needing CHK-2 would close a cycle no close gets
        past, since a close waits on children in any project: it is refused,
        and nothing is written."""
        ask, _ = self.in_process()
        root = self.home.path
        one, two = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("1", "2"))
        stub = self.site.stub
        made: list[str] = []
        for fields in (
            {"project": {"key": "OTH"}, "summary": "Theirs", "issuetype": {"name": "Task"}},
            {"project": {"key": "OTH"}, "summary": "Part", "issuetype": {"name": "Subtask"}},
        ):
            if made:
                fields["parent"] = {"key": made[0]}
            status, answer = stub.handle("POST", "/rest/api/3/issue", {}, {"fields": fields})
            self.assertEqual(status, 201, answer)
            made.append(answer["key"])
        task, part = made
        stub.links += [(task, two), (one, part)]
        out = ask.jira_need({"root": root, "id": one, "needs": two})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)
        self.assertEqual(ask.record(ask.fetch(one))["needs"], [])

    def test_a_write_of_values_more_than_one_property_holds_is_read_whole_or_not_at_all(self):
        """a and b are recorded small, then each as long as half of what one
        property holds and more, so that the write takes two properties: Jira
        answering 503 to the second, the issue reads a and b as they were.
        A value longer than a property holds is kept in pieces and reads
        back whole, and Jira is never asked to keep more than it holds."""
        ask, _ = self.in_process()
        root = self.home.path
        key = ask.jira_create({"root": root, "title": "Report"})["item"]["id"]
        small = [{"label": "a", "text": "1"}, {"label": "b", "text": "2"}]
        out = ask.jira_record_values({"root": root, "id": key, "values": small})
        self.assertEqual(out["status"], "completed", out)
        long = [{"label": "a", "text": "A" * 20000}, {"label": "b", "text": "B" * 20000}]
        puts: list[str] = []

        def second_put_down(method, path, body, real):
            if method == "PUT" and "/properties/dotdiw.write." in path:
                puts.append(path)
                if len(puts) == 2:
                    return 503, {"errorMessages": ["The service is unavailable."]}
            return real()

        with self.wrapped(second_put_down):
            out = ask.jira_record_values({"root": root, "id": key, "values": long})
        self.assertEqual(out["status"], "failed", out)
        self.assertEqual(ask.record(ask.fetch(key)).get("values"), small)

        def limited(method, path, body, real):
            if method == "PUT" and "/properties/" in path and len(json.dumps(body)) > 32768:
                return 400, {"errorMessages": ["The maximum length is 32768 characters."]}
            return real()

        # A write in two parts, and another writer's whole write between
        # them: the two-part write is read where its last part is, whole,
        # after the other.
        w = ask.WRITE
        parts = {
            w + "%020d.a" % 1: {
                "group": "g",
                "part": 0,
                "of": 2,
                "values": [{"label": "a", "text": "A"}],
            },
            w + "%020d.b" % 2: {
                "values": [{"label": "a", "text": "W"}, {"label": "b", "text": "W"}]
            },
            w + "%020d.c" % 3: {
                "group": "g",
                "part": 1,
                "of": 2,
                "values": [{"label": "b", "text": "B"}],
            },
        }
        self.assertEqual(
            ask.written(parts), [{"label": "a", "text": "A"}, {"label": "b", "text": "B"}]
        )
        log = "é" + "x" * 39999
        with self.wrapped(limited):
            out = ask.jira_record_values(
                {"root": root, "id": key, "values": [{"label": "log", "text": log}]}
            )
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual(
            ask.record(ask.fetch(key)).get("values"), small + [{"label": "log", "text": log}]
        )

    def test_a_listed_issue_moved_to_another_project_is_none_of_this_checkouts(self):
        """A step poured here is moved to another project in Jira's screens;
        a search still has it here for a while. Read again whole, it is
        another project's, and the listing leaves it out."""
        ask, _ = self.in_process()
        root = self.home.path
        listed = ask.jira_list({"root": root, "scope": "all"})["items"]
        step = [i["id"] for i in listed if i.get("step")][0]
        stub = self.site.stub
        stub.lagging[step] = {"project": dict(stub.issues[step]["project"])}  # as the search has it
        stub.issues[step]["project"] = {"key": "OTH"}
        with mock.patch.object(ask, "RECENT_SECONDS", 0.0):  # as written through another home
            listed = ask.jira_list({"root": root, "scope": "all"})
        self.assertEqual(listed["status"], "completed", listed)
        self.assertNotIn(step, [i["id"] for i in listed["items"]])

    def test_a_close_of_a_closed_step_closes_a_root_moved_on_while_it_stood_open(self):
        """A step's close is cut short after Jira made it done, its root left
        open; the root is then moved to in progress, never done. Closed
        again, the step closes its root in its wake: the root stood open
        since before the step was done."""
        ask, _ = self.in_process()
        root = self.home.path
        poured = ask.jira_pour(
            {
                "root": root,
                "formulaRef": "mol-one",
                "title": "mol-one",
                "steps": [{"id": "only", "title": "Only"}],
            }
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, (step,) = poured["rootId"], poured["stepIds"]

        def comment_down(method, path, body, real):
            if method == "POST" and path.endswith("/comment"):
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real()

        with self.wrapped(comment_down):
            cut = ask.jira_close({"root": root, "id": step, "closeReason": "shipped"})
        self.assertEqual(cut["status"], "failed", cut)
        moved = ask.jira_update({"root": root, "id": top, "status": "in_progress"})
        self.assertEqual(moved["status"], "completed", moved)
        again = ask.jira_close({"root": root, "id": step, "closeReason": "shipped"})
        self.assertEqual(again["status"], "completed", again)
        self.assertIn(top, again["closedIds"])
        self.assertEqual(ask.record(ask.fetch(top))["status"], "closed")

    def test_a_need_written_a_moment_ago_holds_a_cycle_check_a_lagging_search_misses(self):
        """Y comes to need X through this home, and Jira's search is without
        the link for a while. X needing Y is refused as a cycle: the need
        just written is read by its key, not as the search has it."""
        ask, _ = self.in_process()
        root = self.home.path
        x, y = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("X", "Y"))
        with contextlib.suppress(FileNotFoundError):
            os.remove(ask.lately(root))  # nothing written of late but what follows
        self.assertEqual(ask.jira_need({"root": root, "id": y, "needs": x})["status"], "completed")

        def search_without_links(method, path, body, real):
            status, answer = real()
            if path == "/rest/api/3/search/jql" and isinstance(answer, dict):
                for issue in answer.get("issues") or []:
                    if issue["key"] in (x, y):
                        issue.get("fields", {}).pop("issuelinks", None)
            return status, answer

        with self.wrapped(search_without_links):
            out = ask.jira_need({"root": root, "id": x, "needs": y})
        self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)

    def transition(self, key, name):
        """The issue moved to the status named, as Jira's screens move it."""
        ident = str(list(STATUSES).index(name) + 11)
        status, answer = self.site.stub.handle(
            "POST", "/rest/api/3/issue/%s/transitions" % key, {}, {"transition": {"id": ident}}
        )
        self.assertEqual(status, 204, answer)

    def test_an_update_refused_for_the_person_writes_nothing(self):
        """A person the site knows but Jira will not assign in this project
        answers 400 to the assignment: the update is refused for the person,
        and the title asked with it is not written."""
        ask, _ = self.in_process()
        root = self.home.path
        key = ask.jira_create({"root": root, "title": "Before"})["item"]["id"]

        def not_assignable(method, path, body, real):
            if method == "PUT" and path.endswith("/assignee"):
                return 400, {"errors": {"assignee": "That person cannot be assigned issues."}}
            return real()

        with self.wrapped(not_assignable):
            out = ask.jira_update(
                {"root": root, "id": key, "title": "After", "assignee": "5b10ac8d82e05b22cc7d4ef5"}
            )
        self.assertEqual((out["status"], out.get("reason")), ("failed", "assignee-not-found"), out)
        self.assertEqual(self.site.stub.issues[key]["summary"], "Before")

    def test_an_update_whose_transition_jira_refuses_writes_none_of_the_rest(self):
        """A needs B. The workflow offers the way to in progress, and Jira
        refuses the transition itself, as a validator does: the update is
        refused for its status, and neither its title nor the need it was
        to take off is written -- the title it wrote first is put back."""
        ask, _ = self.in_process()
        root = self.home.path
        a, b = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("A", "B"))
        self.assertEqual(ask.jira_need({"root": root, "id": a, "needs": b})["status"], "completed")

        def validator(method, path, body, real):
            if method == "POST" and path.endswith("/transitions"):
                return 400, {"errorMessages": ["Field 'Resolution' is required."]}
            return real()

        with self.wrapped(validator):
            out = ask.jira_update(
                {"root": root, "id": a, "title": "A v2", "status": "in_progress", "dropNeeds": [b]}
            )
        self.assertEqual((out["status"], out.get("reason")), ("failed", "bad-status"), out)
        shown = ask.record(ask.fetch(a))
        self.assertEqual((shown["title"], shown["status"], shown["needs"]), ("A", "open", [b]))

    def test_a_root_done_when_its_step_closed_and_opened_since_is_left_as_it_stands(self):
        """A run's root is done in Jira's screens before its only step closes
        through dotdiw, then opened again on purpose. A close of the step,
        closed already, leaves the root open: it did not stand open since
        before the step was done."""
        ask, _ = self.in_process()
        root = self.home.path
        poured = ask.jira_pour(
            {
                "root": root,
                "formulaRef": "mol-one",
                "title": "mol-one",
                "steps": [{"id": "only", "title": "Only"}],
            }
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, (step,) = poured["rootId"], poured["stepIds"]
        self.transition(top, "Done")
        first = ask.jira_close({"root": root, "id": step, "closeReason": "shipped"})
        self.assertEqual((first["status"], first["closedIds"]), ("completed", [step]), first)
        self.transition(top, "To Do")
        again = ask.jira_close({"root": root, "id": step, "closeReason": "shipped"})
        self.assertEqual((again["status"], again["closedIds"]), ("completed", []), again)
        self.assertEqual(ask.record(ask.fetch(top))["status"], "open")

    def test_a_priority_outside_0_to_4_is_refused(self):
        """A priority is 0 to 4: 9 and -1 are refused, nothing written."""
        ask, _ = self.in_process()
        root = self.home.path
        key = ask.jira_create({"root": root, "title": "Ship"})["item"]["id"]
        for priority in (9, -1):
            out = ask.jira_update({"root": root, "id": key, "priority": priority})
            self.assertEqual(out["status"], "failed", out)
            self.assertIn("A priority is 0 to 4", out["summary"])
        self.assertEqual(ask.record(ask.fetch(key))["priority"], 2)

    def many_elsewhere(self, count):
        """count issues of this checkout's project, made in Jira's screens."""
        project = (self.site.stub.issues[next(iter(self.site.stub.issues))]["project"])["key"]
        for n in range(count):
            fields = {
                "project": {"key": project},
                "summary": "Old %d" % n,
                "issuetype": {"name": "Task"},
            }
            status, made = self.site.stub.handle(
                "POST", "/rest/api/3/issue", {}, {"fields": fields}
            )
            self.assertEqual(status, 201, made)

    def test_a_need_and_a_pour_read_no_more_of_a_large_project_than_they_reach(self):
        """Three hundred issues stand in the project. A need written between
        two of them reads what the one needed reaches, not the project; a
        pour of a chain of steps, made and checked whole first, searches
        nothing for its needs."""
        ask, _ = self.in_process()
        root = self.home.path
        self.many_elsewhere(300)
        a, b = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("A", "B"))
        stub = self.site.stub
        stub.requests.clear()
        self.assertEqual(ask.jira_need({"root": root, "id": a, "needs": b})["status"], "completed")
        searches = [r for r in stub.requests if r == ("GET", "/rest/api/3/search/jql")]
        self.assertLessEqual(len(searches), 2, stub.requests)
        stub.requests.clear()
        steps: list[dict[str, Any]] = [{"id": "one", "title": "One"}]
        steps += [
            {"id": n, "title": n, "needs": [p]} for p, n in (("one", "two"), ("two", "three"))
        ]
        poured = ask.jira_pour(
            {"root": root, "formulaRef": "mol-chain", "title": "chain", "steps": steps}
        )
        self.assertEqual(poured["status"], "completed", poured)
        searches = [r for r in stub.requests if r == ("GET", "/rest/api/3/search/jql")]
        self.assertEqual(searches, [], stub.requests)

    def test_a_listing_reads_again_none_of_what_was_written_lately_in_another_project(self):
        """Issues written of late through this home in one project are read
        again by their keys in its listings, as a search may be without them
        -- and never in a listing of another project's checkout."""
        ask, _ = self.in_process()
        root = self.home.path
        for n in range(5):
            ask.jira_create({"root": root, "title": "Mine %d" % n})
        with mock.patch.object(ask, "project_of", lambda root: "OTH"):
            self.site.stub.projects.setdefault("OTH", 1)
            stub = self.site.stub
            stub.requests.clear()
            listed = ask.jira_list({"root": root, "scope": "all"})
        self.assertEqual(listed["status"], "completed", listed)
        reads = [r for r in stub.requests if r[1].startswith("/rest/api/3/issue/")]
        self.assertEqual(reads, [], stub.requests)

    def test_an_issue_written_lately_and_moved_to_another_project_is_none_of_this_listing(self):
        """An issue made here a moment ago is moved to another project in
        Jira's screens, keeping the key it had here, and no search finds it
        yet: read by that key, it is another project's, and the listing
        leaves it out."""
        ask, _ = self.in_process()
        root = self.home.path
        key = ask.jira_create({"root": root, "title": "Moving"})["item"]["id"]
        stub = self.site.stub
        stub.issues[key]["project"] = {"key": "OTH"}
        stub.lagging[key] = None
        listed = ask.jira_list({"root": root, "scope": "all"})
        self.assertEqual(listed["status"], "completed", listed)
        self.assertNotIn(key, [i["id"] for i in listed["items"]])

    def test_a_need_written_a_moment_ago_is_listed_though_no_search_has_it(self):
        """A comes to need B through this home, and Jira's search is without
        the link for a while: the listing reads A by its key, and A needs B."""
        ask, _ = self.in_process()
        root = self.home.path
        a, b = (ask.jira_create({"root": root, "title": t})["item"]["id"] for t in ("A", "B"))
        with contextlib.suppress(FileNotFoundError):
            os.remove(ask.lately(root))  # nothing written of late but what follows
        self.assertEqual(ask.jira_need({"root": root, "id": a, "needs": b})["status"], "completed")

        def search_without_links(method, path, body, real):
            status, answer = real()
            if path == "/rest/api/3/search/jql" and isinstance(answer, dict):
                for issue in answer.get("issues") or []:
                    issue.get("fields", {}).pop("issuelinks", None)
            return status, answer

        with self.wrapped(search_without_links):
            listed = ask.jira_list({"root": root, "scope": "all"})
        (row,) = [i for i in listed["items"] if i["id"] == a]
        self.assertEqual(row["needs"], [b])

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

    def comment_refused_once(self):
        """The stub, answering 429 for the first comment it is asked to
        write, as Jira answers a call it did not process."""
        stub = self.site.stub
        real = stub.handle
        hit: list[str] = []

        def limited(method, path, query, body):
            if not hit and method == "POST" and path.endswith("/comment"):
                hit.append(path)
                return 429, {"errorMessages": ["Rate limit exceeded."]}
            return real(method, path, query, body)

        return mock.patch.object(stub, "handle", limited)

    def test_a_step_closed_again_after_a_close_cut_short_closes_its_root(self):
        """Jira moves a run's one step to done and answers 429 for the
        comment that keeps its reason, so the close fails. The same close,
        run again, finishes it and closes the root, nothing of its run left
        open."""
        ask, step = self.in_process()
        top = ask.record(ask.fetch(step))["run"]
        close = {"root": self.home.path, "id": step, "closeReason": "built"}
        with self.comment_refused_once():
            self.assertEqual(ask.jira_close(close)["status"], "failed")
        self.assertEqual(self.site.stub.issues[step]["_status"], "Done")
        self.assertEqual(ask.jira_close(close)["status"], "completed")
        shown = [ask.record(ask.fetch(key)) for key in (step, top)]
        self.assertEqual([(r["status"], r["reason"]) for r in shown][0], ("closed", "built"))
        self.assertEqual(shown[1]["status"], "closed")

    def test_the_reason_an_issue_shows_is_that_of_its_latest_close(self):
        """Closed as shipped, opened again and closed with no reason, an
        issue shows no reason, not the earlier close's. Opened again and
        closed as reverted, Jira answering 429 for the comment that keeps
        the reason, the same close run again writes it, and it is shown."""
        ask, _ = self.in_process()
        root = self.home.path
        made = ask.jira_create({"root": root, "title": "Ship"})
        key = made["item"]["id"]
        for write in (
            ask.jira_close({"root": root, "id": key, "closeReason": "shipped"}),
            ask.jira_update({"root": root, "id": key, "status": "open"}),
            ask.jira_close({"root": root, "id": key}),
        ):
            self.assertEqual(write["status"], "completed", write)
        self.assertEqual(ask.record(ask.fetch(key))["reason"], None)
        self.assertEqual(
            ask.jira_update({"root": root, "id": key, "status": "open"})["status"], "completed"
        )
        close = {"root": root, "id": key, "closeReason": "reverted"}
        with self.comment_refused_once():
            self.assertEqual(ask.jira_close(close)["status"], "failed")
        self.assertEqual(ask.jira_close(close)["status"], "completed")
        self.assertEqual(ask.record(ask.fetch(key))["reason"], "reverted")

    def test_a_description_written_in_jiras_editor_reads_as_it_was_written(self):
        """Jira's editor keeps a description as paragraphs, line breaks and
        lists: shown, it keeps its paragraphs apart, its line breaks, and its
        list's text, and a section headed Verify using:, its list under it,
        reads as the means it names."""
        ask, _ = self.in_process()
        key = ask.jira_create({"root": self.home.path, "title": "Ship"})["item"]["id"]

        def para(*leaves):
            return {"type": "paragraph", "content": list(leaves)}

        def text(said):
            return {"type": "text", "text": said}

        def bullets(*said):
            items = [{"type": "listItem", "content": [para(text(s))]} for s in said]
            return {"type": "bulletList", "content": items}

        self.site.stub.issues[key]["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                para(text("Ship the release.")),
                para(text("Tag it,"), {"type": "hardBreak"}, text("then push.")),
                bullets("Notify ops"),
                para(text("Verify using:")),
                bullets("run:make check", "https://example.invalid/r"),
            ],
        }
        shown = ask.jira_show({"root": self.home.path, "id": key})["item"]
        self.assertEqual(
            (shown["description"], shown.get("verifyUsing")),
            (
                "Ship the release.\n\nTag it,\nthen push.\n- Notify ops",
                ["run:make check", "https://example.invalid/r"],
            ),
        )

    def test_what_jiras_editor_keeps_as_a_node_of_its_own_reads_as_its_text(self):
        """Jira's editor keeps a mention, a link pasted as a card and an
        action item as nodes of their own: shown, each reads as it shows in
        Jira, the action item on one line, marked as one, and a means pasted
        as a card is a means. A note in a list under a means reads indented
        under it, and is no means of its own; nor is an action item under
        Verify using: a means, or the mark it carries one's."""
        ask, _ = self.in_process()
        key = ask.jira_create({"root": self.home.path, "title": "Ship"})["item"]["id"]

        def para(*leaves):
            return {"type": "paragraph", "content": list(leaves)}

        def text(said, *marks):
            return dict(
                {"type": "text", "text": said},
                **({"marks": [{"type": m} for m in marks]} if marks else {}),
            )

        def card(url):
            return {"type": "inlineCard", "attrs": {"url": url}}

        def bullets(*items):
            return {
                "type": "bulletList",
                "content": [{"type": "listItem", "content": list(i)} for i in items],
            }

        def doc(*content):
            return {"type": "doc", "version": 1, "content": list(content)}

        mention = {
            "type": "mention",
            "attrs": {"id": "5b10ac8d82e05b22cc7d4ef5", "text": "@Some Body"},
        }
        action = {
            "type": "taskList",
            "attrs": {"localId": "l1"},
            "content": [
                {
                    "type": "taskItem",
                    "attrs": {"localId": "i1", "state": "TODO"},
                    "content": [text("Call "), text("ops", "strong"), text(" first")],
                }
            ],
        }
        issue = self.site.stub.issues[key]
        issue["description"] = doc(
            para(
                text("Ask "),
                mention,
                text(" about "),
                card("https://example.invalid/spec"),
                text("."),
            ),
            action,
            para(text("Verify using:")),
            bullets([para(card("https://example.invalid/runs/2"))], [para(text("run:make check"))]),
        )
        shown = ask.jira_show({"root": self.home.path, "id": key})["item"]
        self.assertEqual(
            (shown["description"], shown.get("verifyUsing")),
            (
                "Ask @Some Body about https://example.invalid/spec.\n[ ] Call ops first",
                ["https://example.invalid/runs/2", "run:make check"],
            ),
        )
        note = bullets([para(text("on the CI runner"))])
        issue["description"] = doc(
            para(text("Ship it.")),
            para(text("Verify using:")),
            bullets([para(text("run:make check")), note]),
        )
        shown = ask.jira_show({"root": self.home.path, "id": key})["item"]
        self.assertIn("- run:make check\n  - on the CI runner", shown["description"])
        self.assertNotIn("on the CI runner", shown.get("verifyUsing") or [])
        item: dict[str, Any] = {
            "type": "taskItem",
            "attrs": {"localId": "i2", "state": "TODO"},
            "content": [text("run:make check")],
        }
        checks = dict(action, content=[item])
        issue["description"] = doc(para(text("Ship it.")), para(text("Verify using:")), checks)
        shown = ask.jira_show({"root": self.home.path, "id": key})["item"]
        self.assertEqual(
            (shown["description"], shown.get("verifyUsing")),
            ("Ship it.\n\nVerify using:\n[ ] run:make check", None),
        )

    def test_the_project_checked_is_the_key_kept_however_it_is_spelled(self):
        """A prefix holding a character that would end a path, or begin its
        query, is asked of Jira as one part of the path: the project checked
        is the one kept."""
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "chk?x")
        asked = [p for m, p in self.site.stub.requests if p.startswith("/rest/api/3/project/")]
        self.assertEqual(asked, ["/rest/api/3/project/CHK%3FX"], out)


class TwoCheckoutsOnOneProject(unittest.TestCase):
    """Two checkouts adopted on one Jira project are two workspaces reaching
    one store. A write held to what was read is held against the other
    checkout's writes too: the lock it takes is the store's, which every
    checkout under the home reaching that tracker shares, and not its own
    checkout's."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        self.other = tempfile.mkdtemp(prefix="dotdiw-jira-other-")
        self.addCleanup(shutil.rmtree, self.other, True)
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "Test"],
        ):
            subprocess.run(["git"] + args, cwd=self.other, capture_output=True)
        for path in (self.home.path, self.other):
            p = subprocess.run(
                [sys.executable, "-I", DOTDIW, "init", "--tracker", "jira", "--prefix", "CHK"],
                cwd=path,
                env=self.home.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.m = in_process(self, self.home.env, "dotdiw_two_checkouts")

    def write(self, root, key, title, etag):
        return self.m.invoke(
            "operation.forward-to-the-tracker",
            {
                "root": root,
                "tracker": "jira",
                "arguments": ["update", key, "--title", title],
                "etags": [etag],
            },
        )

    def test_a_write_from_another_checkout_waits_then_finds_it_changed(self):
        """One checkout's write is held inside its write, after its compare;
        the other's, on the same issue and the same ETag, cannot compare
        until it is done, and then finds the issue changed."""
        made = self.m.invoke(
            "operation.start-named-work",
            {"root": self.home.path, "title": "Count the plot", "quiet": True},
        )
        key, etag = made["workRef"], made["item"]["etag"]
        _, adapter = self.m.resolve_tracker({"root": self.home.path, "tracker": "jira"})
        writing, go = paused(self, adapter, "operation.update-item")
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "one", self.write(self.home.path, key, "From one checkout", etag)
            )
        )
        one.start()
        self.assertTrue(writing.wait(30))
        self.m.TRACKER_LOCK_SECONDS = 0.5
        waited = self.write(self.other, key, "From the other", etag)
        go.set()
        one.join(30)
        self.assertEqual(answers["one"]["status"], "completed", answers["one"])
        self.assertEqual(waited["status"], "failed", waited)
        self.assertIn("held this checkout's tracker", waited["summary"])
        again = self.write(self.other, key, "From the other", etag)
        self.assertEqual(again["reason"], "changed-since-read", again)
        self.assertEqual(self.site.stub.issues[key]["summary"], "From one checkout")


def in_process(case, env, name):
    """dotdiw as a module of this process, under env, for a test that must
    interleave two requests; the process's environment is restored after."""
    saved = dict(os.environ)
    case.addCleanup(os.environ.update, saved)
    case.addCleanup(os.environ.clear)
    os.environ.clear()
    os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, DOTDIW)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def paused(case, adapter, operation):
    """The adapter's operation held at its first call until go is set:
    started is set once it is held there."""
    real = adapter["operations"][operation]
    started, go, first = threading.Event(), threading.Event(), [True]

    def held(request):
        if first[0]:
            first[0] = False
            started.set()
            go.wait(30)
        return real(request)

    adapter["operations"][operation] = held
    case.addCleanup(adapter["operations"].__setitem__, operation, real)
    return started, go


class AWriteKeepsTheTrackerItResolved(unittest.TestCase):
    """A write resolves its checkout's tracker once: its lock, its compare
    and its write all go to that tracker, though the checkout is moved to
    another while the write runs."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, self.home.env, "dotdiw_one_tracker")

    def test_a_tracker_chosen_during_a_write_does_not_take_it(self):
        """The compare reads the Jira issue; the checkout then chooses local,
        which holds an item of the same id; the write goes to Jira."""
        root = self.home.path
        made = self.m.invoke(
            "operation.start-named-work", {"root": root, "title": "Count the plot", "quiet": True}
        )
        key, etag = made["workRef"], made["item"]["etag"]
        for operation, fields in (
            ("open-tracker", {"prefix": "CHK"}),
            ("create-item", {"id": key, "title": "Kept here"}),
        ):
            out = self.m.invoke_tracker(
                "operation." + operation, dict(fields, root=root, tracker="local")
            )
            self.assertEqual(out["status"], "completed", out)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        comparing, go = paused(self, jira, "operation.show-item")
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "one",
                self.m.invoke(
                    "operation.forward-to-the-tracker",
                    {
                        "root": root,
                        "arguments": ["update", key, "--title", "From the client"],
                        "etags": [etag],
                    },
                ),
            )
        )
        one.start()
        self.assertTrue(comparing.wait(30))
        chosen = self.m.invoke("operation.use-tracker", {"root": root, "name": "local"})
        go.set()
        one.join(30)
        self.assertEqual(chosen["status"], "completed", chosen)
        self.assertEqual(answers["one"]["status"], "completed", answers["one"])
        self.assertEqual(self.site.stub.issues[key]["summary"], "From the client")
        kept = self.m.invoke_tracker(
            "operation.show-item", {"root": root, "tracker": "local", "id": key}
        )
        self.assertEqual(kept["item"]["title"], "Kept here")

    def test_a_tracker_found_by_its_store_holds_for_the_write(self):
        """No tracker is chosen, so the compare finds Jira, the one tracker
        holding a store in the workspace. Another client then opens local
        and makes an item there under the issue's id, with another ETag,
        leaving two stores, so that a request begun after is answered by
        local; the write still goes to the Jira issue it compared. (A move
        of the workspace to local makes such a store too, but waits for the
        write, reading its source under the lock the write holds.)"""
        root = self.home.path
        made = self.m.invoke(
            "operation.start-named-work", {"root": root, "title": "Count the plot", "quiet": True}
        )
        key, etag = made["workRef"], made["item"]["etag"]
        unset = subprocess.run(
            ["git", "config", "--local", "--unset", "dotdiw.tracker"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(unset.returncode, 0, unset.stderr)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        self.assertEqual(self.m.resolve_tracker({"root": root})[0], "jira")
        comparing, go = paused(self, jira, "operation.show-item")
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "one",
                self.m.invoke(
                    "operation.forward-to-the-tracker",
                    {
                        "root": root,
                        "arguments": ["update", key, "--title", "From the client"],
                        "etags": [etag],
                    },
                ),
            )
        )
        one.start()
        self.assertTrue(comparing.wait(30))
        try:
            for operation, fields in (
                ("open-tracker", {"prefix": "CHK"}),
                ("create-item", {"id": key, "title": "Kept here"}),
            ):
                out = self.m.invoke_tracker(
                    "operation." + operation, dict(fields, root=root, tracker="local")
                )
                self.assertEqual(out["status"], "completed", out)
            self.assertEqual(self.m.resolve_tracker({"root": root})[0], "local")
        finally:
            go.set()
            one.join(30)
        self.assertEqual(answers["one"]["status"], "completed", answers["one"])
        self.assertEqual(self.site.stub.issues[key]["summary"], "From the client")
        kept = self.m.invoke_tracker(
            "operation.show-item", {"root": root, "tracker": "local", "id": key}
        )
        self.assertEqual(kept["item"]["title"], "Kept here", kept)


class OneAdoptionOfACheckoutAtATime(unittest.TestCase):
    """Two first adoptions of one checkout at once, one naming Jira and one
    naming no tracker: the one that runs second reads the key and the choice
    the first wrote, so it keeps the checkout on Jira, with the work made
    there."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="CHK"), "dotdiw_adoptions")

    def adopt(self, **fields):
        return self.m.invoke(
            "operation.adopt-a-repository", dict(fields, root=self.home.path, prefix="CHK")
        )

    def test_an_adoption_naming_no_tracker_keeps_the_one_chosen_meanwhile(self):
        root = self.home.path
        real = self.m.UndoEarlierAdoption
        looked, go = threading.Event(), threading.Event()
        seen: list[tuple[str | None, str]] = []

        def held(request):
            out = real(request)
            if threading.current_thread() is second:
                seen.append((self.m.workspace(root), self.m.resolve_tracker({"root": root})[0]))
                looked.set()
                go.wait(30)
            return out

        self.m.UndoEarlierAdoption = held
        self.addCleanup(setattr, self.m, "UndoEarlierAdoption", real)
        answers: dict[str, Any] = {}
        second = threading.Thread(target=lambda: answers.__setitem__("second", self.adopt()))
        second.start()
        try:
            self.assertTrue(looked.wait(30))
            first = self.adopt(tracker="jira")
            self.assertEqual(first["status"], "completed", first)
            made = self.m.invoke(
                "operation.start-named-work",
                {"root": root, "title": "Count the plot", "quiet": True},
            )
            self.assertEqual(made["status"], "completed", made)
        finally:
            go.set()
            second.join(30)
        self.assertEqual(seen, [(None, "local")])
        self.assertEqual(
            (answers["second"]["status"], answers["second"]["summary"]),
            ("completed", "Already adopted."),
            answers["second"],
        )
        chosen = subprocess.run(
            ["git", "config", "--local", "--get", "dotdiw.tracker"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(chosen.stdout.strip(), "jira")
        listed = self.m.invoke_tracker("operation.list-items", {"root": root, "scope": "all"})
        self.assertEqual([item["id"] for item in listed["items"]], [made["workRef"]], listed)


class OneTrackerForARequest(unittest.TestCase):
    """The checkout's choice of tracker is read afresh by each request and
    holds for the length of that request: a choice made meanwhile, by another
    request or on the command line, moves neither its write nor what it reads
    back, and the next request follows it."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="CHK"), "dotdiw_one_choice")

    def named(self, title):
        return self.m.invoke(
            "operation.start-named-work", {"root": self.home.path, "title": title, "quiet": True}
        )

    def test_a_choice_made_on_the_command_line_holds_for_the_next_request(self):
        first = self.named("On Jira")
        self.assertIn(first["workRef"], self.site.stub.issues)
        code, out = self.home.dotdiw("tracker", "use", "local")
        self.assertEqual(code, 0, out)
        second = self.named("On local")
        self.assertEqual(second["status"], "completed", second)
        self.assertEqual(list(self.site.stub.issues), [first["workRef"]])
        shown = self.m.invoke_tracker(
            "operation.show-item",
            {"root": self.home.path, "tracker": "local", "id": second["workRef"]},
        )
        self.assertEqual(shown["item"]["title"], "On local", shown)

    def test_a_claim_reads_back_the_run_it_wrote(self):
        """The values go to Jira, which held the step when the request began;
        the checkout chooses local, holding the same run with other values,
        before the run is read back; what comes back is Jira's."""
        root = self.home.path
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {
                "root": root,
                "tracker": "jira",
                "formulaRef": "mol-count",
                "title": "mol-count",
                "steps": [
                    {
                        "id": "count",
                        "title": "Count the plot",
                        "claim": {"statement": "Counted {{ n }}.", "slots": ["n"]},
                    }
                ],
            },
        )
        self.assertEqual(poured["status"], "completed", poured)
        step = poured["stepIds"][0]
        moved = self.m.invoke(
            "operation.move-a-workspace",
            {"root": root, "fromTracker": "jira", "toTracker": "local"},
        )
        self.assertEqual((moved["status"], moved["mapped"]), ("completed", 0), moved)
        local = self.m.invoke(
            "operation.record-what-a-step-found",
            {
                "root": root,
                "tracker": "local",
                "id": step,
                "values": [{"label": "n", "text": "42"}],
            },
        )
        self.assertEqual(local["status"], "completed", local)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        writing, go = paused(self, jira, "operation.record-values")
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "one",
                self.m.invoke(
                    "operation.record-what-a-step-found",
                    {"root": root, "id": step, "values": [{"label": "n", "text": "50"}]},
                ),
            )
        )
        one.start()
        self.assertTrue(writing.wait(30))
        chosen = self.m.invoke("operation.use-tracker", {"root": root, "name": "local"})
        go.set()
        one.join(30)
        self.assertEqual(chosen["status"], "completed", chosen)
        out = answers["one"]
        self.assertEqual(out["status"], "completed", out)
        on_jira = self.m.invoke(
            "operation.read-run", {"root": root, "tracker": "jira", "id": step}
        )["run"]
        self.assertEqual(out["run"]["steps"][0]["values"], [{"label": "n", "text": "50"}])
        self.assertEqual(out["run"]["etag"], on_jira["etag"])


class AMoveWritesUnderTheTargetsLock(unittest.TestCase):
    """A move holds its target's lock -- the one a write held to what was
    read holds there -- from its first write to its last, as a pour holds it
    from its root to the last need of its steps: none of its writes lands
    between another's compare and its write, and no other write lands
    between an issue the move made and the needs, status and close it
    writes of it, so nothing closes a step before it waits on its need."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "local", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="CHK"), "dotdiw_move_held")

    def test_a_resumed_move_cannot_write_between_a_compare_and_its_write(self):
        """The issue a move made stands unsettled, its status not yet set;
        a client's update of it is held inside its write, after its compare;
        the move resumed cannot set the status until that write is done."""
        root = self.home.path
        source = self.m.invoke(
            "operation.start-named-work", {"root": root, "title": "Count the plot", "quiet": True}
        )["workRef"]
        blocked = self.m.invoke_tracker(
            "operation.update-item",
            {"root": root, "tracker": "local", "id": source, "status": "blocked"},
        )
        self.assertEqual(blocked["status"], "completed", blocked)
        for operation, fields in (
            ("open-tracker", {"prefix": "CHK"}),
            ("create-item", {"title": "Count the plot"}),
        ):
            out = self.m.invoke_tracker(
                "operation." + operation, dict(fields, root=root, tracker="jira")
            )
            self.assertEqual(out["status"], "completed", out)
        key, etag = out["item"]["id"], out["item"]["etag"]
        record = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        with open(record, "w", encoding="utf-8") as fh:
            store = "%s/projects/CHK" % self.site.url
            json.dump({"from": "local", "to": "jira", "ids": {source: key}, "store": store}, fh)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        writing, go = paused(self, jira, "operation.update-item")
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "one",
                self.m.invoke(
                    "operation.forward-to-the-tracker",
                    {
                        "root": root,
                        "tracker": "jira",
                        "arguments": ["update", key, "--status", "in_progress"],
                        "etags": [etag],
                    },
                ),
            )
        )
        one.start()
        self.assertTrue(writing.wait(30))
        self.m.TRACKER_LOCK_SECONDS = 0.5
        resumed = self.m.invoke(
            "operation.move-a-workspace",
            {"root": root, "fromTracker": "local", "toTracker": "jira"},
        )
        go.set()
        one.join(30)
        self.assertEqual(answers["one"]["status"], "completed", answers["one"])
        self.assertEqual(
            (resumed["status"], resumed["summary"]), ("failed", self.m.MOVE_BUSY % "jira")
        )
        self.assertNotIn("blocked", self.site.stub.issues[key].get("labels") or [])
        again = self.m.invoke(
            "operation.move-a-workspace",
            {"root": root, "fromTracker": "local", "toTracker": "jira"},
        )
        self.assertEqual(again["status"], "completed", again)
        shown = self.m.invoke_tracker(
            "operation.show-item", {"root": root, "tracker": "jira", "id": key}
        )
        self.assertEqual(shown["item"]["status"], "blocked", shown)

    def test_a_step_closed_before_the_move_makes_it_need_its_build_waits(self):
        """The move has made the run poured here -- its root, Build and
        Publish -- and is saving its record, Publish not yet made to need
        Build, when a client closes Publish, held to the ETag it read: the
        close cannot look at Publish until the move's last write and, kept
        waiting longer than it waits, closes nothing. Asked again after, it
        finds Publish changed since read; read again, Publish waits on Build."""
        root = self.home.path
        formula = "build-then-publish.formula.toml"
        with open(os.path.join(root, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-build-then-publish"\n'
                'description = "Build, then publish. Use when testing a close during a move."\n'
                '[[steps]]\nid = "build"\ntitle = "Build"\n'
                '[[steps]]\nid = "publish"\ntitle = "Publish"\nneeds = ["build"]\n'
            )
        for args in (["add", formula], ["commit", "-qm", "f"]):
            subprocess.run(["git"] + args, cwd=root, env=self.home.env, capture_output=True)
        poured = self.m.invoke(
            "operation.pour-procedure", {"root": root, "ident": "mol-build-then-publish"}
        )
        self.assertEqual(poured["status"], "completed", poured)
        build, publish = poured["stepRefs"]
        saving, go, made = threading.Event(), threading.Event(), {}
        real = self.m.json

        class HeldAtTheSave:
            """json as this copy of dotdiw reads it, its dump of the move's
            record held, the first time that record holds Build and Publish
            made, until go is set."""

            def __getattr__(self, name):
                return getattr(real, name)

            def dump(self, record, fh, **options):
                ids = record.get("ids") if isinstance(record, dict) else None
                if isinstance(ids, dict) and {build, publish} <= ids.keys():
                    if not saving.is_set():
                        made.update(ids)
                        saving.set()
                        go.wait(30)
                return real.dump(record, fh, **options)

        self.m.json = HeldAtTheSave()
        self.addCleanup(setattr, self.m, "json", real)
        jira = {"root": root, "tracker": "jira"}

        def close(key, etag):
            return self.m.invoke(
                "operation.forward-to-the-tracker",
                dict(jira, arguments=["close", key], etags=[etag]),
            )

        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "move",
                self.m.invoke(
                    "operation.move-a-workspace",
                    {"root": root, "fromTracker": "local", "toTracker": "jira"},
                ),
            )
        )
        one.start()
        try:
            self.assertTrue(saving.wait(30))
            key = made[publish]
            shown = self.m.invoke_tracker("operation.show-item", dict(jira, id=key))
            etag = shown["item"]["etag"]
            self.m.TRACKER_LOCK_SECONDS = 0.5
            waited = close(key, etag)
        finally:
            go.set()
            one.join(30)
        moved = answers["move"]
        self.assertEqual((moved["status"], moved["moved"]), ("completed", 3), moved)
        self.assertEqual(waited["status"], "failed", waited)
        self.assertIn("held this checkout's tracker", waited["summary"])
        again = close(key, etag)
        self.assertEqual(
            (again["status"], again["reason"]), ("failed", "changed-since-read"), again
        )
        shown = self.m.invoke_tracker("operation.show-item", dict(jira, id=key))
        self.assertEqual(
            (shown["item"]["status"], shown["item"]["needs"]), ("open", [made[build]]), shown
        )
        fresh = close(key, shown["item"]["etag"])
        self.assertEqual(
            (fresh["closedRefs"], fresh["summary"]),
            ([], "%s is blocked by %s." % (key, made[build])),
        )


class AStoppedMoveHoldsWhatItMade(unittest.TestCase):
    """A move that stops part way leaves the issues it made unsettled in its
    record, and until a run of it finishes them, nothing but the move closes
    one through dotdiw, nor gives one as ready -- from this checkout or any
    other under the home -- so no step closes before it waits on its needs,
    however long the move stays stopped."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "local", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="CHK"), "dotdiw_move_stopped")

    def move(self, deleted=(), **stores):
        """A run of the move from local to Jira, told the issues given were
        deleted there, and the store given the record's (toStore)."""
        request: dict[str, Any] = {"root": self.home.path, "fromTracker": "local"}
        request["toTracker"] = "jira"
        if deleted:
            request["deletedIds"] = list(deleted)
        request.update(stores)
        return self.m.invoke("operation.move-a-workspace", request)

    def moved(self, root, **stores):
        """A run of the move from Jira to local in the checkout given, told
        the store given the record's (fromStore)."""
        request = dict({"root": root, "fromTracker": "jira", "toTracker": "local"}, **stores)
        return self.m.invoke("operation.move-a-workspace", request)

    def local_titles(self, root):
        """The titles of every item local holds in the checkout given."""
        listed = self.m.invoke_tracker(
            "operation.list-items", {"root": root, "tracker": "local", "scope": "all"}
        )
        self.assertEqual(listed["status"], "completed", listed)
        return sorted(i["title"] for i in listed["items"])

    def made(self, root, title, **fields):
        """The key of an issue made in the checkout given."""
        made = self.m.invoke_tracker(
            "operation.create-item",
            dict({"root": root, "tracker": "jira", "title": title}, **fields),
        )
        self.assertEqual(made["status"], "completed", made)
        return made["item"]["id"]

    def forward(self, root, tracker, *arguments, etags=()):
        return self.m.invoke(
            "operation.forward-to-the-tracker",
            {"root": root, "tracker": tracker, "arguments": list(arguments), "etags": list(etags)},
        )

    def show(self, ident, root=None, tracker="jira"):
        shown = self.m.invoke_tracker(
            "operation.show-item", {"root": root or self.home.path, "tracker": tracker, "id": ident}
        )
        self.assertEqual(shown["status"], "completed", shown)
        return shown["item"]

    def poured(self):
        """Build, then Publish, poured into local: their ids there."""
        root = self.home.path
        formula = "build-then-publish.formula.toml"
        with open(os.path.join(root, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-build-then-publish"\n'
                'description = "Build, then publish. Use when testing a move that stops."\n'
                '[[steps]]\nid = "build"\ntitle = "Build"\n'
                '[[steps]]\nid = "publish"\ntitle = "Publish"\nneeds = ["build"]\n'
            )
        for args in (["add", formula], ["commit", "-qm", "f"]):
            subprocess.run(["git"] + args, cwd=root, env=self.home.env, capture_output=True)
        poured = self.m.invoke(
            "operation.pour-procedure", {"root": root, "ident": "mol-build-then-publish"}
        )
        self.assertEqual(poured["status"], "completed", poured)
        build, publish = poured["stepRefs"]
        return build, publish

    def record(self):
        """The record of the move from local to Jira, as it stands."""
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        with open(path, encoding="utf-8") as fh:
            record: dict[str, Any] = json.load(fh)
        return record

    def stopped(self):
        """Build, then Publish, poured into local and moved to Jira, which
        answers 503 for the link of Publish to Build: the issues the failed
        move made of the two."""
        build, publish = self.poured()
        stub = self.site.stub
        real = stub.handle

        def down(method, path, query, body):
            if method == "POST" and path == "/rest/api/3/issueLink":
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", down):
            moved = self.move()
        self.assertEqual(moved["status"], "failed", moved)
        self.assertIn("jira refused the need of %s on %s" % (publish, build), moved["summary"])
        ids = self.record()["ids"]
        return ids[build], ids[publish]

    def unfinished(self, key, tracker="jira", checkout=None, record=None):
        """What a close of an item the stopped move made answers: run the
        move again, in the checkout it ran in -- or, its record naming none
        (checkout ""), where that record is (record)."""
        source = "local" if tracker == "jira" else "jira"
        where = (
            " in %s" % (checkout or self.record()["checkout"])
            if checkout != ""
            else self.m.MOVE_RECORD_ASIDE % (record, "names none")
        )
        return self.m.MOVE_UNFINISHED % (key, source, tracker, "dotdiw", source, tracker, where)

    def cli(self, root, *arguments):
        """dotdiw run in the checkout given, on this test's site."""
        env = dict(self.home.env, JIRA_PROJECT="CHK", JIRA_SITE=self.site.url)
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW] + list(arguments),
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def checkout(self, site=None, project="CHK"):
        """A second checkout under the home, adopted on project CHK, or the
        one given, of this test's site or the one given."""
        other = tempfile.mkdtemp(prefix="dotdiw-jira-other-")
        self.addCleanup(shutil.rmtree, other, True)
        for args in (["init", "-q", "."], ["config", "user.name", "Test"]):
            subprocess.run(["git"] + args, cwd=other, capture_output=True)
        env = dict(self.home.env, JIRA_PROJECT=project, JIRA_SITE=(site or self.site).url)
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW, "init", "--tracker", "jira"],
            cwd=other,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return other

    def test_a_step_it_made_stays_unclosed_until_a_run_finishes_it(self):
        """Stopped before it linked Publish to Build, the move leaves both
        out of ready, and a close of Publish held to the ETag read is
        refused, blocked by the move, and Publish stays open. Run again, the
        move links the two and finishes: the ETag read no longer holds,
        Publish read afresh is blocked by Build, and Build is ready."""
        root = self.home.path
        build, publish = self.stopped()
        ready = self.forward(root, "jira", "ready")
        self.assertEqual(ready["status"], "completed", ready)
        self.assertFalse({build, publish} & {i["id"] for i in ready["items"]}, ready)
        etag = self.show(publish)["etag"]
        closed = self.forward(root, "jira", "close", publish, etags=[etag])
        self.assertEqual(
            (closed["status"], closed["closedRefs"], closed["summary"]),
            ("failed", [], self.unfinished(publish)),
        )
        self.assertEqual((self.show(publish)["status"], self.show(publish)["needs"]), ("open", []))
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        stale = self.forward(root, "jira", "close", publish, etags=[etag])
        self.assertEqual((stale["status"], stale["reason"]), ("failed", "changed-since-read"))
        shown = self.show(publish)
        self.assertEqual((shown["status"], shown["needs"]), ("open", [build]), shown)
        fresh = self.forward(root, "jira", "close", publish, etags=[shown["etag"]])
        self.assertEqual(
            (fresh["closedRefs"], fresh["summary"]), ([], "%s is blocked by %s." % (publish, build))
        )
        ready = self.forward(root, "jira", "ready")
        self.assertIn(build, [i["id"] for i in ready["items"]])

    def test_another_checkout_on_the_project_cannot_close_it_either(self):
        """A second checkout under the home, adopted on the same project,
        reaches the issues the stopped move made as this one does: Publish
        is no ready issue there, and a close of it is refused, blocked by
        the move, until a run of the move finishes it."""
        build, publish = self.stopped()
        other = self.checkout()
        self.assertEqual(self.show(publish, other)["status"], "open")
        ready = self.forward(other, "jira", "ready")
        self.assertEqual(ready["status"], "completed", ready)
        self.assertNotIn(publish, [i["id"] for i in ready["items"]])
        closed = self.forward(other, "jira", "close", publish)
        self.assertEqual(
            (closed["status"], closed["closedRefs"], closed["summary"]),
            ("failed", [], self.unfinished(publish)),
        )
        self.assertEqual(self.move()["status"], "completed")
        closed = self.forward(other, "jira", "close", publish)
        self.assertEqual(closed["summary"], "%s is blocked by %s." % (publish, build))

    def test_under_local_the_checkouts_own_record_holds_it(self):
        """Under local, whose store is the checkout's: an item the record of
        a stopped move into local holds unsettled is no ready item and
        closes not; settled there, it is ready and it closes."""
        root = self.home.path
        made = self.m.invoke_tracker(
            "operation.create-item", {"root": root, "tracker": "local", "title": "Count the plot"}
        )
        ident = made["item"]["id"]
        record = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        stopped = {"from": "jira", "to": "local", "ids": {"CHK-9": ident}}
        with open(record, "w", encoding="utf-8") as fh:
            json.dump(stopped, fh)
        ready = self.forward(root, "local", "ready")
        self.assertNotIn(ident, [i["id"] for i in ready["items"]])
        closed = self.forward(root, "local", "close", ident)
        self.assertEqual(
            (closed["status"], closed["closedRefs"], closed["summary"]),
            ("failed", [], self.unfinished(ident, "local", checkout="", record=record)),
        )
        with open(record, "w", encoding="utf-8") as fh:
            json.dump(dict(stopped, settled=["CHK-9"]), fh)
        ready = self.forward(root, "local", "ready")
        self.assertIn(ident, [i["id"] for i in ready["items"]])
        closed = self.forward(root, "local", "close", ident)
        self.assertEqual((closed["status"], closed["closedRefs"]), ("completed", [ident]), closed)

    def test_an_issue_jira_made_and_could_not_read_back_is_finished_not_made_again(self):
        """Jira makes Publish and answers 503 when the move reads it back:
        the move fails naming it, and its record holds it made, so it is no
        ready issue and a close of it is refused. Run again, the move
        finishes that issue: no second Publish is made, and it waits on
        Build."""
        root = self.home.path
        build, publish = self.poured()
        stub = self.site.stub
        real = stub.handle
        made: list[str] = []

        def unreadable(method, path, query, body):
            code, answer = real(method, path, query, body)
            if (method, path) == ("POST", "/rest/api/3/issue"):
                if body["fields"]["summary"] == "Publish":
                    made.append(answer["key"])
                    stub.unread.add(answer["key"])
            return code, answer

        with mock.patch.object(stub, "handle", unreadable):
            moved = self.move()
        stub.unread.clear()
        self.assertEqual(moved["status"], "failed", moved)
        self.assertIn("Jira made %s and could not read it back" % made[0], moved["summary"])
        self.assertEqual(self.record()["ids"][publish], made[0])
        ready = self.forward(root, "jira", "ready")
        self.assertNotIn(made[0], [i["id"] for i in ready["items"]], ready)
        closed = self.forward(root, "jira", "close", made[0])
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(made[0])))
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        titles = [f["summary"] for f in stub.issues.values()]
        self.assertEqual(titles.count("Publish"), 1, titles)
        self.assertEqual(self.show(made[0])["needs"], [self.record()["ids"][build]])
        self.assertEqual(self.record()["unread"], [])

    def test_an_issue_jira_made_without_its_step_is_made_again_once_deleted(self):
        """Jira makes the first step the move makes and refuses the property
        that keeps its step: the record holds it made, and the next run of
        the move reads it back before it writes anything and, finding it not
        as the move gave it, writes nothing and says what to do. Deleted in
        Jira, it is still held, and made again only once the run is told it
        was deleted: then it is made whole, and Publish waits on Build."""
        build, publish = self.poured()
        stub = self.site.stub
        stub.refuse_properties = True
        moved = self.move()
        stub.refuse_properties = False
        self.assertEqual(moved["status"], "failed", moved)
        record = self.record()
        (first,) = record["unread"]
        made = record["ids"][first]
        self.assertIn("Jira made %s and could not keep its claim" % made, moved["summary"])
        count = len(stub.issues)
        again = self.move()
        self.assertEqual(
            (again["status"], again["summary"]),
            (
                "failed",
                self.m.MOVE_NOT_AS_MADE
                % (
                    "jira",
                    made,
                    first,
                    "step, run",
                    made,
                    "jira",
                    "dotdiw tracker migrate local jira --deleted %s" % made,
                ),
            ),
        )
        self.assertEqual(len(stub.issues), count, stub.issues)
        del stub.issues[made]
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(len(stub.issues), count - 1, stub.issues)
        self.assertEqual(self.record()["ids"][first], made)
        code, out = self.home.dotdiw(
            "tracker",
            "migrate",
            "local",
            "jira",
            "--deleted",
            made,
            env=dict(self.home.env, JIRA_PROJECT="CHK"),
        )
        self.assertEqual(code, 0, out)
        ids = self.record()["ids"]
        self.assertNotEqual(ids[first], made)
        step = {build: "build", publish: "publish"}[first]
        self.assertEqual(self.show(ids[first])["step"], step)
        self.assertEqual(self.show(ids[publish])["needs"], [ids[build]])

    def test_a_move_from_jira_waits_for_the_move_into_it_to_finish(self):
        """The move into Jira stopped before it linked Publish to Build. A
        move from Jira to local in a second checkout on the project is
        refused before it writes anything, since it would read the two half
        made, and says where to finish the first. Once the first finishes,
        the second moves Publish waiting on Build."""
        build, publish = self.stopped()
        other = self.checkout()
        back = {"root": other, "fromTracker": "jira", "toTracker": "local"}
        moved = self.m.invoke("operation.move-a-workspace", back)
        self.assertEqual(moved["status"], "failed", moved)
        self.assertEqual(
            moved["summary"],
            self.m.MOVE_FROM_UNFINISHED
            % (
                "jira",
                "local",
                "jira",
                ", ".join(sorted(self.record()["ids"].values())),
                "jira",
                "dotdiw",
                "local",
                "jira",
                " in %s" % self.record()["checkout"],
            ),
        )
        record = os.path.join(self.m.workspace(other), "migration-jira-to-local.json")
        self.assertFalse(os.path.exists(record))
        self.assertEqual(self.move()["status"], "completed")
        moved = self.m.invoke("operation.move-a-workspace", back)
        self.assertEqual(moved["status"], "completed", moved)
        with open(record, encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        shown = self.show(ids[publish], other, "local")
        self.assertEqual(shown["needs"], [ids[build]], shown)

    def test_an_issue_on_another_site_is_no_part_of_this_ones_move(self):
        """A second checkout under the home, on a project of the same key on
        another Jira site, holds issues with the keys the stopped move made
        here: those are no part of the move, so they are ready there and they
        close, while the issues the move made here stay held."""
        build, publish = self.stopped()
        site = Site()
        self.addCleanup(site.close)
        other = self.checkout(site)
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            for title in ("One", "Two", "Three"):
                made = self.m.invoke_tracker(
                    "operation.create-item", {"root": other, "tracker": "jira", "title": title}
                )
                self.assertEqual(made["status"], "completed", made)
            self.assertIn(publish, site.stub.issues)
            ready = self.forward(other, "jira", "ready")
            self.assertIn(publish, [i["id"] for i in ready["items"]], ready)
            closed = self.forward(other, "jira", "close", publish)
            self.assertEqual((closed["status"], closed["closedRefs"]), ("completed", [publish]))
        closed = self.forward(self.home.path, "jira", "close", publish)
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(publish)))

    def test_ready_reads_the_issues_and_the_record_at_one_moment(self):
        """A ready has read Publish, not yet linked to Build, when a run of
        the stopped move starts: the run waits for the ready, which leaves
        Publish out as the record then says, and finishes once it has
        answered."""
        root = self.home.path
        build, publish = self.stopped()
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        real = jira["operations"]["operation.ready-items"]
        read, go = threading.Event(), threading.Event()

        def held(request):
            out = real(request)
            read.set()
            go.wait(30)
            return out

        jira["operations"]["operation.ready-items"] = held
        self.addCleanup(jira["operations"].__setitem__, "operation.ready-items", real)
        answers: dict[str, Any] = {}
        ready = threading.Thread(
            target=lambda: answers.__setitem__("ready", self.forward(root, "jira", "ready"))
        )
        ready.start()
        self.assertTrue(read.wait(30))
        move = threading.Thread(target=lambda: answers.__setitem__("move", self.move()))
        move.start()
        move.join(2)
        go.set()
        ready.join(30)
        move.join(30)
        self.assertEqual(answers["ready"]["status"], "completed", answers["ready"])
        self.assertNotIn(publish, [i["id"] for i in answers["ready"]["items"]])
        self.assertEqual(answers["move"]["status"], "completed", answers["move"])

    def test_a_run_of_the_move_on_another_site_writes_nothing_there(self):
        """Stopped before it linked Publish to Build, the move is run again
        from this checkout with JIRA_SITE naming another site, whose project
        of the same key holds issues under the keys the move made here: the
        run writes nothing there and says where the move wrote, and what it
        made here stays held until a run on this site finishes it."""
        build, publish = self.stopped()
        store = self.record()["store"]
        site = Site()
        self.addCleanup(site.close)
        other = self.checkout(site)
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            for title in ("One", "Two", "Three"):
                made = self.m.invoke_tracker(
                    "operation.create-item", {"root": other, "tracker": "jira", "title": title}
                )
                self.assertEqual(made["status"], "completed", made)
            self.assertEqual(sorted(site.stub.issues), sorted(self.record()["ids"].values()))
            again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(site.stub.links, [])
        self.assertEqual(
            again["summary"],
            self.m.MOVE_ELSEWHERE_UNFINISHED
            % (
                "local",
                "jira",
                ", ".join(sorted(self.record()["ids"].values())),
                store,
                "jira",
                "%s/projects/CHK" % site.url,
                "jira",
                store,
            ),
        )
        self.assertEqual(self.record()["settled"], [])
        closed = self.forward(self.home.path, "jira", "close", publish)
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(publish)))
        # Told the other site's store, a run here is held to the record's.
        again = self.move(toStore="%s/projects/CHK" % site.url)
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(publish)["needs"], [build])

    def test_a_move_finished_on_one_site_writes_nothing_on_another(self):
        """Finished on this site, the move is run again with JIRA_SITE
        naming another site, the source holding a new item that needs
        Build: the run writes nothing there -- the key of Build here names
        another issue there -- and says which record to move aside to move
        the items there too. Moved aside, the run makes them all there."""
        root = self.home.path
        build, publish = self.poured()
        self.assertEqual(self.move()["status"], "completed")
        record = self.record()
        site = Site()
        self.addCleanup(site.close)
        other = self.checkout(site)
        ship = self.m.invoke_tracker(
            "operation.create-item", {"root": root, "tracker": "local", "title": "Ship"}
        )["item"]["id"]
        need = {"root": root, "tracker": "local", "id": ship, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        path = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            for title in ("One", "Two", "Three"):
                made = self.m.invoke_tracker(
                    "operation.create-item", {"root": other, "tracker": "jira", "title": title}
                )
                self.assertEqual(made["status"], "completed", made)
            theirs = sorted(site.stub.issues)
            self.assertIn(record["ids"][build], theirs)
            again = self.move()
            self.assertEqual(again["status"], "failed", again)
            self.assertEqual((sorted(site.stub.issues), site.stub.links), (theirs, []))
            self.assertEqual(
                again["summary"],
                self.m.MOVE_ELSEWHERE_FINISHED
                % (
                    "local",
                    "jira",
                    record["store"],
                    "jira",
                    "%s/projects/CHK" % site.url,
                    path,
                    record["store"],
                ),
            )
            os.replace(path, path + ".aside")
            again = self.move()
            self.assertEqual(again["status"], "completed", again)
            ids = self.record()["ids"]
            self.assertEqual(self.show(ids[ship], other)["needs"], [ids[build]])
        self.assertEqual(sorted(record["ids"]), sorted(set(ids) - {ship}))

    def test_an_issue_jira_cannot_find_is_held_until_it_reads_or_its_deletion_is_said(self):
        """Jira makes Publish and answers 503 when the move reads it back.
        Run again, Jira answers 404 for it, as it answers for an issue the
        caller cannot see: the move makes no second Publish, writes nothing
        more and says what to do, and Publish stays held. Once Jira shows
        it, the move finishes it, though told it was deleted."""
        root = self.home.path
        build, publish = self.poured()
        stub = self.site.stub
        real = stub.handle
        made: list[str] = []

        def unreadable(method, path, query, body):
            code, answer = real(method, path, query, body)
            if (method, path) == ("POST", "/rest/api/3/issue"):
                if body["fields"]["summary"] == "Publish":
                    made.append(answer["key"])
                    stub.unread.add(answer["key"])
            return code, answer

        with mock.patch.object(stub, "handle", unreadable):
            moved = self.move()
        stub.unread.clear()
        self.assertEqual(moved["status"], "failed", moved)

        def hidden(method, path, query, body):
            if method == "GET" and path == "/rest/api/3/issue/%s" % made[0]:
                return 404, {
                    "errorMessages": [
                        "Issue does not exist or you do not have permission to see it."
                    ]
                }
            return real(method, path, query, body)

        count = len(stub.issues)
        with mock.patch.object(stub, "handle", hidden):
            again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(len(stub.issues), count, stub.issues)
        self.assertEqual(
            again["summary"],
            self.m.MOVE_NOT_FOUND
            % (
                "jira",
                made[0],
                publish,
                made[0],
                "dotdiw tracker migrate local jira",
                "dotdiw tracker migrate local jira --deleted %s" % made[0],
            ),
        )
        self.assertEqual(self.record()["ids"][publish], made[0])
        closed = self.forward(root, "jira", "close", made[0])
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(made[0])))
        again = self.move(deleted=[made[0]])
        self.assertEqual(again["status"], "completed", again)
        titles = [f["summary"] for f in stub.issues.values()]
        self.assertEqual(titles.count("Publish"), 1, titles)
        self.assertEqual(self.show(made[0])["needs"], [self.record()["ids"][build]])

    def test_a_checkout_on_another_project_reaches_no_issue_of_this_one(self):
        """A second checkout under the home, adopted on another project of
        the same site, reaches none of this project's issues: Publish, which
        the stopped move made here, is none there to show, write or close,
        so it stays open and held here."""
        build, publish = self.stopped()
        other = self.checkout(project="OTH")
        theirs = self.m.invoke_tracker(
            "operation.create-item", {"root": other, "tracker": "jira", "title": "Theirs"}
        )["item"]["id"]
        asked = {"root": other, "tracker": "jira"}
        for operation, fields in (
            ("operation.show-item", {"id": publish}),
            ("operation.update-item", {"id": publish, "title": "Renamed"}),
            ("operation.update-item", {"id": theirs, "parent": build}),
            ("operation.add-need", {"id": publish, "needs": theirs}),
            ("operation.add-need", {"id": theirs, "needs": build}),
            ("operation.record-values", {"id": publish, "values": [{"label": "n", "text": "1"}]}),
            ("operation.close-item", {"id": publish}),
        ):
            out = self.m.invoke_tracker(operation, dict(asked, **fields))
            self.assertEqual((out["status"], out.get("reason")), ("failed", "item-not-found"))
        closed = self.forward(other, "jira", "close", publish)
        self.assertEqual((closed["status"], closed["closedRefs"]), ("failed", []), closed)
        shown = self.show(publish)
        self.assertEqual((shown["status"], shown["title"]), ("open", "Publish"))
        self.assertEqual(self.site.stub.links, [])
        closed = self.forward(self.home.path, "jira", "close", publish)
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(publish)))
        # Nor is an issue made there under a root of this project, or in its
        # run, so none closes it from there, and none stands open under it
        # unseen by a close here; one Jira itself put under it from there,
        # as a site whose projects take parents of another allows, holds
        # its close as an open child of its own does.
        steps = [{"id": "a", "title": "A"}]
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": self.home.path, "tracker": "jira", "formulaRef": "m", "title": "Ours"}
            | {"steps": steps},
        )
        ours, (step,) = poured["rootId"], poured["stepIds"]
        count = len(self.site.stub.issues)
        for fields in ({"parent": ours}, {"run": ours}):
            made = self.m.invoke_tracker(
                "operation.create-item", dict(asked, title="Under ours", **fields)
            )
            self.assertEqual(
                (made["status"], made.get("reason"), made["summary"]),
                ("failed", "parent-not-found", "%s names no issue here." % ours),
            )
        self.assertEqual(len(self.site.stub.issues), count)
        under = self.made(other, "Under ours")
        self.site.stub.issues[under]["parent"] = {"key": ours}
        closed = self.m.invoke_tracker(
            "operation.close-item", {"root": self.home.path, "tracker": "jira", "id": step}
        )
        self.assertEqual(closed["closedIds"], [step], closed)
        self.assertEqual(self.show(ours)["status"], "open")
        closed = self.m.invoke_tracker(
            "operation.close-item", {"root": self.home.path, "tracker": "jira", "id": ours}
        )
        self.assertEqual((closed["status"], closed["blockedBy"]), ("blocked", [under]), closed)
        self.assertEqual(self.show(ours)["status"], "open")
        # Nor does a close there of what Jira put under it, or in its run,
        # close this project's root: it closes from here alone.
        closed = self.m.invoke_tracker("operation.close-item", dict(asked, id=under))
        self.assertEqual(closed["closedIds"], [under], closed)
        self.assertEqual(self.show(ours)["status"], "open")
        loose = self.made(other, "In our run")
        self.site.stub.properties[loose] = {"dotdiw": {"run": ours}}
        closed = self.m.invoke_tracker("operation.close-item", dict(asked, id=loose))
        self.assertEqual(closed["closedIds"], [loose], closed)
        self.assertEqual(self.show(ours)["status"], "open")
        closed = self.m.invoke_tracker(
            "operation.close-item", {"root": self.home.path, "tracker": "jira", "id": ours}
        )
        self.assertEqual(closed["closedIds"], [ours], closed)

    def test_an_issue_waiting_on_a_closed_issue_of_another_project_is_ready(self):
        """An issue of this project that Jira holds waiting on one of another
        project, linked there as a site allows, is ready once that one is
        closed, and not before: wherever it stands, a need is open or closed
        as Jira says."""
        ours, other = self.checkout(), self.checkout(project="OTH")
        mine, theirs = self.made(ours, "Mine"), self.made(other, "Theirs")
        self.site.stub.links.append((theirs, mine))
        self.assertEqual(self.show(mine, ours)["needs"], [theirs])

        def ready():
            answer = self.m.invoke_tracker(
                "operation.ready-items", {"root": ours, "tracker": "jira"}
            )
            self.assertEqual(answer["status"], "completed", answer)
            return [i["id"] for i in answer["items"]]

        self.assertNotIn(mine, ready())
        closed = self.m.invoke_tracker(
            "operation.close-item", {"root": other, "tracker": "jira", "id": theirs}
        )
        self.assertEqual(closed["closedIds"], [theirs], closed)
        self.assertIn(mine, ready())

    def test_a_record_that_names_no_store_is_held_to_one_only_once_told(self):
        """A record of a stopped move that names no store, as an earlier
        dotdiw wrote it, is held to none: run again with JIRA_SITE naming
        another site, whose project of the same key holds issues under the
        keys the move made, the move writes nothing there and says to name
        the store it wrote to; told this site's, it writes nothing there
        either, and says to point Jira back here. Until then, what the move
        made stays held in every store of the tracker under the home. Told
        this site's from the command line, here, the move finishes, and the
        record names the store from then on."""
        build, publish = self.stopped()
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        record = self.record()
        store = record.pop("store")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        made = ", ".join(sorted(record["ids"].values()))
        site = Site()
        self.addCleanup(site.close)
        other, theirs = self.checkout(site), "%s/projects/CHK" % site.url
        said = (
            "jira",
            "wrote to",
            "jira",
            theirs,
            "dotdiw",
            "local",
            "jira",
            "--to-store " + theirs,
        )
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            for title in ("One", "Two", "Three"):
                self.made(other, title)
            again = self.move()
            self.assertEqual(again["status"], "failed", again)
            self.assertEqual(
                again["summary"],
                self.m.MOVE_STORE_UNSAID % ((path, "local", "jira") + said + ("jira", "wrote to")),
            )
            told = self.move(toStore=store)
            self.assertEqual(told["status"], "failed", told)
            self.assertEqual(
                told["summary"],
                self.m.MOVE_ELSEWHERE_UNFINISHED
                % ("local", "jira", made, store, "jira", theirs, "jira", store),
            )
            self.assertEqual(site.stub.links, [])
            closed = self.forward(other, "jira", "close", publish)
        self.assertEqual((closed["closedRefs"], closed["summary"]), ([], self.unfinished(publish)))
        self.assertNotIn("store", self.record())
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(self.site.stub.links, [])
        code, out = self.home.dotdiw("tracker", "migrate", "local", "jira", "--to-store", store)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.record()["store"], store)
        self.assertEqual(self.show(publish)["needs"], [build])

    def test_a_move_from_one_site_is_no_move_from_another(self):
        """Moved from this site into local, the move is run again in the
        checkout with JIRA_SITE naming another site, whose project of the
        same key holds an issue under the key moved from here and one that
        needs it: the run writes nothing into local -- the record's key
        names another issue there -- and says which record to move aside.
        Moved aside, the run moves that site's issues as their own."""
        root, here = self.checkout(), "%s/projects/CHK" % self.site.url
        build = self.made(root, "Build")
        first = self.moved(root)
        self.assertEqual(first["status"], "completed", first)
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["fromStore"], here)
        site = Site()
        self.addCleanup(site.close)
        other, theirs = self.checkout(site), "%s/projects/CHK" % site.url
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            their_build, their_ship = self.made(other, "Their build"), self.made(other, "Ship")
            self.assertEqual(their_build, build)
            need = {"root": other, "tracker": "jira", "id": their_ship, "needs": their_build}
            self.assertEqual(
                self.m.invoke_tracker("operation.add-need", need)["status"], "completed"
            )
            again = self.moved(root)
            self.assertEqual(again["status"], "failed", again)
            self.assertEqual(
                again["summary"],
                self.m.MOVE_FROM_ELSEWHERE_FINISHED
                % ("jira", "local", here, "jira", theirs, path, here),
            )
            self.assertEqual(self.local_titles(root), ["Build"])
            os.replace(path, path + ".aside")
            again = self.moved(root)
            self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.local_titles(root), ["Build", "Ship", "Their build"])
        with open(path, encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        self.assertNotEqual(ids[their_build], build)
        self.assertEqual(self.show(ids[their_ship], root, "local")["needs"], [ids[their_build]])

    def test_a_stopped_move_from_one_site_finishes_from_it_alone(self):
        """A move from this site into local stops before it links Ship to
        Build. Run again with JIRA_SITE naming another site, whose project
        of the same key holds issues under the same keys, the move writes
        nothing into local and says to point Jira back here; what it made
        stays held. Run here again, it finishes."""
        root, here = self.checkout(), "%s/projects/CHK" % self.site.url
        build, ship = self.made(root, "Build"), self.made(root, "Ship")
        need = {"root": root, "tracker": "jira", "id": ship, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        real = local["operations"]["operation.add-need"]
        down = {"status": "failed", "reason": "adapter-failed", "exitCode": 1, "summary": "down"}
        local["operations"]["operation.add-need"] = lambda request: dict(down)
        try:
            first = self.moved(root)
        finally:
            local["operations"]["operation.add-need"] = real
        self.assertEqual(first["status"], "failed", first)
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            made = sorted(json.load(fh)["ids"].values())
        site = Site()
        self.addCleanup(site.close)
        other, theirs = self.checkout(site), "%s/projects/CHK" % site.url
        with mock.patch.dict(os.environ, {"JIRA_SITE": site.url}):
            for title in ("Their build", "Their ship"):
                self.made(other, title)
            again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(
            again["summary"],
            self.m.MOVE_FROM_ELSEWHERE_UNFINISHED
            % ("jira", "local", here, ", ".join(made), "jira", theirs, "jira", here),
        )
        self.assertEqual(self.local_titles(root), ["Build", "Ship"])
        with open(path, encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        self.assertEqual(self.show(ids[ship], root, "local")["needs"], [])
        self.assertEqual(self.moved(root)["status"], "completed")
        self.assertEqual(self.show(ids[ship], root, "local")["needs"], [ids[build]])

    def test_a_record_that_names_no_store_read_from_is_held_to_one_only_once_told(self):
        """A record of a move from Jira that names no store it read from, as
        an earlier dotdiw wrote it, is held to none: run again, the move
        writes nothing and says to name the store it read from. Told it, the
        move goes on, and the record names the store from then on."""
        root, here = self.checkout(), "%s/projects/CHK" % self.site.url
        build = self.made(root, "Build")
        self.assertEqual(self.moved(root)["status"], "completed")
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        del record["fromStore"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        ship = self.made(root, "Ship")
        need = {"root": root, "tracker": "jira", "id": ship, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        said = (
            "jira",
            "read from",
            "jira",
            here,
            "dotdiw",
            "jira",
            "local",
            "--from-store " + here,
        )
        self.assertEqual(
            again["summary"],
            self.m.MOVE_STORE_UNSAID % ((path, "jira", "local") + said + ("jira", "read from")),
        )
        self.assertEqual(self.local_titles(root), ["Build"])
        with open(path, encoding="utf-8") as fh:
            self.assertNotIn("fromStore", json.load(fh))
        code, out = self.cli(root, "tracker", "migrate", "jira", "local", "--from-store=%s" % here)
        self.assertEqual(code, 0, out)
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        self.assertEqual(record["fromStore"], here)
        self.assertEqual(
            self.show(record["ids"][ship], root, "local")["needs"], [record["ids"][build]]
        )

    def test_a_record_told_its_store_keeps_it_though_nothing_is_written(self):
        """Told the store of a record that names none, a run of the move
        that finds nothing to write keeps the store in the record all the
        same, so that the next run needs no telling."""
        root, here = self.checkout(), "%s/projects/CHK" % self.site.url
        self.made(root, "Build")
        self.assertEqual(self.moved(root)["status"], "completed")
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        del record["fromStore"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        told = self.moved(root, fromStore=here)
        self.assertEqual(told["status"], "completed", told)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["fromStore"], here)
        self.made(root, "Ship")
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.local_titles(root), ["Build", "Ship"])

    def test_a_target_that_names_no_store_now_is_held_to_none(self):
        """Finished into this site, the move is run again where Jira names
        no store it keeps the checkout's issues in: the record's keys could
        name other issues there, so the run writes nothing and says so."""
        root = self.home.path
        build, publish = self.poured()
        self.assertEqual(self.move()["status"], "completed")
        store = self.record()["store"]
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        real = jira["operations"]["operation.describe-tracker"]
        jira["operations"]["operation.describe-tracker"] = lambda request: dict(
            real(request), storeId=None
        )
        self.addCleanup(jira["operations"].__setitem__, "operation.describe-tracker", real)
        ship = self.m.invoke_tracker(
            "operation.create-item", {"root": root, "tracker": "local", "title": "Ship"}
        )
        self.assertEqual(ship["status"], "completed", ship)
        count = len(self.site.stub.issues)
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        path = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        self.assertEqual(
            again["summary"],
            self.m.MOVE_ELSEWHERE_FINISHED
            % ("local", "jira", store, "jira", self.m.STORE_UNNAMED, path, store),
        )
        self.assertEqual(len(self.site.stub.issues), count)

    def local(self, title, root=None, **fields):
        """The id of an item made in local, in the checkout given."""
        made = self.m.invoke_tracker(
            "operation.create-item",
            dict({"root": root or self.home.path, "tracker": "local", "title": title}, **fields),
        )
        self.assertEqual(made["status"], "completed", made)
        return made["item"]["id"]

    def test_a_close_the_target_refuses_holds_only_what_is_closed(self):
        """Ship, closed in local while it needs Notes, still open: Jira will
        not close Ship while Notes stands open, and the move stops. Notes has
        nothing left to write, so nothing holds it, and closed there it lets
        the next run close Ship."""
        root = self.home.path
        ship, notes = self.local("Ship"), self.local("Notes")
        self.assertEqual(self.forward(root, "local", "close", ship)["status"], "completed")
        need = {"root": root, "tracker": "local", "id": ship, "needs": notes}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        first = self.move()
        self.assertEqual(first["status"], "failed", first)
        self.assertIn("jira refused the close of %s" % ship, first["summary"])
        ids = self.record()["ids"]
        self.assertEqual(self.record()["settled"], [notes])
        closed = self.forward(root, "jira", "close", ids[notes])
        self.assertEqual(closed["closedRefs"], [ids[notes]], closed)
        held = self.forward(root, "jira", "close", ids[ship])
        self.assertEqual((held["closedRefs"], held["summary"]), ([], self.unfinished(ids[ship])))
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(ids[ship])["status"], "closed")

    def test_an_issue_done_over_an_open_child_moves_once_the_child_closes(self):
        """An issue Jira holds done with a child not done, as Jira allows:
        local will not close it while the child stands open, and the move
        stops. The child has nothing left to write, so nothing holds it, and
        closed in local it lets the next run close its parent."""
        root = self.checkout()
        epic, story = self.made(root, "Epic"), self.made(root, "Story")
        self.site.stub.issues[epic]["_status"] = "Done"
        self.site.stub.issues[story]["parent"] = {"key": epic}
        first = self.moved(root)
        self.assertEqual(first["status"], "failed", first)
        self.assertIn("local refused the close of %s" % epic, first["summary"])
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        closed = self.forward(root, "local", "close", ids[story])
        self.assertEqual(closed["closedRefs"], [ids[story]], closed)
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(ids[epic], root, "local")["status"], "closed")

    def down_in_local(self, root, operation="add-need"):
        """local, answering every add-need of the checkout given as down, or
        every request of the operation given."""
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        down = {"status": "failed", "reason": "adapter-failed", "exitCode": 1, "summary": "down"}
        return mock.patch.dict(
            local["operations"], {"operation." + operation: lambda request: dict(down)}
        )

    def lagging(self, *keys):
        """The stub, its search leaving out the issues given, as a search
        catching up with what was written does, its lookup showing them."""
        return mock.patch.dict(self.site.stub.lagging, {k: None for k in keys})

    def written_elsewhere(self):
        """Forget what this home wrote of late in Jira, so that it stands as
        what was written through another home, or in Jira itself: a search
        is then all the adapter knows of it."""
        path = os.path.join(os.path.dirname(self.m.workspace(self.home.path)), "trackers")
        with contextlib.suppress(FileNotFoundError):
            os.remove(os.path.join(path, "jira-written.log"))

    def unlisted(self, key, *told):
        """What a move from Jira to local answers of an issue Jira shows and
        does not list, told the others given are gone from Jira."""
        again = "dotdiw tracker migrate jira local"
        first = " ".join([again] + ["--source-gone %s" % k for k in sorted(told)])
        gone = " ".join([again] + ["--source-gone %s" % k for k in sorted(told + (key,))])
        return self.m.MOVE_UNLISTED % ("jira", key, first, gone)

    def j2l(self, root):
        """The record of the move from Jira to local in the checkout given."""
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        with open(path, encoding="utf-8") as fh:
            record: dict[str, Any] = json.load(fh)
        return path, record

    def test_an_item_the_source_holds_no_more_stays_held_until_said(self):
        """A move from Jira stops before it links Two to One, and Three is
        deleted in Jira meanwhile: Jira neither lists nor shows it, as it
        answers of an issue its caller cannot see, so the next run writes
        nothing, says so, and Three's copy stays held. Told Three was
        deleted there, the run finishes One and Two and leaves Three's copy
        as it was made, held by nothing; Three back, the copy stays so."""
        root = self.checkout()
        one, two, three = self.made(root, "One"), self.made(root, "Two"), self.made(root, "Three")
        need = {"root": root, "tracker": "jira", "id": two, "needs": one}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        path, record = self.j2l(root)
        ids = record["ids"]
        kept = self.site.stub.issues.pop(three)
        again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(
            again["summary"],
            self.m.MOVE_SOURCE_GONE
            % (
                "jira",
                three,
                ids[three],
                "jira",
                "dotdiw tracker migrate jira local",
                "dotdiw tracker migrate jira local --source-gone %s" % three,
                ids[three],
            ),
        )
        closed = self.forward(root, "local", "close", ids[three])
        self.assertEqual(
            (closed["closedRefs"], closed["summary"]),
            ([], self.unfinished(ids[three], "local", root)),
        )
        self.assertEqual(self.show(ids[two], root, "local")["needs"], [])
        code, out = self.cli(
            root, "tracker", "migrate", "jira", "local", "--source-gone=%s" % three
        )
        self.assertEqual(code, 0, out)
        self.assertIn(
            "; left %s as made, as jira holds none of what local made it of." % ids[three], out
        )
        self.assertEqual(self.show(ids[two], root, "local")["needs"], [ids[one]])
        ready = self.forward(root, "local", "ready")
        self.assertIn(ids[three], [i["id"] for i in ready["items"]], ready)
        _, record = self.j2l(root)
        self.assertEqual((record["gone"], three in record["settled"]), ([three], True))
        self.site.stub.issues[three] = kept
        back = self.moved(root)
        self.assertEqual((back["status"], back["moved"], back["resumed"]), ("completed", 0, 0))
        _, record = self.j2l(root)
        self.assertEqual((record["gone"], three in record["settled"]), ([three], True))

    def test_an_issue_jira_lists_late_stays_held_until_it_lists_it(self):
        """A move from Jira stops before it links Publish to Build, issues
        written elsewhere than through this home. Run again while Jira's
        search leaves Publish out, though its lookup shows it: the run
        writes nothing, says so, and Publish's copy stays held, and
        unclosed. Listed again, the run links the two, Publish's copy
        waiting on Build's."""
        root = self.checkout()
        build, publish = self.made(root, "Build"), self.made(root, "Publish")
        need = {"root": root, "tracker": "jira", "id": publish, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.written_elsewhere()
        with self.lagging(publish):
            again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(again["summary"], self.unlisted(publish))
        closed = self.forward(root, "local", "close", ids[publish])
        self.assertEqual(
            (closed["closedRefs"], closed["summary"]),
            ([], self.unfinished(ids[publish], "local", root)),
        )
        _, record = self.j2l(root)
        self.assertEqual(record["settled"], [])
        third = self.moved(root)
        self.assertEqual(third["status"], "completed", third)
        shown = self.show(ids[publish], root, "local")
        self.assertEqual((shown["needs"], shown["status"]), ([ids[build]], "open"))

    def test_a_need_jira_lists_late_stops_the_move_before_it_writes(self):
        """Jira's search leaves Build out, though its lookup shows it, and
        Publish needs Build, both written elsewhere than through this home:
        the move writes nothing, rather than make Publish without its need.
        Listed, the move makes both."""
        root = self.checkout()
        build, publish = self.made(root, "Build"), self.made(root, "Publish")
        need = {"root": root, "tracker": "jira", "id": publish, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.written_elsewhere()
        with self.lagging(build):
            first = self.moved(root)
        self.assertEqual(first["status"], "failed", first)
        self.assertEqual(first["summary"], self.unlisted(build))
        path = os.path.join(self.m.workspace(root), "migration-jira-to-local.json")
        self.assertFalse(os.path.exists(path), "the move made nothing, and recorded nothing")
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        _, record = self.j2l(root)
        self.assertEqual(
            self.show(record["ids"][publish], root, "local")["needs"], [record["ids"][build]]
        )

    def refusing(self, nth):
        """The stub, answering 400 for the nth issue a move asks it to make."""
        stub = self.site.stub
        real = stub.handle
        posts: list[str] = []

        def refuse(method, path, query, body):
            if (method, path) == ("POST", "/rest/api/3/issue"):
                posts.append(body["fields"]["summary"])
                if len(posts) == nth:
                    return 400, {"errors": {"summary": "That summary is refused."}}
            return real(method, path, query, body)

        return mock.patch.object(stub, "handle", refuse)

    def test_an_issue_deleted_in_jira_is_made_again_once_said(self):
        """A move makes two of three items and is refused the third; the
        issue of one it made is deleted in Jira. The next run writes nothing
        more and says so, since Jira answers alike for an issue its caller
        cannot see; told the issue was deleted, it makes that item again,
        then the third, once each."""
        made_of = {self.local(t): t for t in ("Alpha", "Beta", "Gamma")}
        with self.refusing(3):
            first = self.move()
        self.assertEqual(first["status"], "failed", first)
        ident, made = sorted(self.record()["ids"].items())[0]
        del self.site.stub.issues[made]
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertEqual(
            again["summary"],
            self.m.MOVE_NOT_FOUND
            % (
                "jira",
                made,
                ident,
                made,
                "dotdiw tracker migrate local jira",
                "dotdiw tracker migrate local jira --deleted %s" % made,
            ),
        )
        told = self.move(deleted=[made])
        self.assertEqual(told["status"], "completed", told)
        titles = sorted(f["summary"] for f in self.site.stub.issues.values())
        self.assertEqual(titles, ["Alpha", "Beta", "Gamma"])
        self.assertNotEqual(self.record()["ids"][ident], made)
        self.assertEqual(
            self.site.stub.issues[self.record()["ids"][ident]]["summary"], made_of[ident]
        )
        self.assertEqual(sorted(self.record()["settled"]), sorted(made_of))

    def closing_refused(self):
        """The stub, answering 503 for every transition of an issue to done."""
        stub = self.site.stub
        real = stub.handle

        def refuse(method, path, query, body):
            if method == "POST" and path.endswith("/transitions"):
                wanted = ((body or {}).get("transition") or {}).get("id")
                for i, name in enumerate(STATUSES):
                    if str(i + 11) == wanted and STATUSES[name] == "done":
                        return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        return mock.patch.object(stub, "handle", refuse)

    def test_an_issue_waiting_on_a_deleted_one_waits_on_it_made_again(self):
        """Alpha, closed in local, and Beta, open and waiting on it, are
        moved; Jira will not close Alpha, so Beta is finished and Alpha not.
        Alpha's issue deleted in Jira and said so, the run makes Alpha again
        and Beta waits on the new one, as Beta stands there still; told that
        Beta was deleted too, the run makes both again."""
        root = self.home.path
        alpha, beta = self.local("Alpha"), self.local("Beta")
        need = {"root": root, "tracker": "local", "id": beta, "needs": alpha}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.forward(root, "local", "close", alpha)["status"], "completed")
        with self.closing_refused():
            first = self.move()
        self.assertEqual(first["status"], "failed", first)
        self.assertIn("jira refused the close of %s" % alpha, first["summary"])
        self.assertEqual(self.record()["settled"], [beta])
        ids = dict(self.record()["ids"])
        stub = self.site.stub
        del stub.issues[ids[alpha]]
        stub.links = [link for link in stub.links if ids[alpha] not in link]
        again = self.move(deleted=[ids[alpha]])
        self.assertEqual(again["status"], "completed", again)
        anew = dict(self.record()["ids"])
        self.assertNotEqual(anew[alpha], ids[alpha])
        self.assertEqual(self.show(anew[beta])["needs"], [anew[alpha]])
        self.assertEqual(self.show(anew[alpha])["status"], "closed")
        # Both deleted, and both named, as an earlier answer asked: both made.
        for key in (anew[alpha], anew[beta]):
            del stub.issues[key]
        stub.links = []
        both = self.move(deleted=[anew[alpha], anew[beta]])
        self.assertEqual(both["status"], "completed", both)
        last = self.record()["ids"]
        self.assertEqual(self.show(last[beta])["needs"], [last[alpha]])
        titles = sorted(f["summary"] for f in stub.issues.values())
        self.assertEqual(titles, ["Alpha", "Beta"])

    def test_issues_within_a_deleted_calling_step_are_made_again_with_it(self):
        """A move makes a run's Root, a calling step Call in it, and Inner
        poured within Call; Call's issue is deleted in Jira. Told so, the
        run makes nothing, and names Inner, which only its make puts within
        a call, to delete and name too."""
        top = self.local("Root")
        call = self.local("Call", parent=top, run=top, calls="mol-called")
        inner = self.local("Inner", parent=top, run=top, within=call, step="inner")
        self.assertEqual(self.move()["status"], "completed")
        stub = self.site.stub
        ids = dict(self.record()["ids"])
        self.assertEqual(
            (stub.properties[ids[inner]]["dotdiw"]["within"]), ids[call], "moved within its call"
        )
        del stub.issues[ids[call]]
        again = self.move(deleted=[ids[call]])
        self.assertEqual(again["status"], "failed", again)
        both = " ".join("--deleted %s" % key for key in sorted([ids[call], ids[inner]]))
        self.assertEqual(
            again["summary"],
            self.m.MOVE_DELETED_HELD
            % ("jira", ids[call], ids[inner], "jira", "dotdiw tracker migrate local jira " + both),
        )

    def test_issues_in_the_run_of_a_deleted_one_are_made_again_with_it(self):
        """A move makes Root, Step under it and Loose in its run, and stops
        on Loose's status; Root's issue is deleted in Jira. Told so, the run
        makes nothing, and names Loose, whose run only its make writes, to
        delete and name too -- not Step, which it puts under the new Root.
        Told both, it makes them again, though Loose was finished."""
        root = self.home.path
        top = self.local("Root")
        step = self.local("Step", parent=top)
        loose = self.local("Loose", run=top)
        moving = {"root": root, "tracker": "local", "id": loose, "status": "in_progress"}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", moving)["status"], "completed"
        )
        stub = self.site.stub
        real = stub.handle

        def stuck(method, path, query, body):
            if method == "POST" and path.endswith("/transitions"):
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", stuck):
            self.assertEqual(self.move()["status"], "failed")
        self.assertEqual(self.move()["status"], "completed")
        ids = dict(self.record()["ids"])
        del stub.issues[ids[top]]
        again = self.move(deleted=[ids[top]])
        self.assertEqual(again["status"], "failed", again)
        both = " ".join("--deleted %s" % key for key in sorted([ids[top], ids[loose]]))
        self.assertEqual(
            again["summary"],
            self.m.MOVE_DELETED_HELD
            % ("jira", ids[top], ids[loose], "jira", "dotdiw tracker migrate local jira " + both),
        )
        del stub.issues[ids[loose]]
        told = self.move(deleted=[ids[top], ids[loose]])
        self.assertEqual(told["status"], "completed", told)
        anew = self.record()["ids"]
        self.assertEqual(anew[step], ids[step])
        self.assertEqual(self.show(anew[step])["parent"], anew[top])
        shown = self.show(anew[loose])
        self.assertEqual((shown["run"], shown["status"]), (anew[top], "in_progress"))

    def closed(self, root, key):
        """What a close of the issue answers in the checkout given."""
        return self.m.invoke_tracker(
            "operation.close-item", {"root": root, "tracker": "jira", "id": key}
        )

    def test_a_child_made_a_moment_ago_holds_its_parents_close_though_no_search_finds_it(self):
        """A child is made under an issue, and Jira's search is still without
        it: a close of the issue is held by the child, read by its key, from
        this checkout and from another on the project. Written elsewhere
        than through this home, a search is all that is known of it."""
        root = self.checkout()
        parent = self.made(root, "Parent")
        child = self.made(root, "Child", parent=parent)
        with self.lagging(child):
            for checkout in (root, self.checkout()):
                held = self.closed(checkout, parent)
                self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [child]))
            self.written_elsewhere()
            self.assertEqual(self.closed(root, parent)["closedIds"], [parent])

    def test_a_step_closed_right_after_its_pour_leaves_the_root_open(self):
        """A run is poured and Jira's search is still without its steps: the
        close of its first step leaves the root open, the second standing
        open in its run. The close of the second closes the root, though
        the search has both steps open still."""
        root = self.checkout()
        steps = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "jira", "formulaRef": "m", "title": "Run", "steps": steps},
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, (a, b) = poured["rootId"], poured["stepIds"]
        with self.lagging(a, b):
            self.assertEqual(self.closed(root, a)["closedIds"], [a])
            held = self.closed(root, top)
            self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [b]))
        # And a search that still has both open: closed, they hold nothing.
        stale = {a: {"_status": "To Do"}, b: {"_status": "To Do"}}
        with mock.patch.dict(self.site.stub.lagging, stale):
            self.assertEqual(self.closed(root, b)["closedIds"], [b, top])

    def test_what_was_written_elsewhere_holds_a_close_by_what_a_search_finds(self):
        """A run and an issue made in it apart from its steps, written
        elsewhere than through this home, so that a search is all that is
        known of them: the close of the run's one step leaves the root open,
        the other issue standing open in its run, and holds the root's."""
        root = self.checkout()
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "jira", "formulaRef": "m", "title": "Run"}
            | {"steps": [{"id": "a", "title": "A"}]},
        )
        top, (step,) = poured["rootId"], poured["stepIds"]
        loose = self.made(root, "Loose", run=top)
        self.written_elsewhere()
        self.assertEqual(self.closed(root, step)["closedIds"], [step])
        held = self.closed(root, top)
        self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [loose]))

    def test_a_child_closed_or_opened_a_moment_ago_is_read_as_it_stands(self):
        """A child is closed, and Jira's search still has it open: its
        parent closes all the same. Another is opened again, and the search
        still has it closed: its parent's close is held by it."""
        root = self.checkout()
        stub = self.site.stub
        parent, other = self.made(root, "Parent"), self.made(root, "Other")
        child = self.made(root, "Child", parent=parent)
        again = self.made(root, "Again", parent=other)
        self.assertEqual(self.closed(root, again)["closedIds"], [again])
        self.written_elsewhere()  # so that the close is all this home wrote of Child
        self.assertEqual(self.closed(root, child)["closedIds"], [child])
        with mock.patch.dict(stub.lagging, {child: {"_status": "To Do"}}):
            self.assertEqual(self.closed(root, parent)["closedIds"], [parent])
        self.written_elsewhere()  # and the opening again all it wrote of Again
        opened = self.m.invoke_tracker(
            "operation.update-item",
            {"root": root, "tracker": "jira", "id": again, "status": "open"},
        )
        self.assertEqual(opened["status"], "completed", opened)
        with mock.patch.dict(stub.lagging, {again: {"_status": "Done"}}):
            held = self.closed(root, other)
            self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [again]))

    def test_a_child_moved_under_another_a_moment_ago_holds_that_ones_close(self):
        """An issue is moved under another, and Jira's search still has it
        under none: a close of its new parent is held by it."""
        root = self.checkout()
        parent, child = self.made(root, "Parent"), self.made(root, "Child")
        moved = self.m.invoke_tracker(
            "operation.update-item",
            {"root": root, "tracker": "jira", "id": child, "parent": parent},
        )
        self.assertEqual(moved["status"], "completed", moved)
        with mock.patch.dict(self.site.stub.lagging, {child: {"parent": None}}):
            held = self.closed(root, parent)
            self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [child]))

    def test_a_child_a_search_has_open_and_no_lookup_reads_holds_its_parents_close(self):
        """A child is made under Parent, and its lookup then answers that
        there is no such issue -- deleted, or no longer the token's to see,
        which Jira does not tell apart -- while Jira's search still has it
        open under Parent: Parent's close is held by it, as it is where
        nothing was written of late and the search is all that is known.
        Once the search is without it too, Parent closes."""
        root = self.checkout()
        parent = self.made(root, "Parent")
        child = self.made(root, "Child", parent=parent)
        self.site.stub.gone.add(child)
        held = self.closed(root, parent)
        self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [child]))
        self.written_elsewhere()
        held = self.closed(root, parent)
        self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [child]))
        with self.lagging(child):
            self.assertEqual(self.closed(root, parent)["closedIds"], [parent])

    def test_a_step_a_search_has_open_and_no_lookup_reads_keeps_its_root_open(self):
        """Two steps are poured, and the lookup of the second then answers
        that there is no such issue while Jira's search still has it open:
        the first's close closes no root in its wake."""
        root = self.checkout()
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {
                "root": root,
                "tracker": "jira",
                "formulaRef": "mol-two",
                "title": "mol-two",
                "steps": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            },
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, (a, b) = poured["rootId"], poured["stepIds"]
        self.site.stub.gone.add(b)
        self.assertEqual(self.closed(root, a)["closedIds"], [a])
        self.assertEqual(self.show(top, root)["status"], "open")

    def test_ready_reads_what_was_written_a_moment_ago_as_show_does(self):
        """Build is made, and Jira's search is still without it: ready gives
        it, in the order it was made. Publish comes to need Build through
        this home, and the search is without the link for a while: ready
        leaves Publish out, as show has it waiting on Build. Build is
        closed, and the search still has it open: ready gives Publish, its
        row the record show gives, with the same ETag, so a close held to
        it goes through."""
        root = self.checkout()
        stub = self.site.stub
        build, publish = self.made(root, "Build"), self.made(root, "Publish")
        with self.lagging(build):
            ready = self.forward(root, "jira", "ready")
        self.assertEqual([i["id"] for i in ready["items"]], [build, publish], ready)
        need = {"root": root, "tracker": "jira", "id": publish, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with mock.patch.dict(stub.lagging, {publish: {"issuelinks": []}}):
            ready = self.forward(root, "jira", "ready")
            self.assertEqual(ready["status"], "completed", ready)
            self.assertNotIn(publish, [i["id"] for i in ready["items"]], ready)
            self.assertEqual(self.closed(root, build)["closedIds"], [build])
            with mock.patch.dict(stub.lagging, {build: {"_status": "To Do"}}):
                ready = self.forward(root, "jira", "ready")
                (row,) = [i for i in ready["items"] if i["id"] == publish]
                shown = self.show(publish, root)
                self.assertEqual((row["needs"], row["etag"]), ([build], shown["etag"]))
                closed = self.forward(root, "jira", "close", publish, etags=[row["etag"]])
                self.assertEqual(closed["status"], "completed", closed)

    def test_show_gives_the_children_a_listing_under_the_issue_gives_though_a_search_lags(self):
        """Early, Moved and Late are made under Parent, and Moved taken to
        Other; Jira's search is still without Early, and has Moved under
        Parent: show gives Parent's children as a listing under it does,
        Early and Late in the order they were made, and not Moved."""
        root = self.checkout()
        parent, other = self.made(root, "Parent"), self.made(root, "Other")
        early, moved, late = (self.made(root, t, parent=parent) for t in ("Early", "Moved", "Late"))
        out = self.m.invoke_tracker(
            "operation.update-item", {"root": root, "tracker": "jira", "id": moved, "parent": other}
        )
        self.assertEqual(out["status"], "completed", out)
        with mock.patch.dict(
            self.site.stub.lagging, {early: None, moved: {"parent": {"key": parent}}}
        ):
            shown = self.m.invoke_tracker(
                "operation.show-item", {"root": root, "tracker": "jira", "id": parent}
            )
            listed = self.m.invoke_tracker(
                "operation.list-items",
                {"root": root, "tracker": "jira", "parent": parent, "scope": "all"},
            )
        self.assertEqual([c["id"] for c in shown["children"]], [early, late], shown)
        self.assertEqual([i["id"] for i in listed["items"]], [early, late], listed)

    def test_a_child_taken_from_under_an_issue_a_moment_ago_closes_no_cycle_through_it(self):
        """Child is taken from under Parent through this home, and Jira's
        search still has it there: Parent's close is not held by it, and
        Child needing Parent closes no cycle, so the need is written. Taken
        from under it elsewhere than through this home, the search is all
        that is known: Parent's close is held by Child, and the need is
        refused as a cycle."""
        root = self.checkout()
        for elsewhere, closes, needs in (
            (False, "completed", "completed"),
            (True, "blocked", "failed"),
        ):
            with self.subTest(elsewhere=elsewhere):
                parent = self.made(root, "Parent")
                child = self.made(root, "Child", parent=parent)
                out = self.m.invoke_tracker(
                    "operation.update-item",
                    {"root": root, "tracker": "jira", "id": child, "dropParent": True},
                )
                self.assertEqual(out["status"], "completed", out)
                if elsewhere:
                    self.written_elsewhere()
                need = {"root": root, "tracker": "jira", "id": child, "needs": parent}
                with mock.patch.dict(self.site.stub.lagging, {child: {"parent": {"key": parent}}}):
                    self.assertEqual(self.closed(root, parent)["status"], closes)
                    out = self.m.invoke_tracker("operation.add-need", need)
                self.assertEqual(out["status"], needs, out)
                if elsewhere:
                    self.assertEqual(out["reason"], "cycle", out)

    def test_a_step_poured_shows_its_claim_among_its_roots_children_as_a_search_reads_it(self):
        """A step with a claim is poured, and nothing this home wrote of
        late is read again by its key: its root's show gives the step among
        its children with its claim and its run, as the search reads them."""
        root = self.checkout()
        claim = {"statement": "Counted {{ n }}.", "slots": ["n"]}
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {
                "root": root,
                "tracker": "jira",
                "formulaRef": "mol-count",
                "title": "mol-count",
                "steps": [{"id": "count", "title": "Count", "claim": claim}],
            },
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, (step,) = poured["rootId"], poured["stepIds"]
        self.written_elsewhere()
        shown = self.m.invoke_tracker(
            "operation.show-item", {"root": root, "tracker": "jira", "id": top}
        )
        (child,) = shown["children"]
        self.assertEqual((child["id"], child.get("claim"), child.get("run")), (step, claim, top))

    def test_an_issue_made_a_moment_ago_is_listed_and_moved_though_no_search_finds_it(self):
        """An issue is made and Jira's search is still without it: a listing
        of every issue holds it, under its parent and in the project, so a
        move to local makes it. One of another project it does not hold."""
        root, other = self.checkout(), self.checkout(project="OTH")
        build = self.made(root, "Build")
        ship = self.made(root, "Ship", parent=build)
        theirs = self.made(other, "Theirs")
        with self.lagging(build, ship, theirs):
            for fields, wanted in (({}, [build, ship]), ({"parent": build}, [ship])):
                listed = self.m.invoke_tracker(
                    "operation.list-items",
                    dict({"root": root, "tracker": "jira", "scope": "all"}, **fields),
                )
                self.assertEqual([i["id"] for i in listed["items"]], wanted, listed)
            moved = self.moved(root)
        self.assertEqual(moved["status"], "completed", moved)
        self.assertEqual(self.local_titles(root), ["Build", "Ship"])

    def test_what_was_written_longer_ago_than_a_search_lags_is_kept_no_more(self):
        """What was written is kept for as long as a search may be without
        it, and no longer: past that, the next write forgets it, and a
        search is taken at its word."""
        root = self.checkout()
        parent = self.made(root, "Parent")
        child = self.made(root, "Child", parent=parent)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        module = jira["operations"]["operation.close-item"].__globals__
        path = module["lately"](root)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual([json.loads(line)["key"] for line in fh], [parent, child])
        self.assertEqual(module["written_lately"](root), {child: {parent}, parent: set()})
        with mock.patch.dict(os.environ, {"JIRA_SITE": "https://another.example"}):
            self.assertEqual(module["written_lately"](root), {})
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('cut sho\n{"at": "then", "key": "%s"}\n[1]\n' % parent)
        self.assertEqual(module["written_lately"](root), {child: {parent}, parent: set()})
        with mock.patch.dict(module, {"RECENT_SECONDS": 0.0}):
            self.assertEqual(module["written_lately"](root), {})
            other = self.made(root, "Other")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual([json.loads(line)["key"] for line in fh], [other])
            with self.lagging(child):
                self.assertEqual(self.closed(root, parent)["closedIds"], [parent])

    def test_a_run_says_what_it_was_told_and_had_nothing_to_do_of(self):
        """Told of a deletion in Jira of an issue Jira still holds, of one
        the move never made, and of a deletion in local of an item local
        still lists: the run does as it would untold, and says of each that
        nothing was made again, or left as made, of it."""
        build, publish = self.poured()
        self.assertEqual(self.move()["status"], "completed")
        made = self.record()["ids"][build]
        again = self.move(deleted=[made, "CHK-999"], sourceGoneIds=[publish])
        self.assertEqual(again["status"], "completed", again)
        self.assertTrue(
            again["summary"].endswith(
                "; nothing was made again of %s; nothing was left as made of %s."
                % (", ".join(sorted(["CHK-999", made])), publish)
            ),
            again["summary"],
        )
        self.assertEqual(self.record()["ids"][build], made)

    def test_the_command_given_names_all_the_run_was_told(self):
        """Alpha's issue and Beta's, which waits on it, are both gone from
        Jira, and the run is told of Alpha's alone: it writes nothing, and
        the command it gives names both, so that the next run is told all."""
        root = self.home.path
        alpha, beta = self.local("Alpha"), self.local("Beta")
        need = {"root": root, "tracker": "local", "id": beta, "needs": alpha}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.forward(root, "local", "close", alpha)["status"], "completed")
        with self.closing_refused():
            self.assertEqual(self.move()["status"], "failed")
        ids = dict(self.record()["ids"])
        stub = self.site.stub
        for key in (ids[alpha], ids[beta]):
            del stub.issues[key]
        stub.links = []
        again = self.move(deleted=[ids[alpha]])
        self.assertEqual(again["status"], "failed", again)
        both = " ".join("--deleted %s" % key for key in sorted([ids[alpha], ids[beta]]))
        command = again["summary"].split("if it was deleted, run ", 1)[1].split(", and the")[0]
        self.assertEqual(command, "dotdiw tracker migrate local jira %s" % both)
        self.assertEqual(self.record()["ids"], ids)
        code, out = self.home.dotdiw(*shlex.split(command)[1:])
        self.assertEqual(code, 0, out)
        last = self.record()["ids"]
        self.assertEqual(self.show(last[beta])["needs"], [last[alpha]])

    def test_an_issue_jira_shows_and_lists_no_more_is_gone_once_the_run_is_told(self):
        """Build is archived in Jira, which shows it by its key and lists it
        no more, and Publish needs it: the move writes nothing, and gives
        the command that tells it Build is gone from the source. Told so,
        it makes Publish without the need, and says so. Dock is archived
        before a run has finished it: told so, the run leaves its copy as
        it was made, and says so."""
        root = self.checkout()
        build, publish = self.made(root, "Build"), self.made(root, "Publish")
        need = {"root": root, "tracker": "jira", "id": publish, "needs": build}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.written_elsewhere()
        with self.lagging(build):
            first = self.moved(root)
            self.assertEqual((first["status"], first["summary"]), ("failed", self.unlisted(build)))
            told = self.moved(root, sourceGoneIds=[build])
            self.assertEqual(told["status"], "completed", told)
            self.assertTrue(
                told["summary"].endswith(
                    "; left out, as jira lists none of them: %s needs %s." % (publish, build)
                ),
                told["summary"],
            )
            ship, dock = self.made(root, "Ship"), self.made(root, "Dock")
            need = {"root": root, "tracker": "jira", "id": dock, "needs": ship}
            done = self.m.invoke_tracker("operation.add-need", need)
            self.assertEqual(done["status"], "completed", done)
            self.written_elsewhere()
            with self.down_in_local(root):
                self.assertEqual(self.moved(root)["status"], "failed")
            with self.lagging(dock):
                again = self.moved(root)
                self.assertEqual(
                    (again["status"], again["summary"]), ("failed", self.unlisted(dock))
                )
                last = self.moved(root, sourceGoneIds=[dock])
        self.assertEqual(last["status"], "completed", last)
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertTrue(
            last["summary"].endswith(
                "; left %s as made, as jira holds none of what local made it of." % ids[dock]
            ),
            last["summary"],
        )
        self.assertEqual((record["gone"], sorted(record["settled"])), ([dock], sorted(ids)))
        self.assertEqual(self.show(ids[publish], root, "local")["needs"], [])

    def test_a_parent_jira_lists_late_stops_the_move_before_it_writes(self):
        """Jira's search leaves Epic out, though its lookup shows it, and
        Story stands under Epic, both written elsewhere than through this
        home: the move writes nothing, rather than make Story under none."""
        root = self.checkout()
        epic = self.made(root, "Epic")
        self.made(root, "Story", parent=epic)
        self.written_elsewhere()
        with self.lagging(epic):
            first = self.moved(root)
        self.assertEqual(first["status"], "failed", first)
        self.assertEqual(first["summary"], self.unlisted(epic))
        self.assertEqual(self.moved(root)["status"], "completed")
        self.assertEqual(self.local_titles(root), ["Epic", "Story"])

    def test_a_move_takes_an_issue_as_jira_shows_it_not_as_its_search_has_it(self):
        """Story was put under Epic and closed, and Jira's search still has
        it open, under none: the move makes it as Jira shows it by its key,
        under Epic's copy, and closed."""
        root = self.checkout()
        epic, story = self.made(root, "Epic"), self.made(root, "Story")
        under = {"root": root, "tracker": "jira", "id": story, "parent": epic}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", under)["status"], "completed"
        )
        self.assertEqual(self.closed(root, story)["closedIds"], [story])
        self.written_elsewhere()  # a search is then all that is known of the writes
        stale = {story: {"_status": "To Do", "parent": None}}
        with mock.patch.dict(self.site.stub.lagging, stale):
            moved = self.moved(root)
        self.assertEqual(moved["status"], "completed", moved)
        _, record = self.j2l(root)
        shown = self.show(record["ids"][story], root, "local")
        self.assertEqual((shown["status"], shown["parent"]), ("closed", record["ids"][epic]))

    def test_an_id_with_a_space_is_one_word_in_the_command_given(self):
        """An item of local whose id holds a space is moved and not finished,
        then gone from local: the command the run gives to say so names it
        as one word to a shell, and run as given, the move goes on."""
        root = self.home.path
        odd = self.local("Odd", id="odd id")
        self.assertEqual(odd, "odd id")
        closing = {"root": root, "tracker": "local", "id": odd}
        self.assertEqual(
            self.m.invoke_tracker("operation.close-item", closing)["status"], "completed"
        )
        with self.closing_refused():
            self.assertEqual(self.move()["status"], "failed")
        made = self.record()["ids"][odd]
        conn = sqlite3.connect(self.m.local_store(root))
        with conn:
            conn.execute("DELETE FROM items WHERE id = ?", (odd,))
        conn.close()
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        command = (
            again["summary"].split("if it was deleted, run ", 1)[1].split(", and %s" % made)[0]
        )
        self.assertEqual(
            shlex.split(command),
            ["dotdiw", "tracker", "migrate", "local", "jira", "--source-gone", odd],
        )
        code, out = self.home.dotdiw(*shlex.split(command)[1:])
        self.assertEqual(code, 0, out)
        self.assertEqual((self.record()["gone"], self.record()["settled"]), ([odd], [odd]))

    def test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed(self):
        """Root needs X, and Loose is in Root's run. The move from Jira stops
        before it writes the need; Loose is gone from Jira and the run told
        so, which leaves its copy as made while the run stops again. A close
        of Loose's copy closes it alone: Root's copy, which the move holds,
        stays open, and the next run makes it wait on X's."""
        root = self.checkout()
        top, x = self.made(root, "Root"), self.made(root, "X")
        loose = self.made(root, "Loose", run=top)
        need = {"root": root, "tracker": "jira", "id": top, "needs": x}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
            _, record = self.j2l(root)
            ids = record["ids"]
            del self.site.stub.issues[loose]
            self.assertEqual(self.moved(root, sourceGoneIds=[loose])["status"], "failed")
        _, record = self.j2l(root)
        self.assertEqual((record["gone"], record["settled"]), ([loose], [loose]))
        wake = self.forward(root, "local", "close", ids[loose])
        self.assertEqual(wake["closedRefs"], [ids[loose]], wake)
        self.assertEqual(self.show(ids[top], root, "local")["status"], "open")
        self.assertEqual(self.moved(root)["status"], "completed")
        shown = self.show(ids[top], root, "local")
        self.assertEqual((shown["status"], shown["needs"]), ("open", [ids[x]]))

    def test_a_root_held_to_wait_on_an_issue_made_again_stays_open_in_the_wake_of_its_run(self):
        """Moved to Jira and finished: Root needs X, and Loose is in Root's
        run. X's issue is deleted and the run told so, Jira refusing to make
        it again, so Root is held until it waits on the new one. A close of
        Loose's issue closes it alone, and the next run links Root, open."""
        root = self.home.path
        top, x = self.local("Root"), self.local("X")
        loose = self.local("Loose", run=top)
        need = {"root": root, "tracker": "local", "id": top, "needs": x}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.move()["status"], "completed")
        ids = dict(self.record()["ids"])
        stub = self.site.stub
        del stub.issues[ids[x]]
        stub.links = [link for link in stub.links if ids[x] not in link]
        with self.refusing(1):
            self.assertEqual(self.move(deleted=[ids[x]])["status"], "failed")
        self.assertEqual(self.record()["relink"], [top])
        direct = self.forward(root, "jira", "close", ids[top])
        self.assertEqual((direct["closedRefs"], direct["summary"]), ([], self.unfinished(ids[top])))
        wake = self.forward(root, "jira", "close", ids[loose])
        self.assertEqual(wake["closedRefs"], [ids[loose]], wake)
        self.assertEqual(self.show(ids[top])["status"], "open")
        self.assertEqual(self.move()["status"], "completed")
        anew = self.record()["ids"]
        shown = self.show(anew[top])
        self.assertEqual((shown["status"], shown["needs"]), ("open", [anew[x]]))
        self.assertEqual(self.record()["relink"], [])

    def test_a_key_in_another_case_is_the_issue_it_names(self):
        """Jira reads an issue's key in any case, and gives the issue's own:
        a close of a parent named in lower case is held by its open child as
        one named as Jira has it is, and each write so named is of that
        issue, kept and answered under its own key."""
        root = self.checkout()
        parent, other = self.made(root, "Parent"), self.made(root, "Other")
        child = self.made(root, "Child", parent=parent.lower())
        self.assertEqual(self.show(child, root)["parent"], parent)
        out = self.forward(root, "jira", "close", parent.lower())
        self.assertEqual(out["closedRefs"], [], out)
        self.assertEqual(out["summary"], "%s is blocked by %s." % (parent, child))
        asked = {"root": root, "tracker": "jira"}
        need = self.m.invoke_tracker(
            "operation.add-need", dict(asked, id=other.lower(), needs=child.lower())
        )
        self.assertEqual(need["edge"], {"id": other, "needs": child}, need)
        moved = self.m.invoke_tracker(
            "operation.update-item", dict(asked, id=other.lower(), parent=parent.lower())
        )
        self.assertEqual((moved["status"], moved["item"]["parent"]), ("completed", parent), moved)
        with self.lagging(other):
            held = self.closed(root, parent.lower())
            self.assertEqual(held.get("blockedBy"), [other, child], held)
            listed = self.m.invoke_tracker(
                "operation.list-items", dict(asked, scope="all", parent=parent.lower())
            )
            self.assertEqual([i["id"] for i in listed["items"]], [other, child], listed)
        shut = self.closed(root, child.lower())
        self.assertEqual((shut["closedIds"], shut["item"]["id"]), ([child], child), shut)
        values = self.m.invoke_tracker(
            "operation.record-values",
            dict(asked, id=other.lower(), values=[{"label": "n", "text": "1"}]),
        )
        self.assertEqual((values["status"], values["item"]["id"]), ("completed", other), values)
        self.assertEqual(self.show(other.lower(), root)["id"], other)

    def test_each_command_given_names_the_stores_the_run_was_told(self):
        """A stopped move from Jira whose record names no store read from,
        as an earlier dotdiw wrote it, and an issue it has not finished gone
        from Jira: told the store, as its answer says, the run answers that
        the issue is gone, and the command that answer gives names the
        store as well, so that it goes on."""
        root, here = self.checkout(), "%s/projects/CHK" % self.site.url
        one, two, three = self.made(root, "One"), self.made(root, "Two"), self.made(root, "Three")
        need = {"root": root, "tracker": "jira", "id": two, "needs": one}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        path, record = self.j2l(root)
        del record["fromStore"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        del self.site.stub.issues[three]
        code, out = self.cli(root, "tracker", "migrate", "jira", "local")
        self.assertEqual((code, "does not say which store" in out), (1, True), out)
        command = shlex.split(out.split(" run ", 1)[1].split(", and the move goes on")[0])
        self.assertEqual(command[1:], ["tracker", "migrate", "jira", "local", "--from-store", here])
        code, out = self.cli(root, *command[1:])
        self.assertEqual((code, "nor shows it by its id" in out), (1, True), out)
        command = shlex.split(out.split("if it was deleted, run ", 1)[1].split(", and ")[0])
        self.assertEqual(command[5:], ["--from-store", here, "--source-gone", three])
        code, out = self.cli(root, *command[1:])
        self.assertEqual(code, 0, out)
        # And the other way about: told what is gone, the answer for the
        # store names that too.
        _, record = self.j2l(root)
        del record["fromStore"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        again = self.moved(root, sourceGoneIds=[two], deletedIds=["CHK-999"])
        self.assertEqual(again["status"], "failed", again)
        self.assertIn(
            " run dotdiw tracker migrate jira local --from-store %s --deleted CHK-999 "
            "--source-gone %s, and the move goes on" % (here, two),
            again["summary"],
        )

    def test_the_root_of_a_run_jira_lists_late_stops_the_move_before_it_writes(self):
        """Jira's search leaves Root out, though its lookup shows it, and
        Loose is in Root's run, both written elsewhere than through this
        home: the move writes nothing, rather than make Loose out of its
        run. Listed, the move makes both, Loose's copy in the run of Root's."""
        root = self.checkout()
        top = self.made(root, "Root")
        loose = self.made(root, "Loose", run=top)
        self.written_elsewhere()
        with self.lagging(top):
            first = self.moved(root)
        self.assertEqual((first["status"], first["summary"]), ("failed", self.unlisted(top)))
        self.assertEqual(self.moved(root)["status"], "completed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(self.show(ids[loose], root, "local")["run"], ids[top])

    def test_a_close_cut_short_keeps_its_reason_on_the_next_run(self):
        """Alpha is closed in local with a reason. Jira moves its issue to
        done and answers 503 for the comment that keeps the reason, so the
        move stops. Run again, it finds the issue closed, and without its
        reason: it writes the reason before it finishes the item."""
        root = self.home.path
        alpha = self.local("Alpha")
        closed = self.forward(root, "local", "close", alpha, "--reason", "shipped in 1.2")
        self.assertEqual(closed["status"], "completed", closed)
        stub = self.site.stub
        real = stub.handle

        def no_comment(method, path, query, body):
            if method == "POST" and path.endswith("/comment"):
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", no_comment):
            self.assertEqual(self.move()["status"], "failed")
        made = self.record()["ids"][alpha]
        self.assertEqual((self.show(made)["status"], self.show(made)["reason"]), ("closed", None))
        self.assertEqual(self.move()["status"], "completed")
        shown = self.show(made)
        self.assertEqual((shown["status"], shown["reason"]), ("closed", "shipped in 1.2"))
        # One that has its reason keeps it, whatever a later close gives.
        again = self.m.invoke_tracker(
            "operation.close-item",
            {"root": root, "tracker": "jira", "id": made, "closeReason": "another"},
        )
        self.assertEqual((again["closedIds"], again["item"]["reason"]), ([], "shipped in 1.2"))

    def test_an_issue_moved_under_another_a_moment_ago_is_listed_as_it_stands(self):
        """Y is moved under X, so that X waits on Y, and Jira's search still
        has Y under none: the listing of every issue has Y under X, as Jira
        shows it by its key, so making Y need X is refused, as it is when
        the search has caught up -- neither could close."""
        root = self.checkout()
        x, y = self.made(root, "X"), self.made(root, "Y")
        moved = self.forward(root, "jira", "update", y, "--parent", x)
        self.assertEqual(moved["status"], "completed", moved)
        with mock.patch.dict(self.site.stub.lagging, {y: {"parent": None}}):
            listed = self.m.invoke_tracker(
                "operation.list-items", {"root": root, "tracker": "jira", "scope": "all"}
            )
            self.assertEqual({i["id"]: i["parent"] for i in listed["items"]}, {x: None, y: x})
            out = self.forward(root, "jira", "dep", "add", y, x)
        self.assertEqual((out["status"], self.site.stub.links), ("failed", []), out)
        self.assertIn("neither could close", out["summary"])

    def test_an_issue_closed_in_jira_stays_closed_when_its_need_is_made_again(self):
        """W, in progress, and V, closed, need X; moved and finished. W's
        issue is then closed in Jira, and X's deleted there and the run told
        so: the run makes X again and both issues wait on the new one, W's
        closed as it was -- its status is no longer the move's to write."""
        root = self.home.path
        x, w, v = self.local("X"), self.local("W"), self.local("V")
        for one in (w, v):
            need = {"root": root, "tracker": "local", "id": one, "needs": x}
            linked = self.m.invoke_tracker("operation.add-need", need)
            self.assertEqual(linked["status"], "completed", linked)
        for one in (x, v):
            self.assertEqual(self.forward(root, "local", "close", one)["status"], "completed")
        going = {"root": root, "tracker": "local", "id": w, "status": "in_progress"}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", going)["status"], "completed"
        )
        self.assertEqual(self.move()["status"], "completed")
        ids = dict(self.record()["ids"])
        closed = self.forward(root, "jira", "close", ids[w], "--reason", "shipped")
        self.assertEqual(closed["closedRefs"], [ids[w]], closed)
        stub = self.site.stub
        del stub.issues[ids[x]]
        stub.links = [link for link in stub.links if ids[x] not in link]
        again = self.move(deleted=[ids[x]])
        self.assertEqual(again["status"], "completed", again)
        anew = self.record()["ids"]
        shown = self.show(ids[w])
        self.assertEqual(
            (shown["status"], shown["reason"], shown["needs"]), ("closed", "shipped", [anew[x]])
        )
        shown = self.show(ids[v])
        self.assertEqual((shown["status"], shown["needs"]), ("closed", [anew[x]]))
        self.assertEqual(
            (self.record()["relink"], sorted(self.record()["settled"])), ([], sorted(ids))
        )

    def test_a_store_said_with_a_space_is_quoted_in_the_command_given(self):
        """A store named with a space, in a record that names none: the
        command the run gives names it as one word to the shell."""
        build, publish = self.stopped()
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        record = self.record()
        del record["store"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        _, jira = self.m.resolve_tracker({"root": self.home.path, "tracker": "jira"})
        real = jira["operations"]["operation.describe-tracker"]
        spaced = "%s/projects/CHK of ours" % self.site.url
        jira["operations"]["operation.describe-tracker"] = lambda request: dict(
            real(request), storeId=spaced
        )
        self.addCleanup(jira["operations"].__setitem__, "operation.describe-tracker", real)
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        command = again["summary"].split(" run ", 1)[1].split(", and the move goes on")[0]
        self.assertEqual(
            shlex.split(command),
            ["dotdiw", "tracker", "migrate", "local", "jira", "--to-store", spaced],
        )

    def test_a_finished_issue_said_deleted_is_made_again(self):
        """Finished, the move is told an issue it made was deleted in Jira:
        it makes the item again, and what waits on it waits on the new one."""
        build, publish = self.poured()
        self.assertEqual(self.move()["status"], "completed")
        ids = dict(self.record()["ids"])
        stub = self.site.stub
        del stub.issues[ids[build]]
        stub.links = [link for link in stub.links if ids[build] not in link]
        again = self.move(deleted=[ids[build]])
        self.assertEqual(again["status"], "completed", again)
        anew = dict(self.record()["ids"])
        self.assertNotEqual(anew[build], ids[build])
        self.assertEqual(self.show(ids[publish])["needs"], [anew[build]])
        self.assertEqual(sorted(self.record()["settled"]), sorted(ids))
        # And Publish's, which waits on it: made again, waiting on Build's.
        del stub.issues[anew[publish]]
        stub.links = []
        again = self.move(deleted=[anew[publish]])
        self.assertEqual(again["status"], "completed", again)
        last = self.record()["ids"]
        self.assertEqual((last[build], last[publish] != anew[publish]), (anew[build], True))
        self.assertEqual(self.show(last[publish])["needs"], [last[build]])

    def test_a_move_says_what_it_leaves_out_of_another_project(self):
        """Moved from Jira, an issue waiting on one of another project, one
        standing under another project's, and one in the run of it: local
        holds none of those, so the move leaves the need, the parent and
        the run out and says so."""
        root, other = self.checkout(), self.checkout(project="OTH")
        mine, theirs = self.made(root, "Mine"), self.made(other, "Theirs")
        child, epic = self.made(root, "Child"), self.made(other, "Their epic")
        loose = self.made(root, "Loose")
        self.site.stub.links.append((theirs, mine))
        self.site.stub.issues[child]["parent"] = {"key": epic}
        self.site.stub.properties[loose] = {"dotdiw": {"run": epic}}
        moved = self.moved(root)
        self.assertEqual(moved["status"], "completed", moved)
        self.assertTrue(
            moved["summary"].endswith(
                "; left out, as jira lists none of them: %s needs %s, %s stands under %s, "
                "%s is in the run of %s." % (mine, theirs, child, epic, loose, epic)
            ),
            moved["summary"],
        )

    def test_a_listing_under_a_parent_reaches_no_other_project(self):
        """A parent to list under that reads as more of the query is one
        value to Jira: the listing names no issue of another project."""
        ours, other = self.checkout(), self.checkout(project="OTH")
        mine, theirs = self.made(ours, "Mine"), self.made(other, "Theirs")
        under = self.made(ours, "Under", parent=mine)
        self.written_elsewhere()  # what the search finds is all the listing knows
        for parent, wanted in (
            (mine, [under]),
            ("%s/../../myself" % mine, []),
            ("%s?fields=summary" % mine, []),
            ("%s OR project = OTH" % mine, []),
            ('%s" OR project = OTH OR parent = "%s' % (mine, mine), []),
            ('%s\\" OR project = OTH OR parent = "%s' % (mine, mine), []),
        ):
            listed = self.m.invoke_tracker(
                "operation.list-items", {"root": ours, "tracker": "jira", "parent": parent}
            )
            self.assertEqual(listed["status"], "completed", listed)
            self.assertEqual([i["id"] for i in listed["items"]], wanted, (parent, theirs))

    def down_for(self, wanted):
        """The stub, answering 503 for every request wanted(method, path) picks."""
        stub = self.site.stub
        real = stub.handle

        def down(method, path, query, body):
            if wanted(method, path):
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        return mock.patch.object(stub, "handle", down)

    def deleted_in_local(self, root, ident):
        """The item taken out of local's store in the checkout given, with
        the needs that name it, and the parent it is of, as a hand in the
        store would."""
        conn = sqlite3.connect(self.m.local_store(root))
        with conn:
            conn.execute("UPDATE items SET parent = NULL WHERE parent = ?", (ident,))
            conn.execute("DELETE FROM edges WHERE id = ? OR needs = ?", (ident, ident))
            conn.execute("DELETE FROM items WHERE id = ?", (ident,))
        conn.close()

    def test_a_need_turned_round_in_jira_while_stopped_is_written_as_jira_shows_it(self):
        """A and B are done, A needing B, and Story, open, stands under B:
        local will not close A while B's copy stands open over Story's, and
        the move stops, A's copy waiting on B's. The need is turned round in
        Jira and Story's copy closed: the next run finishes, B's copy
        waiting on A's and A's on nothing, as Jira shows them."""
        root = self.checkout()
        a, b, story = self.made(root, "A"), self.made(root, "B"), self.made(root, "Story")
        stub = self.site.stub
        for key in (a, b):
            stub.issues[key]["_status"] = "Done"
        stub.issues[story]["parent"] = {"key": b}
        need = {"root": root, "tracker": "jira", "id": a, "needs": b}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(self.show(ids[a], root, "local")["needs"], [ids[b]])
        stub.links = [(inward, outward) for outward, inward in stub.links]
        self.written_elsewhere()
        self.assertEqual(self.forward(root, "local", "close", ids[story])["status"], "completed")
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        needs = [self.show(ids[k], root, "local")["needs"] for k in (a, b)]
        self.assertEqual(needs, [[], [ids[a]]])

    def test_an_archived_need_whose_copy_was_deleted_is_left_out_once_both_are_said(self):
        """Two needs Three, and the move from Jira stops before it writes
        the need. Three's copy is then deleted in local, and Three archived
        in Jira, which shows it by its key and lists it no more: told both,
        the run goes on, makes Two's copy without the need, and says so."""
        root = self.checkout()
        two, three = self.made(root, "Two"), self.made(root, "Three")
        need = {"root": root, "tracker": "jira", "id": two, "needs": three}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.deleted_in_local(root, ids[three])
        self.written_elsewhere()
        with self.lagging(three):
            told = self.moved(root, deletedIds=[ids[three]], sourceGoneIds=[three])
        self.assertEqual(told["status"], "completed", told)
        self.assertIn(
            "left out, as jira lists none of them: %s needs %s" % (two, three), told["summary"]
        )
        self.assertEqual(self.show(ids[two], root, "local")["needs"], [])

    def test_a_copy_an_earlier_run_left_as_made_is_said_by_the_run_that_finishes(self):
        """Three, in progress, needs One, and Epic is done over Story, open;
        the move from Jira stops before it writes the need. Three archived
        and the run told so, it leaves Three's copy as made, and stops on
        Epic's close. Story's copy closed, the same run finishes and says
        it left Three's copy as made -- not that it left nothing so."""
        root = self.checkout()
        one, three = self.made(root, "One"), self.made(root, "Three")
        epic, story = self.made(root, "Epic"), self.made(root, "Story")
        stub = self.site.stub
        stub.issues[three]["_status"] = "In Progress"
        stub.issues[epic]["_status"] = "Done"
        stub.issues[story]["parent"] = {"key": epic}
        need = {"root": root, "tracker": "jira", "id": three, "needs": one}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.written_elsewhere()
        with self.lagging(three):
            told = self.moved(root, sourceGoneIds=[three])
            self.assertEqual(told["status"], "failed", told)
            self.assertEqual(self.j2l(root)[1]["gone"], [three])
            closed = self.forward(root, "local", "close", ids[story])
            self.assertEqual(closed["status"], "completed", closed)
            last = self.moved(root, sourceGoneIds=[three])
        self.assertEqual(last["status"], "completed", last)
        self.assertNotIn("nothing was left as made of %s" % three, last["summary"])
        self.assertIn("left %s as made" % ids[three], last["summary"])

    def test_a_parent_written_in_the_source_between_runs_reaches_the_copy(self):
        """Child stands under Old, and the move to Jira stops at the links,
        every item made and none finished; Child is moved under New in local.
        The run that finishes puts Child's issue under New's. The same of a
        move from Jira of Story, put under Epic between its runs."""
        root = self.home.path
        old, new = self.local("Old"), self.local("New")
        child, other = self.local("Child", parent=old), self.local("Other")
        need = {"root": root, "tracker": "local", "id": other, "needs": child}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_for(lambda method, path: path.endswith("/issueLink")):
            self.assertEqual(self.move()["status"], "failed")
        ids = self.record()["ids"]
        self.assertEqual(self.show(ids[child])["parent"], ids[old])
        moving = self.forward(root, "local", "update", child, "--parent", new)
        self.assertEqual(moving["status"], "completed", moving)
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual(self.show(ids[child])["parent"], ids[new])
        there = self.checkout()
        epic, story, task = (self.made(there, t) for t in ("Epic", "Story", "Task"))
        need = {"root": there, "tracker": "jira", "id": task, "needs": epic}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(there):
            self.assertEqual(self.moved(there)["status"], "failed")
        under = {"root": there, "tracker": "jira", "id": story, "parent": epic}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", under)["status"], "completed"
        )
        self.assertEqual(self.moved(there)["status"], "completed")
        ids = self.j2l(there)[1]["ids"]
        self.assertEqual(self.show(ids[story], there, "local")["parent"], ids[epic])

    def test_a_status_set_back_to_open_between_runs_reaches_the_copy(self):
        """A and B, in progress, and Ship, closed with a reason, are moved:
        Jira refuses the second status, and the move stops with one issue in
        progress. That one set back to open in local, the next run stops at
        the comment that keeps Ship's reason, Ship's issue done; Ship opened
        again in local, the run that finishes leaves both issues open, as
        local shows them."""
        root = self.home.path
        pair, ship = [self.local("A"), self.local("B")], self.local("Ship")
        for ident in pair:
            going = self.forward(root, "local", "update", ident, "--status", "in_progress")
            self.assertEqual(going["status"], "completed", going)
        shut = self.forward(root, "local", "close", ship, "--reason", "shipped")
        self.assertEqual(shut["status"], "completed", shut)
        seen: list[str] = []

        def second(method, path):
            if method != "POST" or not path.endswith("/transitions"):
                return False
            seen.append(path)
            return path != seen[0]

        with self.down_for(second):
            self.assertEqual(self.move()["status"], "failed")
        ids = self.record()["ids"]
        (busy,) = [i for i in pair if self.show(ids[i])["status"] == "in_progress"]
        back = {"root": root, "tracker": "local", "id": busy, "status": "open"}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", back)["status"], "completed"
        )
        with self.down_for(lambda method, path: path.endswith("/comment")):
            self.assertEqual(self.move()["status"], "failed")
        self.assertEqual(self.show(ids[ship])["status"], "closed")
        back = dict(back, id=ship)
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", back)["status"], "completed"
        )
        self.assertEqual(self.move()["status"], "completed")
        self.assertEqual([self.show(ids[i])["status"] for i in (busy, ship)], ["open", "open"])

    def test_a_closed_run_root_keeps_its_own_close_reason_either_way(self):
        """Root needs Gate, and Loose is in Root's run; Loose and Gate are
        closed, then Root with a reason of its own. Moved from Jira to local,
        and from local to Jira, Root's copy is closed with that reason, not
        with the one a close in the wake of its run's last item gives."""
        there = self.checkout()
        for root, tracker, make in (
            (there, "jira", lambda title, **f: self.made(there, title, **f)),
            (self.home.path, "local", self.local),
        ):
            gate, top = make("Gate"), make("Root")
            loose = make("Loose", run=top)
            need = {"root": root, "tracker": tracker, "id": top, "needs": gate}
            self.assertEqual(
                self.m.invoke_tracker("operation.add-need", need)["status"], "completed"
            )
            for ident in (loose, gate):
                self.assertEqual(self.forward(root, tracker, "close", ident)["status"], "completed")
            shut = self.forward(root, tracker, "close", top, "--reason", "released 1.2")
            self.assertEqual(shut["closedRefs"], [top], shut)
            if tracker == "jira":
                self.assertEqual(self.moved(root)["status"], "completed")
                copy = self.show(self.j2l(root)[1]["ids"][top], root, "local")
            else:
                self.assertEqual(self.move()["status"], "completed")
                copy = self.show(self.record()["ids"][top])
            self.assertEqual((copy["status"], copy["reason"]), ("closed", "released 1.2"))

    def test_a_migrate_given_help_or_an_option_it_does_not_take_writes_nothing(self):
        """tracker migrate given --help or -h prints its usage; given an
        option it does not know, one it once took under another name, or
        one that takes a value given none, it refuses it. None of them
        moves anything, nor keeps a record of a move."""
        root = self.home.path
        self.local("Alpha")
        path = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        for told, wanted in (
            (["--help"], 0),
            (["-h"], 0),
            (["--dry-run"], 2),
            (["--source-deleted=CHK-9"], 2),
            (["--deleted"], 2),
            (["--to-store="], 2),
        ):
            code, out = self.cli(root, "tracker", "migrate", "local", "jira", *told)
            self.assertEqual(code, wanted, (told, out))
            self.assertEqual((self.site.stub.issues, os.path.exists(path)), ({}, False), out)
            if not wanted:
                self.assertIn("tracker migrate", out)
            elif told[0].partition("=")[0] in ("--dry-run", "--source-deleted"):
                self.assertIn("%s is not one of its options" % told[0], out)

    def test_a_close_names_the_record_once_the_checkout_the_move_ran_in_is_gone(self):
        """The move stops, and the checkout it ran in is then removed: a
        close of what it made, from another checkout under the home, names
        the record that holds it, and how to let go of it, not the checkout
        that is no more."""
        build, publish = self.stopped()
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        gone, other = self.record()["checkout"], self.checkout()
        shutil.rmtree(self.home.path)
        closed = self.forward(other, "jira", "close", publish)
        self.assertEqual(closed["closedRefs"], [], closed)
        self.assertIn(path, closed["summary"])
        self.assertNotIn("again in %s," % gone, closed["summary"])
        aside = self.m.MOVE_RECORD_ASIDE % (path, "names as %s, now none of it" % gone)
        said = self.m.MOVE_UNFINISHED % (publish, "local", "jira", "dotdiw", "local", "jira", aside)
        self.assertEqual(closed["summary"], said)

    def test_a_need_left_out_is_said_by_the_run_that_finishes_after_a_stop_at_a_close(self):
        """Mine needs Theirs, of another project, so the move leaves the need
        out; Ship is done, and local is down for its close, so the run that
        settled Mine stops. The run that finishes says the need was left."""
        root, other = self.checkout(), self.checkout(project="OTH")
        mine, theirs = self.made(root, "Mine"), self.made(other, "Theirs")
        self.site.stub.links.append((theirs, mine))
        ship = self.made(root, "Ship")
        self.site.stub.issues[ship]["_status"] = "Done"
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        down = {"status": "failed", "reason": "adapter-failed", "exitCode": 1, "summary": "down"}
        with mock.patch.dict(local["operations"], {"operation.close-item": lambda r: dict(down)}):
            first = self.moved(root)
        self.assertIn("local refused the close of %s" % ship, first["summary"])
        self.assertIn(mine, self.j2l(root)[1]["settled"])
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        left = "left out, as jira lists none of them: %s needs %s" % (mine, theirs)
        self.assertIn(left, again["summary"])

    def test_a_title_a_priority_and_values_written_between_runs_reach_the_copy(self):
        """Task needs Other, and Confirm has a claim; the move to Jira stops
        at the link, nothing finished. Task renamed, its priority set to 0,
        and Confirm's values recorded in local, the run that finishes leaves
        each copy as local shows it."""
        asked = {"root": self.home.path, "tracker": "local"}
        claim = {"statement": "Roster {{ roster-id }}", "slots": ["roster-id"]}
        steps = [{"id": "c", "title": "Confirm", "claim": claim}]
        poured = self.m.invoke_tracker(
            "operation.pour-steps", dict(asked, formulaRef="m", title="Run", steps=steps)
        )
        (confirm,) = poured["stepIds"]
        task, other = self.local("Task"), self.local("Other")
        need = self.m.invoke_tracker("operation.add-need", dict(asked, id=task, needs=other))
        self.assertEqual(need["status"], "completed", need)
        with self.down_for(lambda method, path: path.endswith("/issueLink")):
            self.assertEqual(self.move()["status"], "failed")
        self.assertEqual(self.record()["settled"], [])
        values = [{"label": "roster-id", "text": "42"}]
        for operation, fields in (
            ("update-item", {"id": task, "title": "Task renamed", "priority": 0}),
            ("record-values", {"id": confirm, "values": values}),
        ):
            done = self.m.invoke_tracker("operation." + operation, dict(asked, **fields))
            self.assertEqual(done["status"], "completed", done)
        self.assertEqual(self.move()["status"], "completed")
        ids = self.record()["ids"]
        copy, step = self.show(ids[task]), self.show(ids[confirm])
        self.assertEqual(
            (copy["title"], copy["priority"], step.get("values")), ("Task renamed", 0, values)
        )

    def test_jira_refuses_a_need_that_would_wait_on_itself_through_a_parent_or_a_run(self):
        """Y needs P, and X stands under P, which waits on its child: X
        needing Y would wait on itself, and Jira's add-need refuses it, as
        dotdiw's own check does, so that no write of it -- a move's among
        them -- leaves a need nothing could close past. The same of Loose,
        in R's run, needing Z, which needs R."""
        root = self.checkout()
        p, y, top, z = (self.made(root, title) for title in ("P", "Y", "R", "Z"))
        x, loose = self.made(root, "X", parent=p), self.made(root, "Loose", run=top)
        asked = {"root": root, "tracker": "jira"}
        for ident, needs in ((y, p), (z, top)):
            done = self.m.invoke_tracker("operation.add-need", dict(asked, id=ident, needs=needs))
            self.assertEqual(done["status"], "completed", done)
        links = list(self.site.stub.links)
        for ident, needs in ((x, y), (loose, z)):
            out = self.m.invoke_tracker("operation.add-need", dict(asked, id=ident, needs=needs))
            self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)
        self.assertEqual(self.site.stub.links, links)

    def test_the_site_spelled_with_its_scheme_in_upper_case_holds_what_the_move_made(self):
        """Stopped before it linked Publish to Build: with JIRA_SITE naming
        the same site, its scheme in upper case, ready leaves both out and a
        close of Publish is refused. Run again, the move finishes, Publish
        open and waiting on Build."""
        root = self.home.path
        port = self.site.url.rsplit(":", 1)[1]
        with mock.patch.dict(os.environ, {"JIRA_SITE": "http://localhost:%s" % port}):
            build, publish = self.stopped()
        with mock.patch.dict(os.environ, {"JIRA_SITE": "HTTP://LocalHost:%s" % port}):
            ready = self.forward(root, "jira", "ready")
            self.assertFalse({build, publish} & {i["id"] for i in ready["items"]}, ready)
            closed = self.forward(root, "jira", "close", publish)
            self.assertEqual(closed["closedRefs"], [], closed)
        with mock.patch.dict(os.environ, {"JIRA_SITE": "http://localhost:%s" % port}):
            self.assertEqual(self.move()["status"], "completed")
            shown = self.show(publish)
        self.assertEqual((shown["status"], shown["needs"]), ("open", [build]))

    def test_a_parent_whose_copy_is_gone_from_jira_is_named_when_a_child_is_made_under_it(self):
        """Parent was moved to Jira, and its issue deleted there since. Child,
        made under it in local after, cannot be made under an issue Jira
        holds no more: the run says which copy is gone and how to go on, and
        told it was deleted, makes Parent again and Child under it."""
        parent = self.local("Parent")
        self.assertEqual(self.move()["status"], "completed")
        copy = self.record()["ids"][parent]
        del self.site.stub.issues[copy]
        child = self.local("Child", parent=parent)
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        said = "dotdiw tracker migrate local jira"
        self.assertEqual(
            again["summary"],
            self.m.MOVE_NOT_FOUND
            % ("jira", copy, parent, copy, said, "%s --deleted %s" % (said, copy)),
        )
        self.assertEqual(self.move(deleted=[copy])["status"], "completed")
        ids = self.record()["ids"]
        self.assertNotEqual(ids[parent], copy)
        self.assertEqual(self.show(ids[child])["parent"], ids[parent])

    def test_a_copy_gone_from_local_of_an_issue_gone_from_jira_is_not_said_left_as_made(self):
        """A move from Jira stops before it links Two to One. Two is then
        deleted in Jira, and its copy in local too. Told only that Two is
        gone from Jira, the run cannot leave as made a copy local holds no
        more: it says so, and told both, forgets Two and finishes One."""
        root = self.checkout()
        one, two = self.made(root, "One"), self.made(root, "Two")
        need = {"root": root, "tracker": "jira", "id": two, "needs": one}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        copy = record["ids"][two]
        del self.site.stub.issues[two]
        self.deleted_in_local(root, copy)
        told = self.moved(root, sourceGoneIds=[two])
        self.assertEqual(told["status"], "failed", told)
        self.assertIn("--deleted %s --source-gone %s" % (copy, two), told["summary"])
        both = self.moved(root, sourceGoneIds=[two], deletedIds=[copy])
        self.assertEqual(both["status"], "completed", both)
        self.assertIn("forgot %s" % two, both["summary"])
        self.assertNotIn("left %s as made" % copy, both["summary"])
        self.assertNotIn(two, self.j2l(root)[1]["ids"])

    def test_values_recorded_on_a_step_the_move_holds_ask_for_no_deletion_of_it(self):
        """A step with a claim is moved to Jira, which makes its issue and
        answers 503 when the move reads it back. A record of what the step
        found on that issue is refused, blocked by the move, or kept: either
        way the next run finishes the step, asking for no deletion of it,
        as though only a make wrote its values, and what was kept stays."""
        root = self.home.path
        claim = {"statement": "Roster {{ roster-id }}", "slots": ["roster-id"]}
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "local", "formulaRef": "m", "title": "Run"}
            | {"steps": [{"id": "c", "title": "Count", "claim": claim}]},
        )
        (step,) = poured["stepIds"]
        stub = self.site.stub
        real = stub.handle

        def unreadable(method, path, query, body):
            code, answer = real(method, path, query, body)
            if (method, path) == ("POST", "/rest/api/3/issue"):
                if body["fields"]["summary"] == "Count":
                    stub.unread.add(answer["key"])
            return code, answer

        with mock.patch.object(stub, "handle", unreadable):
            self.assertEqual(self.move()["status"], "failed")
        stub.unread.clear()
        copy = self.record()["ids"][step]
        values = [{"label": "roster-id", "text": "42"}]
        found = self.m.invoke(
            "operation.record-what-a-step-found",
            {"root": root, "tracker": "jira", "id": copy, "values": values},
        )
        self.assertIn(
            (found["status"], found.get("reason")),
            [("failed", "blocked"), ("completed", None)],
            found,
        )
        again = self.move()
        self.assertEqual((again["status"], self.record()["unread"]), ("completed", []), again)
        if found["status"] == "completed":
            self.assertEqual(self.show(copy).get("values"), values)

    def test_values_too_long_for_one_property_are_kept_one_property_each(self):
        """Report holds five values, together longer than Jira keeps in one
        issue property: the move's make keeps each in a property of its own,
        and the move finishes, the copy holding all five."""
        report = self.local("Report")
        values = [{"label": "part%d" % n, "text": chr(ord("a") + n) * 8000} for n in range(5)]
        for value in values:
            done = self.m.invoke_tracker(
                "operation.record-values",
                {"root": self.home.path, "tracker": "local", "id": report, "values": [value]},
            )
            self.assertEqual(done["status"], "completed", done)
        with self.kept_to_a_property():
            moved = self.move()
        self.assertEqual(moved["status"], "completed", moved)
        self.assertEqual(self.show(self.record()["ids"][report])["values"], values)

    def kept_to_a_property(self):
        """The stub, refusing an issue property longer than Jira keeps."""
        stub = self.site.stub
        real = stub.handle

        def limited(method, path, query, body):
            if method == "PUT" and "/properties/" in path and len(json.dumps(body)) > 32768:
                return 400, {"errorMessages": ["The maximum length is 32768 characters."]}
            return real(method, path, query, body)

        return mock.patch.object(stub, "handle", limited)

    def test_a_close_the_target_refuses_is_named_where_what_holds_it_is_not_held(self):
        """Parent, closed, over Child, closed, which needs Need, open: Jira
        will not close Parent while Child's issue is open, nor Child's while
        Need's is. The refusal names Child's close, held by Need's issue,
        which nothing holds -- not Parent's, held by Child's, which the move
        does -- and Need's issue closed, the next run finishes."""
        root = self.home.path
        parent = self.local("Parent")
        child, need = self.local("Child", parent=parent), self.local("Need")
        for ident in (child, parent):
            self.assertEqual(self.forward(root, "local", "close", ident)["status"], "completed")
        edge = {"root": root, "tracker": "local", "id": child, "needs": need}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", edge)["status"], "completed")
        first = self.move()
        ids = self.record()["ids"]
        self.assertIn("jira refused the close of %s" % child, first["summary"])
        self.assertTrue(first["summary"].endswith("blocked by %s." % ids[need]), first)
        shut = self.forward(root, "jira", "close", ids[need])
        self.assertEqual(shut["closedRefs"], [ids[need]], shut)
        self.assertEqual(self.move()["status"], "completed")

    def test_a_deleted_copy_of_a_run_root_gone_from_local_too_leads_on_once_both_are_said(self):
        """A run's root is made in Jira, and the make of a step refused. The
        root's issue is then deleted in Jira, and the root in local: told the
        first, as the run's answer says, the run answers that local holds no
        root either, and told both, as that answer says, the move finishes."""
        root = self.home.path
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "local", "formulaRef": "m", "title": "Run"}
            | {"steps": [{"id": "a", "title": "A"}, {"id": "b", "title": "B", "needs": ["a"]}]},
        )
        top = poured["rootId"]
        with self.refusing(2):
            self.assertEqual(self.move()["status"], "failed")
        made = self.record()["ids"][top]
        del self.site.stub.issues[made]
        again = self.move()
        self.assertIn(
            "run dotdiw tracker migrate local jira --deleted %s," % made, again["summary"]
        )
        self.deleted_in_local(root, top)
        told = self.move(deleted=[made])
        self.assertEqual(told["status"], "failed", told)
        both = "dotdiw tracker migrate local jira --deleted %s --source-gone %s" % (made, top)
        self.assertIn(both, told["summary"])
        last = self.move(deleted=[made], sourceGoneIds=[top])
        self.assertEqual(last["status"], "completed", last)

    def test_a_child_whose_parent_is_made_again_stands_where_jira_shows_it(self):
        """C was moved under New, and Jira's search still has it under Old:
        the move puts C's copy under New's, as Jira shows it by its key. Old's
        copy deleted in local and the run told so, it makes Old again and
        leaves C's copy under New's, not under Old's made again."""
        root = self.checkout()
        old, new = self.made(root, "Old"), self.made(root, "New")
        c = self.made(root, "C", parent=old)
        moving = {"root": root, "tracker": "jira", "id": c, "parent": new}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", moving)["status"], "completed"
        )
        self.written_elsewhere()
        with mock.patch.dict(self.site.stub.lagging, {c: {"parent": {"key": old}}}):
            self.assertEqual(self.moved(root)["status"], "completed")
            ids = self.j2l(root)[1]["ids"]
            self.assertEqual(self.show(ids[c], root, "local")["parent"], ids[new])
            self.deleted_in_local(root, ids[old])
            again = self.moved(root, deletedIds=[ids[old]])
        self.assertEqual(again["status"], "completed", again)
        anew = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(anew[c], root, "local")["parent"], anew[new])

    def test_an_archived_waiter_of_an_item_made_again_waits_on_the_new_copy(self):
        """W needs A; moved from Jira and finished. A's copy is deleted in
        local, and W archived in Jira, which shows it by its key and lists it
        no more: told A's copy was deleted, the run makes A again, and W's
        copy waits on the new one, as Jira shows W waiting on A."""
        root = self.checkout()
        a, w = self.made(root, "A"), self.made(root, "W")
        need = {"root": root, "tracker": "jira", "id": w, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.moved(root)["status"], "completed")
        old = self.j2l(root)[1]["ids"]
        self.deleted_in_local(root, old[a])
        self.written_elsewhere()
        with self.lagging(w):
            again = self.moved(root, deletedIds=[old[a]])
        self.assertEqual(again["status"], "completed", again)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[w], root, "local")["needs"], [ids[a]])

    def test_a_need_taken_off_in_jira_while_the_move_stands_stopped_is_taken_off_the_copy(self):
        """Two needs One; the process dies just after local writes the need,
        before the record keeps it. In Jira the need is then taken off and
        Two closed: the next run takes the need off Two's copy, closes it,
        and finishes."""

        class Killed(BaseException):
            """The process dying."""

        root = self.checkout()
        one, two = self.made(root, "One"), self.made(root, "Two")
        need = {"root": root, "tracker": "jira", "id": two, "needs": one}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        real = local["operations"]["operation.add-need"]

        def then_die(request):
            real(request)
            raise Killed()

        with mock.patch.dict(local["operations"], {"operation.add-need": then_die}):
            self.assertRaises(Killed, self.moved, root)
        self.site.stub.links = []
        self.assertEqual(self.closed(root, two)["closedIds"], [two])
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        shown = self.show(self.j2l(root)[1]["ids"][two], root, "local")
        self.assertEqual((shown["status"], shown["needs"]), ("closed", []))

    def test_a_move_whose_record_another_move_keeps_under_its_name_writes_nothing(self):
        """A move from a to b-to-c and one from a-to-b to c would keep their
        records under one name. The first made, the second writes nothing,
        and says so, rather than read the first's record as its own."""
        if HERE not in sys.path:
            sys.path.insert(0, HERE)  # run as a script with -I, as the breaks run it
        import test_tracker  # its tracker in memory; it imports this module

        trackers = {
            n: test_tracker.Memory(n.replace("-", "")) for n in ("a", "b-to-c", "a-to-b", "c")
        }
        for name, tracker in trackers.items():
            self.m.register_tracker(name, tracker.table())
        trackers["a"].add("Old")
        trackers["a-to-b"].add("One")
        move = {"root": self.home.path, "fromTracker": "a", "toTracker": "b-to-c"}
        self.assertEqual(self.m.invoke("operation.move-a-workspace", move)["status"], "completed")
        path = os.path.join(self.m.workspace(self.home.path), "migration-a-to-b-to-c.json")
        with open(path, encoding="utf-8") as fh:
            kept = fh.read()
        second = self.m.invoke(
            "operation.move-a-workspace", dict(move, fromTracker="a-to-b", toTracker="c")
        )
        self.assertEqual((second["status"], trackers["c"].items), ("failed", {}), second)
        said = self.m.MOVE_OTHERS_RECORD % (path, "a", "b-to-c", "a-to-b", "c")
        self.assertEqual(second["summary"], said)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), kept)

    def test_a_run_of_the_move_writes_jira_json_beside_it_and_only_where_it_changes(self):
        """A run of the move opens Jira again. The file that keeps the
        checkout's project is not written in its place, where a close of a
        step the move holds, at that moment, would find it empty and the
        project named nowhere: unchanged, it is not written at all, and
        written anew, it is written beside it and put in its place."""
        root = self.home.path
        self.stopped()
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        module = jira["operations"]["operation.close-item"].__globals__
        path = module["store"](root)
        before, written = os.stat(path), []

        def watched(file, mode="r", *args, **kwargs):
            if mode != "r":
                written.append(str(file))
            return open(file, mode, *args, **kwargs)

        with mock.patch.dict(module, {"open": watched}):
            self.assertEqual(self.move()["status"], "completed")
            self.assertNotIn(path, written)
            self.assertEqual(os.stat(path).st_mtime_ns, before.st_mtime_ns)
            os.remove(path)
            asked = {"root": root, "tracker": "jira", "prefix": "CHK"}
            opened = self.m.invoke_tracker("operation.open-tracker", asked)
        self.assertEqual(opened["status"], "completed", opened)
        self.assertNotIn(path, written)
        self.assertTrue([f for f in written if f.startswith(path + ".")], written)

    def test_a_write_of_the_journal_that_fails_keeps_what_it_held(self):
        """A write of the journal of what this home wrote of late fails, as
        a full disk fails it: what it held before is kept, so that a child
        made a moment ago still holds its parent's close while no search
        finds it."""
        root = self.checkout()
        parent = self.made(root, "Parent")
        child = self.made(root, "Child", parent=parent)
        _, jira = self.m.resolve_tracker({"root": root, "tracker": "jira"})
        module = jira["operations"]["operation.close-item"].__globals__
        path = module["lately"](root)

        class Full:
            """A file of the journal, opened to write, on a full disk."""

            def __init__(self, fh):
                self.fh = fh

            def __getattr__(self, name):
                return getattr(self.fh, name)

            def __iter__(self):
                return iter(self.fh)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.fh.close()

            def write(self, text):
                raise OSError(errno.ENOSPC, "No space left on device")

        def opened(file, mode="r", *args, **kwargs):
            fh = open(file, mode, *args, **kwargs)
            journal = str(file).startswith(path) and not str(file).endswith(".lock")
            return Full(fh) if journal and mode != "r" else fh

        with mock.patch.dict(module, {"open": opened}):
            self.made(root, "Other")
        self.assertEqual(module["written_lately"](root), {child: {parent}, parent: set()})
        with self.lagging(child):
            held = self.closed(root, parent)
        self.assertEqual((held["status"], held.get("blockedBy")), ("blocked", [child]), held)

    def test_the_command_to_run_once_it_lists_it_names_what_the_run_was_told(self):
        """Publish needs Build and Dock, which Jira's search does not list
        yet. Build is archived, and the run told so: it refuses for Dock,
        and the command it gives to run once Jira lists Dock names Build as
        gone too, so that, followed as given, the move finishes."""
        root = self.checkout()
        build, dock = self.made(root, "Build"), self.made(root, "Dock")
        publish = self.made(root, "Publish")
        for needed in (build, dock):
            need = {"root": root, "tracker": "jira", "id": publish, "needs": needed}
            done = self.m.invoke_tracker("operation.add-need", need)
            self.assertEqual(done["status"], "completed", done)
        self.written_elsewhere()
        with self.lagging(build, dock):
            told = self.moved(root, sourceGoneIds=[build])
        self.assertEqual(told["status"], "failed", told)
        first = re.search(r"[Rr]un (dotdiw tracker migrate .*?)(?: again|,)", told["summary"])
        assert first is not None, told
        command = shlex.split(first.group(1))
        self.assertEqual(command[5:], ["--source-gone", build], told["summary"])
        with self.lagging(build):
            code, out = self.cli(root, *command[1:])
        self.assertEqual(code, 0, out)

    def test_a_need_turned_into_a_parent_while_the_move_stood_stopped_is_carried_into_local(self):
        """A and N need X; the move from Jira writes A's need and is refused
        N's, nothing settled. In Jira, A's need is then taken off and A put
        under X: the next run takes the need off A's copy before it puts it
        under X's, which would otherwise wait on it, and finishes, N's copy
        still waiting on X's."""
        root = self.checkout()
        x, a, n = self.made(root, "X"), self.made(root, "A"), self.made(root, "N")
        for ident in (a, n):
            need = {"root": root, "tracker": "jira", "id": ident, "needs": x}
            done = self.m.invoke_tracker("operation.add-need", need)
            self.assertEqual(done["status"], "completed", done)
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        real = local["operations"]["operation.add-need"]
        down = {"status": "failed", "reason": "adapter-failed", "exitCode": 1, "summary": "down"}

        def all_but_ns(request):
            # local keeps the source's ids, so N's copy is named as N is.
            return dict(down) if request["id"] == n else real(request)

        with mock.patch.dict(local["operations"], {"operation.add-need": all_but_ns}):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(record["settled"], [])
        self.assertEqual(self.show(ids[a], root, "local")["needs"], [ids[x]])
        self.site.stub.links.remove((x, a))
        self.site.stub.issues[a]["parent"] = {"key": x}
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        shown = self.show(ids[a], root, "local")
        self.assertEqual((shown["parent"], shown["needs"]), (ids[x], []))
        self.assertEqual(self.show(ids[n], root, "local")["needs"], [ids[x]])

    def test_a_need_taken_off_one_copy_and_a_parent_set_on_another_while_stopped_reach_local(
        self,
    ):
        """A needs C, which needs P; the move from Jira stops at its first
        status, every need written and nothing settled. In Jira, C's need on
        P is taken off, then A put under P, as Jira allows in that order: the
        next run takes the need off C's copy before it puts A's under P's,
        and finishes, the copies standing as Jira shows them."""
        root = self.checkout()
        p, a, c, z = (self.made(root, title) for title in ("P", "A", "C", "Z"))
        self.site.stub.issues[z]["_status"] = "In Progress"  # a status to stop at
        asked = {"root": root, "tracker": "jira"}
        for ident, needs in ((a, c), (c, p)):
            done = self.m.invoke_tracker("operation.add-need", dict(asked, id=ident, needs=needs))
            self.assertEqual(done["status"], "completed", done)
        with self.down_in_local(root, "update-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(record["settled"], [])
        self.assertEqual(self.show(ids[c], root, "local")["needs"], [ids[p]])
        for change in ({"id": c, "dropNeeds": [p]}, {"id": a, "parent": p}):
            done = self.m.invoke_tracker("operation.update-item", dict(asked, **change))
            self.assertEqual(done["status"], "completed", done)
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        copy_a, copy_c = (self.show(ids[k], root, "local") for k in (a, c))
        self.assertEqual(
            (copy_a["parent"], copy_a["needs"], copy_c["needs"]), (ids[p], [ids[c]], [])
        )

    def test_values_too_long_for_one_property_recorded_while_stopped_reach_the_copy(self):
        """Report needs Notes, and the move to Jira stops at the link,
        Report's copy made and not finished. Five values, together longer
        than Jira keeps in one issue property, are recorded on Report in
        local meanwhile: the next run writes them as a make does, as many to
        a property as it holds, and finishes, the copy holding all five."""
        root = self.home.path
        report, notes = self.local("Report"), self.local("Notes")
        need = {"root": root, "tracker": "local", "id": report, "needs": notes}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        with self.down_for(lambda method, path: path.endswith("/issueLink")):
            self.assertEqual(self.move()["status"], "failed")
        self.assertNotIn(report, self.record()["settled"])
        values = [{"label": "part%d" % n, "text": chr(ord("a") + n) * 8000} for n in range(5)]
        for value in values:
            done = self.m.invoke_tracker(
                "operation.record-values",
                {"root": root, "tracker": "local", "id": report, "values": [value]},
            )
            self.assertEqual(done["status"], "completed", done)
        with self.kept_to_a_property():
            moved = self.move()
        self.assertEqual(moved["status"], "completed", moved)
        self.assertEqual(self.show(self.record()["ids"][report])["values"], values)

    def test_a_parent_whose_copy_is_gone_from_jira_is_named_when_a_held_copy_is_put_under_it(
        self,
    ):
        """P1 and P2 are moved and finished, and C, closed under P1, is held,
        Jira refusing its close. P2's issue is deleted in Jira, and C put
        under P2 in local: the run that would put C's copy under P2's says
        which copy is gone and how to go on, and told it was deleted, makes
        P2 again and finishes C under it, closed."""
        root = self.home.path
        p1, p2 = self.local("P1"), self.local("P2")
        c = self.local("C", parent=p1)
        self.assertEqual(self.forward(root, "local", "close", c)["status"], "completed")
        with self.closing_refused():
            self.assertEqual(self.move()["status"], "failed")
        self.assertEqual(sorted(self.record()["settled"]), sorted([p1, p2]))
        copy = self.record()["ids"][p2]
        del self.site.stub.issues[copy]
        moving = {"root": root, "tracker": "local", "id": c, "parent": p2}
        self.assertEqual(
            self.m.invoke_tracker("operation.update-item", moving)["status"], "completed"
        )
        again = self.move()
        said = "dotdiw tracker migrate local jira"
        self.assertEqual(
            (again["status"], again["summary"]),
            (
                "failed",
                self.m.MOVE_NOT_FOUND
                % ("jira", copy, p2, copy, said, "%s --deleted %s" % (said, copy)),
            ),
        )
        self.assertEqual(self.move(deleted=[copy])["status"], "completed")
        ids = self.record()["ids"]
        self.assertNotEqual(ids[p2], copy)
        shown = self.show(ids[c])
        self.assertEqual((shown["parent"], shown["status"]), (ids[p2], "closed"))

    def test_a_parent_whose_copy_is_gone_from_local_is_named_when_a_child_is_made_under_it(self):
        """P is moved from Jira and finished, and its copy deleted in local
        since. C, made under P in Jira after, cannot be made under an item
        local holds no more: the run says which copy is gone and how to go
        on, and told it was deleted, makes P again and C under it."""
        root = self.checkout()
        p = self.made(root, "P")
        self.assertEqual(self.moved(root)["status"], "completed")
        copy = self.j2l(root)[1]["ids"][p]
        self.deleted_in_local(root, copy)
        c = self.made(root, "C", parent=p)
        again = self.moved(root)
        said = "dotdiw tracker migrate jira local"
        self.assertEqual(
            (again["status"], again["summary"]),
            (
                "failed",
                self.m.MOVE_NOT_FOUND
                % ("local", copy, p, copy, said, "%s --deleted %s" % (said, copy)),
            ),
        )
        told = self.moved(root, deletedIds=[copy])
        self.assertEqual(told["status"], "completed", told)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[c], root, "local")["parent"], ids[p])

    def test_a_child_and_its_parent_that_change_places_while_stopped_change_places_in_local(self):
        """A stands under B, and the move from Jira stops at its first
        status, nothing settled. In Jira they change places, B under A and A
        under none: the next run takes A's copy from under B's before it puts
        B's under A's, and finishes, the copies standing as Jira shows them
        and nothing said kept of either."""
        root = self.checkout()
        b = self.made(root, "B")
        a = self.made(root, "A", parent=b)
        z = self.made(root, "Z")
        self.site.stub.issues[z]["_status"] = "In Progress"  # a status to stop at
        with self.down_in_local(root, "update-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(record["settled"], [])
        self.assertEqual(self.show(ids[a], root, "local")["parent"], ids[b])
        self.site.stub.issues[a]["parent"] = None
        self.site.stub.issues[b]["parent"] = {"key": a}
        self.written_elsewhere()  # so that the listing is Jira's, as it stands
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        parents = [self.show(ids[k], root, "local")["parent"] for k in (a, b)]
        self.assertEqual(parents, [None, ids[a]])
        self.assertNotIn("the parent of", again["summary"])

    def test_a_parent_taken_away_and_needed_instead_while_stopped_reaches_local_as_a_need(self):
        """H stands under P, and Z needs H; the move from Jira makes all three
        and is refused the need, nothing settled. In Jira, H is taken from
        under P and made to wait on P instead: the next run takes H's copy
        from under P's before it writes the need, which would otherwise wait
        on itself, and finishes, H's copy under none and waiting on P's."""
        root = self.checkout()
        p = self.made(root, "P")
        h = self.made(root, "H", parent=p)
        z = self.made(root, "Z")
        asked = {"root": root, "tracker": "jira"}
        done = self.m.invoke_tracker("operation.add-need", dict(asked, id=z, needs=h))
        self.assertEqual(done["status"], "completed", done)
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        _, record = self.j2l(root)
        ids = record["ids"]
        self.assertEqual(self.show(ids[h], root, "local")["parent"], ids[p])
        self.site.stub.issues[h]["parent"] = None
        done = self.m.invoke_tracker("operation.add-need", dict(asked, id=h, needs=p))
        self.assertEqual(done["status"], "completed", done)
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        shown = self.show(ids[h], root, "local")
        self.assertEqual((shown["parent"], shown["needs"]), (None, [ids[p]]))
        self.assertEqual(self.show(ids[z], root, "local")["needs"], [ids[h]])

    def test_a_need_taken_off_a_held_copy_in_jira_is_written_again(self):
        """X needs Y, and Z is in progress; the move to Jira stops at Z's
        status, X's need written and nothing settled. The link of X's copy
        is then taken off in Jira's own screens, local unchanged: the next
        run writes it again, as the copy it reads lacks it, and finishes."""
        root = self.home.path
        x, y, z = self.local("X"), self.local("Y"), self.local("Z")
        need = {"root": root, "tracker": "local", "id": x, "needs": y}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        busy = self.forward(root, "local", "update", z, "--status", "in_progress")
        self.assertEqual(busy["status"], "completed", busy)
        with self.down_for(lambda method, path: method == "POST" and path.endswith("/transitions")):
            self.assertEqual(self.move()["status"], "failed")
        ids = self.record()["ids"]
        self.assertEqual((self.record()["settled"], self.show(ids[x])["needs"]), ([], [ids[y]]))
        self.site.stub.links.remove((ids[y], ids[x]))
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(ids[x])["needs"], [ids[y]])

    def test_a_need_written_in_jira_between_held_copies_is_kept_and_said(self):
        """Two of three items are moved and held, Jira refusing to make the
        third. Through dotdiw on Jira, the first copy is made to wait on the
        second -- a need the move never wrote, nor local shows: the run that
        finishes keeps it, and says so."""
        root = self.home.path
        for title in ("Alpha", "Beta", "Gamma"):
            self.local(title)
        with self.refusing(3):
            self.assertEqual(self.move()["status"], "failed")
        ids = self.record()["ids"]
        first, second = sorted(ids)
        self.assertEqual((self.record()["settled"], self.record()["linked"]), ([], []))
        dep = self.forward(root, "jira", "dep", "add", ids[first], ids[second])
        self.assertEqual(dep["status"], "completed", dep)
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(ids[first])["needs"], [ids[second]])
        self.assertIn(
            "; kept what jira holds and local does not: %s needs %s" % (ids[first], ids[second]),
            again["summary"],
        )

    def test_a_close_reason_changed_in_local_while_stopped_is_said_kept_as_the_copy_has_it(self):
        """X is closed as first, and the move to Jira closes its copy so and
        stops, Jira answering 503 when the move reads the copy back. X is
        opened again in local and closed as second: the next run leaves the
        copy closed, as the source shows it -- opening it again could leave
        it held by what then stands open -- and finishes, saying the copy
        keeps the reason it was closed with."""
        root = self.home.path
        x = self.local("X")
        asked = {"root": root, "tracker": "local", "id": x}
        shut = self.m.invoke_tracker("operation.close-item", dict(asked, closeReason="first"))
        self.assertEqual(shut["status"], "completed", shut)
        stub = self.site.stub
        real = stub.handle
        commented: list[str] = []

        def unread_once_commented(method, path, query, body):
            if commented and method == "GET" and re.fullmatch(r"/rest/api/3/issue/[^/]+", path):
                return 503, {"errorMessages": ["The service is unavailable."]}
            if method == "POST" and path.endswith("/comment"):
                commented.append(path)
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", unread_once_commented):
            self.assertEqual(self.move()["status"], "failed")
        self.assertNotIn(x, self.record()["settled"])
        copy = self.record()["ids"][x]
        self.assertEqual(
            (self.show(copy)["status"], self.show(copy)["reason"]), ("closed", "first")
        )
        for change, operation in (
            ({"status": "open"}, "update"),
            ({"closeReason": "second"}, "close"),
        ):
            done = self.m.invoke_tracker("operation.%s-item" % operation, dict(asked, **change))
            self.assertEqual(done["status"], "completed", done)
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(
            (self.show(copy)["status"], self.show(copy)["reason"]), ("closed", "first")
        )
        self.assertIn(
            "; kept as jira has it, as it would not change it: the close reason of %s." % copy,
            again["summary"],
        )

    def test_a_close_reason_changed_in_jira_while_stopped_is_said_kept_as_the_copy_has_it(self):
        """X is closed as first; the process dies just after local closes
        X's copy so, before the record keeps it. X is opened again in Jira
        and closed as second: the next run leaves the copy closed as first,
        and finishes, saying so."""

        class Killed(BaseException):
            """The process dying."""

        root = self.checkout()
        x = self.made(root, "X")
        asked = {"root": root, "tracker": "jira", "id": x}
        shut = self.m.invoke_tracker("operation.close-item", dict(asked, closeReason="first"))
        self.assertEqual(shut["status"], "completed", shut)
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        real = local["operations"]["operation.close-item"]

        def then_die(request):
            real(request)
            raise Killed()

        with mock.patch.dict(local["operations"], {"operation.close-item": then_die}):
            self.assertRaises(Killed, self.moved, root)
        _, record = self.j2l(root)
        copy = record["ids"][x]
        self.assertNotIn(x, record["settled"])
        shown = self.show(copy, root, "local")
        self.assertEqual((shown["status"], shown["reason"]), ("closed", "first"))
        for change, operation in (
            ({"status": "open"}, "update"),
            ({"closeReason": "second"}, "close"),
        ):
            done = self.m.invoke_tracker("operation.%s-item" % operation, dict(asked, **change))
            self.assertEqual(done["status"], "completed", done)
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        shown = self.show(copy, root, "local")
        self.assertEqual((shown["status"], shown["reason"]), ("closed", "first"))
        self.assertIn(
            "; kept as local has it, as it would not change it: the close reason of %s." % copy,
            again["summary"],
        )

    def test_what_a_run_said_was_kept_as_made_is_said_no_more_once_the_copy_matches(self):
        """X and Y have descriptions, and the move from Jira stops at its
        first status. Both descriptions change in Jira, and a run stopping
        again keeps the copies' as made; X's is then changed back. The run
        that finishes says Y's description was kept as made, and nothing of
        X's, whose copy reads as Jira shows X."""
        root = self.checkout()
        adapter = load_adapter()
        x = self.made(root, "X", description="first words")
        y = self.made(root, "Y", description="its words")
        z = self.made(root, "Z")
        stub = self.site.stub
        stub.issues[z]["_status"] = "In Progress"  # a status to stop at
        with self.down_in_local(root, "update-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        stub.issues[x]["description"] = adapter.adf("other words")
        stub.issues[y]["description"] = adapter.adf("new words")
        with self.down_in_local(root, "update-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        stub.issues[x]["description"] = adapter.adf("first words")
        last = self.moved(root)
        self.assertEqual(last["status"], "completed", last)
        self.assertEqual(self.show(ids[x], root, "local")["description"], "first words")
        self.assertNotIn("the description of %s" % ids[x], last["summary"])
        self.assertIn(
            "; kept as made, as only a make writes it: the description of %s" % ids[y],
            last["summary"],
        )

    def test_an_unread_copy_holding_what_it_was_given_is_finished_though_the_source_changed(self):
        """Jira makes X's issue and answers 503 when the move reads it back,
        so the record holds the copy unread; it holds the description the
        move gave it. X's description is changed in local meanwhile: the
        next run finishes the copy as made, rather than ask for its deletion,
        and says its description was kept as made."""
        x = self.local("X", description="first words")
        stub = self.site.stub
        real = stub.handle

        def unreadable(method, path, query, body):
            code, answer = real(method, path, query, body)
            if (method, path) == ("POST", "/rest/api/3/issue") and code < 300:
                stub.unread.add(answer["key"])
            return code, answer

        with mock.patch.object(stub, "handle", unreadable):
            self.assertEqual(self.move()["status"], "failed")
        stub.unread.clear()
        self.assertEqual(self.record()["unread"], [x])
        made = self.record()["ids"][x]
        self.assertEqual(self.show(made)["description"], "first words")
        count = len(stub.issues)
        conn = sqlite3.connect(self.m.local_store(self.home.path))
        with conn:
            conn.execute("UPDATE items SET description = 'second words' WHERE id = ?", (x,))
        conn.close()
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual((len(stub.issues), self.record()["ids"][x]), (count, made))
        self.assertEqual(self.record()["unread"], [])
        self.assertIn(
            "kept as made, as only a make writes it: the description of %s" % made, again["summary"]
        )

    def test_a_label_recorded_again_while_stopped_reaches_the_copy_in_the_sources_order(self):
        """Count's claim holds n, then m, and the move to Jira stops at a
        link, Count's copy made and not finished. n is taken off and
        recorded again in local, which then shows m, then n: the run that
        finishes leaves the copy's values in that order, as a move that never
        stopped would, and says nothing of them."""
        root = self.home.path
        asked = {"root": root, "tracker": "local"}
        claim = {"statement": "Counted {{ n }} and {{ m }}", "slots": ["n", "m"]}
        steps = [{"id": "c", "title": "Count", "claim": claim}]
        poured = self.m.invoke_tracker(
            "operation.pour-steps", dict(asked, formulaRef="m", title="Run", steps=steps)
        )
        (count,) = poured["stepIds"]
        task, other = self.local("Task"), self.local("Other")
        need = self.m.invoke_tracker("operation.add-need", dict(asked, id=task, needs=other))
        self.assertEqual(need["status"], "completed", need)

        def recorded(*values):
            for label, said in values:
                done = self.m.invoke_tracker(
                    "operation.record-values",
                    dict(asked, id=count, values=[{"label": label, "text": said}]),
                )
                self.assertEqual(done["status"], "completed", done)

        recorded(("n", "1"), ("m", "2"))
        with self.down_for(lambda method, path: path.endswith("/issueLink")):
            self.assertEqual(self.move()["status"], "failed")
        copy = self.record()["ids"][count]
        self.assertEqual([v["label"] for v in self.show(copy)["values"]], ["n", "m"])
        recorded(("n", ""), ("n", "3"))
        source = self.show(count, tracker="local")["values"]
        self.assertEqual(source, [{"label": "m", "text": "2"}, {"label": "n", "text": "3"}])
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(copy)["values"], source)
        self.assertNotIn("values", again["summary"])

    def test_an_issue_with_values_and_no_step_lists_as_it_shows(self):
        """Report, no step of any run, is given a value in Jira: listed, as
        a search finds it, it holds its values and the ETag its show gives,
        so that a write held to the listing's ETag goes through."""
        root = self.checkout()
        key = self.made(root, "Report")
        values = [{"label": "count", "text": "42"}]
        done = self.m.invoke_tracker(
            "operation.record-values",
            {"root": root, "tracker": "jira", "id": key, "values": values},
        )
        self.assertEqual(done["status"], "completed", done)
        self.written_elsewhere()  # so that the listing is the search's
        listed = self.forward(root, "jira", "list", "--all")
        self.assertEqual(listed["status"], "completed", listed)
        (row,) = [i for i in listed["items"] if i["id"] == key]
        shown = self.show(key, root)
        self.assertEqual((row.get("values"), row["etag"]), (values, shown["etag"]))
        wrote = self.forward(
            root, "jira", "update", key, "--title", "Report v2", etags=[row["etag"]]
        )
        self.assertEqual(wrote["status"], "completed", wrote)

    def test_jira_refuses_a_need_that_would_wait_on_itself_through_another_projects_child(self):
        """A run's root, an Epic, stands over Other, an issue of another
        project put under it in Jira's own screens, as a site may let an Epic
        hold one; Other needs Y. Y needing the root would wait on itself, as
        a close of the root waits on Other, and Jira's add-need refuses it."""
        root = self.checkout()
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "jira", "formulaRef": "m", "title": "Run"}
            | {"steps": [{"id": "a", "title": "A"}]},
        )
        self.assertEqual(poured["status"], "completed", poured)
        top, y = poured["rootId"], self.made(root, "Y")
        self.assertEqual(self.site.stub.issues[top]["issuetype"]["name"], "Epic")
        other = self.made(self.checkout(project="OTH"), "Other")
        stub = self.site.stub
        stub.issues[other]["parent"] = {"key": top}
        stub.links.append((y, other))
        out = self.m.invoke_tracker(
            "operation.add-need", {"root": root, "tracker": "jira", "id": y, "needs": top}
        )
        self.assertEqual((out["status"], out.get("reason")), ("failed", "cycle"), out)
        self.assertEqual(stub.links, [(y, other)])

    def test_a_close_of_a_closed_step_leaves_a_root_opened_again_since_open(self):
        """A run's one step closed as built closes its root; the root is
        then opened again. The same close run again names the step closed
        already and closes nothing in its wake: the root stays open, as
        under local, since it was opened after the step's close, not left
        open by a close cut short."""
        root = self.checkout()
        poured = self.m.invoke_tracker(
            "operation.pour-steps",
            {"root": root, "tracker": "jira", "formulaRef": "m", "title": "Run"}
            | {"steps": [{"id": "a", "title": "A"}]},
        )
        top, (step,) = poured["rootId"], poured["stepIds"]
        first = self.forward(root, "jira", "close", step, "--reason", "built")
        self.assertEqual(sorted(first["closedRefs"]), sorted([step, top]), first)
        back = self.forward(root, "jira", "update", top, "--status", "open")
        self.assertEqual(back["status"], "completed", back)
        again = self.forward(root, "jira", "close", step, "--reason", "built")
        self.assertEqual((again["status"], again["closedRefs"]), ("completed", []), again)
        self.assertEqual(self.show(top, root)["status"], "open")

    def test_a_close_the_target_refuses_is_one_whose_blockers_can_be_closed(self):
        """X needs R, which needs Z; X and Z are closed in local, R open, and
        C, open, stands under Z. Jira closes neither X's issue, over R's,
        nor Z's, over C's. The refusal names Z's close, held by C's issue,
        which can be closed -- not X's, held by R's, which waits on Z's --
        and once C's issue is closed, and then R's, the runs finish."""
        ticks = iter(range(10000))
        self.enterContext(
            mock.patch.object(
                self.m, "local_now", lambda: "2026-11-01T00:%02d:%02dZ" % divmod(next(ticks), 60)
            )
        )  # made in this order, as the listing orders them
        root = self.home.path
        asked = {"root": root, "tracker": "local"}
        x, r, z = self.local("X"), self.local("R"), self.local("Z")
        for operation, fields in (
            ("close-item", {"id": z}),
            ("add-need", {"id": r, "needs": z}),
            ("close-item", {"id": x}),
            ("add-need", {"id": x, "needs": r}),
        ):
            done = self.m.invoke_tracker("operation." + operation, dict(asked, **fields))
            self.assertEqual(done["status"], "completed", done)
        c = self.local("C", parent=z)
        first = self.move()
        ids = self.record()["ids"]
        self.assertIn("jira refused the close of %s" % z, first["summary"])
        self.assertTrue(first["summary"].endswith("blocked by %s." % ids[c]), first["summary"])
        self.assertEqual(self.forward(root, "jira", "close", ids[c])["closedRefs"], [ids[c]])
        again = self.move()
        self.assertIn("jira refused the close of %s" % x, again["summary"])
        self.assertTrue(again["summary"].endswith("blocked by %s." % ids[r]), again)
        self.assertEqual(self.forward(root, "jira", "close", ids[r])["closedRefs"], [ids[r]])
        self.assertEqual(self.move()["status"], "completed")

    def test_an_archived_waiter_held_to_wait_on_an_item_made_again_is_relinked_after_a_stop(self):
        """W needs A; moved from Jira and finished. A's copy is deleted in
        local, and W archived in Jira, which shows it by its key and lists it
        no more: told A's copy was deleted, the run holds W's copy to wait on
        A's made again, and stops, local refusing the make. The same command
        run again makes A, and W's copy waits on the new one."""
        root = self.checkout()
        a, w = self.made(root, "A"), self.made(root, "W")
        need = {"root": root, "tracker": "jira", "id": w, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", need)["status"], "completed")
        self.assertEqual(self.moved(root)["status"], "completed")
        old = self.j2l(root)[1]["ids"]
        self.deleted_in_local(root, old[a])
        self.written_elsewhere()
        with self.lagging(w):
            with self.down_in_local(root, "create-item"):
                stopped = self.moved(root, deletedIds=[old[a]])
            self.assertEqual(stopped["status"], "failed", stopped)
            self.assertIn(w, self.j2l(root)[1]["relink"])
            again = self.moved(root, deletedIds=[old[a]])
        self.assertEqual(again["status"], "completed", again)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[w], root, "local")["needs"], [ids[a]])

    def test_an_archived_child_of_an_item_made_again_stands_under_the_new_copy(self):
        """C stands under P; moved from Jira and finished. P's copy is
        deleted in local, and C archived in Jira, which shows it by its key
        and lists it no more: told P's copy was deleted, the run makes P
        again, and C's copy stands under it, as Jira shows C under P."""
        root = self.checkout()
        p = self.made(root, "P")
        c = self.made(root, "C", parent=p)
        self.assertEqual(self.moved(root)["status"], "completed")
        old = self.j2l(root)[1]["ids"]
        self.deleted_in_local(root, old[p])
        self.written_elsewhere()
        with self.lagging(c):
            again = self.moved(root, deletedIds=[old[p]])
        self.assertEqual(again["status"], "completed", again)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[c], root, "local")["parent"], ids[p])

    def test_a_record_that_names_no_pair_holds_what_its_stopped_run_made(self):
        """A record of the move that names neither tracker, as an earlier
        dotdiw wrote one, is this move's: a run that makes Build and Publish
        into it and stops before it links them names its pair in it, and a
        close of Publish is refused, held by the move, until a run finishes
        it."""
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"ids": {}, "linked": [], "settled": []}, fh)
        build, publish = self.stopped()
        closed = self.forward(self.home.path, "jira", "close", publish)
        self.assertEqual(
            (closed["status"], closed["closedRefs"], closed["summary"]),
            ("failed", [], self.unfinished(publish)),
        )
        self.assertEqual(self.show(publish)["status"], "open")
        self.assertEqual((self.record()["from"], self.record()["to"]), ("local", "jira"))

    def test_a_run_from_where_the_checkout_was_moved_keeps_that_place_though_it_stops_early(self):
        """The move stops, and its checkout is then moved elsewhere. A run
        from the new place stops before it writes anything, Jira answering
        that it holds no copy of Build: the record names the new place, and
        a close of Publish says to run the move there."""
        build, publish = self.stopped()
        new = self.home.path + "-moved"
        os.rename(self.home.path, new)
        self.home.path = new  # so that the cleanup removes it
        del self.site.stub.issues[build]
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertIn("holds no %s" % build, again["summary"])
        self.assertEqual(self.record()["checkout"], new)
        closed = self.forward(new, "jira", "close", publish)
        self.assertEqual(
            (closed["closedRefs"], closed["summary"]), ([], self.unfinished(publish, checkout=new))
        )

    def test_a_record_that_holds_no_object_is_refused_and_left_as_it_is(self):
        """The move's record file holds JSON that is no record of a move: the
        move writes nothing, says so, and leaves the file as it was."""
        self.local("Alpha")
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        for text in ('["not", "a", "record"]', '"a record"', "7"):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            moved = self.move()
            self.assertEqual(moved["status"], "failed", moved)
            self.assertEqual(moved["summary"], self.m.MOVE_NO_RECORD % path)
            self.assertEqual(self.site.stub.issues, {})
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), text + "\n")

    def test_an_id_the_run_is_told_is_one_a_command_it_gives_can_take(self):
        """Two of three items are moved, and the issue of the first deleted
        in Jira. Told an empty id, the run writes nothing and says so. Told
        one that starts with a dash, as --deleted=-x gives it, each command
        the run gives names it as the command line takes it, and the one
        that says the issue was deleted, run as given, finishes the move."""
        root = self.home.path
        for title in ("Alpha", "Beta", "Gamma"):
            self.local(title)
        with self.refusing(3):
            self.assertEqual(self.move()["status"], "failed")
        kept = self.record()
        _, made = sorted(kept["ids"].items())[0]
        del self.site.stub.issues[made]
        empty = self.move(deleted=[""])
        self.assertEqual(empty["status"], "failed", empty)
        self.assertTrue(empty["summary"].startswith("Nothing was moved:"), empty)
        self.assertEqual(empty["summary"], self.m.MOVE_TOLD_EMPTY)
        self.assertEqual(self.record(), kept)
        code, out = self.cli(root, "tracker", "migrate", "local", "jira", "--deleted=-x")
        self.assertEqual(code, 1, out)
        given = re.findall(r"run (dotdiw tracker migrate [^,]*?), and the move", out)
        self.assertEqual(len(given), 2, out)
        for command in given:
            self.assertIn(" --deleted=-x", command)
        code, out = self.cli(root, *shlex.split(given[-1])[1:])
        self.assertEqual(code, 0, out)
        titles = sorted(f["summary"] for f in self.site.stub.issues.values())
        self.assertEqual(titles, ["Alpha", "Beta", "Gamma"])

    def in_jiras_screens(self, project, title, kind="Task", parent=None):
        """An issue made in Jira's own screens, as no dotdiw writes it: its key."""
        fields: dict[str, Any] = {
            "project": {"key": project},
            "summary": title,
            "issuetype": {"name": kind},
        }
        if parent:
            fields["parent"] = {"key": parent}
        status, made = self.site.stub.handle("POST", "/rest/api/3/issue", {}, {"fields": fields})
        self.assertEqual(status, 201, made)
        return made["key"]

    def test_a_copy_closed_without_its_reason_is_finished_where_it_stands(self):
        """A is closed in local as shipped. The move closes A's copy, and Jira
        answers 503 to the comment that keeps the reason: the copy stands
        closed without it, and A is not settled. C is made under A in local
        meanwhile, as local allows. The next run opens nothing again: the
        copy is finished where it stands, carrying shipped, C's copy stands
        open under it, and nothing is said kept."""
        root = self.home.path
        a = self.local("A")
        asked = {"root": root, "tracker": "local", "id": a, "closeReason": "shipped"}
        self.assertEqual(
            self.m.invoke_tracker("operation.close-item", asked)["status"], "completed"
        )
        with self.down_for(lambda method, path: method == "POST" and path.endswith("/comment")):
            first = self.move()
        self.assertEqual(first["status"], "failed", first)
        copy = self.record()["ids"][a]
        self.assertEqual((self.show(copy)["status"], self.show(copy)["reason"]), ("closed", None))
        c = self.local("C", parent=a)
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertNotIn("kept", again["summary"])
        self.assertEqual(
            (self.show(copy)["status"], self.show(copy)["reason"]), ("closed", "shipped")
        )
        child = self.show(self.record()["ids"][c])
        self.assertEqual((child["status"], child["parent"]), ("open", copy))

    def test_a_held_copy_whose_parent_is_moved_to_one_left_out_stands_under_none(self):
        """P, H under P, and Z needing H move from Jira, and the move stops,
        local refusing every need: H's copy stands under P's. H is then put
        under an Epic of another project, which the move leaves out. The next
        run takes H's copy from under P's, as a first run would have made it,
        says the parent it left out, and finishes."""
        root = self.checkout()
        p = self.made(root, "P")
        h = self.made(root, "H", parent=p)
        z = self.made(root, "Z")
        asked = {"root": root, "tracker": "jira", "id": z, "needs": h}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[h], root, "local")["parent"], ids[p])
        theirs = self.in_jiras_screens("OTH", "Theirs", "Epic")
        self.site.stub.issues[h]["parent"] = {"key": theirs}
        again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        self.assertIsNone(self.show(ids[h], root, "local")["parent"])
        self.assertIn(
            "; left out, as jira lists none of them: %s stands under %s" % (h, theirs),
            again["summary"],
        )
        self.assertNotIn("the parent of", again["summary"])

    def test_a_need_found_written_on_a_copy_waits_on_the_new_copy_of_what_it_needs(self):
        """N, W and Z in Jira, W needing N. The move to local makes N and W
        and is refused Z, so it stops before it writes W's need; the need is
        written on W's copy through dotdiw, and the next run finds it there
        and finishes -- its record, as an earlier dotdiw's, holding no edge
        of it. N's copy is then deleted in local, and the run told so makes
        N again: W's copy waits on the new copy, as Jira shows W waiting on
        N."""
        root = self.checkout()
        n, w, _ = (self.made(root, t) for t in ("N", "W", "Z"))
        asked = {"root": root, "tracker": "jira", "id": w, "needs": n}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        _, local = self.m.resolve_tracker({"root": root, "tracker": "local"})
        real = local["operations"]["operation.create-item"]
        made: list[str] = []

        def third_refused(request):
            made.append(request["title"])
            if len(made) == 3:
                return {"status": "failed", "exitCode": 1, "summary": "down"}
            return real(request)

        with mock.patch.dict(local["operations"], {"operation.create-item": third_refused}):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        written = self.forward(root, "local", "dep", "add", ids[w], ids[n])
        self.assertEqual(written["status"], "completed", written)
        self.assertEqual(self.moved(root)["status"], "completed")
        # As an earlier dotdiw's record holds it: no need it found written.
        path, record = self.j2l(root)
        record["linked"] = [e for e in record["linked"] if e != [w, n]]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        self.deleted_in_local(root, ids[n])
        told = self.moved(root, deletedIds=[ids[n]])
        self.assertEqual(told["status"], "completed", told)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[w], root, "local")["needs"], [ids[n]])

    def test_a_need_found_written_on_a_copy_is_taken_off_when_the_source_takes_it_off(self):
        """N and W are done in Jira, and the move to local makes both and
        stops at their closes. W then comes to need N in Jira, and its copy
        to need N's through dotdiw: the next run finds the need there, as
        Jira shows it, writes nothing of it, and stops at the closes again.
        The need is taken off W in Jira: the run after takes it off W's copy
        too, as of a need the move holds as its own, closes both and
        finishes."""
        root = self.checkout()
        n, w = (self.made(root, t) for t in ("N", "W"))
        for done in (n, w):
            shut = {"root": root, "tracker": "jira", "id": done, "closeReason": "done"}
            self.assertEqual(
                self.m.invoke_tracker("operation.close-item", shut)["status"], "completed"
            )
        with self.down_in_local(root, "close-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.j2l(root)[1]["linked"], [])
        self.site.stub.links.append((n, w))  # W needs N, written in Jira's screens
        written = self.forward(root, "local", "dep", "add", ids[w], ids[n])
        self.assertEqual(written["status"], "completed", written)
        with self.down_in_local(root, "close-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        self.assertNotIn(w, self.j2l(root)[1]["settled"])
        self.site.stub.links.remove((n, w))
        last = self.moved(root)
        self.assertEqual(last["status"], "completed", last)
        shown = self.show(ids[w], root, "local")
        self.assertEqual((shown["status"], shown["needs"]), ("closed", []))
        self.assertNotIn("kept what", last["summary"])

    def test_an_unfinished_item_is_taken_as_jira_shows_it_while_its_search_lags(self):
        """X and Y move from Jira, Y needing X, and the move stops, local
        refusing every need. X is renamed in Jira, and Jira's search still
        has its old title. The next run takes X as Jira shows it by its key,
        and X's copy carries the new title."""
        root = self.checkout()
        x, y = (self.made(root, t) for t in ("X", "Y"))
        asked = {"root": root, "tracker": "jira", "id": y, "needs": x}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        self.site.stub.issues[x]["summary"] = "X renamed"
        self.written_elsewhere()
        with mock.patch.dict(self.site.stub.lagging, {x: {"summary": "X"}}):
            again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        self.assertEqual(self.show(ids[x], root, "local")["title"], "X renamed")

    def test_ready_gives_the_etag_show_and_list_give_for_an_issue_with_values(self):
        """Report holds a value, under Reports. Ready's row is the record
        show and list give, with the same ETag, so a close held to it goes
        through; and Reports shows it among its children with its value."""
        root = self.checkout()
        reports = self.made(root, "Reports")
        key = self.made(root, "Report", parent=reports)
        done = self.m.invoke_tracker(
            "operation.record-values",
            {
                "root": root,
                "tracker": "jira",
                "id": key,
                "values": [{"label": "count", "text": "42"}],
            },
        )
        self.assertEqual(done["status"], "completed", done)
        self.written_elsewhere()  # what the search finds is all ready knows
        ready = self.forward(root, "jira", "ready")
        (row,) = [i for i in ready["items"] if i["id"] == key]
        listed = self.forward(root, "jira", "list", "--all")
        (line,) = [i for i in listed["items"] if i["id"] == key]
        self.assertEqual((row["etag"], line["etag"]), (self.show(key, root)["etag"],) * 2)
        shown = self.m.invoke_tracker(
            "operation.show-item", {"root": root, "tracker": "jira", "id": reports}
        )
        (child,) = shown["children"]
        self.assertEqual(child["values"], [{"label": "count", "text": "42"}], shown)
        closed = self.forward(root, "jira", "close", key, etags=[row["etag"]])
        self.assertEqual(closed["status"], "completed", closed)

    def test_a_cycle_refused_names_the_need_that_closes_it_among_others_kept(self):
        """As where one need kept closes a cycle, but four other copies hold
        a need written in local too: the refusal names the one that closes
        the cycle, read from what local holds, and none of the others."""
        root = self.checkout()
        others = [self.made(root, "P%d" % n) for n in range(1, 5)]
        a, b, x = (self.made(root, t) for t in ("A", "B", "X"))
        asked = {"root": root, "tracker": "jira", "id": x, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        for other in others:
            held = self.local("Held by %s" % other, root=root)
            out = self.forward(root, "local", "dep", "add", ids[other], held)
            self.assertEqual(out["status"], "completed", out)
        out = self.forward(root, "local", "dep", "add", ids[a], ids[b])
        self.assertEqual(out["status"], "completed", out)
        asked = {"root": root, "tracker": "jira", "id": b, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        self.assertIn(
            self.m.MOVE_KEPT_IN_THE_WAY
            % (
                "local",
                "jira",
                "%s needs %s" % (ids[a], ids[b]),
                "dotdiw tracker migrate jira local",
            ),
            again["summary"],
        )

    def test_a_record_naming_no_pair_holds_what_its_stopped_run_made_before_any_run(self):
        """The stopped move's record, as an earlier dotdiw wrote it, names no
        pair and no store. Before any run binds it, it holds what it made as
        its name says: Publish, made without its need on Build, is neither
        ready nor closed."""
        root = self.home.path
        build, publish = self.stopped()
        path = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        record = self.record()
        for field in ("from", "to", "store", "fromStore", "checkout"):
            record.pop(field, None)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        ready = self.forward(root, "jira", "ready")
        self.assertFalse({build, publish} & {i["id"] for i in ready["items"]}, ready)
        closed = self.forward(root, "jira", "close", publish)
        self.assertEqual((closed["status"], closed["closedRefs"]), ("failed", []), closed)

    def test_a_record_with_a_field_not_as_a_move_keeps_it_is_no_traceback_on_close_or_ready(self):
        """The stopped move's record holds settled as a number: the move says
        its record is not one it can read, and a close and ready answer in a
        line each, holding what the record made."""
        root = self.home.path
        build, publish = self.stopped()
        path = os.path.join(self.m.workspace(root), "migration-local-to-jira.json")
        record = self.record()
        record["settled"] = 7
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        moved = self.move()
        self.assertEqual(moved["summary"], self.m.MOVE_RECORD_MISSHAPEN % (path, "settled"))
        for arguments in (("close", publish), ("ready",)):
            code, out = self.cli(root, "--tracker", "jira", *arguments)
            self.assertNotIn("Traceback", out)
        closed = self.forward(root, "jira", "close", publish)
        self.assertEqual(closed["closedRefs"], [], closed)

    def test_a_stuck_close_named_is_one_whose_blocker_waits_on_no_close_the_move_holds(self):
        """A, done, needs N; M, done, needs K, open; the move from Jira stops
        at the needs, nothing settled. N's copy is made to need M's in local,
        which the move keeps and says. The next run is refused the closes of
        A and M, and names M's, held by K's copy, which waits on nothing the
        move holds -- not A's, held by N's copy, which waits on M's."""
        root = self.checkout()
        a, n, m, k = (self.made(root, t) for t in ("A", "N", "M", "K"))
        asked = {"root": root, "tracker": "jira"}
        for operation, fields in (
            ("close-item", {"id": a, "closeReason": "done"}),
            ("add-need", {"id": a, "needs": n}),
            ("close-item", {"id": m, "closeReason": "done"}),
            ("add-need", {"id": m, "needs": k}),
        ):
            out = self.m.invoke_tracker("operation." + operation, dict(asked, **fields))
            self.assertEqual(out["status"], "completed", out)
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        kept = self.forward(root, "local", "dep", "add", ids[n], ids[m])
        self.assertEqual(kept["status"], "completed", kept)
        again = self.moved(root)
        self.assertEqual(
            again["summary"],
            "local refused the close of %s: %s is blocked by %s." % (m, ids[m], ids[k]),
        )

    def test_a_cycle_closed_by_a_need_a_copy_left_as_made_keeps_is_named(self):
        """X, Y and Z move from Jira, Z needing X; the move stops at Z's
        need. Y's copy is made to need X's in local; X comes to need Y in
        Jira, and Y is archived there. Told Y is gone, the run leaves Y's
        copy as made, is refused X's need as a cycle, and names the need of
        Y's copy that closes it, with the command to run."""
        root = self.checkout()
        x, y, z = (self.made(root, t) for t in ("X", "Y", "Z"))
        asked = {"root": root, "tracker": "jira"}
        out = self.m.invoke_tracker("operation.add-need", dict(asked, id=z, needs=x))
        self.assertEqual(out["status"], "completed", out)
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        kept = self.forward(root, "local", "dep", "add", ids[y], ids[x])
        self.assertEqual(kept["status"], "completed", kept)
        out = self.m.invoke_tracker("operation.add-need", dict(asked, id=x, needs=y))
        self.assertEqual(out["status"], "completed", out)
        self.written_elsewhere()
        with self.lagging(y):
            told = self.moved(root, sourceGoneIds=[y])
        self.assertEqual(told["status"], "failed", told)
        self.assertIn("local refused the need of %s on %s" % (x, y), told["summary"])
        self.assertIn(
            self.m.MOVE_KEPT_IN_THE_WAY
            % (
                "local",
                "jira",
                "%s needs %s" % (ids[y], ids[x]),
                "dotdiw tracker migrate jira local --source-gone %s" % y,
            ),
            told["summary"],
        )

    def test_a_need_taken_off_as_a_cycle_refused_asks_is_said_kept_no_more(self):
        """C, D and E move from Jira, E needing C, D done; the move stops at
        E's need. C's copy is made to need D's in local; the next run says C's
        copy keeps it, settles C and stops at D's close. D comes to need C in
        Jira: the run is refused D's need as a cycle and names C's copy's
        need. Taken off with dotdiw dep remove, and C's copy closed when the
        run then names it, the move finishes -- and says nothing of a need
        C's copy no longer holds."""
        root = self.checkout()
        c, d, e = (self.made(root, t) for t in ("C", "D", "E"))
        asked = {"root": root, "tracker": "jira"}
        out = self.m.invoke_tracker("operation.add-need", dict(asked, id=e, needs=c))
        self.assertEqual(out["status"], "completed", out)
        out = self.m.invoke_tracker("operation.close-item", dict(asked, id=d, closeReason="done"))
        self.assertEqual(out["status"], "completed", out)
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        kept = self.forward(root, "local", "dep", "add", ids[c], ids[d])
        self.assertEqual(kept["status"], "completed", kept)
        with self.down_in_local(root, "close-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        self.assertIn(c, self.j2l(root)[1]["settled"])
        out = self.m.invoke_tracker("operation.add-need", dict(asked, id=d, needs=c))
        self.assertEqual(out["status"], "completed", out)
        refused = self.moved(root)
        self.assertIn("%s needs %s" % (ids[c], ids[d]), refused["summary"])
        off = self.forward(root, "local", "dep", "remove", ids[c], ids[d])
        self.assertEqual(off["status"], "completed", off)
        self.assertEqual(self.moved(root)["status"], "failed")  # D's close, over C's copy
        shut = self.forward(root, "local", "close", ids[c])
        self.assertEqual(shut["closedRefs"], [ids[c]], shut)
        last = self.moved(root)
        self.assertEqual(last["status"], "completed", last)
        self.assertNotIn("%s needs %s" % (ids[c], ids[d]), last["summary"])

    def test_a_stuck_close_named_is_none_whose_blocker_waits_on_one_through_its_run(self):
        """R is open, its run holding M and an open item, standing under
        nothing; M is done though it needs K, open; X is done though it needs R. The
        move's closes of X and M are refused: X's over R's copy, which waits
        on M's in its run -- a close the move has yet to make -- and M's over
        K's copy, which waits on nothing. The close named is M's."""
        ticks = iter(range(10000))
        self.enterContext(
            mock.patch.object(
                self.m, "local_now", lambda: "2026-11-01T00:%02d:%02dZ" % divmod(next(ticks), 60)
            )
        )  # made in this order, as the listing orders them
        root = self.home.path
        r, k = self.local("R"), self.local("K")
        x = self.local("X")  # made before M, so that the move tries X's close first
        m = self.local("M", run=r)
        self.local("Open", run=r)  # so that R stays open as M closes
        asked = {"root": root, "tracker": "local"}
        for operation, fields in (
            ("close-item", {"id": m, "closeReason": "done"}),
            ("add-need", {"id": m, "needs": k}),
            ("close-item", {"id": x, "closeReason": "done"}),
            ("add-need", {"id": x, "needs": r}),
        ):
            out = self.m.invoke_tracker("operation." + operation, dict(asked, **fields))
            self.assertEqual(out["status"], "completed", out)
        moved = self.move()
        self.assertEqual(moved["status"], "failed", moved)
        ids = self.record()["ids"]
        self.assertEqual(
            moved["summary"],
            "jira refused the close of %s: %s is blocked by %s." % (m, ids[m], ids[k]),
        )

    def test_what_was_said_of_a_copy_made_again_goes_with_it(self):
        """Notes moves to Jira with Build and Publish, and the move stops at
        Publish's need. Notes' description changes in local, and a run
        stopping again keeps the copy's as made. The copy is deleted in
        Jira, and the run told so makes Notes again, as local shows it now,
        and says nothing of the copy that is no more."""
        root = self.home.path
        notes = self.local("Notes", description="First words.")
        self.stopped()
        conn = sqlite3.connect(self.m.local_store(root))
        with conn:
            conn.execute("UPDATE items SET description = ? WHERE id = ?", ("Second words.", notes))
        conn.close()
        with self.down_for(
            lambda method, path: (method, path) == ("POST", "/rest/api/3/issueLink")
        ):
            self.assertEqual(self.move()["status"], "failed")
        copy = self.record()["ids"][notes]
        self.assertIn("the description of %s" % copy, json.dumps(self.record()["said"]))
        del self.site.stub.issues[copy]
        told = self.move(deleted=[copy])
        self.assertEqual(told["status"], "completed", told)
        self.assertNotIn(copy, told["summary"].replace("nothing was made again of", ""))
        again = self.record()["ids"][notes]
        self.assertNotEqual(again, copy)
        self.assertEqual(self.show(again)["description"], "Second words.")

    def test_what_a_run_that_stops_takes_back_is_said_no_more(self):
        """Alpha needs Beta, and Ship is closed; the move stops at Alpha's
        need. The copy the move looks at first is made to need Other in
        Jira, and the next run, stopping too, says the copy keeps it. The
        need is taken off in Jira; the run after finds the copy as local
        shows its item, takes that back, finishes Alpha and Beta, and stops
        at Ship's close. The run that finishes says nothing of the copy."""
        root = self.home.path
        alpha, beta = self.local("Alpha"), self.local("Beta")
        asked = {"root": root, "tracker": "local", "id": alpha, "needs": beta}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        ship = self.local("Ship")
        asked = {"root": root, "tracker": "local", "id": ship, "closeReason": "shipped"}
        self.assertEqual(
            self.m.invoke_tracker("operation.close-item", asked)["status"], "completed"
        )
        links_down = self.down_for(
            lambda method, path: (method, path) == ("POST", "/rest/api/3/issueLink")
        )
        with links_down:
            self.assertEqual(self.move()["status"], "failed")
        # The copy of the item the move looks at first, as local lists it.
        listed = self.m.invoke_tracker(
            "operation.list-items", {"root": root, "tracker": "local", "scope": "all"}
        )
        copy = self.record()["ids"][listed["items"][0]["id"]]
        other = self.in_jiras_screens("CHK", "Other")
        self.site.stub.links.append((other, copy))
        with links_down:
            self.assertEqual(self.move()["status"], "failed")
        self.assertIn("%s needs %s" % (copy, other), json.dumps(self.record()["said"]))
        self.site.stub.links.remove((other, copy))
        with self.closing_refused():
            self.assertEqual(self.move()["status"], "failed")
        self.assertNotIn("%s needs %s" % (copy, other), json.dumps(self.record()["said"]))
        last = self.move()
        self.assertEqual(last["status"], "completed", last)
        self.assertNotIn("kept what", last["summary"])

    def test_a_record_whose_field_is_not_as_a_move_keeps_it_moves_nothing(self):
        """The record names this pair, and its ids are a list: the move says
        so and writes nothing, the record left as it is."""
        self.local("Alpha")
        path = os.path.join(self.m.workspace(self.home.path), "migration-local-to-jira.json")
        held = {"from": "local", "to": "jira", "ids": [], "settled": []}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(held, fh)
        for _ in range(2):
            out = self.move()
            self.assertEqual(
                (out["status"], out["summary"]),
                ("failed", self.m.MOVE_RECORD_MISSHAPEN % (path, "ids")),
            )
        self.assertEqual(self.site.stub.issues, {})
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), held)

    def test_a_run_from_a_moved_checkout_keeps_its_place_though_it_stops_reading_the_source(self):
        """The move stops, and its checkout is moved. Publish is deleted from
        local in the new place, so a run from there stops while it reads the
        source: the record names the new place all the same, and a close of
        Build says to run the move there."""
        build, publish = self.stopped()
        new = self.home.path + "-moved"
        os.rename(self.home.path, new)
        self.home.path = new  # so that the cleanup removes it
        listed = self.m.invoke_tracker(
            "operation.list-items", {"root": new, "tracker": "local", "scope": "all"}
        )
        gone = [i["id"] for i in listed["items"] if i["title"] == "Publish"]
        conn = sqlite3.connect(self.m.local_store(new))
        with conn:
            conn.execute("DELETE FROM edges WHERE id = ? OR needs = ?", (gone[0], gone[0]))
            conn.execute("DELETE FROM items WHERE id = ?", (gone[0],))
        conn.close()
        again = self.move()
        self.assertEqual(again["status"], "failed", again)
        self.assertIn("nor shows it by its id", again["summary"])
        self.assertEqual(self.record()["checkout"], new)
        closed = self.forward(new, "jira", "close", build)
        self.assertEqual(
            (closed["closedRefs"], closed["summary"]), ([], self.unfinished(build, checkout=new))
        )

    def test_a_cycle_refused_names_what_the_move_keeps_that_closes_it(self):
        """A, B and X move from Jira, X needing A, and the move stops, local
        refusing every need. A's copy is made to need B's in local; B is
        made to need A in Jira. The next run is refused B's need as a cycle,
        and says the need of A's copy it keeps closes it, with the command
        to run; that need taken off with dotdiw dep remove, the command
        finishes the move."""
        root = self.checkout()
        a, b, x = (self.made(root, t) for t in ("A", "B", "X"))
        asked = {"root": root, "tracker": "jira", "id": x, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        with self.down_in_local(root):
            self.assertEqual(self.moved(root)["status"], "failed")
        ids = self.j2l(root)[1]["ids"]
        kept = self.forward(root, "local", "dep", "add", ids[a], ids[b])
        self.assertEqual(kept["status"], "completed", kept)
        asked = {"root": root, "tracker": "jira", "id": b, "needs": a}
        self.assertEqual(self.m.invoke_tracker("operation.add-need", asked)["status"], "completed")
        again = self.moved(root)
        self.assertEqual(again["status"], "failed", again)
        self.assertIn("local refused the need of %s on %s" % (b, a), again["summary"])
        self.assertIn(
            self.m.MOVE_KEPT_IN_THE_WAY
            % (
                "local",
                "jira",
                "%s needs %s" % (ids[a], ids[b]),
                "dotdiw tracker migrate jira local",
            ),
            again["summary"],
        )
        off = self.forward(root, "local", "dep", "remove", ids[a], ids[b])
        self.assertEqual(off["status"], "completed", off)
        self.assertEqual(self.show(ids[a], root, "local")["needs"], [])
        last = self.moved(root)
        self.assertEqual(last["status"], "completed", last)
        self.assertEqual(self.show(ids[b], root, "local")["needs"], [ids[a]])

    def test_a_value_the_move_wrote_and_the_source_took_off_is_taken_off_the_copy(self):
        """n is recorded on Build in local, and the move gives Build's copy n
        and stops at Publish's need. n is taken off Build in local: the next
        run takes it off the copy, and says nothing kept."""
        root = self.home.path
        build, publish = self.poured()
        recorded = {"root": root, "tracker": "local", "id": build}
        out = self.m.invoke_tracker(
            "operation.record-values", dict(recorded, values=[{"label": "n", "text": "3"}])
        )
        self.assertEqual(out["status"], "completed", out)
        with self.down_for(
            lambda method, path: (method, path) == ("POST", "/rest/api/3/issueLink")
        ):
            self.assertEqual(self.move()["status"], "failed")
        copy = self.record()["ids"][build]
        self.assertEqual(self.show(copy).get("values"), [{"label": "n", "text": "3"}])
        out = self.m.invoke_tracker(
            "operation.record-values", dict(recorded, values=[{"label": "n", "text": ""}])
        )
        self.assertEqual(out["status"], "completed", out)
        again = self.move()
        self.assertEqual(again["status"], "completed", again)
        self.assertFalse(self.show(copy).get("values"))
        self.assertNotIn("kept what", again["summary"])

    def test_a_copy_told_deleted_that_stands_is_left_as_made_and_kept(self):
        """S is done in Jira; the move makes S's copy in local and is refused
        its close. S is archived in Jira, and the run is told S is gone from
        Jira and its copy deleted in local -- though the copy stands. The run
        reads the copy back, leaves it as made and keeps it in the record;
        S, back in Jira's listing, is not made a second time."""
        root = self.checkout()
        s = self.made(root, "S")
        shut = self.m.invoke_tracker(
            "operation.close-item",
            {"root": root, "tracker": "jira", "id": s, "closeReason": "done"},
        )
        self.assertEqual(shut["status"], "completed", shut)
        with self.down_in_local(root, "close-item"):
            self.assertEqual(self.moved(root)["status"], "failed")
        copy = self.j2l(root)[1]["ids"][s]
        self.written_elsewhere()
        with self.lagging(s):
            told = self.moved(root, deletedIds=[copy], sourceGoneIds=[s])
        self.assertEqual(told["status"], "completed", told)
        self.assertIn("left %s as made" % copy, told["summary"])
        self.assertNotIn("forgot", told["summary"])
        self.assertEqual(self.j2l(root)[1]["ids"][s], copy)
        self.assertEqual(self.moved(root)["status"], "completed")
        self.assertEqual(self.local_titles(root), ["S"])

    def test_what_stood_under_an_item_made_again_stands_under_it_after_a_stop(self):
        """C stands under P; moved from Jira and finished. P's copy is
        deleted in local and C archived in Jira. The run told so stops,
        local refusing to make P again; the run after, told nothing, makes
        P and puts C's copy under it, as Jira shows C."""
        root = self.checkout()
        p = self.made(root, "P")
        c = self.made(root, "C", parent=p)
        self.assertEqual(self.moved(root)["status"], "completed")
        old = self.j2l(root)[1]["ids"]
        self.deleted_in_local(root, old[p])
        self.written_elsewhere()
        with self.lagging(c):
            with self.down_in_local(root, "create-item"):
                self.assertEqual(self.moved(root, deletedIds=[old[p]])["status"], "failed")
            again = self.moved(root)
        self.assertEqual(again["status"], "completed", again)
        ids = self.j2l(root)[1]["ids"]
        self.assertEqual(self.show(ids[c], root, "local")["parent"], ids[p])
        self.assertEqual(self.j2l(root)[1].get("unparented"), [])


class OneMoveOfAWorkspaceAtATime(unittest.TestCase):
    """Two moves of one workspace at once: the second cannot read the record
    of what was made until the first has saved all it made, so nothing is
    made twice."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "local", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="CHK"), "dotdiw_one_move")

    def move(self):
        return self.m.invoke(
            "operation.move-a-workspace",
            {"root": self.home.path, "fromTracker": "local", "toTracker": "jira"},
        )

    def test_a_second_move_waits_and_makes_nothing_the_first_made(self):
        made = self.m.invoke(
            "operation.start-named-work",
            {"root": self.home.path, "title": "Count the plot", "quiet": True},
        )
        self.assertEqual(made["status"], "completed", made)
        _, jira = self.m.resolve_tracker({"root": self.home.path, "tracker": "jira"})
        creating, go = paused(self, jira, "operation.create-item")
        answers: dict[str, Any] = {}
        one = threading.Thread(target=lambda: answers.__setitem__("one", self.move()))
        one.start()
        self.assertTrue(creating.wait(30))
        self.m.TRACKER_LOCK_SECONDS = 0.5
        waited = self.move()
        go.set()
        one.join(30)
        self.assertEqual(answers["one"]["status"], "completed", answers["one"])
        self.assertEqual((waited["status"], waited.get("moved")), ("failed", None), waited)
        self.assertIn("another move of this workspace", waited["summary"])
        again = self.move()
        self.assertEqual((again["status"], again["moved"]), ("completed", 0), again)
        self.assertEqual(len(self.site.stub.issues), 1, self.site.stub.issues)


class OneFirstOpenOfACheckoutsTracker(unittest.TestCase):
    """A move opens its target under the lock an adoption of the checkout
    holds, as the adoption opens its tracker, so that the two cannot each
    find no store and record a project of their own, the later over the
    earlier: the second finds the store the first made, and keeps it."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "local", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, dict(self.home.env, JIRA_PROJECT="MIG"), "dotdiw_first_open")

    def adopt(self):
        return self.m.invoke(
            "operation.adopt-a-repository",
            {"root": self.home.path, "tracker": "jira", "prefix": "OTHER"},
        )

    def test_an_adoption_while_a_move_opens_jira_keeps_the_moves_project(self):
        """The move to Jira has found no store and is asking the site for
        its project, MIG; an adoption on Jira naming OTHER cannot open the
        tracker until the move has, and, kept waiting longer than it waits,
        adopts nothing. Adopted after, it finds the project the move
        recorded, and the work made then is the checkout's with the work
        moved."""
        root = self.home.path
        made = self.m.invoke(
            "operation.start-named-work", {"root": root, "title": "Count the plot", "quiet": True}
        )
        self.assertEqual(made["status"], "completed", made)
        asking, go, first = threading.Event(), threading.Event(), [True]

        def held(method, path):
            if path.endswith("/project/MIG") and first[0]:
                first[0] = False
                asking.set()
                go.wait(30)

        self.site.stub.held = held
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "move",
                self.m.invoke(
                    "operation.move-a-workspace",
                    {"root": root, "fromTracker": "local", "toTracker": "jira"},
                ),
            )
        )
        one.start()
        try:
            self.assertTrue(asking.wait(30))
            self.m.TRACKER_LOCK_SECONDS = 0.5
            waited = self.adopt()
        finally:
            go.set()
            one.join(30)
        self.assertEqual(waited["status"], "failed", waited)
        self.assertIn("adopting it or opening its tracker", waited["summary"])
        moved = answers["move"]
        self.assertEqual((moved["status"], moved["moved"]), ("completed", 1), moved)
        again = self.adopt()
        self.assertEqual((again["status"], again["summary"]), ("completed", "Already adopted."))
        after = self.m.invoke(
            "operation.start-named-work", {"root": root, "title": "Made after", "quiet": True}
        )
        self.assertEqual(after["status"], "completed", after)
        with open(os.path.join(self.m.workspace(root), "jira.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["project"], "MIG")
        listed = self.m.invoke_tracker("operation.list-items", {"root": root, "scope": "all"})
        self.assertIn(after["workRef"], [item["id"] for item in listed["items"]], listed)
        self.assertEqual(len(listed["items"]), 2, listed)
        self.assertEqual(
            {f["project"]["key"] for f in self.site.stub.issues.values()},
            {"MIG"},
            "nothing on OTHER",
        )


class WorkMadeUnderAnIssueWhileItCloses(unittest.TestCase):
    """A close checks that nothing under the issue it closes stands open,
    and then closes it, under the lock of the store it writes to. Work made
    under an issue is made under that lock too, given an ETag or not: a
    child named under it, and a pour's steps under their root. So none is
    made between a close's check and its close, left open under an issue
    closed for having nothing open under it."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, self.home.env, "dotdiw_made_under")

    def named(self, title, **fields):
        return self.m.invoke(
            "operation.start-named-work",
            dict(fields, root=self.home.path, title=title, quiet=True),
        )

    def close(self, key, etags=()):
        return self.m.invoke(
            "operation.forward-to-the-tracker",
            {"root": self.home.path, "arguments": ["close", key], "etags": list(etags)},
        )

    def held_at(self, wanted):
        """The site held at the first request wanted says True of, until go
        is set: asked is set once it is held there."""
        asked, go, first = threading.Event(), threading.Event(), [True]

        def held(method, path):
            if first[0] and wanted(method, path):
                first[0] = False
                asked.set()
                go.wait(30)

        self.site.stub.held = held
        return asked, go

    def test_a_child_named_while_its_parent_closes_waits(self):
        """The close of the parent, held to its ETag, has found nothing open
        under it and is moving it to done when a child is named under it,
        given no ETag: the child cannot be made until the close is done,
        and, kept waiting longer than it waits, is not made."""
        parent = self.named("Count the plot")
        key, etag = parent["workRef"], parent["item"]["etag"]
        closing, go = self.held_at(
            lambda method, path: method == "GET" and path.endswith("/issue/%s/transitions" % key)
        )
        answers: dict[str, Any] = {}
        one = threading.Thread(target=lambda: answers.__setitem__("close", self.close(key, [etag])))
        one.start()
        try:
            self.assertTrue(closing.wait(30))
            self.m.TRACKER_LOCK_SECONDS = 0.5
            waited = self.named("Count the beds", parent=key)
        finally:
            go.set()
            one.join(30)
        self.assertEqual(answers["close"]["closedRefs"], [key], answers["close"])
        self.assertEqual(waited["status"], "failed", waited)
        self.assertIn("held this checkout's tracker", waited["summary"])
        under = [
            k for k, f in self.site.stub.issues.items() if (f.get("parent") or {}).get("key") == key
        ]
        self.assertEqual(under, [], "nothing made under the issue closed")

    def test_a_step_closed_while_its_pour_runs_waits(self):
        """A pour has made its root and its first step and is making the
        second when the first is closed: the close cannot look at what
        stands open under the root until the pour is done, and, kept waiting
        longer than it waits, closes nothing. Closed after, it leaves the
        root open while the second step is."""
        formula = "two-steps.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-two-steps"\n'
                'description = "Pour it. Use when testing a close during a pour."\n'
                '[[steps]]\nid = "one"\ntitle = "One"\n'
                '[[steps]]\nid = "two"\ntitle = "Two"\n'
            )
        for args in (["add", formula], ["commit", "-qm", "f"]):
            subprocess.run(
                ["git"] + args, cwd=self.home.path, env=self.home.env, capture_output=True
            )
        creates = [0]

        def third_create(method, path):
            if method == "POST" and path == "/rest/api/3/issue":
                creates[0] += 1
            return creates[0] == 3

        making, go = self.held_at(third_create)
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "pour",
                self.m.invoke(
                    "operation.pour-procedure", {"root": self.home.path, "ident": "mol-two-steps"}
                ),
            )
        )
        one.start()
        try:
            self.assertTrue(making.wait(30))
            root_key, first_key = list(self.site.stub.issues)[-2:]
            self.m.TRACKER_LOCK_SECONDS = 0.5
            waited = self.close(first_key)
        finally:
            go.set()
            one.join(30)
        poured = answers["pour"]
        self.assertEqual(poured["status"], "completed", poured)
        self.assertEqual((poured["moleculeRef"], poured["stepRefs"][0]), (root_key, first_key))
        self.assertEqual(waited["status"], "failed", waited)
        self.assertIn("held this checkout's tracker", waited["summary"])
        closed = self.close(first_key)
        self.assertEqual(closed["closedRefs"], [first_key], closed)
        root = self.m.invoke_tracker(
            "operation.show-item", {"root": self.home.path, "id": root_key}
        )
        self.assertEqual(root["item"]["status"], "open", root)


class AMoveReadsNoPourHalfMade(unittest.TestCase):
    """A move reads its source -- the listing, and each issue it makes,
    shown -- under the lock a write of that source holds, the lock a pour
    holds from its root to the last need of its steps. So a move cannot read
    a run whose steps are made and whose needs are not, and settle it so,
    leaving a second move nothing to write and a step ready before the step
    it needs."""

    m: Any

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "CHK")
        self.assertEqual(code, 0, out)
        self.m = in_process(self, self.home.env, "dotdiw_move_mid_pour")

    def move(self):
        return self.m.invoke(
            "operation.move-a-workspace",
            {"root": self.home.path, "fromTracker": "jira", "toTracker": "local"},
        )

    def test_a_move_while_a_pour_links_its_steps_waits(self):
        """A pour has made Build and Publish and is about to make Publish
        need Build when the workspace is moved to local: the move cannot read
        the issues until the pour is done, and, kept waiting longer than it
        waits, moves nothing. Moved after, Publish waits on Build there."""
        formula = "build-then-publish.formula.toml"
        with open(os.path.join(self.home.path, formula), "w", encoding="utf-8") as fh:
            fh.write(
                'formula = "mol-build-then-publish"\n'
                'description = "Build, then publish. Use when testing a move during a pour."\n'
                '[[steps]]\nid = "build"\ntitle = "Build"\n'
                '[[steps]]\nid = "publish"\ntitle = "Publish"\nneeds = ["build"]\n'
            )
        for args in (["add", formula], ["commit", "-qm", "f"]):
            subprocess.run(
                ["git"] + args, cwd=self.home.path, env=self.home.env, capture_output=True
            )
        asked, go = threading.Event(), threading.Event()

        def held(method, path):
            if method == "POST" and path == "/rest/api/3/issueLink" and not asked.is_set():
                asked.set()
                go.wait(30)

        self.site.stub.held = held
        answers: dict[str, Any] = {}
        one = threading.Thread(
            target=lambda: answers.__setitem__(
                "pour",
                self.m.invoke(
                    "operation.pour-procedure",
                    {"root": self.home.path, "ident": "mol-build-then-publish"},
                ),
            )
        )
        one.start()
        try:
            self.assertTrue(asked.wait(30))
            self.m.TRACKER_LOCK_SECONDS = 0.5
            waited = self.move()
        finally:
            go.set()
            one.join(30)
        poured = answers["pour"]
        self.assertEqual(poured["status"], "completed", poured)
        build, publish = poured["stepRefs"]
        self.assertEqual((waited["status"], waited.get("moved")), ("failed", None), waited)
        self.assertIn("Nothing was moved: another dotdiw command held jira", waited["summary"])
        moved = self.move()
        self.assertEqual((moved["status"], moved["moved"]), ("completed", 3), moved)
        with open(moved["mappingPath"], encoding="utf-8") as fh:
            ids = json.load(fh)["ids"]
        local = {"root": self.home.path, "tracker": "local"}
        shown = self.m.invoke_tracker("operation.show-item", dict(local, id=ids[publish]))
        self.assertEqual(shown["item"]["needs"], [ids[build]], shown)
        ready = self.m.invoke_tracker("operation.ready-items", local)
        self.assertNotIn(ids[publish], [i["id"] for i in ready["items"]], ready)


def have_grpc():
    try:
        importlib.import_module("grpc")
        importlib.import_module("google.protobuf.descriptor_pool")
    except ImportError:
        return False
    return True


@unittest.skipUnless(have_grpc(), "grpcio and protobuf are not installed")
class TheHostedAdapterServed(unittest.TestCase):
    """Over gRPC, under Jira: an issue read carries its ETag, every read of
    it the same one, and a write on a stale read is ABORTED and writes
    nothing."""

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)
        self.grpc = importlib.import_module("grpc")
        pb = importlib.import_module("google.protobuf.descriptor_pb2")
        pools = importlib.import_module("google.protobuf.descriptor_pool")
        self.factory = importlib.import_module("google.protobuf.message_factory")
        loader = importlib.machinery.SourceFileLoader("dotdiw_served_jira", DOTDIW)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        assert spec is not None
        m = importlib.util.module_from_spec(spec)
        loader.exec_module(m)
        self.pool = pools.DescriptorPool()
        self.pool.Add(m.grpc_descriptor(pb))
        self.package, self.service = m.GRPC_PACKAGE, "/%s.%s/" % (m.GRPC_PACKAGE, m.GRPC_SERVICE)
        server = subprocess.Popen(
            [sys.executable, "-I", DOTDIW, "serve", "--address", "127.0.0.1:0"],
            cwd=self.home.path,
            env=self.home.env,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert server.stderr is not None
        self.addCleanup(server.stderr.close)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        line = server.stderr.readline()
        self.assertIn("serving gRPC on 127.0.0.1:", line)
        self.channel = self.grpc.insecure_channel(line.strip().rsplit(" ", 1)[1])
        self.addCleanup(self.channel.close)

    def call(self, method, **fields):
        def kind(name):
            return self.factory.GetMessageClass(
                self.pool.FindMessageTypeByName("%s.%s" % (self.package, name))
            )

        rpc = self.channel.unary_unary(
            self.service + method,
            request_serializer=lambda m: m.SerializeToString(),
            response_deserializer=kind(method + "Response").FromString,
        )
        fields.setdefault("root", self.home.path)
        return rpc(kind(method + "Request")(**fields), timeout=120)

    def test_a_write_on_a_stale_read_is_aborted_and_writes_nothing(self):
        made = self.call("StartNamedWork", title="Count the plot", quiet=True)
        key, first = made.work_ref, made.item.etag
        shown = self.call("RunATrackerCommand", arguments=["show", key]).items[0]
        listed = self.call("RunATrackerCommand", arguments=["list"]).items
        self.assertEqual([shown.etag], [i.etag for i in listed if i.id == key])
        self.assertEqual(shown.etag, first)
        self.call(
            "RunATrackerCommand", arguments=["update", key, "--title", "North"], etags=[first]
        )
        with self.assertRaises(self.grpc.RpcError) as raised:
            self.call(
                "RunATrackerCommand", arguments=["update", key, "--title", "South"], etags=[first]
            )
        self.assertEqual(raised.exception.code(), self.grpc.StatusCode.ABORTED)
        self.assertEqual(self.site.stub.issues[key]["summary"], "North")

    def test_a_move_given_no_root_is_answered_and_no_internal_error(self):
        """MoveAWorkspace names no root, as a client that leaves the field
        unset sends it: the answer is the move of the checkout dotdiw is
        served in, or a refusal that says no checkout was given -- never the
        server's own error."""
        self.call("StartNamedWork", title="Count the plot", quiet=True)
        try:
            moved = self.call("MoveAWorkspace", root="", from_tracker="jira", to_tracker="local")
        except self.grpc.RpcError as e:
            self.fail("%s: %s" % (e.code(), e.details()))
        done = (moved.status, moved.moved) == ("completed", 1)
        self.assertTrue(done or "no checkout was given" in moved.summary, moved)


def dotdiw_tests():
    """test_dotdiw.py as a module: the one suites.py loaded, where it did, so
    that its scenarios are held of Jira as of every adapter."""
    if "test_dotdiw" in sys.modules:
        return sys.modules["test_dotdiw"]
    loader = importlib.machinery.SourceFileLoader(
        "test_dotdiw", os.path.join(HERE, "test_dotdiw.py")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


if TYPE_CHECKING:
    from test_dotdiw import NestedPours
else:
    NestedPours = dotdiw_tests().NestedPours


class NestedPoursUnderJira(NestedPours, unittest.TestCase):
    """The scenario of a pour that calls formulas, under Jira, as under the
    local tracker and beads."""

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        self.where, self.env = self.home.path, self.home.env
        self.write_nested()
        self.did("init", "--tracker", "jira", "--prefix", "demo")


class APourUnderJiraCutShort(unittest.TestCase):
    """Jira writes a pour one request at a time, so a pour that calls a
    formula is held on a guard, made first and closed last: stopped after
    any write it makes, no root and no calling step it made can complete,
    and the guard closes for no close but the pour's."""

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        tests = dotdiw_tests()
        for rel, text in (
            ("campaigns/publish-campaign.formula.toml", tests.CAMPAIGN),
            ("rights/clear-image-for-paid-social.formula.toml", tests.CLEARANCE),
        ):
            path = os.path.join(self.home.path, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        code, out = self.home.dotdiw("init", "--tracker", "jira", "--prefix", "demo")
        self.assertEqual(code, 0, out)

    @staticmethod
    def a_write(method, path):
        return method in ("POST", "PUT", "DELETE") and not path.startswith("/rest/api/3/search")

    def pour(self, cut=None):
        """The pour, the write numbered cut answered 503; the writes, and the
        answer as JSON where the pour made its root."""
        stub = self.site.stub
        real = stub.handle
        writes = []

        def counted(method, path, query, body):
            if self.a_write(method, path):
                writes.append((method, path))
                if len(writes) == cut:
                    return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", counted):
            p = subprocess.run(
                [sys.executable, "-I", DOTDIW, "formula", "pour", "publish-campaign", "--json"],
                cwd=self.home.path,
                env=self.home.env,
                input="",
                capture_output=True,
                text=True,
            )
        answer = json.loads(p.stdout) if p.stdout.strip() else None
        return p.returncode, answer, p.stderr, writes

    def status(self, key):
        category = STATUSES.get(self.site.stub.issues[key]["_status"], "new")
        return {"new": "open", "indeterminate": "in_progress", "done": "closed"}[category]

    def guards(self):
        return [
            k
            for k, props in self.site.stub.properties.items()
            if (props.get("dotdiw") or {}).get("kind") == "guard"
        ]

    def test_a_whole_pour_closes_its_guard(self):
        code, answer, err, writes = self.pour()
        self.assertEqual(code, 0, err)
        # The guard, the root, the guard's run; each step, then each of its
        # links -- licence's to its calling step, release's need and its
        # calling step's, prepare's need -- the root marked whole, and the
        # guard's close.
        self.assertEqual(
            [m for m, _ in writes], ["POST"] * 2 + ["PUT"] + ["POST"] * 8 + ["PUT"] + ["POST"]
        )
        self.assertEqual(
            [p for _, p in writes if p.endswith("/issueLink")], ["/rest/api/3/issueLink"] * 4
        )
        (guard,) = self.guards()
        self.assertEqual(self.status(guard), "closed")
        self.assertIsNone(self.site.stub.issues[guard]["parent"], "outside the root's epic")
        self.assertEqual(
            self.site.stub.properties[guard]["dotdiw"], {"kind": "guard", "run": answer["rootId"]}
        )
        self.assertEqual(
            self.site.stub.properties[answer["rootId"]]["dotdiw"], {"guard": guard, "whole": True}
        )
        # Each calling step names the guard in the create that makes it.
        callers = [
            own["dotdiw"]
            for own in self.site.stub.properties.values()
            if (own.get("dotdiw") or {}).get("calls")
        ]
        self.assertEqual([c.get("guard") for c in callers], [guard], callers)
        code, out = self.home.dotdiw("show", answer["rootId"], "--json")
        self.assertEqual(code, 0, out)
        self.assertIs(json.loads(out)["whole"], True, out)
        code, out = self.home.dotdiw("close", guard)
        self.assertEqual(code, 1, out)
        self.assertIn("is a pour's guard: only the pour that made it closes it", out)

    def test_a_guard_no_read_confirms_closed_holds_ready_and_a_move(self):
        """Stopped once the first step of its call is made, a pour's guard is
        deleted in Jira, so that no search lists it and no lookup reads it:
        the root and the calling step that name it hold the pour back until
        it is read as closed -- nothing of the pour is given ready, and the
        move into local moves nothing."""
        code, answer, err, _ = self.pour(cut=6)
        self.assertEqual(code, 1, err)
        (guard,) = self.guards()
        root = answer["rootId"]
        made = [root] + [
            k
            for k, props in self.site.stub.properties.items()
            if (props.get("dotdiw") or {}).get("run") == root and k != guard
        ]
        self.assertEqual(len(made), 3, "the root, the calling step and the step within it")
        # Listed, but no longer read as a guard: its property gone, it is a
        # task that stands open, and holds as its guard did.
        del self.site.stub.properties[guard]["dotdiw"]
        self.held_back(made, guard)
        # Then gone from every listing and every lookup.
        del self.site.stub.issues[guard]
        self.held_back(made, guard)

    def held_back(self, made, guard):
        """Nothing of what made holds is ready, and the move into local moves
        nothing, naming the guard."""
        code, out = self.home.dotdiw("ready", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual([i["id"] for i in json.loads(out) if i["id"] in made], [])
        code, out = self.home.dotdiw("tracker", "migrate", "jira", "local")
        self.assertEqual(code, 1, out)
        self.assertIn(
            "Nothing was moved: a pour into jira is not known to have finished: its guard %s"
            % guard,
            out,
        )

    def run_of(self, root, guard):
        return [
            k
            for k, props in self.site.stub.properties.items()
            if (props.get("dotdiw") or {}).get("run") == root and k != guard
        ]

    def test_a_guard_that_no_longer_reads_as_one_is_closed_by_no_one_but_its_pour(self):
        """Stopped once the first step of its call is made, its guard's
        property taken off in Jira, so that it reads as a task: the root and
        the calling step name it, so it is a guard still, and no close
        through dotdiw closes it."""
        code, answer, err, _ = self.pour(cut=6)
        self.assertEqual(code, 1, err)
        (guard,) = self.guards()
        del self.site.stub.properties[guard]["dotdiw"]
        code, out = self.home.dotdiw("close", guard)
        self.assertEqual(code, 1, out)
        self.assertIn("nothing else writes it", out)
        self.assertNotEqual(self.status(guard), "closed")

    def test_a_whole_pours_guard_deleted_holds_nothing(self):
        """A whole pour's guard, closed, is deleted in Jira, as old done
        issues are: its root reads whole, so its work is ready, and its
        calling step and root close once their steps do."""
        code, answer, err, _ = self.pour()
        self.assertEqual(code, 0, err)
        (guard,) = self.guards()
        root = answer["rootId"]
        del self.site.stub.issues[guard]
        run = self.run_of(root, guard)
        given = json.loads(self.home.dotdiw("ready", "--json")[1] or "[]")
        self.assertTrue([i for i in given if i["id"] in run], given)
        callers = [k for k in run if self.site.stub.properties[k]["dotdiw"].get("calls")]
        for _ in run:
            for key in run:
                if key not in callers:
                    self.home.dotdiw("close", key)
        for held in callers + [root]:
            self.assertEqual(self.status(held), "closed", held)

    def test_a_calling_step_waits_on_its_runs_guard_whatever_names_it(self):
        """Stopped at the root's mark, every issue made: the root's and the
        calling step's guard properties taken off in Jira, the guard left as
        it stands. The calling step is of a run whose guard stands open, so
        no close of it, asked or in the wake of its steps', closes it."""
        _, _, _, writes = self.pour()
        code, answer, err, _ = self.pour(len(writes) - 1)
        self.assertEqual(code, 1, err)
        root = answer["rootId"]
        (guard,) = [
            g for g in self.guards() if self.site.stub.properties[g]["dotdiw"].get("run") == root
        ]
        run = self.run_of(root, guard)
        callers = [k for k in run if self.site.stub.properties[k]["dotdiw"].get("calls")]
        for k in callers + [root]:
            self.site.stub.properties[k]["dotdiw"].pop("guard", None)
        for _ in run:
            for key in run:
                if key not in callers:
                    self.home.dotdiw("close", key)
        for held in callers:
            code, out = self.home.dotdiw("close", held)
            self.assertEqual(code, 1, (held, out))
            self.assertIn(guard, out)
            self.assertEqual(self.status(held), "open")

    def test_a_guard_whose_root_no_search_finds_yet_is_not_closed(self):
        """Stopped after the root is made, before the guard is given its run:
        no search finds the root yet, and the guard is not closed -- only
        one whose run's root reads whole, as read by its key, is -- nor does
        the root, which names it, close."""
        code, answer, err, _ = self.pour(cut=3)
        self.assertEqual(code, 1, err)
        (guard,) = self.guards()
        root = answer["rootId"]
        self.assertNotIn("run", self.site.stub.properties[guard]["dotdiw"])
        self.site.stub.lagging[root] = None
        for ident in (guard, root):
            code, out = self.home.dotdiw("close", ident)
            self.assertEqual(code, 1, (ident, out))
            self.assertEqual(self.status(ident), "open", ident)
        self.assertIn("nothing else writes it", self.home.dotdiw("close", guard)[1])

    def test_a_guard_whose_root_reads_whole_closes_whatever_a_search_still_shows(self):
        """Stopped at the guard's close, the root marked whole: a search still
        shows the root as it was before the mark, and the guard's close,
        read by its key, finishes the pour."""
        _, _, _, writes = self.pour()
        code, answer, err, _ = self.pour(len(writes))
        self.assertEqual(code, 1, err)
        root = answer["rootId"]
        (guard,) = [
            g for g in self.guards() if self.site.stub.properties[g]["dotdiw"].get("run") == root
        ]
        self.site.stub.lagging[root] = {"_properties": {"dotdiw": {"guard": guard}}}
        code, out = self.home.dotdiw("close", guard)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.status(guard), "closed")

    def test_a_root_a_search_lists_and_no_lookup_reads_holds_its_pour(self):
        """Stopped once the first step of its call is made, its guard's
        property taken off, its root no longer read by its key though a
        search lists it -- deleted, or no longer the token's to see, which
        Jira's 404 does not tell apart: the root is not read as whole, so
        the guard is not closed, and the step's close closes neither its
        calling step nor the root."""
        code, answer, err, _ = self.pour(cut=6)
        self.assertEqual(code, 1, err)
        (guard,) = self.guards()
        root = answer["rootId"]
        run = self.run_of(root, guard)
        callers = [k for k in run if self.site.stub.properties[k]["dotdiw"].get("calls")]
        (leaf,) = [k for k in run if k not in callers]
        del self.site.stub.properties[guard]["dotdiw"]
        self.site.stub.gone.add(root)
        code, out = self.home.dotdiw("close", guard)
        self.assertEqual(code, 1, out)
        self.assertNotEqual(self.status(guard), "closed")
        self.home.dotdiw("close", leaf)
        for held in callers + [root]:
            self.assertEqual(self.status(held), "open", held)

    def test_a_root_marked_whole_holds_its_run_while_its_guard_stands_open(self):
        """Stopped at the guard's close, the root marked whole and the guard
        open: as under beads, whose edges hold it, nothing of the run is
        ready and no calling step closes until the guard's close through
        dotdiw, which then frees the run."""
        _, _, _, writes = self.pour()
        code, answer, err, _ = self.pour(len(writes))
        self.assertEqual(code, 1, err)
        root = answer["rootId"]
        (guard,) = [
            g for g in self.guards() if self.site.stub.properties[g]["dotdiw"].get("run") == root
        ]
        run = self.run_of(root, guard)
        callers = [k for k in run if self.site.stub.properties[k]["dotdiw"].get("calls")]
        given = json.loads(self.home.dotdiw("ready", "--json")[1] or "[]")
        self.assertEqual([i["id"] for i in given if i["id"] in run + [root]], [], given)
        for _ in run:
            for key in run:
                if key not in callers:
                    self.home.dotdiw("close", key)
        for held in callers:
            self.assertEqual(self.status(held), "open", held)
            code, out = self.home.dotdiw("close", held)
            self.assertEqual(code, 1, out)
        code, out = self.home.dotdiw("close", guard)
        self.assertEqual(code, 0, out)
        for held in callers:
            code, out = self.home.dotdiw("close", held)
            self.assertEqual(code, 0, out)

    def test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete(self):
        _, _, _, writes = self.pour()
        for cut in range(1, len(writes) + 1):
            before = set(self.guards())
            code, answer, err, _ = self.pour(cut)
            self.assertEqual(code, 1, (cut, err))
            made = sorted(set(self.guards()) - before)
            if cut == 1:
                self.assertEqual(made, [], "nothing was made")
                continue
            (guard,) = made
            self.assertEqual(self.status(guard), "open", cut)
            root = (answer or {}).get("rootId")
            if root is None:
                # Stopped before the root was made: the guard holds nothing,
                # and, with no root of it known, no close through dotdiw
                # closes it.
                self.assertIn("Nothing but its guard %s was made" % guard, err)
                code, out = self.home.dotdiw("close", guard)
                self.assertEqual(code, 1, out)
                continue
            self.assertIn("%s holds" % guard, err)
            if cut == len(writes):
                # Stopped at the guard's close, the last write: every issue
                # is made and the root marked whole, and the guard's close
                # through dotdiw finishes the pour, its steps then work.
                self.assertIn("finishes the pour", err)
                code, out = self.home.dotdiw("close", guard)
                self.assertEqual(code, 0, out)
                self.assertEqual(self.status(guard), "closed")
                given = json.loads(self.home.dotdiw("ready", "--json")[1] or "[]")
                self.assertTrue(
                    [
                        i
                        for i in given
                        if (self.site.stub.properties.get(i["id"], {}).get("dotdiw") or {}).get(
                            "run"
                        )
                        == root
                    ],
                    given,
                )
                continue
            self.assertIn("no close but a pour's closes it", err)
            run = [
                k
                for k, props in self.site.stub.properties.items()
                if root and (props.get("dotdiw") or {}).get("run") == root and k != guard
            ]
            callers = [k for k in run if self.site.stub.properties[k]["dotdiw"].get("calls")]
            given = json.loads(self.home.dotdiw("ready", "--json")[1] or "[]")
            self.assertEqual(
                [i["id"] for i in given if i["id"] in run + [root, guard]],
                [],
                "nothing of a pour whose guard stands open is ready",
            )
            for _ in run:
                for key in run:
                    if key not in callers:
                        self.home.dotdiw("close", key)
            for held in ([root] if root else []) + callers:
                code, out = self.home.dotdiw("close", held)
                self.assertEqual(code, 1, (cut, held, out))
                self.assertEqual(self.status(held), "open", (cut, held))
            code, out = self.home.dotdiw("close", guard)
            self.assertEqual(code, 1, out)
            self.assertEqual(self.status(guard), "open", cut)


class ACallMoves(unittest.TestCase):
    """A job that calls a formula moves between trackers whole: each item
    keeps the call it was poured within, as the id the move gave the
    calling step, and the formula a calling step calls, so that the call
    still holds its calling step and reads back its own claims and means. A
    pour that did not finish moves nothing, nor does a call into a tracker
    that does not keep calls."""

    def setUp(self):
        self.site = Site()
        self.addCleanup(self.site.close)
        self.home = Home(self.site)
        self.addCleanup(self.home.close)
        self.home.env["JIRA_PROJECT"] = "CHK"  # where a move into Jira writes
        tests = dotdiw_tests()
        for rel, text in (
            ("campaigns/publish-campaign.formula.toml", tests.CAMPAIGN),
            ("rights/clear-image-for-paid-social.formula.toml", tests.CLEARANCE),
        ):
            path = os.path.join(self.home.path, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    def records(self, *args):
        p = subprocess.run(
            [sys.executable, "-I", DOTDIW] + list(args) + ["--json"],
            cwd=self.home.path,
            env=self.home.env,
            input="",
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def did(self, *args):
        code, out = self.home.dotdiw(*args)
        self.assertEqual(code, 0, out)
        return out

    def test_a_job_that_calls_a_formula_moves_whole(self):
        self.did("init", "--tracker", "local")
        poured = self.records("formula", "pour", "publish-campaign")
        licence = poured["calls"][0]["stepIds"][0]
        self.did("claim", licence, "number: L-5")
        self.did("tracker", "migrate", "local", "jira")
        moved = {i["title"]: i for i in self.records("--tracker", "jira", "list", "--all")}
        root = moved["publish-campaign"]
        rights = moved["Clear the selected image for paid social"]
        within = [moved[t] for t in moved if moved[t].get("within")]
        self.assertEqual(
            (rights["calls"], rights["run"]), ("clear-image-for-paid-social", root["id"])
        )
        self.assertEqual(sorted(i["step"] for i in within), ["licence", "release"])
        for item in within:
            self.assertEqual((item["within"], item["run"]), (rights["id"], root["id"]))
            self.assertIn(item["id"], rights["needs"])
        read = self.records("--tracker", "jira", "claim", root["id"])
        self.assertEqual(read["calls"][0]["item"], rights["id"])
        self.assertEqual(read["calls"][0]["verifyUsing"], ["run:check-licence L-5"])

    def test_a_pour_that_did_not_finish_moves_nothing(self):
        self.did("init", "--tracker", "jira", "--prefix", "demo")
        stub = self.site.stub
        real = stub.handle
        writes = []

        def cut_at_the_fifth(method, path, query, body):
            if method in ("POST", "PUT") and not path.startswith("/rest/api/3/search"):
                writes.append(path)
                if len(writes) == 5:
                    return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", cut_at_the_fifth):
            code, out = self.home.dotdiw("formula", "pour", "publish-campaign")
        self.assertEqual(code, 1, out)
        code, out = self.home.dotdiw("tracker", "migrate", "jira", "local")
        self.assertEqual(code, 1, out)
        self.assertIn("Nothing was moved: a pour into jira is not known to have finished", out)

    def test_a_move_whose_read_back_fails_makes_nothing_twice(self):
        """Jira makes a step poured within a call, links its calling step's
        need of it, and cannot read it back: the move names it made, and the
        next run finishes it rather than make a second."""
        self.did("init", "--tracker", "local")
        self.records("formula", "pour", "publish-campaign")
        stub = self.site.stub
        real = stub.handle
        linked: list[Any] = []

        def unread_once(method, path, query, body):
            if method == "POST" and path == "/rest/api/3/issueLink":
                linked.append(((body or {}).get("outwardIssue") or {}).get("key"))
            elif method == "GET" and len(linked) == 1 and path.endswith("/" + linked[0]):
                linked.append("read")
                return 503, {"errorMessages": ["The service is unavailable."]}
            return real(method, path, query, body)

        with mock.patch.object(stub, "handle", unread_once):
            code, out = self.home.dotdiw("tracker", "migrate", "local", "jira")
        self.assertEqual(code, 1, out)
        self.assertEqual(linked[1:], ["read"], "the step made within the call was not read back")
        self.did("tracker", "migrate", "local", "jira")
        steps = sorted(
            (p["dotdiw"].get("step"), p["dotdiw"].get("within"))
            for p in stub.properties.values()
            if (p.get("dotdiw") or {}).get("within")
        )
        self.assertEqual([s for s, _ in steps], ["licence", "release"], "each made once")

    def test_a_calling_step_its_steps_stand_under_closes_with_them(self):
        """Moved under their calling step, the steps of its call close it
        as they would have under the root."""
        self.did("init", "--tracker", "jira", "--prefix", "demo")
        poured = self.records("formula", "pour", "publish-campaign")
        rights, prepare = poured["stepIds"]
        for item in poured["calls"][0]["stepIds"]:
            self.did("update", item, "--parent", rights)
        for item in poured["calls"][0]["stepIds"]:
            self.did("close", item)
        shown = self.records("show", rights)
        self.assertEqual(shown["status"], "closed")

    def test_a_call_moves_into_no_tracker_that_does_not_keep_calls(self):
        installed = os.path.join(self.home.home, ".dotdiw", "trackers", "jira.py")
        with open(installed, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count('"nests": True,'), 2)
        with open(installed, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"nests": True,', ""))
        self.did("init", "--tracker", "local")
        self.records("formula", "pour", "publish-campaign")
        code, out = self.home.dotdiw("tracker", "migrate", "local", "jira")
        self.assertEqual(code, 1, out)
        self.assertIn("holds items poured within a call", out)
        self.assertIn("and jira does not say it keeps calls.", out)
        self.assertEqual(self.site.stub.issues, {}, "nothing was written")


if __name__ == "__main__":
    unittest.main(verbosity=2)
