"""Score a round from the witness logs, through the contract, and measure the
create latency the promise names.

score3.py and score4.py read the shim's invocation log and decide by hand what
counts as discovery having fired. From 0.3.0 the runs write their own
.beads/witness.jsonl, and the contract in ../../contracts decides: a story is
valid, caveated, incomplete, open, conflicted or invalid, and only valid and
caveated may be reported as "discovery fired" (report.discovery-fired in
operation-idl.json). Past rounds were not re-scored; they have no logs.

    DOTDIW_SIM_ROOT=<root> python3 -I witness.py [runmap3.tsv|runmap4.tsv]
    python3 -I witness.py --log <some .beads/witness.jsonl>     one log, latency only

sli.create-feedback-latency is the time from invoking dotdiw create to the
applying formulas being printed. Both ends are in the log: work_named carries
startedAt, when the process began, and the formula_surfaced or
nothing_surfaced event of the same case carries occurredAt, written as the
match was printed. slo.create-feedback-under-one-second is 1000 ms.
"""
import datetime
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CONTRACT = os.path.join(REPO, "contracts", "named-work-found-its-procedure.cesc.yaml")
WATERMARKS = os.path.join(REPO, "events", "source-watermarks.yaml")
POA = os.path.expanduser("~/poa")
S = os.environ.get("DOTDIW_SIM_ROOT", "./sim-root")
REPORTABLE = ("valid", "caveated")        # report.discovery-fired's allowedStoryStatuses


def stories(log):
    p = subprocess.run([POA, "match", "cesc", "--contract", CONTRACT, "--events", log,
                        "--watermarks", WATERMARKS, "--json"],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return None
    return [(m["caseKey"], m["storyStatus"]) for m in json.loads(p.stdout).get("matches", [])]


def when(stamp):
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")


def latencies(log):
    """Milliseconds from invoking create to the match, per case in one log."""
    started, out = {}, []
    with open(log, encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    for e in events:
        if e.get("label") == "work_named" and e.get("startedAt"):
            started[e["workId"]] = e["startedAt"]
    for e in events:
        if e.get("label") in ("formula_surfaced", "nothing_surfaced") and e.get("workId") in started:
            try:
                ms = (when(e["occurredAt"]) - when(started.pop(e["workId"]))).total_seconds() * 1000
            except (ValueError, KeyError):
                continue
            out.append(round(ms))
    return out


if len(sys.argv) > 2 and sys.argv[1] == "--log":
    ms = latencies(sys.argv[2])
    print("%d creates: median %d ms, min %d, max %d; SLO 1000 ms %s"
          % (len(ms), statistics.median(ms), min(ms), max(ms),
             "met" if ms and max(ms) <= 1000 else "missed") if ms else "no create with both ends in the log")
    sys.exit(0)

def log_of(run_dir):
    """The run's witness log: under the harness's home, at the run's key."""
    p = subprocess.run(["git", "config", "--local", "--get", "dotdiw.workspace"],
                       cwd=run_dir, capture_output=True, text=True)
    key = p.stdout.strip()
    home = os.environ.get("HOME", S)
    return os.path.join(home, ".dotdiw", key, "witness.jsonl") if key else ""


runmap = sys.argv[1] if len(sys.argv) > 1 else "runmap3.tsv"
rows = []
for line in open(os.path.join(S, runmap), encoding="utf-8"):
    rid, proj, state, d = line.rstrip("\n").split("\t")
    log = log_of(d)
    found = stories(log) if os.path.exists(log) else []
    rows.append({"id": rid, "project": proj, "state": state,
                 "stories": found, "witnessed": os.path.exists(log),
                 "fired": sum(1 for _, st in (found or []) if st in REPORTABLE),
                 "latencyMs": latencies(log) if os.path.exists(log) else []})

json.dump(rows, open(os.path.join(S, "score-witness.json"), "w"), indent=1)
all_ms = [ms for r in rows for ms in r["latencyMs"]]
print("%d runs, %d with a witness log, %d stories, %d reportable as discovery fired"
      % (len(rows), sum(1 for r in rows if r["witnessed"]),
         sum(len(r["stories"] or []) for r in rows), sum(r["fired"] for r in rows)))
if all_ms:
    print("create latency: %d creates, median %d ms, max %d ms (SLO 1000 ms)\n"
          % (len(all_ms), statistics.median(all_ms), max(all_ms)))
else:
    print()
for r in rows:
    print("%-4s %-14s %-5s %s" % (r["id"], r["project"], r["state"],
                                  " ".join("%s:%s" % s for s in (r["stories"] or [])) or "-"))
