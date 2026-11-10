#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A Jira Cloud adapter for dotdiw's tracker interface: a worked example on a
tracker hosted elsewhere, tested against a stub of its API.

Install it with Homebrew, naming both packages, because Homebrew loads a
dependency from a tap only if that formula is trusted, and naming a formula
trusts it. Or copy the file to `~/.dotdiw/trackers/`. dotdiw loads it when
`--tracker`, a checkout's choice or `tracker use` names it:

    brew install adimpression/tap/dotdiw adimpression/tap/dotdiw-tracker-jira
    # or: mkdir -p ~/.dotdiw/trackers && cp trackers/jira.py ~/.dotdiw/trackers/jira.py
    dotdiw tracker list                      # jira is listed, from where it was found
    dotdiw init --tracker jira --prefix PROJ # this checkout's work goes to project PROJ

Credentials never touch dotdiw: this module reads them from the environment,
JIRA_SITE (https://<you>.atlassian.net), JIRA_EMAIL and JIRA_API_TOKEN, or
from ~/.dotdiw/trackers/jira.json holding the same three names, under the
home and never in a repository. JIRA_PROJECT is the project a checkout opened
without a prefix goes to; JIRA_CHECK_PROJECT is the one project
`dotdiw tracker check jira` may fill, and the check runs against nothing
else. Nothing here prints, and no response carries a credential.

How the interface maps onto Jira: a project is a workspace, recorded in the
workspace's jira.json; an issue is an item, its key the id; summary is the
title; a poured root is an Epic labelled `root`, and every other issue is a task,
whatever its type, the root's description keeping the means to prove the run
as its last section; the status category is the status, new, indeterminate or
done, with a
label `blocked` for blocked; priority is Highest to Lowest for 0 to 4; the
parent field is the parent; the assignee is read by display name and set by
account id, `me` being the account behind the token; a Blocks issue link is a
need, the inward issue needing the outward one, which is where Jira carries
edges natively; and the close reason is a comment, "closed: <reason>", the
last of them read back.
A close is refused while an open need or an open child exists, and a poured
root closes when its last step does, both decided here, since Jira decides
neither. Ids are Jira's: an id asked for is not honoured, and the record
says which.

Jira's REST API v3, over urllib: nothing outside the standard library.
"""

import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

Request = dict[str, Any]
Response = dict[str, Any]
Record = dict[str, Any]

VERSION = "0.1"
STORE = "jira.json"
PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")
CATEGORIES = {"new": "open", "indeterminate": "in_progress", "done": "closed"}

NOT_CONFIGURED: Response = {
    "status": "failed",
    "reason": "not-installed",
    "exitCode": 1,
    "summary": "JIRA_SITE, JIRA_EMAIL and JIRA_API_TOKEN are not set, in the "
    "environment or in ~/.dotdiw/trackers/jira.json.",
}
NO_WORKSPACE: Response = {
    "status": "failed",
    "reason": "no-workspace",
    "exitCode": 1,
    "summary": "This checkout has no project here; init adopts it, or open names one.",
}


def config() -> tuple[str, str, str] | None:
    """site, email, token: the environment first, then the file under the home."""
    names = ("JIRA_SITE", "JIRA_EMAIL", "JIRA_API_TOKEN")
    values = {n: os.environ.get(n) for n in names}
    if not all(values.values()):
        try:
            with open(os.path.expanduser("~/.dotdiw/trackers/jira.json"), encoding="utf-8") as fh:
                held = json.load(fh)
            for n in names:
                values[n] = values[n] or held.get(n)
        except (OSError, ValueError):
            pass
    site, email, token = values["JIRA_SITE"], values["JIRA_EMAIL"], values["JIRA_API_TOKEN"]
    if not (site and email and token):
        return None
    return site.rstrip("/"), email, token


def workspace(root: str) -> str | None:
    """This checkout's workspace under the home, as dotdiw hands it in; read
    from git the same way when the module runs on its own."""
    handed = globals().get("dotdiw_workspace")
    if handed is not None:
        given: str | None = handed(root)
        return given
    try:
        p = subprocess.run(
            ["git", "config", "--local", "--get", "dotdiw.workspace"],
            capture_output=True,
            text=True,
            cwd=root,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    key = p.stdout.strip() if p.returncode == 0 else ""
    return os.path.join(os.path.expanduser("~/.dotdiw"), key) if key else None


def store(root: str | None) -> str | None:
    ws = workspace(root) if root else None
    return os.path.join(ws, STORE) if ws else None


def project_of(root: str | None) -> str | None:
    """The project this checkout's work goes to, from the workspace's record."""
    path = store(root)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            project: str | None = json.load(fh).get("project")
            return project
    except (OSError, ValueError):
        return None


class JiraError(Exception):
    def __init__(self, status: int, text: str) -> None:
        Exception.__init__(self, "%s: %s" % (status, text))
        self.status = status
        self.text = text


def call(method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
    """One request to the site, Basic auth from the config; the JSON answer."""
    cfg = config()
    if cfg is None:
        raise JiraError(0, "JIRA_SITE, JIRA_EMAIL and JIRA_API_TOKEN are not set")
    site, email, token = cfg
    url = site + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header(
        "Authorization",
        "Basic " + base64.b64encode(("%s:%s" % (email, token)).encode("utf-8")).decode("ascii"),
    )
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as e:
        with e:
            raise JiraError(e.code, e.read().decode("utf-8", "replace")[:300]) from e
    except (urllib.error.URLError, OSError) as e:
        raise JiraError(0, str(e)) from e


def failed(e: JiraError, reasons: Sequence[tuple[str, int]] = ()) -> Response:
    """A failed response from what Jira said, with the reason its status names."""
    reason = None
    for key, status in reasons:
        if e.status == status:
            reason = key
            break
    return {
        "status": "failed",
        "reason": reason,
        "exitCode": 1,
        "summary": "Jira answered %s" % (e.status or "nothing")
        + (": %s" % e.text if e.text else ""),
    }


def adf(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def plain(doc: Any) -> str:
    if isinstance(doc, str):
        return doc
    out = []
    for node in (doc or {}).get("content") or []:
        for leaf in node.get("content") or []:
            if leaf.get("type") == "text":
                out.append(leaf.get("text") or "")
    return "".join(out)


# An item keeps the means to prove a run, a root's from its pour and a moved
# item's from its move, as the last section of its description, one to a line,
# the way the file dotdiw tracker new writes does.
VERIFY_HEADING = "Verify using:"


def keep_verify_using(description: str | None, means: list[str]) -> str | None:
    """The description, with the means kept as its last section. With none,
    the description as given, or followed by an empty section when it would
    otherwise read back as holding one."""
    if means:
        block = "\n".join([VERIFY_HEADING] + ["- " + m for m in means])
        return description + "\n\n" + block if description else block
    if not description or read_verify_using(description) == (description, []):
        return description
    return description + "\n\n" + VERIFY_HEADING


def read_verify_using(text: str | None) -> tuple[str | None, list[str]]:
    """The description as it was given, and the means kept in it: the last
    section headed Verify using:, at the start or after a blank line, whose
    lines to the end are each a means."""
    if not text:
        return text, []
    at = text.rfind("\n\n" + VERIFY_HEADING)
    if at < 0 and not text.startswith(VERIFY_HEADING):
        return text, []
    start, description = (at + 2, text[:at]) if at >= 0 else (0, None)
    rest = text[start + len(VERIFY_HEADING) :]
    if not rest:
        return description, []
    lines = rest.split("\n")
    if lines[0] or not all(line.startswith("- ") and len(line) > 2 for line in lines[1:]):
        return text, []
    return description, [line[2:] for line in lines[1:]]


FIELDS = (
    "summary,status,issuetype,parent,labels,priority,issuelinks,created,updated,comment,assignee,"
    "description"
)


def record(issue: dict[str, Any]) -> Record:
    """An issue as the interface's record."""
    f = issue.get("fields") or {}
    labels = f.get("labels") or []
    kind = "root" if "root" in labels else "task"
    status = CATEGORIES.get(
        ((f.get("status") or {}).get("statusCategory") or {}).get("key") or "", "open"
    )
    if status != "closed" and "blocked" in labels:
        status = "blocked"
    needs = [
        link["inwardIssue"]["key"]
        for link in f.get("issuelinks") or []
        if (link.get("type") or {}).get("name") == "Blocks" and link.get("inwardIssue")
    ]
    reason = None
    for comment in (f.get("comment") or {}).get("comments") or []:
        text = plain(comment.get("body"))
        if text.startswith("closed: "):
            reason = text[len("closed: ") :] or None
    name = (f.get("priority") or {}).get("name")
    assignee = f.get("assignee") or {}
    out: Record = {
        "id": issue["key"],
        "title": f.get("summary") or "",
        "kind": kind,
        "status": status,
        "priority": PRIORITIES.index(name) if name in PRIORITIES else 2,
        "parent": (f.get("parent") or {}).get("key"),
        "assignee": assignee.get("displayName") or assignee.get("accountId"),
        "reason": reason if status == "closed" else None,
        "needs": sorted(needs),
        "createdAt": f.get("created"),
        "updatedAt": f.get("updated"),
    }
    description, means = read_verify_using(
        plain(f["description"]) if f.get("description") else None
    )
    if description is not None:
        out["description"] = description
    if means:
        out["verifyUsing"] = means
    return out


def search(jql: str) -> list[dict[str, Any]]:
    """Every issue the JQL names, in pages."""
    out: list[dict[str, Any]] = []
    token = None
    while True:
        query = {"jql": jql, "maxResults": 100, "fields": FIELDS}
        if token:
            query["nextPageToken"] = token
        page = call("GET", "/rest/api/3/search/jql", query=query)
        out.extend(page.get("issues") or [])
        token = page.get("nextPageToken")
        if not token or page.get("isLast"):
            return out


def fetch(key: str) -> dict[str, Any] | None:
    try:
        issue: dict[str, Any] = call("GET", "/rest/api/3/issue/%s" % key, query={"fields": FIELDS})
        return issue
    except JiraError as e:
        if e.status == 404:
            return None
        raise


def held(key: str) -> dict[str, Any]:
    """The issue that must be there: its absence is Jira's 404, raised."""
    issue = fetch(key)
    if issue is None:
        raise JiraError(404, "%s names no issue" % key)
    return issue


def transition_to(key: str, category: str) -> bool:
    """Move an issue to the first transition whose target is in the category."""
    answer = call("GET", "/rest/api/3/issue/%s/transitions" % key)
    for t in answer.get("transitions") or []:
        if (((t.get("to") or {}).get("statusCategory") or {}).get("key")) == category:
            call("POST", "/rest/api/3/issue/%s/transitions" % key, {"transition": {"id": t["id"]}})
            return True
    return False


def move_to(key: str, issue: dict[str, Any], category: str) -> bool:
    """The issue in the status category, moved only if it is not there already,
    since a workflow offers no transition from a status to itself; False when
    it offers none that reaches the category."""
    status = (issue.get("fields") or {}).get("status") or {}
    if (status.get("statusCategory") or {}).get("key") == category:
        return True
    return transition_to(key, category)


def in_order(steps: list[Any]) -> list[Any]:
    """The steps each after those it needs, otherwise as declared. A need
    naming no step raises LookupError, and a cycle ValueError."""
    known = {s["id"] for s in steps}
    for s in steps:
        for need in s.get("needs") or []:
            if need not in known:
                raise LookupError("%s needs %s, which is not a step." % (s["id"], need))
    order: list[Any] = []
    placed: set[str] = set()
    left = list(steps)
    while left:
        ready = [s for s in left if all(n in placed for n in s.get("needs") or [])]
        if not ready:
            raise ValueError("A cycle among the steps: %s." % ", ".join(s["id"] for s in left))
        order.extend(ready)
        placed.update(s["id"] for s in ready)
        left = [s for s in left if s["id"] not in placed]
    return order


def ready_to_go(cfg: tuple[str, str, str] | None) -> Response | None:
    if cfg is None:
        return dict(NOT_CONFIGURED)
    return None


def opened(root: str | None) -> tuple[str | None, Response | None]:
    """The project, or the response that says there is none."""
    project = project_of(root)
    return project, (None if project else dict(NO_WORKSPACE))


def jira_open(request: Request) -> Response:
    """open-tracker: the project a checkout's work goes to, recorded under the
    workspace; the prefix is the project key, else JIRA_PROJECT."""
    if config() is None:
        return dict(NOT_CONFIGURED)
    root = request.get("root")
    path = store(root)
    if path is None:
        return dict(NO_WORKSPACE)
    created = not os.path.exists(path)
    project = (
        (project_of(root) if not created else None)  # a second open changes nothing
        or (request.get("prefix") or "").upper()
        or os.environ.get("JIRA_PROJECT")
    )
    if not project:
        return {
            "status": "failed",
            "reason": "no-workspace",
            "exitCode": 1,
            "summary": "No project named: init --prefix <KEY>, or JIRA_PROJECT.",
        }
    try:
        call("GET", "/rest/api/3/project/%s" % project)
    except JiraError as e:
        return failed(e, [("no-workspace", 404)])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"project": project}, fh)
            fh.write("\n")
    except OSError as e:
        return {"status": "failed", "reason": "store-unwritable", "exitCode": 1, "summary": str(e)}
    return {
        "status": "completed",
        "summary": "Project %s." % project,
        "path": path,
        "created": created,
        "exitCode": 0,
    }


def myself() -> dict[str, Any]:
    """The account behind the token, which is who every request here acts as."""
    mine: dict[str, Any] = call("GET", "/rest/api/3/myself")
    return mine


def acting_as() -> Record | None:
    """Who the token says this is. Jira checked it. Never the email address."""
    try:
        mine = myself()
    except JiraError:
        return None
    ident = mine.get("accountId")
    if not ident:
        return None
    return {"name": mine.get("displayName") or ident, "id": ident, "verified": True}


def jira_describe(request: Request) -> Response:
    cfg = config()
    version = VERSION
    if cfg is not None:
        try:
            version = "%s, site %s" % (
                VERSION,
                call("GET", "/rest/api/3/serverInfo").get("version") or "?",
            )
        except JiraError:
            version = VERSION
    path = store(request.get("root"))
    return {
        "status": "completed",
        "summary": "Jira Cloud, through its REST API.",
        "info": {
            "name": "jira",
            "version": version,
            "origin": "loaded",
            "nativeNeeds": True,
            "checkTarget": os.environ.get("JIRA_CHECK_PROJECT"),
            "extras": [],
        },
        "actor": acting_as() if cfg is not None else None,
        "path": path if path and os.path.isfile(path) else None,
        "exitCode": 0,
    }


def make(request: Request, root: bool = False) -> tuple[Response, str | None]:
    """One issue: a task, or a poured root, an Epic labelled root; and the key
    Jira answered for it, which an issue Jira made and could not be read back
    keeps, so that a failure still names what is in Jira."""
    if config() is None:
        return dict(NOT_CONFIGURED), None
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE), None
    priority = 2 if request.get("priority") is None else int(request["priority"])
    fields = {
        "project": {"key": project},
        "summary": request["title"],
        "issuetype": {"name": "Epic" if root else "Task"},
        "priority": {"name": PRIORITIES[min(max(priority, 0), 4)]},
        "labels": ["root"] if root else [],
    }
    if request.get("parent"):
        fields["parent"] = {"key": request["parent"]}
    description = keep_verify_using(
        request.get("description"), list(request.get("verifyUsing") or [])
    )
    if description:
        fields["description"] = adf(description)
    try:
        made = call("POST", "/rest/api/3/issue", {"fields": fields})
    except JiraError as e:
        if request.get("parent") and e.status in (400, 404) and fetch(request["parent"]) is None:
            return {
                "status": "failed",
                "reason": "parent-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % request["parent"],
            }, None
        return failed(e), None
    key = made["key"]
    try:
        issue = held(key)
    except JiraError as e:
        out = failed(e)
        out["summary"] = "Jira made %s and could not read it back: %s" % (key, out["summary"])
        return out, key
    return {
        "status": "completed",
        "summary": "Created %s." % key,
        "item": record(issue),
        "exitCode": 0,
    }, key


def jira_create(request: Request) -> Response:
    return make(request)[0]


def reaches(start: str, target: str, seen: set[str] | None = None) -> bool:
    """Whether following needs from start arrives at target."""
    seen = seen if seen is not None else set()
    if start == target:
        return True
    if start in seen:
        return False
    seen.add(start)
    issue = fetch(start)
    return any(reaches(n, target, seen) for n in (record(issue)["needs"] if issue else []))


def jira_need(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    _, refused = opened(request.get("root"))
    if refused:
        return refused
    ident, needs = request["id"], request["needs"]
    try:
        for one in (ident, needs):
            if fetch(one) is None:
                return {
                    "status": "failed",
                    "reason": "item-not-found",
                    "exitCode": 1,
                    "summary": "%s names no issue here." % one,
                }
        if ident == needs or reaches(needs, ident):
            return {
                "status": "failed",
                "reason": "cycle",
                "exitCode": 1,
                "summary": "%s needing %s would close a cycle." % (ident, needs),
            }
        if needs not in record(held(ident))["needs"]:
            call(
                "POST",
                "/rest/api/3/issueLink",
                {
                    "type": {"name": "Blocks"},
                    "outwardIssue": {"key": needs},
                    "inwardIssue": {"key": ident},
                },
            )
    except JiraError as e:
        return failed(e, [("item-not-found", 404)])
    return {
        "status": "completed",
        "summary": "%s needs %s." % (ident, needs),
        "edge": {"id": ident, "needs": needs},
        "exitCode": 0,
    }


def jira_pour(request: Request) -> Response:
    steps = list(request.get("steps") or [])
    if not steps:
        return {
            "status": "failed",
            "reason": "no-steps",
            "exitCode": 1,
            "summary": "No steps to pour.",
        }
    seen: set[str] = set()
    for s in steps:
        if s["id"] in seen:
            # One id per step comes back, so two steps with one id pour nothing.
            return {
                "status": "failed",
                "reason": "duplicate-step",
                "exitCode": 1,
                "summary": "Two steps share the id %s, so nothing was poured." % s["id"],
            }
        seen.add(s["id"])
    try:
        ordered = in_order(steps)
    except LookupError as e:
        return {"status": "failed", "reason": "step-not-found", "exitCode": 1, "summary": str(e)}
    except ValueError as e:
        return {"status": "failed", "reason": "cycle", "exitCode": 1, "summary": str(e)}
    root = request.get("root")
    made, root_id = make(
        {
            "root": root,
            "title": request["title"],
            "description": request.get("description"),
            "verifyUsing": list(request.get("verifyUsing") or []),
        },
        root=True,
    )
    if made["status"] != "completed":
        if root_id is None:
            return made
        # Jira made the root: the pour names it, though it poured nothing.
        return {
            "status": "failed",
            "reason": "adapter-failed",
            "exitCode": 1,
            "rootId": root_id,
            "stepIds": [],
            "summary": "Poured 0 of %d steps under %s: %s" % (len(steps), root_id, made["summary"]),
        }
    ids: dict[str, str] = {}

    def cut_short(said: Response) -> Response:
        """A pour that fails after making its root names the root and the steps
        it made, so that what is in Jira can be found and put right."""
        done = [ids[x["id"]] for x in steps if x["id"] in ids]
        return {
            "status": "failed",
            "reason": "adapter-failed",
            "exitCode": 1,
            "rootId": root_id,
            "stepIds": done,
            "summary": "Poured %d of %d steps under %s%s, and the next failed: %s"
            % (
                len(done),
                len(steps),
                root_id,
                " (%s)" % ", ".join(done) if done else "",
                said["summary"],
            ),
        }

    for s in ordered:
        step, key = make({"root": root, "title": s["title"], "parent": root_id})
        if key is not None:
            ids[s["id"]] = key
        if step["status"] != "completed":
            return cut_short(step)
        for n in s.get("needs") or []:
            edge = jira_need({"root": root, "id": ids[s["id"]], "needs": ids[n]})
            if edge["status"] != "completed":
                return cut_short(edge)
    return {
        "status": "completed",
        "summary": "Poured %d steps under %s." % (len(ids), root_id),
        "rootId": root_id,
        "stepIds": [ids[s["id"]] for s in steps],
        "exitCode": 0,
    }


def blockers(project: str, key: str, item: Record) -> list[str]:
    """Open needs, then open children, of an issue."""
    open_needs = []
    for n in item["needs"]:
        issue = fetch(n)
        if issue is None or record(issue)["status"] != "closed":
            open_needs.append(n)
    children = [
        record(i)
        for i in search("project = %s AND parent = %s ORDER BY created ASC" % (project, key))
    ]
    return open_needs + [
        c["id"] for c in children if c["status"] != "closed" and c["id"] not in open_needs
    ]


def close_one(key: str, reason: str | None) -> bool:
    """Done, read back, and only then the reason: False when the workflow has
    no way there or Jira does not say the issue is closed, and nothing is
    written on it."""
    if not transition_to(key, "done") or record(held(key))["status"] != "closed":
        return False
    if reason:
        call("POST", "/rest/api/3/issue/%s/comment" % key, {"body": adf("closed: %s" % reason)})
    return True


def jira_close(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    key = request["id"]
    try:
        issue = fetch(key)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        item = record(issue)
        if item["status"] == "closed":
            return {
                "status": "completed",
                "summary": "%s was closed already." % key,
                "item": item,
                "closedIds": [],
                "exitCode": 0,
            }
        blocked = blockers(project, key, item)
        if blocked:
            return {
                "status": "blocked",
                "reason": "blocked",
                "blockedBy": blocked,
                "exitCode": 1,
                "summary": "%s is blocked by %s." % (key, ", ".join(blocked)),
            }
        if not close_one(key, request.get("closeReason")):
            return {
                "status": "failed",
                "exitCode": 1,
                "summary": "%s has no transition to done in its workflow; it stays %s."
                % (key, item["status"]),
            }
        closed = [key]
        parent = item.get("parent")
        if parent:
            above = fetch(parent)
            if above is not None:
                root = record(above)
                if (
                    root["kind"] == "root"
                    and root["status"] != "closed"
                    and not blockers(project, parent, root)
                    and close_one(parent, "every step closed")
                ):
                    closed.append(parent)
        item = record(held(key))
    except JiraError as e:
        return failed(e, [("item-not-found", 404)])
    return {
        "status": "completed",
        "summary": "Closed %s." % ", ".join(closed),
        "item": item,
        "closedIds": closed,
        "exitCode": 0,
    }


def jira_show(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    key = request["id"]
    try:
        issue = fetch(key)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        children = [
            record(i)
            for i in search("project = %s AND parent = %s ORDER BY created ASC" % (project, key))
        ]
    except JiraError as e:
        return failed(e, [("item-not-found", 404)])
    return {
        "status": "completed",
        "summary": "Showed %s." % key,
        "item": record(issue),
        "children": children,
        "exitCode": 0,
    }


def jira_list(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    jql = "project = %s" % project
    if request.get("parent"):
        jql += " AND parent = %s" % request["parent"]
    jql += " ORDER BY created ASC"
    try:
        items = [record(i) for i in search(jql)]
    except JiraError as e:
        return failed(e)
    if request.get("scope") != "all":
        items = [i for i in items if i["status"] != "closed"]
    items.sort(key=lambda i: (i["status"] == "closed", i["createdAt"] or "", i["id"]))
    if request.get("limit"):
        items = items[: int(request["limit"])]
    return {
        "status": "completed",
        "summary": "%d items." % len(items),
        "items": items,
        "exitCode": 0,
    }


def jira_update(request: Request) -> Response:
    if request.get("status") == "closed":
        return {
            "status": "failed",
            "reason": "close-through-update",
            "exitCode": 1,
            "summary": "Closing is close-item's, with a reason.",
        }
    if request.get("status") is not None and request["status"] not in (
        "open",
        "in_progress",
        "blocked",
    ):
        return {
            "status": "failed",
            "reason": "bad-status",
            "exitCode": 1,
            "summary": "%s is not a status here." % request["status"],
        }
    if config() is None:
        return dict(NOT_CONFIGURED)
    _, refused = opened(request.get("root"))
    if refused:
        return refused
    key = request["id"]
    try:
        issue = fetch(key)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        if request.get("parent") and fetch(request["parent"]) is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % request["parent"],
            }
        # The move first: a workflow with no way there leaves the rest untouched.
        wanted = request.get("status")
        category = {"open": "new", "blocked": "new", "in_progress": "indeterminate"}.get(
            wanted or ""
        )
        if category and not move_to(key, issue, category):
            return {
                "status": "failed",
                "reason": "bad-status",
                "exitCode": 1,
                "summary": "%s has no transition to %s in its workflow." % (key, wanted),
            }
        fields = {}
        if request.get("title") is not None:
            fields["summary"] = request["title"]
        if request.get("priority") is not None:
            fields["priority"] = {"name": PRIORITIES[min(max(int(request["priority"]), 0), 4)]}
        if request.get("parent"):
            fields["parent"] = {"key": request["parent"]}
        labels = list((issue.get("fields") or {}).get("labels") or [])
        if request.get("status") is not None:
            labels = [label for label in labels if label != "blocked"]
            if request["status"] == "blocked":
                labels.append("blocked")
            fields["labels"] = labels
        if fields:
            call("PUT", "/rest/api/3/issue/%s" % key, {"fields": fields})
        if request.get("assignee"):
            who = myself().get("accountId") if request["assignee"] == "me" else request["assignee"]
            try:
                call("PUT", "/rest/api/3/issue/%s/assignee" % key, {"accountId": who})
            except JiraError as e:
                return failed(e, [("assignee-not-found", 400), ("assignee-not-found", 404)])
        item = record(held(key))
        if wanted and item["status"] != wanted:
            return {
                "status": "failed",
                "reason": "bad-status",
                "exitCode": 1,
                "summary": "%s stayed %s, not %s." % (key, item["status"], wanted),
            }
    except JiraError as e:
        return failed(e, [("item-not-found", 404)])
    return {"status": "completed", "summary": "Updated %s." % key, "item": item, "exitCode": 0}


def jira_ready(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    try:
        items = [record(i) for i in search("project = %s ORDER BY created ASC" % project)]
    except JiraError as e:
        return failed(e)
    status = {i["id"]: i["status"] for i in items}
    ready = [
        i
        for i in items
        if i["status"] == "open" and not any(status.get(n, "open") != "closed" for n in i["needs"])
    ]
    return {
        "status": "completed",
        "summary": "%d ready." % len(ready),
        "items": ready,
        "exitCode": 0,
    }


TRACKER = {
    "info": {
        "name": "jira",
        "version": VERSION,
        "interface": 3,
        "origin": "loaded",
        "nativeNeeds": True,
        "checkTarget": os.environ.get("JIRA_CHECK_PROJECT"),
        "extras": [],
    },
    "operations": {
        "operation.open-tracker": jira_open,
        "operation.describe-tracker": jira_describe,
        "operation.create-item": jira_create,
        "operation.add-need": jira_need,
        "operation.pour-steps": jira_pour,
        "operation.close-item": jira_close,
        "operation.show-item": jira_show,
        "operation.list-items": jira_list,
        "operation.update-item": jira_update,
        "operation.ready-items": jira_ready,
    },
    "extras": {},
    "store": store,
}
