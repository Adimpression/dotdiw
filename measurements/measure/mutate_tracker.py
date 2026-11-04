"""Do the tests that hold the tracker door bite?

Each mutation below breaks one rule the tracker abstraction promises -- in
a copy of the repository, never here -- and the test named for it must fail
on the broken copy. A mutation that survives is a rule nothing holds. The
table printed is the record; it goes in ../results/mutation-tracker.txt.

    python3 -I measure/mutate_tracker.py [-k substring]

Run from `measurements/`. bd must be on PATH for the beads mutations; the
others need no binary. The byte-identity mutation takes a minute.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# (name, file, the text as it stands, the text that breaks the rule, the test that must fail)
MUTATIONS = [
    (
        "local closes a blocked item",
        "dotdiw",
        "            blocked = local_blockers(conn, ident)\n            if blocked:\n",
        "            blocked = local_blockers(conn, ident)\n            if False:\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local pours steps without their edges",
        "dotdiw",
        '                for n in s.get("needs") or []:\n                    conn.execute(\n                        "INSERT OR IGNORE INTO edges (id, needs) VALUES (?, ?)", (ident, ids[n])\n                    )\n',
        '                for n in []:\n                    conn.execute(\n                        "INSERT OR IGNORE INTO edges (id, needs) VALUES (?, ?)", (ident, ids[n])\n                    )\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "the tracker door lets a response step outside its type",
        "dotdiw",
        '    for key in response:\n        if key not in spec["response"]:\n            raise DoorError(\'%s: "%s" is not a field of its response\' % (operation, key))\n    for key in spec["responseRequired"]:\n        if response.get(key) is None:\n            raise DoorError(\'%s: "%s" is required in its response and missing\' % (operation, key))\n    if response["status"] not in STATUSES:\n        raise DoorError(\n            \'%s: status "%s" is not one of %s\'\n            % (operation, response["status"], ", ".join(STATUSES))\n        )\n    kinds = record_kinds(spec["responseType"])\n',
        '    kinds = record_kinds(spec["responseType"])\n',
        [
            "test_promise.py",
            "TheTrackerDoor.test_the_tracker_door_raises_naming_the_operation_and_the_key",
        ],
    ),
    (
        "a workspace with one store and no choice falls to the default",
        "dotdiw",
        "    return found[0] if len(found) == 1 else None\n",
        "    return None\n",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_workspace_with_one_store_and_no_choice_is_answered_by_that_adapter",
        ],
    ),
    (
        "the upgrade writes no choice",
        "dotdiw",
        '            git(["config", "--local", TRACKER_KEY, pinned], root)\n            forget_workspace(root)\n            done.append(',
        "            forget_workspace(root)\n            done.append(",
        ["test_dotdiw.py", "TheUpgradePin.test_the_choice_is_written_once_and_said_once"],
    ),
    (
        "the stream rewrite is dropped",
        "dotdiw",
        "        out, err = _BD_WORD.sub(PROG, p.stdout), _BD_WORD.sub(PROG, p.stderr)\n",
        "        out, err = p.stdout, p.stderr\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_the_extras"],
    ),
    (
        "a body runs the binary itself",
        "dotdiw",
        '    root = request["root"]\n    args = list(request.get("arguments") or [])\n    if args and args[0] == "create":\n        args = args[1:]\n',
        '    root = request["root"]\n    beads_quiet(["list"], root)\n    args = list(request.get("arguments") or [])\n    if args and args[0] == "create":\n        args = args[1:]\n',
        ["test_promise.py", "TheSort.test_only_the_adapter_names_the_binary"],
    ),
    (
        "the tracker door's table is edited by hand",
        "dotdiw",
        '    "operation.add-need": {\n        "request": (\n            "correlationId", "id", "needs",',
        '    "operation.add-need": {\n        "request": (\n            "correlationId", "id", "needed",',
        ["test_promise.py", "TheDoor.test_the_table_is_a_fresh_generation_from_the_idl"],
    ),
    (
        "the move leaves the needs behind",
        "dotdiw",
        '        for need in item.get("needs") or []:\n            if need in ids and [item["id"], need] not in linked:\n',
        '        for need in []:\n            if need in ids and [item["id"], need] not in linked:\n',
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "the presenter prints the created issue under beads too",
        "dotdiw",
        '    elif response.get("workRef") and not response.get("printed"):\n',
        '    elif response.get("workRef"):\n',
        [
            "test_dotdiw.py",
            "TheBytesUnderBeads.test_the_seventeen_commands_print_what_0_5_0_printed",
        ],
    ),
    (
        "the witness forgets which adapter answered",
        "dotdiw",
        '                title=request.get("title"),\n                startedAt=STARTED_AT,\n                tracker=response.get("tracker"),\n            )\n',
        '                title=request.get("title"),\n                startedAt=STARTED_AT,\n            )\n',
        [
            "test_promise.py",
            "TheWitnessLogUnderLocal.test_a_real_run_is_a_story_the_contract_calls_valid",
        ],
    ),
    (
        "an adapter answers the interface from outside its sort",
        "dotdiw",
        "def local_ready(request: ReadyItemsRequest) -> ReadyItemsResponse:\n",
        "def ready_elsewhere(request: ReadyItemsRequest) -> ReadyItemsResponse:\n    return local_ready(request)\n\n\ndef local_ready(request: ReadyItemsRequest) -> ReadyItemsResponse:\n",
        ["test_promise.py", "TheSort.test_every_definition_is_sorted"],
    ),
    (
        "help under a store is refused",
        "dotdiw",
        '    if verb in ("--help", "-h", "help"):\n',
        "    if verb in ():\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_help_is_the_conventions_text"],
    ),
    (
        "a loaded adapter's failure is a traceback",
        "dotdiw",
        '    return adapter["info"].get("origin") == "loaded"\n',
        "    return False\n",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_loaded_adapter_that_fails_is_refused_in_one_line",
        ],
    ),
    (
        "a run does not finish what an earlier one left",
        "dotdiw",
        '    unsettled = [i for i in order if i["id"] in ids and i["id"] not in settled]\n',
        '    unsettled = [i for i in order[-moved:] if i["id"] in ids and i["id"] not in settled]\n',
        [
            "test_tracker.py",
            "AnInterruptedMove.test_a_refused_item_leaves_the_earlier_ones_to_be_finished",
        ],
    ),
    (
        "a refused need passes for a completed move",
        "dotdiw",
        '                if out["status"] != "completed":\n                    return refused("the need of %s on %s" % (item["id"], need), out)\n',
        '                if False:\n                    return refused("the need of %s on %s" % (item["id"], need), out)\n',
        [
            "test_tracker.py",
            "AnInterruptedMove.test_a_refused_need_is_reported_and_written_by_the_next_run",
        ],
    ),
    (
        "metrics stay on for an adapter the checkout did not choose",
        "dotdiw",
        '        settle_adapter(name, adapter, request.get("root"))\n        try:\n',
        "        try:\n",
        ["test_dotdiw.py", "Metrics.test_off_before_the_tracker_runs_whichever_adapter_is_chosen"],
    ),
    (
        "Jira is searched through the endpoint being removed",
        "trackers/jira.py",
        'page = call("GET", "/rest/api/3/search/jql", query=query)',
        'page = call("GET", "/rest/api/3/search", query=query)',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_search_uses_the_endpoint_jira_keeps_and_its_tokens",
        ],
    ),
    (
        "a check reads before it holds the lock",
        "dotdiw",
        '        conn.execute("BEGIN IMMEDIATE")\n        yield\n',
        "        yield\n",
        ["test_dotdiw.py", "TheLocalAdapter.test_two_needs_cannot_close_a_cycle_between_them"],
    ),
    (
        "Jira reports a close it did not make",
        "trackers/jira.py",
        '    if not transition_to(key, "done") or record(held(key))["status"] != "closed":\n        return False\n',
        '    transition_to(key, "done")\n',
        ["test_jira.py", "TheHostedAdapter.test_a_close_with_no_way_to_done_is_refused"],
    ),
    (
        "a switch that fails still changes the choice",
        "dotdiw",
        '    opened = invoke_tracker(\n        "operation.open-tracker",\n        {\n            "root": root,\n            "tracker": name,\n            "prefix": prefix,\n',
        '    git(["config", "--local", TRACKER_KEY, name], root)\n    opened = invoke_tracker(\n        "operation.open-tracker",\n        {\n            "root": root,\n            "tracker": name,\n            "prefix": prefix,\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_a_switch_that_fails_keeps_the_choice"],
    ),
    (
        "a need on a step declared later is refused",
        "dotdiw",
        "            for s in ordered:\n                ident = local_new_id(conn)\n",
        "            for s in steps:\n                ident = local_new_id(conn)\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_a_need_on_a_step_declared_later_pours"],
    ),
    (
        "the description stops short of the item",
        "dotdiw",
        '            "title": request["title"],\n            "description": request.get("description"),\n',
        '            "title": request["title"],\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_a_description_is_saved_on_the_item"],
    ),
    (
        "create --json prints prose",
        "dotdiw",
        '        if "--json" in (request.get("arguments") or []):\n            print(json.dumps(item, indent=2, ensure_ascii=False))\n            return\n',
        "",
        ["test_dotdiw.py", "TheLocalCommandLine.test_json_is_json"],
    ),
    (
        "grandchildren are not drawn",
        "dotdiw",
        '            draw(child, kids, seen, lead + ("    " if last else "\\u2502   "))\n',
        '            seen.add(child["id"])\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_a_chain_is_listed_to_its_end"],
    ),
    (
        "a value outside its type passes the door",
        "dotdiw",
        "    for key, value in response.items():\n        hold_value(operation, key, value, kinds[key])\n",
        "",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_value_outside_its_type_is_one_line_from_a_loaded_adapter",
        ],
    ),
    (
        "Jira turns priority zero into two",
        "trackers/jira.py",
        '    priority = 2 if request.get("priority") is None else int(request["priority"])\n',
        '    priority = int(request.get("priority") or 2)\n',
        ["test_jira.py", "TheHostedAdapter.test_priority_zero_is_kept"],
    ),
    (
        "a Jira assignee goes by name",
        "trackers/jira.py",
        '{"accountId": request["assignee"]}',
        '{"name": request["assignee"]}',
        ["test_jira.py", "TheHostedAdapter.test_an_assignee_is_an_account_id"],
    ),
]


def copy_of_repo():
    """The tracked files, in a temporary directory, with the release tag's
    history kept for the byte test."""
    out = tempfile.mkdtemp(prefix="dotdiw-mutate-")
    subprocess.run(["git", "clone", "-q", ROOT, out], check=True)
    files = subprocess.run(
        ["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split("\n")
    for rel in files:
        if not rel:
            continue
        src, dst = os.path.join(ROOT, rel), os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    return out


def main(argv):
    only = argv[argv.index("-k") + 1] if "-k" in argv else ""
    copy = copy_of_repo()
    bites, misses = [], []
    try:
        for name, rel, old, new, (suite, test) in MUTATIONS:
            if only and only not in name:
                continue
            path = os.path.join(copy, rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if text.count(old) != 1:
                print("?      %-58s the text to mutate is not there once" % name)
                misses.append(name)
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace(old, new))
            started = time.perf_counter()
            p = subprocess.run(
                [sys.executable, "-I", suite, test], cwd=copy, capture_output=True, text=True
            )
            took = time.perf_counter() - started
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            if p.returncode != 0:
                bites.append(name)
                print("bites  %-58s %s %s (%.0f s)" % (name, suite, test.split(".")[-1], took))
            else:
                misses.append(name)
                print("MISS   %-58s %s %s passed on the broken copy" % (name, suite, test))
    finally:
        shutil.rmtree(copy, ignore_errors=True)
    print("%d of %d mutations caught" % (len(bites), len(bites) + len(misses)))
    return 1 if misses else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
