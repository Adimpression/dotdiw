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
import datetime
import fcntl
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from typing import Any

Request = dict[str, Any]
Response = dict[str, Any]
Record = dict[str, Any]

VERSION = "0.1"
STORE = "jira.json"
PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")
CATEGORIES = {"new": "open", "indeterminate": "in_progress", "done": "closed"}
# Jira's search is without a write for a while after it -- seconds as a rule,
# minutes at the most it says -- while a read by key holds it at once. So what
# is written through here is kept, by key, for RECENT_SECONDS, in one file for
# every checkout under the dotdiw home, and read by its key wherever a search
# decides what may close or what a listing of every issue holds.
RECENT = "jira-written.log"
RECENT_SECONDS = 600.0

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
    # One site however it is spelled: its scheme and host read in any case,
    # and its port left out where it is the one its scheme takes, so that
    # where the checkout's items are (storeId) and what was written there of
    # late name it alike.
    # The port a scheme takes by default is the same site spelled without it.
    parts = urllib.parse.urlsplit(site.rstrip("/"))
    scheme, netloc = parts.scheme.lower(), parts.netloc.lower()
    default = {"https": ":443", "http": ":80"}.get(scheme)
    if default and netloc.endswith(default):
        netloc = netloc[: -len(default)]
    site = urllib.parse.urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))
    return site, email, token


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


def of(key: str, *more: str) -> str:
    """The path of an issue, or of what it holds, each part quoted, so that
    whatever a key handed in holds -- a space, a slash, a question mark --
    is that one part of the path and never more of the request."""
    parts = "".join("/" + urllib.parse.quote(part, safe="") for part in (key,) + more)
    return "/rest/api/3/issue" + parts


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


LISTS = ("bulletList", "orderedList", "taskList", "decisionList")


def plain(doc: Any) -> str:
    """A document's text, as adf() is given it: what one adf() wrote reads
    back as written, and one Jira's editor wrote reads with its paragraphs
    apart, its line breaks kept, and each item of a list -- an action item
    or a decision among them -- on a line of its own, after the line before
    it, so that a section of means, a heading and a list under it, reads as
    one; a list within an item reads indented under it, as no more of the
    list it is in, and an ordered one numbered from where it starts. What
    the editor keeps as a node of its own reads as its text: a link card as
    its address, a mention, an emoji or a status as it shows, a date as the
    day; an expand as its title, then what it holds. An empty paragraph
    holds no text."""
    if isinstance(doc, str):
        return doc

    def attrs(node: dict[str, Any]) -> dict[str, Any]:
        given = node.get("attrs")
        return given if isinstance(given, dict) else {}

    def day(stamp: Any) -> str:
        try:
            when = datetime.datetime.fromtimestamp(int(str(stamp)) / 1000, datetime.UTC)
        except (TypeError, ValueError, OverflowError, OSError):
            return ""
        return when.strftime("%Y-%m-%d")

    def inline(node: dict[str, Any]) -> str:
        out = []
        for leaf in node.get("content") or []:
            if not isinstance(leaf, dict):
                continue
            kind = leaf.get("type")
            if kind == "text":
                out.append(leaf.get("text") or "")
            elif kind == "hardBreak":
                out.append("\n")
            elif kind in ("inlineCard", "blockCard", "embedCard"):
                out.append(str(attrs(leaf).get("url") or ""))
            elif kind in ("mention", "emoji", "status", "placeholder"):
                out.append(str(attrs(leaf).get("text") or attrs(leaf).get("shortName") or ""))
            elif kind == "date":
                out.append(day(attrs(leaf).get("timestamp")))
            elif leaf.get("content"):
                out.append(inline(leaf))
        return "".join(out)

    def listed(node: dict[str, Any], depth: int) -> list[str]:
        kind = node.get("type")
        order = attrs(node).get("order")
        first = order if isinstance(order, int) and not isinstance(order, bool) else 1
        lines: list[str] = []
        n = 0
        for entry in node.get("content") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") in LISTS:  # a list held straight in a list
                lines.extend(listed(entry, depth + 1))
                continue
            if kind == "orderedList":
                mark = "%d. " % (first + n)
            elif kind == "taskList":
                mark = "[x] " if attrs(entry).get("state") == "DONE" else "[ ] "
            elif kind == "decisionList":
                mark = "* "
            else:
                mark = "- "
            n += 1
            said: list[str] = []
            nested: list[str] = []
            if entry.get("type") in ("taskItem", "decisionItem"):
                said.append(inline(entry))  # what an action item holds is inline
            else:
                for child in entry.get("content") or []:
                    if isinstance(child, dict) and child.get("type") in LISTS:
                        nested.extend(listed(child, depth + 1))
                    elif isinstance(child, dict):
                        said.extend(text for _, text in blocks({"content": [child]}))
            lines.append("  " * depth + mark + "\n".join(said))
            lines.extend(nested)
        return lines

    def blocks(node: dict[str, Any]) -> list[tuple[bool, str]]:
        out: list[tuple[bool, str]] = []
        for child in node.get("content") or []:
            if not isinstance(child, dict):
                continue
            kind = child.get("type")
            if kind in LISTS:
                lines = listed(child, 0)
                if lines:
                    out.append((True, "\n".join(lines)))
            elif kind in ("paragraph", "heading", "codeBlock"):
                said = inline(child)
                if said:
                    out.append((False, said))
            elif kind == "text":
                out.append((False, child.get("text") or ""))
            elif kind in ("blockCard", "embedCard"):
                if attrs(child).get("url"):
                    out.append((False, str(attrs(child)["url"])))
            elif kind in ("expand", "nestedExpand"):
                if attrs(child).get("title"):
                    out.append((False, str(attrs(child)["title"])))
                out.extend(blocks(child))
            elif child.get("content"):
                out.extend(blocks(child))
        return out

    said = ""
    for n, (listed_here, text) in enumerate(blocks(doc or {})):
        said += ("" if n == 0 else "\n" if listed_here else "\n\n") + text
    return said


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


# The issue property dotdiw keeps a poured step's id, its claim and its run
# in, and the prefix of the properties that keep a claim's values: one for
# each write, named for a moment after every write the issue held when it
# was written. Jira sets one property at a time, so a write is there whole or
# not at all, a writer of other labels keeps what it recorded, and the
# values are the writes read in the order of their names.
PROPERTY = "dotdiw"
WRITE = PROPERTY + ".write."
PROPERTY_HOLDS = 32000  # characters: Jira holds no more than 32768 in a property


def write_moment(key: str) -> int | None:
    """The moment a write property was written, in microseconds, from its
    name; None for any other property."""
    moment = key[len(WRITE) :].partition(".")[0] if key.startswith(WRITE) else ""
    return int(moment) if moment.isdigit() else None


def write_name(properties: dict[str, Any]) -> str:
    """A new write's property: named for now, or for just after the latest
    write the issue holds, should a clock be behind it."""
    moments = [m for m in (write_moment(k) for k in properties) if m is not None]
    moment = max([time.time_ns() // 1000] + [m + 1 for m in moments])
    return "%s%020d.%s" % (WRITE, moment, os.urandom(4).hex())


def written(properties: dict[str, Any]) -> list[dict[str, str]]:
    """A claim's values: the writes read in order, each label at the last
    text written for it, a label written empty removed, in the order each
    was first recorded. A write kept in more properties than one (group)
    is read whole once all its parts are there, where its last part is, and
    not at all while one is missing, as a write cut short leaves it; a text
    cut in pieces (more) is read joined."""
    names = sorted(k for k in properties if write_moment(k) is not None)
    there: dict[str, int] = {}
    for key in names:
        write = properties[key]
        if isinstance(write, dict) and isinstance(write.get("group"), str):
            there[write["group"]] = there.get(write["group"], 0) + 1
    held: dict[str, str] = {}
    gathered: dict[str, list[Any]] = {}
    for key in names:
        write = properties[key]
        if not isinstance(write, dict):
            continue
        values = [v for v in write.get("values") or [] if isinstance(v, dict)]
        group = write.get("group")
        if isinstance(group, str):
            parts = write.get("of")
            if not isinstance(parts, int) or there.get(group, 0) < parts:
                continue  # a part is missing: none of it
            gathered.setdefault(group, []).extend(values)
            if write.get("part") != parts - 1:
                continue  # read where its last part is
            values = gathered.pop(group)
        piece = ""
        for v in values:
            if not isinstance(v.get("text"), str):
                continue
            if v.get("more"):
                piece += v["text"]
                continue
            text, piece = piece + v["text"], ""
            if text:
                held[str(v.get("label"))] = text
            else:
                held.pop(str(v.get("label")), None)
    return [{"label": label, "text": text} for label, text in held.items()]


def in_writes(values: list[Any]) -> list[list[dict[str, Any]]]:
    """The values in as few writes as properties hold them, in the order
    given: each value whole where one property holds it, a longer one's text
    cut in pieces, each but the last marked as followed by more."""
    room = PROPERTY_HOLDS - 200  # what a write's group, part and count take
    pieces: list[dict[str, Any]] = []
    for value in values:
        v = dict(value)
        if len(json.dumps(v)) <= room:
            pieces.append(v)
            continue
        text, label = str(v.get("text") or ""), v.get("label")
        start = 0
        while start < len(text):
            size = room - len(json.dumps({"label": label, "text": "", "more": True}))
            while size > 1 and len(json.dumps(text[start : start + size])) > room - 100:
                size //= 2
            pieces.append({"label": label, "text": text[start : start + size], "more": True})
            start += size
        pieces[-1].pop("more", None)
    writes: list[list[dict[str, Any]]] = []
    for piece in pieces:
        if writes and len(json.dumps({"values": writes[-1] + [piece]})) <= room:
            writes[-1].append(piece)
        else:
            writes.append([piece])
    return writes


def keep_values(key: str, values: list[Any], properties: dict[str, Any]) -> None:
    """The values written on the issue, after every write it holds
    (properties): in one property where they fit, or in as few as hold
    them, one group, so that the write is read whole or not at all."""
    writes = in_writes(values)
    group = os.urandom(8).hex() if len(writes) > 1 else None
    for n, part in enumerate(writes):
        name = write_name(properties)
        properties[name] = None
        body: dict[str, Any] = {"values": part}
        if group is not None:
            body.update(group=group, part=n, of=len(writes))
        call("PUT", of(key, "properties", name), body)


FIELDS = (
    "summary,status,issuetype,parent,labels,priority,issuelinks,created,updated,comment,assignee,"
    "description,project,statuscategorychangedate"
)


def moment(value: Any) -> datetime.datetime | None:
    """A time as Jira writes one, or None."""
    if not isinstance(value, str):
        return None
    for shape in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(value, shape)
        except ValueError:
            continue
    return None


def record(issue: dict[str, Any]) -> Record:
    """An issue as the interface's record."""
    f = issue.get("fields") or {}
    labels = f.get("labels") or []
    own = (issue.get("properties") or {}).get(PROPERTY) or {}
    kind = "guard" if own.get("kind") == "guard" else "root" if "root" in labels else "task"
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
    # The reason of the latest close: one written since the issue last came
    # to be done, where Jira says when that was, and none where it wrote none
    # since -- an earlier close's is not this one's.
    reason = None
    since = moment(f.get("statuscategorychangedate"))
    for comment in (f.get("comment") or {}).get("comments") or []:
        text = plain(comment.get("body"))
        made = moment(comment.get("created"))
        if since is not None and made is not None and made < since:
            continue
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
    if isinstance(own.get("step"), str):
        out["step"] = own["step"]
    if isinstance(own.get("claim"), dict):
        out["claim"] = own["claim"]
    for name in ("run", "within", "calls", "guard"):
        if isinstance(own.get(name), str):
            out[name] = own[name]
    if own.get("whole") is True:
        out["whole"] = True
    values = written(issue.get("properties") or {})
    if values:
        out["values"] = values
    return out


def full(issue: dict[str, Any], project: str) -> dict[str, Any] | None:
    """An issue a search found, read again with every property of its own
    where it was poured for a step or holds values -- its own property says
    so -- so that its values come with it: a search answers only the
    properties it names; None where it is the project's no more."""
    own = (issue.get("properties") or {}).get(PROPERTY) or {}
    if issue.get("whole") or not (own.get("step") or own.get("values")):
        return issue
    return fetch_here(issue["key"], project)  # None where it is the project's no more


def as_they_stand(
    root: str | None, project: str, found: list[dict[str, Any]], under: str | None = None
) -> list[dict[str, Any]]:
    """The project's issues a search found, as they stand: each written of
    late through this dotdiw home read by its key in place of what the
    search has of it, and left out where it is the project's no more, or no
    longer under the issue the search was of (under); and those written of
    late that the search is still without, read by key as well. Each so
    read is whole, every property of its own with it."""
    lately_written = written_lately(root)
    out = []
    for issue in found:
        if issue["key"] in lately_written:
            fresh = fetch_here(issue["key"], project)
            if fresh is None or (under and record(fresh).get("parent") != under):
                continue
            issue = dict(fresh, whole=True)
        out.append(issue)
    have = {i["key"] for i in found}
    for key, above in lately_written.items():
        if key in have or (under and under not in above):
            continue
        if not key.upper().startswith(project.upper() + "-"):
            continue  # another project's key: none of this one's, unread
        fresh = fetch_here(key, project)
        if fresh is not None and not (under and record(fresh).get("parent") != under):
            out.append(dict(fresh, whole=True))
    return out


def text(value: str) -> str:
    """A value as JQL reads one: quoted, a quote or backslash within it
    escaped, so that whatever it holds -- a key handed in by a caller --
    is that one value, never more of the query."""
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def search(jql: str) -> list[dict[str, Any]]:
    """Every issue the JQL names, in pages. A page that holds no list of
    issues fails the search: it says nothing of the issues it leaves out, and
    those would be taken for not there -- an open step, for one, under a root
    about to close."""
    out: list[dict[str, Any]] = []
    token = None
    while True:
        query = {"jql": jql, "maxResults": 100, "fields": FIELDS, "properties": PROPERTY}
        if token:
            query["nextPageToken"] = token
        page = call("GET", "/rest/api/3/search/jql", query=query)
        issues = page.get("issues") if isinstance(page, dict) else None
        if not isinstance(issues, list):
            raise JiraError(200, "a search page that holds no list of issues")
        out.extend(issues)
        token = page.get("nextPageToken")
        if not token or page.get("isLast"):
            return out


def fetch(key: str) -> dict[str, Any] | None:
    try:
        issue: dict[str, Any] = call("GET", of(key), query={"fields": FIELDS, "properties": "*all"})
        return issue
    except JiraError as e:
        if e.status == 404:
            return None
        raise


def lately(root: str | None) -> str | None:
    """The file of what was written of late, beside the modules under the
    dotdiw home this checkout's workspace is in; None without a workspace."""
    ws = workspace(root) if root else None
    return os.path.join(os.path.dirname(ws), "trackers", RECENT) if ws else None


def entries(lines: Any) -> list[dict[str, Any]]:
    """The writes a file of them holds, a line cut short or not one left out."""
    out = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)):
            out.append(entry)
    return out


def wrote(root: str | None, key: str, *above: str | None) -> None:
    """Keep that the issue is written now, with the issues it stands under
    and in the run of once written, and forget what was written longer ago
    than a search may be without. Kept before a write of an issue there, and
    once a new one has its key; a file that cannot be written keeps nothing,
    and a search is then all that is known of the write."""
    cfg, path = config(), lately(root)
    if cfg is None or path is None:
        return
    now = time.time()
    entry = {"site": cfg[0], "key": key, "above": sorted({a for a in above if a}), "at": now}
    # Written whole to a file beside it and put in its place, under a lock of
    # its own: a write cut short -- a full disk, a stop -- loses at most its
    # own entry, never the others.
    temporary = "%s.%d.tmp" % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".lock", "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                with open(path, encoding="utf-8") as fh:
                    kept = [e for e in entries(fh) if e["at"] > now - RECENT_SECONDS]
            except FileNotFoundError:
                kept = []
            try:
                with open(temporary, "w", encoding="utf-8") as fh:
                    fh.write("".join(json.dumps(e) + "\n" for e in kept + [entry]))
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    except OSError:
        pass


def written_lately(root: str | None) -> dict[str, set[str]]:
    """Each issue written through this dotdiw home on this site within
    RECENT_SECONDS, the latest first, with every issue it stood under or in
    the run of when written."""
    cfg, path = config(), lately(root)
    if cfg is None or path is None:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            held = entries(fh)  # whole, as each write puts a whole file in its place
    except OSError:
        return {}
    out: dict[str, set[str]] = {}
    for e in reversed(held):
        if e.get("site") == cfg[0] and e["at"] > time.time() - RECENT_SECONDS:
            out.setdefault(str(e.get("key")), set()).update(e.get("above") or [])
    return out


def fetch_here(key: str, project: str) -> dict[str, Any] | None:
    """The issue under the key where it is one of the project's: a checkout's
    store is its project, and an issue of another, on the same site, is none
    of this checkout's to read or write -- nor does anything this checkout
    holds of a move hold it."""
    issue = fetch(key)
    if issue is None or ((issue.get("fields") or {}).get("project") or {}).get("key") != project:
        return None
    return issue


def held(key: str) -> dict[str, Any]:
    """The issue that must be there: its absence is Jira's 404, raised."""
    issue = fetch(key)
    if issue is None:
        raise JiraError(404, "%s names no issue" % key)
    return issue


def way_to(key: str, category: str) -> str | None:
    """The first transition the issue's workflow offers whose target is in
    the category, or None: asked, nothing written."""
    answer = call("GET", of(key, "transitions"))
    for t in answer.get("transitions") or []:
        if (((t.get("to") or {}).get("statusCategory") or {}).get("key")) == category:
            return str(t["id"])
    return None


def transition_to(key: str, category: str) -> bool:
    """Move an issue to the first transition whose target is in the category."""
    way = way_to(key, category)
    if way is None:
        return False
    call("POST", of(key, "transitions"), {"transition": {"id": way}})
    return True


def move_to(key: str, issue: dict[str, Any], category: str) -> bool:
    """The issue in the status category, moved only if it is not there already,
    since a workflow offers no transition from a status to itself; False when
    it offers none that reaches the category."""
    status = (issue.get("fields") or {}).get("status") or {}
    if (status.get("statusCategory") or {}).get("key") == category:
        return True
    return transition_to(key, category)


def in_order(steps: list[Any]) -> list[Any]:
    """The steps each after those it needs and the calling step it stands
    within, otherwise as declared; steps are named by key where they have
    one, and steps under keys keep the order given where it is one. A need
    naming no step raises LookupError, and a cycle ValueError."""

    def name(s: Any) -> str:
        return str(s.get("key") or s["id"])

    def waits(s: Any) -> list[str]:
        return [str(n) for n in s.get("needs") or []] + (
            [str(s["within"])] if s.get("within") else []
        )

    known = {name(s) for s in steps}
    for s in steps:
        for need in waits(s):
            if need not in known:
                raise LookupError("%s needs %s, which is not a step." % (name(s), need))
    if any(s.get("key") for s in steps):
        seen: set[str] = set()
        for s in steps:
            if not all(n in seen for n in waits(s)):
                break
            seen.add(name(s))
        else:
            return list(steps)
    order: list[Any] = []
    placed: set[str] = set()
    left = list(steps)
    while left:
        ready = [s for s in left if all(n in placed for n in waits(s))]
        if not ready:
            raise ValueError("A cycle among the steps: %s." % ", ".join(name(s) for s in left))
        order.extend(ready)
        placed.update(name(s) for s in ready)
        left = [s for s in left if name(s) not in placed]
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
        call("GET", "/rest/api/3/project/%s" % urllib.parse.quote(project, safe=""))
    except JiraError as e:
        return failed(e, [("no-workspace", 404)])
    # Written whole beside it and put in its place, and only where it
    # changes: a reader at that moment finds the project, never an empty
    # file it would read as no project at all.
    if created or project_of(root) != project:
        temporary = "%s.%d.tmp" % (path, os.getpid())
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump({"project": project}, fh)
                fh.write("\n")
            os.replace(temporary, path)
        except OSError as e:
            if os.path.exists(temporary):
                os.unlink(temporary)
            return {
                "status": "failed",
                "reason": "store-unwritable",
                "exitCode": 1,
                "summary": str(e),
            }
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
    project = project_of(request.get("root"))
    return {
        "status": "completed",
        "summary": "Jira Cloud, through its REST API.",
        # Where this checkout's issues are: the site and the project, which
        # two checkouts name alike only when they reach the same issues.
        "storeId": "%s/projects/%s" % (cfg[0], project) if cfg is not None and project else None,
        "info": {
            "name": "jira",
            "version": version,
            "origin": "loaded",
            "nativeNeeds": True,
            "nests": True,
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
    wrote(request.get("root"), key, request.get("parent"), request.get("run"))
    kept: dict[str, Any] = {
        k: request[k] for k in ("step", "claim", "run", "within", "calls") if request.get(k)
    }
    values = list(request.get("values") or [])
    if values:
        kept["values"] = True  # so that a search's issue is read again whole (full)
    if kept or values:
        try:
            if kept:
                call("PUT", of(key, "properties", PROPERTY), kept)
            if values:
                keep_values(key, values, {})
        except JiraError as e:
            out = failed(e)
            out["summary"] = "Jira made %s and could not keep its claim: %s" % (key, out["summary"])
            return out, key
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
    """create-item: one issue, under its parent and in its run where they are
    issues of the checkout's project, and nothing made where either is not:
    a parent or a run root of another project is none this checkout reaches,
    and its close would not see the issue stand open under it. A create that
    fails once Jira made the issue names it (madeId), so that a move holds it
    as made and finishes it, rather than make a second."""
    run_root: dict[str, Any] | None = None
    if config() is not None and (
        request.get("parent") or request.get("run") or request.get("within")
    ):
        project, refused = opened(request.get("root"))
        if refused or not project:
            return refused or dict(NO_WORKSPACE)
        try:
            for field in ("parent", "run", "within"):
                above = fetch_here(request[field], project) if request.get(field) else None
                if request.get(field) and above is None:
                    return {
                        "status": "failed",
                        "reason": "parent-not-found",
                        "exitCode": 1,
                        "summary": "%s names no issue here." % request[field],
                    }
                if above is not None:
                    request = dict(request, **{field: above["key"]})
                if field == "run":
                    run_root = above
        except JiraError as e:
            return failed(e)
    out, key = make(request)
    if out["status"] == "completed" and key is not None and request.get("within"):
        # The calling step needs what is poured within it; the issue is read
        # back with that need, and a failure of either still names it made.
        edge = linked_to({"root": request.get("root"), "id": request["within"], "needs": key}, True)
        if edge["status"] != "completed":
            out = dict(
                edge, summary="Jira made %s and could not link it: %s" % (key, edge["summary"])
            )
        else:
            try:
                out = dict(out, item=record(held(key)))
            except JiraError as e:
                said = failed(e)
                out = dict(
                    said,
                    summary="Jira made %s and could not read it back: %s" % (key, said["summary"]),
                )
    if out["status"] != "completed" and key is not None:
        out = dict(out, madeId=key)
    if out["status"] == "completed" and run_root is not None:
        # The root of the run said to be one in its own property, so that a
        # cycle check reads the run's issues where it reaches it, and only
        # there: written where Jira takes it, the issue made either way.
        own = (run_root.get("properties") or {}).get(PROPERTY) or {}
        if not own.get("runRoot"):
            try:
                call("PUT", of(run_root["key"], "properties", PROPERTY), dict(own, runRoot=True))
            except JiraError:
                pass
    return out


def reaches(
    root: str | None,
    project: str,
    start: str,
    target: str,
    dropped: Iterable[str] = (),
) -> bool:
    """Whether start waits on target before it can close, to any depth: its
    needs, its children and the issues poured in its run, as local_waiting
    has them, and as blockers() holds a close to them. Each issue reached is
    read by its key, as it stands; its children are searched for on the
    site, in whichever project Jira holds them, with what was written under
    it of late through this home (as_they_stand), and without what was
    written of late that its lookup shows under it no more -- moved from
    under it a moment ago, as the search does not yet know, which
    blockers() holds no close to either; and the issues poured in
    the run of a root reached -- a poured root, or one its own property
    says a run's -- are the project's whose run it is, read in one search,
    since JQL reaches no run: once, and only where such a root is reached.
    Needs of start given as dropped are not followed: an update that takes
    them off checks what the issue will wait on."""
    left_off = {str(n).upper() for n in dropped}
    lately = written_lately(root)
    whole: list[dict[str, Any]] | None = None
    seen: set[str] = set()
    # Each issue to read, with the one it was found under or in the run of
    # by a search (via), None for a need: a need is read from a lookup.
    todo: list[tuple[str, str | None]] = [(start, None)]
    while todo:
        key, via = todo.pop()
        unsure = via is not None and key in lately  # a search's, of an issue written of late
        if key == target and not unsure:
            return True
        if key in seen:
            continue
        fetched = fetch(key)
        now = record(fetched) if fetched is not None else None
        if (
            unsure
            and now is not None
            and via
            not in (
                now.get("parent"),
                now.get("run"),
                now.get("within"),
            )
        ):
            continue  # under it no more, as blockers() reads it
        if key == target:
            return True
        seen.add(key)
        if fetched is None or now is None:
            continue
        key = now["id"]  # as Jira gives it
        if key == target:
            return True
        needs = [n for n in now["needs"] if key != start or n.upper() not in left_off]
        needs += [now["guard"]] if now.get("guard") else []
        children = {i["key"] for i in search("parent = %s" % text(key))} | {
            i["key"] for i in as_they_stand(root, project, [], key)
        }
        poured: set[str] = set()
        own = (fetched.get("properties") or {}).get(PROPERTY) or {}
        if now["kind"] == "root" or own.get("runRoot"):
            if whole is None:
                whole = as_they_stand(root, project, search("project = %s" % text(project)))
            poured = {
                i["key"]
                for i in whole
                if ((i.get("properties") or {}).get(PROPERTY) or {}).get("run") == key
            }
        if now.get("calls"):
            if whole is None:
                whole = as_they_stand(root, project, search("project = %s" % text(project)))
            poured |= {
                i["key"]
                for i in whole
                if ((i.get("properties") or {}).get(PROPERTY) or {}).get("within") == key
            }
        todo.extend([(n, None) for n in needs] + [(c, key) for c in sorted(children | poured)])
    return False


def jira_need(request: Request) -> Response:
    """add-need: the issue waits on the one it needs, a Blocks link, where
    that closes no cycle."""
    return linked_to(request, fresh=False)


def linked_to(request: Request, fresh: bool) -> Response:
    """The need written, a Blocks link, where it closes no cycle -- unasked
    where both are steps a pour has just made (fresh), whose needs it read
    whole for a cycle before it made any."""
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    try:
        ends = []
        for one in (request["id"], request["needs"]):
            issue = fetch_here(one, project)
            if issue is None:
                return {
                    "status": "failed",
                    "reason": "item-not-found",
                    "exitCode": 1,
                    "summary": "%s names no issue here." % one,
                }
            ends.append(str(issue["key"]))
        ident, needs = ends
        if ident == needs or (not fresh and reaches(request.get("root"), project, needs, ident)):
            return {
                "status": "failed",
                "reason": "cycle",
                "exitCode": 1,
                "summary": "%s needing %s would close a cycle." % (ident, needs),
            }
        waiting = record(held(ident))
        if needs not in waiting["needs"]:
            # Kept as written of late, so that a cycle check made at once
            # reads the issue by its key, as a search may be without it.
            wrote(request.get("root"), ident, waiting.get("parent"), waiting.get("run"))
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
        named = str(s.get("key") or s["id"])
        if named in seen:
            # One id per step comes back, so two steps with one id pour nothing.
            return {
                "status": "failed",
                "reason": "duplicate-step",
                "exitCode": 1,
                "summary": "Two steps share the id %s, so nothing was poured." % named,
            }
        seen.add(named)
    try:
        ordered = in_order(steps)
    except LookupError as e:
        return {"status": "failed", "reason": "step-not-found", "exitCode": 1, "summary": str(e)}
    except ValueError as e:
        return {"status": "failed", "reason": "cycle", "exitCode": 1, "summary": str(e)}
    root = request.get("root")
    if any(s.get("within") or s.get("calls") for s in steps):
        return pour_guarded(request, steps, ordered)
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
        step, key = make(
            {
                "root": root,
                "title": s["title"],
                "parent": root_id,
                "step": s["id"],
                "claim": s.get("claim"),
                "run": root_id,
            }
        )
        if key is not None:
            ids[s["id"]] = key
        if step["status"] != "completed":
            return cut_short(step)
        for n in s.get("needs") or []:
            edge = linked_to({"root": root, "id": ids[s["id"]], "needs": ids[n]}, fresh=True)
            if edge["status"] != "completed":
                return cut_short(edge)
    return {
        "status": "completed",
        "summary": "Poured %d steps under %s." % (len(ids), root_id),
        "rootId": root_id,
        "stepIds": [ids[s["id"]] for s in steps],
        "exitCode": 0,
    }


def made_at_once(checkout: str | None, fields: dict[str, Any], own: dict[str, Any]) -> str:
    """One issue made by one write: its fields and the adapter's property
    together in the create, so that what holds it -- the guard it names --
    holds it from the moment Jira has made it; its key. Jira takes no more
    than one link in a create, so a need is written after it, by itself."""
    body: dict[str, Any] = {"fields": fields, "properties": [{"key": PROPERTY, "value": own}]}
    above = [own.get("run"), own.get("within")] + [(fields.get("parent") or {}).get("key")]
    made = call("POST", "/rest/api/3/issue", body)
    key = str(made["key"])
    wrote(checkout, key, *above)
    return key


# What the core says of these, as an adapter of its own says it.
GUARD_HELD = (
    "%s is a pour's guard: only the pour that made it closes it, and nothing else writes it."
)
CALL_NEED_HELD = (
    "%s needs %s, which was poured within it: a calling step needs every item of its "
    "call, and that need is not taken off."
)


class LinkRefused(Exception):
    """A need a guarded pour asked for and did not get, in Jira's words."""


def pour_guarded(request: Request, steps: list[Any], ordered: list[Any]) -> Response:
    """A pour of steps that call a formula, which Jira cannot write at once,
    held on a guard until it is whole, one write at a time:

    1. the guard: a task labelled blocked, under no parent -- outside the
       root's epic -- its property saying it is a guard;
    2. the root, an Epic labelled root, its property naming the guard;
    3. the guard's property given the root's run;
    4. each step, in the order given, under the root, made by one create
       with its property -- its step, its claim, its run, the calling step
       it stands within, and, for a calling step, the formula it calls and
       the guard -- and then, a Blocks link each, as add-need writes one,
       its needs and its calling step's need of it, since Jira takes no
       more than one link in a create;
    5. the guard closed, by its transition alone.

    Stopped after any of them, nothing it made can complete: the root and
    every calling step name the guard from the create that made each, a
    close of one is refused while its guard stands open (blockers), a
    guard's close is refused, and nothing closes one in the wake of another
    close; and nothing of the pour is given ready while the guard stands
    open (jira_ready), so a step made before its needs are linked is no
    work yet. A pour that fails part of the way names the guard, the root
    and the steps it made, in the order given."""
    checkout = request.get("root")
    project, refused = opened(checkout)
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    ref = request.get("formulaRef") or request["title"]
    guard: str | None = None
    root_id: str | None = None
    ids: dict[str, str] = {}

    def named(s: Any) -> str:
        return str(s.get("key") or s["id"])

    def task(title: str, labels: list[str], **more: Any) -> dict[str, Any]:
        fields = {
            "project": {"key": project},
            "summary": title,
            "issuetype": {"name": "Task"},
            "priority": {"name": PRIORITIES[2]},
            "labels": labels,
        }
        fields.update(more)
        return fields

    try:
        guard = made_at_once(checkout, task("Pour of %s" % ref, ["blocked"]), {"kind": "guard"})
        fields = task(request["title"], ["root"], issuetype={"name": "Epic"})
        described = keep_verify_using(
            request.get("description"), list(request.get("verifyUsing") or [])
        )
        if described:
            fields["description"] = adf(described)
        root_id = made_at_once(checkout, fields, {"guard": guard})
        call("PUT", of(guard, "properties", PROPERTY), {"kind": "guard", "run": root_id})
        wrote(checkout, guard, root_id)
        for s in ordered:
            own: dict[str, Any] = {"step": s["id"], "run": root_id}
            if s.get("claim"):
                own["claim"] = s["claim"]
            more: dict[str, Any] = {"parent": {"key": root_id}}
            if s.get("calls"):
                own["calls"] = s["calls"]
                own["guard"] = guard
                described = keep_verify_using(
                    s.get("description"), list(s.get("verifyUsing") or [])
                )
                if described:
                    more["description"] = adf(described)
            if s.get("within"):
                own["within"] = ids[str(s["within"])]
            made = made_at_once(checkout, task(s["title"], [], **more), own)
            ids[named(s)] = made
            # Each need, then the calling step's need of it, a link each: the
            # writes add-need makes.
            edges = [(made, ids[str(n)]) for n in s.get("needs") or []]
            if s.get("within"):
                edges.append((own["within"], made))
            for waiter, needed in edges:
                edge = linked_to({"root": checkout, "id": waiter, "needs": needed}, fresh=True)
                if edge["status"] != "completed":
                    raise LinkRefused(edge["summary"])
        # The root marked whole: so a guard Jira no longer holds -- deleted,
        # as old done issues are, once it closed -- holds nothing of the run.
        wrote(checkout, root_id)
        call("PUT", of(root_id, "properties", PROPERTY), {"guard": guard, "whole": True})
        # Closed by the transition alone: a reason is a comment, a write of
        # its own, which could fail once the guard was closed.
        if not close_one(guard, None):
            raise JiraError(0, "the guard %s has no transition to done" % guard)
    except (JiraError, LinkRefused) as e:
        said = failed(e)["summary"] if isinstance(e, JiraError) else str(e)
        done = [ids[named(x)] for x in steps if named(x) in ids]
        out: Response = {
            "status": "failed",
            "reason": "adapter-failed",
            "exitCode": 1,
            "stepIds": done,
            "summary": "Poured %d of %d steps%s%s, and the next write failed: %s"
            % (
                len(done),
                len(steps),
                " under %s" % root_id if root_id else ", no root made",
                " (%s)" % ", ".join(done) if done else "",
                said,
            ),
        }
        if root_id:
            out["rootId"] = root_id
        if guard:
            out["guardId"] = guard
        return out
    return {
        "status": "completed",
        "summary": "Poured %d steps under %s." % (len(ids), root_id),
        "rootId": root_id,
        "stepIds": [ids[named(s)] for s in steps],
        "exitCode": 0,
    }


def pours_held(every: dict[str, Record]) -> dict[str, dict[str, Any]]:
    """Each pour not known to be whole, by its guard, of every issue listed
    (by key), as dotdiw tells one: a guard is an issue that reads as one, or
    a key an issue names as its guard; its pour's roots are each namer's
    run, or the namer itself where it names none, and the guard's own run.
    A guard that stands open and reads as one holds its run whatever its
    roots read; otherwise a root that reads whole -- marked so once every
    issue and link was made -- holds nothing, and nor does a root no longer
    listed. With a root listed that does not read whole, the pour
    holds unless its guard reads closed: listed so, or read so by its key,
    which only then is read. One no lookup finds holds; one Jira would not
    answer holds, and what it said is kept (unread). What it holds: the
    guard, every namer, every issue of its roots' runs and the roots."""
    named: dict[str, list[str]] = {}
    for k, o in every.items():
        g = o.get("guard")
        if isinstance(g, str) and g:
            named.setdefault(g, []).append(k)
    out: dict[str, dict[str, Any]] = {}
    for g in sorted({k for k, o in every.items() if o["kind"] == "guard"} | set(named)):
        namers = sorted(named.get(g, []))
        listed = every.get(g)
        roots = {str(every[n].get("run") or n) for n in namers}
        if listed is not None and isinstance(listed.get("run"), str) and listed["run"]:
            roots.add(str(listed["run"]))
        standing = listed is not None and listed["kind"] == "guard" and listed["status"] != "closed"
        live = [r for r in roots if r in every and every[r].get("whole") is not True]
        if not live and not (standing and roots):
            continue
        unread: str | None = None
        if listed is not None:
            if listed["status"] == "closed":
                continue
        else:
            try:
                issue = fetch(g)
            except JiraError as e:
                issue, unread = None, str(failed(e)["summary"])
            if issue is not None and record(issue)["status"] == "closed":
                continue
        runs = [k for k, o in every.items() if k in roots or o.get("run") in roots]
        out[g] = {
            "guard": g,
            "roots": sorted(roots),
            "namers": namers,
            "holds": sorted({g, *namers, *runs}),
            "unread": unread,
        }
    return out


def whole_by_its_run(guard: Record) -> bool:
    """Whether a guard's pour is known to be whole: the root of the run the
    guard was given, read by its key -- never as a search has it, which may
    be without the root, or without its mark -- reads whole. A guard given
    no run yet stopped before its root could be known, and is not."""
    run = guard.get("run")
    if not isinstance(run, str) or not run:
        return False
    fetched = fetch(run)
    return fetched is not None and record(fetched).get("whole") is True


def guarded_still(guard: Record, namers: list[Record]) -> bool:
    """Whether the pour a guard holds is not known to be whole (pours_held),
    given the guard and the open issues that name it: some root of it --
    each namer's run, or the namer itself, and the guard's own run -- that
    is not read by its key as whole: no lookup reads it -- deleted, or not
    the token's to see, which Jira's 404 does not tell apart -- or it reads
    otherwise."""
    roots = {str(n.get("run") or n["id"]) for n in namers}
    if isinstance(guard.get("run"), str) and guard["run"]:
        roots.add(guard["run"])
    for k in sorted(roots):
        fetched = fetch(k)
        if fetched is None or record(fetched).get("whole") is not True:
            return True
    return False


def blockers(
    root: str | None,
    project: str,
    key: str,
    item: Record,
    first: bool = False,
    namers: list[Record] | None = None,
) -> list[str]:
    """Open needs, then open children, then the open issues poured in its run,
    wherever they stand, of an issue: its needs and its children in whichever
    project Jira holds them, as a site may link an issue to, and put one
    under, another project's; the issues poured in its run in its project,
    where alone a run is poured or made. What was written of late through
    this dotdiw home -- made under the issue or in its run, moved under it,
    closed or opened again -- is read by its key, as it stands, and not as
    a search has it, which may be without the write for a while: a child
    made a moment ago stands open under the issue though no search finds it
    yet, and one closed a moment ago is closed though a search has it open.
    One the search has open under it that no lookup reads -- deleted, or no
    longer the token's to see, which Jira's 404 does not tell apart -- holds
    the close as the search has it: what cannot be read is not taken for
    closed. Given first, one that stands open is answer enough, and the
    first found is all that is answered."""
    out = []
    for n in item["needs"]:
        issue = fetch(n)
        if (issue is None or record(issue)["status"] != "closed") and n not in out:
            out.append(n)
    # A root, or a calling step, waits on its guard -- its own, its run
    # root's, and any guard of its run: one that stands open and reads as a
    # guard, whatever the root reads, as bd's own edges hold it; and, while
    # the run's root is not known to be whole, one no lookup reads or that no
    # longer reads as a guard. A root no lookup reads that a search still
    # lists open is not gone: Jira's 404 does not tell a deleted issue from
    # one no longer the token's to see.
    rows: list[dict[str, Any]] = search(
        "project = %s AND statusCategory != Done ORDER BY created ASC" % text(project)
    )
    run_key = str(item.get("run") or key)
    guards: list[str] = []
    live = False
    if item["kind"] == "root" or item.get("calls") or item.get("guard"):
        run_root: Record | None = item
        if run_key != key:
            fetched = fetch(run_key)
            run_root = record(fetched) if fetched is not None else None
        live = (
            run_root.get("whole") is not True
            if run_root is not None
            else run_key in {r["key"] for r in rows}
        )
        guards = [
            g
            for g in (item.get("guard"), (run_root or {}).get("guard"))
            if isinstance(g, str) and g
        ]
        guards += [
            r["key"]
            for r in rows
            if ((r.get("properties") or {}).get(PROPERTY) or {}).get("kind") == "guard"
            and ((r.get("properties") or {}).get(PROPERTY) or {}).get("run") == run_key
        ]
    for g in dict.fromkeys(guards):
        issue = fetch(g)
        if issue is None:
            holds = live
        else:
            as_read = record(issue)
            holds = as_read["status"] != "closed" and (as_read["kind"] == "guard" or live)
        if holds and g not in out:
            out.append(g)
    if first and out:
        return out[:1]
    found = {i["key"]: record(i) for i in search("parent = %s ORDER BY created ASC" % text(key))}
    for i in rows:
        own = (i.get("properties") or {}).get(PROPERTY) or {}
        if key in (own.get("run"), own.get("within")):
            found.setdefault(i["key"], record(i))
        if namers is not None and own.get("guard") == key:
            namers.append(record(i))
    again = [
        k for k, above in written_lately(root).items() if k != key and (key in above or k in found)
    ]
    if first:
        for k, r in found.items():
            if k not in again and r["status"] != "closed":
                return [k]
    # The least lately written first: what was just closed is the last to stand open.
    for k in reversed(again):
        fresh = fetch(k)
        if fresh is None and k in found and found[k]["status"] != "closed":
            if first:
                return [k]
            continue  # open as the search has it, unread: it holds the close
        now = record(fresh) if fresh is not None else None
        if now is None or key not in (now.get("parent"), now.get("run"), now.get("within")):
            found.pop(k, None)
            continue
        found[k] = now
        if first and now["status"] != "closed":
            return [k]
    under = sorted(found.values(), key=lambda r: (r.get("createdAt") or "", r["id"]))
    children = [r for r in under if r.get("parent") == key]
    poured = [r for r in under if key in (r.get("run"), r.get("within"))]
    for c in children + poured:
        if c["status"] != "closed" and c["id"] not in out:
            out.append(c["id"])
    return out


def close_one(key: str, reason: str | None) -> bool:
    """Done, read back, and only then the reason: False when the workflow has
    no way there or Jira does not say the issue is closed, and nothing is
    written on it."""
    if not transition_to(key, "done") or record(held(key))["status"] != "closed":
        return False
    if reason:
        call("POST", of(key, "comment"), {"body": adf("closed: %s" % reason)})
    return True


def stood_open_since(key: str, since: datetime.datetime) -> bool | None:
    """Whether the issue has stood open from the moment given to now, as its
    changelog has it -- open then, the last status it was moved to before
    that in an open category, or never moved, and never done since -- each
    status read for its category; None where Jira says nothing of it."""
    categories: dict[str, str | None] = {}
    changes: list[tuple[datetime.datetime, str | None]] = []
    start = 0
    while True:
        try:
            page = call("GET", of(key, "changelog"), query={"startAt": start, "maxResults": 100})
        except JiraError:
            return None
        values = page.get("values") if isinstance(page, dict) else None
        if not isinstance(values, list):
            return None
        for entry in values:
            made = moment(entry.get("created")) if isinstance(entry, dict) else None
            if made is None:
                continue
            for change in entry.get("items") or []:
                if not isinstance(change, dict) or change.get("field") != "status":
                    continue
                to = str(change.get("to") or "")
                if to not in categories:
                    try:
                        shown = call(
                            "GET", "/rest/api/3/status/%s" % urllib.parse.quote(to, safe="")
                        )
                    except JiraError:
                        return None
                    categories[to] = ((shown or {}).get("statusCategory") or {}).get("key")
                changes.append((made, categories[to]))
        start += len(values)
        if not values or page.get("isLast", True):
            break
    changes.sort(key=lambda c: c[0])
    then = [category for when, category in changes if when <= since]
    if then and then[-1] == "done":
        return False
    return not any(category == "done" for when, category in changes if when > since)


def in_the_wake(
    checkout: str | None,
    project: str,
    item: Record,
    keep: set[str],
    since: datetime.datetime | None = None,
) -> list[str]:
    """The poured root above a closed issue, and the root of the run it was
    poured in, wherever it stands, each closed when that was its last open
    step -- save one to keep open (keepOpen); the keys closed. Given when
    the issue came to be done (since), as a close of one closed already
    gives it, a root done then, or since, and opened again -- on purpose --
    is left as it stands, as is one whose changelog Jira does not give:
    only one that has stood open since before the close, as a close cut
    short leaves it, moved between open statuses or not, is closed in its
    wake."""
    closed: list[str] = []
    todo = [item]
    while todo:
        at = todo.pop(0)
        for root in above_in_the_wake(checkout, project, at, keep, since, closed):
            closed.append(root["id"])
            todo.append(root)
        since = None  # what closes in the wake of this close closes now
    return closed


def above_in_the_wake(
    checkout: str | None,
    project: str,
    item: Record,
    keep: set[str],
    since: datetime.datetime | None,
    closed: list[str],
) -> list[Record]:
    """What in_the_wake closes one level up from an issue: its poured root,
    the root of the run it was poured in, the calling step it was poured
    within, and each calling step that needs it, whose last need it may have
    been, each closed when nothing of it stands open; the records closed.
    One that is the parent as well as one of the others is taken for the
    other."""
    reached: dict[str, bool] = {}
    for up, must_be_root in (
        (item.get("parent"), True),
        (item.get("run"), False),
        (item.get("within"), False),
    ):
        if up:
            reached[str(up)] = reached.get(str(up), True) and must_be_root
    # The issues that need it: Blocks links of which it is the end that blocks.
    for link in ((held(item["id"]).get("fields") or {}).get("issuelinks")) or []:
        other = (link.get("outwardIssue") or {}).get("key")
        if (link.get("type") or {}).get("name") == "Blocks" and other and other not in reached:
            needing = fetch_here(other, project)
            if needing is not None and record(needing).get("calls"):
                reached[str(needing["key"])] = False
    roots = []
    for up, must_be_root in reached.items():
        above = fetch_here(up, project)
        if above is not None and (not must_be_root or record(above)["kind"] == "root"):
            roots.append(above)
    shut: list[Record] = []
    for issue in roots:
        root = record(issue)
        if root["id"] in keep or root["id"] in closed or root["kind"] == "guard":
            continue  # one to keep open: nothing closes it in the wake of this close
        changed = moment((issue.get("fields") or {}).get("statuscategorychangedate"))
        if (
            since is not None
            and changed is not None
            and changed > since
            and stood_open_since(root["id"], since) is not True
        ):
            continue  # done when the issue was, or since, and opened again: as it stands
        if root["status"] == "closed" or blockers(checkout, project, root["id"], root, True):
            continue
        wrote(checkout, root["id"], root.get("parent"), root.get("run"), root.get("within"))
        if close_one(root["id"], "every step closed"):
            shut.append(record(held(root["id"])))
    return shut


def jira_close(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    key = request["id"]
    try:
        issue = fetch_here(key, project)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        key = issue["key"]  # as Jira gives it, which reads a key in any case
        item = record(issue)
        if item["kind"] == "guard" and item["status"] == "closed":
            return {
                "status": "blocked",
                "reason": "blocked",
                "exitCode": 1,
                "summary": GUARD_HELD % key,
            }
        checkout = request.get("root")
        keep = set(request.get("keepOpen") or [])
        if item["status"] == "closed":
            if request.get("closeReason") and not item.get("reason"):
                # Closed, and without the reason it was to keep: a close cut
                # short once the issue was done, finished now.
                body = {"body": adf("closed: %s" % request["closeReason"])}
                call("POST", of(key, "comment"), body)
                item = record(held(key))
            # And what a close cut short left open above it: a root whose
            # last step this was, and that has stood open since, closes now,
            # as it would have then.
            done_at = moment((issue.get("fields") or {}).get("statuscategorychangedate"))
            after = in_the_wake(checkout, project, item, keep, done_at)
            return {
                "status": "completed",
                "summary": "%s was closed already." % key
                + (" Closed %s." % ", ".join(after) if after else ""),
                "item": item,
                "closedIds": after,
                "exitCode": 0,
            }
        # A pour's guard -- one that reads as one, or a key an open issue names
        # as its guard -- closes only where its pour is known to be whole:
        # the pour's own last write again, the way out of a pour cut short at
        # its guard's close.
        namers: list[Record] = []
        blocked = blockers(checkout, project, key, item, namers=namers)
        if (
            not whole_by_its_run(item)
            if item["kind"] == "guard"
            else bool(namers) and guarded_still(item, namers)
        ):
            return {
                "status": "blocked",
                "reason": "blocked",
                "exitCode": 1,
                "summary": GUARD_HELD % key,
            }
        if blocked:
            return {
                "status": "blocked",
                "reason": "blocked",
                "blockedBy": blocked,
                "exitCode": 1,
                "summary": "%s is blocked by %s." % (key, ", ".join(blocked)),
            }
        wrote(checkout, key, item.get("parent"), item.get("run"), item.get("within"))
        if not close_one(key, request.get("closeReason")):
            return {
                "status": "failed",
                "exitCode": 1,
                "summary": "%s has no transition to done in its workflow; it stays %s."
                % (key, item["status"]),
            }
        closed = [key] + in_the_wake(checkout, project, item, keep)
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
        issue = fetch_here(key, project)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        key = issue["key"]
        # Its children as a listing under it has them: what was written of
        # late through this dotdiw home read by its key (as_they_stand).
        children = [
            record(whole)
            for whole in (
                full(i, project)
                for i in as_they_stand(
                    request.get("root"),
                    project,
                    search(
                        "project = %s AND parent = %s ORDER BY created ASC"
                        % (text(project), text(key))
                    ),
                    key,
                )
            )
            if whole is not None
        ]
        children.sort(key=lambda c: (c["createdAt"] or "", c["id"]))
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
    run = request.get("run")
    under = request.get("parent")
    try:
        if under:
            # The parent under the key Jira gives it, which reads one in any case.
            above = fetch(under)
            under = above["key"] if above is not None else under
        jql = "project = %s" % text(project)
        if under:
            jql += " AND parent = %s" % text(under)
        # JQL reaches no property Jira was not told to index, so a run is
        # kept here, before each of its issues is read again whole. And a
        # search may be without a write for a while after it, so what was
        # written of late through this dotdiw home is read by its key.
        items = [
            record(whole)
            for whole in (
                full(i, project)
                for i in as_they_stand(
                    request.get("root"), project, search(jql + " ORDER BY created ASC"), under
                )
                if run is None
                or ((i.get("properties") or {}).get(PROPERTY) or {}).get("run") == run
            )
            if whole is not None
        ]
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
    if request.get("priority") is not None and not 0 <= int(request["priority"]) <= 4:
        return {
            "status": "failed",
            "exitCode": 1,
            "summary": "A priority is 0 to 4, 0 the highest: %d." % int(request["priority"]),
        }
    request = dict(request, parent=request.get("parent") or None)  # empty is none given
    if request["parent"] and request.get("dropParent"):
        return {
            "status": "failed",
            "exitCode": 1,
            "summary": "A parent given and taken off at once: give one or the other.",
        }
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    key = request["id"]
    try:
        issue = fetch_here(key, project)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        key = issue["key"]  # as Jira gives it, which reads a key in any case
        drop = {str(n).upper() for n in request.get("dropNeeds") or []}
        if record(issue)["kind"] == "guard":
            return {"status": "failed", "exitCode": 1, "summary": GUARD_HELD % key}
        for need in sorted(drop):
            held_need = fetch(need)
            if held_need is not None and record(held_need).get("within") == key:
                return {"status": "failed", "exitCode": 1, "summary": CALL_NEED_HELD % (key, need)}
        if request.get("parent"):
            above = fetch_here(request["parent"], project)
            if above is None:
                return {
                    "status": "failed",
                    "reason": "item-not-found",
                    "exitCode": 1,
                    "summary": "%s names no issue here." % request["parent"],
                }
            request = dict(request, parent=above["key"])
            # A parent that waits on the issue to close, as add-need refuses
            # such a need -- the needs given to take off left out of it.
            if above["key"] == key or reaches(
                request.get("root"), project, key, above["key"], drop
            ):
                return {
                    "status": "failed",
                    "reason": "cycle",
                    "exitCode": 1,
                    "summary": "%s cannot stand under %s, which waits on it to close, so "
                    "neither could close." % (key, above["key"])
                    if above["key"] != key
                    else "%s cannot stand under %s: an issue cannot wait on itself."
                    % (key, above["key"]),
                }
        was = record(issue)
        # What Jira can be asked before anything is written, asked first: the
        # way to the status, so that a workflow with no way there leaves it
        # all as it was. Jira writes an issue in parts, one request each.
        wanted = request.get("status")
        category = {"open": "new", "blocked": "new", "in_progress": "indeterminate"}.get(
            wanted or ""
        )
        status = (issue.get("fields") or {}).get("status") or {}
        way = None
        if category and (status.get("statusCategory") or {}).get("key") != category:
            way = way_to(key, category)
            if way is None:
                return {
                    "status": "failed",
                    "reason": "bad-status",
                    "exitCode": 1,
                    "summary": "%s has no transition to %s in its workflow." % (key, wanted),
                }
        wrote(request.get("root"), key, request.get("parent") or was.get("parent"), was.get("run"))
        # Jira writes an issue in parts, one request each. Those it may
        # refuse once asked go first -- the person, the parent taken off, the
        # fields, the status -- each put back as it was where a later one is
        # refused, so that a refused update writes nothing; the needs given to
        # take off come off last, once the status asked for is reached.
        now = issue.get("fields") or {}
        undo: list[tuple[str, dict[str, Any]]] = []

        def put_back() -> None:
            for path, body in reversed(undo):
                try:
                    call("PUT", path, body)
                except JiraError:
                    pass  # as much as Jira takes back

        try:
            if request.get("assignee"):
                who = (
                    myself().get("accountId")
                    if request["assignee"] == "me"
                    else request["assignee"]
                )
                try:
                    call("PUT", of(key, "assignee"), {"accountId": who})
                except JiraError as e:
                    return failed(e, [("assignee-not-found", 400), ("assignee-not-found", 404)])
                undo.append(
                    (
                        of(key, "assignee"),
                        {"accountId": (now.get("assignee") or {}).get("accountId")},
                    )
                )
            if request.get("dropParent") and was.get("parent"):
                refusal = None
                try:
                    call("PUT", of(key), {"fields": {"parent": None}})
                except JiraError as e:
                    if e.status != 400:
                        raise
                    refusal = "Jira would not take %s from under %s: %s" % (
                        key,
                        was["parent"],
                        e.text,
                    )
                kept = record(held(key)) if refusal is None else None
                if kept is not None and kept.get("parent"):
                    refusal = "Jira kept %s under %s." % (key, kept["parent"])
                if refusal is not None:
                    put_back()
                    return {
                        "status": "failed",
                        "reason": "unsupported",
                        "exitCode": 1,
                        "summary": refusal,
                    }
                undo.append((of(key), {"fields": {"parent": {"key": was["parent"]}}}))
            fields: dict[str, Any] = {}
            if request.get("title") is not None:
                fields["summary"] = request["title"]
            if request.get("priority") is not None:
                fields["priority"] = {"name": PRIORITIES[int(request["priority"])]}
            if request.get("parent"):
                fields["parent"] = {"key": request["parent"]}
            labels = list(now.get("labels") or [])
            if request.get("status") is not None:
                labels = [label for label in labels if label != "blocked"]
                if request["status"] == "blocked":
                    labels.append("blocked")
                fields["labels"] = labels
            if fields:
                call("PUT", of(key), {"fields": fields})
                old = {
                    "summary": now.get("summary"),
                    "priority": {"name": (now.get("priority") or {}).get("name")},
                    "parent": {"key": was["parent"]} if was.get("parent") else None,
                    "labels": list(now.get("labels") or []),
                }
                undo.append((of(key), {"fields": {k: old[k] for k in fields}}))
            if way is not None:
                try:
                    call("POST", of(key, "transitions"), {"transition": {"id": way}})
                except JiraError as e:
                    if e.status != 400:
                        raise
                    put_back()
                    return {
                        "status": "failed",
                        "reason": "bad-status",
                        "exitCode": 1,
                        "summary": "Jira refused %s the way to %s: %s" % (key, wanted, e.text),
                    }
        except JiraError:
            put_back()
            raise
        # Each need given to take off, its link deleted: the issue waits on
        # it no more.
        for link in now.get("issuelinks") or []:
            other = str((link.get("inwardIssue") or {}).get("key") or "").upper()
            if (link.get("type") or {}).get("name") == "Blocks" and other in drop:
                call(
                    "DELETE",
                    "/rest/api/3/issueLink/%s" % urllib.parse.quote(str(link["id"]), safe=""),
                )
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


def jira_record_values(request: Request) -> Response:
    """operation.record-values: the values given, kept whole in one issue
    property named after every write the issue holds, so that a write is
    there whole or not at all and is read after them: a write cut short
    reads as it was, writers of the same labels at once leave one write
    whole, and a writer of other labels keeps what it recorded. Values more
    than one property holds are kept in as few as hold them, a text longer
    than one holds cut in pieces, each named after the one before and all
    one write (keep_values), read whole or not at all."""
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    key = request["id"]
    try:
        issue = fetch_here(key, project)
        if issue is None:
            return {
                "status": "failed",
                "reason": "item-not-found",
                "exitCode": 1,
                "summary": "%s names no issue here." % key,
            }
        key = issue["key"]  # as Jira gives it, which reads a key in any case
        properties = dict(issue.get("properties") or {})
        own = properties.get(PROPERTY) or {}
        if not (own.get("step") or own.get("values")):
            # Its own property says it holds values, so that a search's
            # issue is read again whole (full), and its values come with it.
            call("PUT", of(key, "properties", PROPERTY), dict(own, values=True))
        keep_values(key, list(request["values"]), properties)
        issue = held(key)
    except JiraError as e:
        return failed(e, [("item-not-found", 404)])
    count = len(request["values"])
    return {
        "status": "completed",
        "summary": "Recorded %d value%s on %s." % (count, "" if count == 1 else "s", key),
        "item": record(issue),
        "exitCode": 0,
    }


def jira_ready(request: Request) -> Response:
    if config() is None:
        return dict(NOT_CONFIGURED)
    project, refused = opened(request.get("root"))
    if refused or not project:
        return refused or dict(NO_WORKSPACE)
    try:
        # Each read whole where it holds values (full), and what was written
        # of late through this dotdiw home read by its key, as a search may
        # be without it (as_they_stand) -- a need written a moment ago among
        # it -- so that ready gives the record, and the ETag, that show and
        # list give.
        items = [
            record(whole)
            for whole in (
                full(i, project)
                for i in as_they_stand(
                    request.get("root"),
                    project,
                    search("project = %s ORDER BY created ASC" % text(project)),
                )
            )
            if whole is not None
        ]
        items.sort(key=lambda i: (i["createdAt"] or "", i["id"]))
        status = {i["id"]: i["status"] for i in items}
        # A need of another project, as a site may link an issue to, is open
        # or closed as Jira says; one it holds none of now, open.
        for n in sorted({n for i in items for n in i["needs"]} - set(status)):
            issue = fetch(n)
            status[n] = record(issue)["status"] if issue is not None else "open"
    except JiraError as e:
        return failed(e)
    # Nothing of a pour not known to be whole is work yet (pours_held): its
    # guard, the root and the calling steps that name it, and every item of
    # its run, a step among them perhaps made before its needs were linked.
    pours = pours_held({i["id"]: i for i in items})
    held = {k for p in pours.values() for k in p["holds"]}
    ready = [
        i
        for i in items
        if i["status"] == "open"
        and i["kind"] != "guard"
        and i["id"] not in held
        and not any(status.get(n, "open") != "closed" for n in i["needs"])
    ]
    unread = sorted(g for g, p in pours.items() if p["unread"])
    return {
        "status": "completed",
        "summary": "%d ready." % len(ready)
        + (
            " Left out: what the pour held on %s made, whose guard could not be read."
            % ", ".join(unread)
            if unread
            else ""
        ),
        "items": ready,
        "exitCode": 0,
    }


TRACKER = {
    "info": {
        "name": "jira",
        "version": VERSION,
        "interface": 4,
        "origin": "loaded",
        "nativeNeeds": True,
        "nests": True,
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
        "operation.record-values": jira_record_values,
    },
    "extras": {},
    "store": store,
}
