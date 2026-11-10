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
        '            git(["config", "--local", TRACKER_KEY, pinned], root)\n            forget_workspace(root)\n            if tracker_name(root) == pinned:\n',
        "            forget_workspace(root)\n            if True:\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_choice_that_could_not_be_pinned_is_not_said_to_be",
        ],
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
        '    root = request["root"]\n    made = invoke_tracker(\n        "operation.create-item",\n',
        '    root = request["root"]\n    beads_quiet(["list"], root)\n    made = invoke_tracker(\n        "operation.create-item",\n',
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
        '    opened = invoke_tracker(\n        "operation.open-tracker",\n        {"root": root, "tracker": name, "prefix": prefix},\n    )\n',
        '    git(["config", "--local", TRACKER_KEY, name], root)\n    opened = invoke_tracker(\n        "operation.open-tracker",\n        {"root": root, "tracker": name, "prefix": prefix},\n    )\n',
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
        '        if request.get("json"):\n            print(json.dumps(item, indent=2, ensure_ascii=False))\n            return\n',
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
        '{"accountId": who}',
        '{"name": who}',
        ["test_jira.py", "TheHostedAdapter.test_an_assignee_is_an_account_id"],
    ),
    (
        "a package's directory is not searched",
        "dotdiw",
        "    for prefix in prefixes:\n        shared = os.path.join(prefix, shared_under)\n",
        "    for prefix in []:\n        shared = os.path.join(prefix, shared_under)\n",
        ["test_dotdiw.py", "ThePlacesAModuleIsFound.test_a_module_beside_bin_is_found_and_answers"],
    ),
    (
        "a package comes before the home directory",
        "dotdiw",
        "        if shared not in dirs:\n            dirs.append(shared)\n",
        "        if shared not in dirs:\n            dirs.insert(0, shared)\n",
        ["test_dotdiw.py", "ThePlacesAModuleIsFound.test_the_home_directory_comes_first"],
    ),
    (
        "a keg does not look above Cellar",
        "dotdiw",
        "    if cellar in real:\n",
        "    if False:\n",
        ["test_dotdiw.py", "ThePlacesAModuleIsFound.test_a_keg_reads_the_directory_above_cellar"],
    ),
    (
        "a tool outside a bin directory reads beside itself",
        "dotdiw",
        '    if os.path.basename(os.path.dirname(here)) == "bin":\n',
        "    if True:\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_a_tool_outside_a_bin_directory_reads_only_the_home_directory",
        ],
    ),
    (
        "a package's bytecode lands where packages share a directory",
        "dotdiw",
        ", os.path.realpath(path))\n",
        ", path)\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_a_package_leaves_nothing_in_the_directory_packages_share",
        ],
    ),
    (
        "a module's store that raises is a traceback",
        "dotdiw",
        "        except MODULE_MISTAKES:  # a module's mistake must not stop another adapter answering\n            if not is_loaded(adapter):\n                raise\n",
        "        except MODULE_MISTAKES:\n            raise\n",
        ["test_dotdiw.py", "ThePlacesAModuleIsFound.test_a_store_that_raises_is_no_traceback"],
    ),
    (
        "another interface is accepted",
        "dotdiw",
        "    if declared != TRACKER_INTERFACE or isinstance(declared, bool):\n",
        "    if False:\n",
        ["test_promise.py", "TheTrackerDoor.test_a_module_says_which_interface_it_was_written_for"],
    ),
    (
        "a module that does not say its interface reads as 0",
        "dotdiw",
        "        declared = 1  # written",
        "        declared = 0  # written",
        ["test_promise.py", "TheTrackerDoor.test_a_module_says_which_interface_it_was_written_for"],
    ),
    (
        "the interface's digest is not held",
        "poa/complete-idl.py",
        '    if digest == held["digest"]:\n',
        "    if True:\n",
        ["test_promise.py", "TheDoor.test_the_interface_number_moves_by_decision"],
    ),
    (
        "a check by path leaves bytecode beside the file",
        "dotdiw",
        "    sys.dont_write_bytecode = True\n    try:\n        yield\n",
        "    try:\n        yield\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_what_a_checked_file_imports_leaves_no_bytecode_beside_it",
        ],
    ),
    (
        "a check by path reads the bytecode beside the file",
        "dotdiw",
        "        if given:  # bytecode is matched by size and second, which a same-sized edit can keep\n            exec(loader.source_to_code(loader.get_data(loader.path), loader.path), vars(module))\n        else:\n            loader.exec_module(module)\n",
        "        loader.exec_module(module)\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_a_check_by_path_reads_the_file_and_not_its_bytecode",
        ],
    ),
    (
        "a check by path leaves the file registered",
        "dotdiw",
        "        (TRACKERS, name),\n",
        "",
        [
            "test_dotdiw.py",
            "ACheckByPathLeavesTheProcessAsItWas.test_the_adapter_that_was_answering_answers_again",
        ],
    ),
    (
        "a check by path leaves the file's module",
        "dotdiw",
        '        (sys.modules, "dotdiw_tracker_" + name),\n',
        "",
        [
            "test_dotdiw.py",
            "ACheckByPathLeavesTheProcessAsItWas.test_the_adapter_that_was_answering_answers_again",
        ],
    ),
    (
        "a check by path forgets a failure already recorded",
        "dotdiw",
        "        (LOAD_FAILED, name),\n",
        "",
        [
            "test_dotdiw.py",
            "ACheckByPathLeavesTheProcessAsItWas.test_a_failure_already_recorded_is_still_said",
        ],
    ),
    (
        "a file that did not load counts against the installed one",
        "dotdiw",
        "        (LOAD_TRIED.add if tried else LOAD_TRIED.discard)(name)\n",
        "",
        [
            "test_dotdiw.py",
            "ACheckByPathLeavesTheProcessAsItWas.test_a_file_that_did_not_load_counts_against_nothing",
        ],
    ),
    (
        "a check by path leaves writing bytecode off",
        "dotdiw",
        "        sys.dont_write_bytecode = writes\n",
        "",
        [
            "test_dotdiw.py",
            "ACheckByPathLeavesTheProcessAsItWas.test_the_adapter_that_was_answering_answers_again",
        ],
    ),
    (
        "the check command printed splits at a space",
        "dotdiw",
        '% (PROG, shlex.quote(written if os.path.isabs(written) else "./" + written))\n',
        '% (PROG, written if os.path.isabs(written) else "./" + written)\n',
        ["test_dotdiw.py", "TheCommandsPrinted.test_the_check_after_tracker_new_runs_as_printed"],
    ),
    (
        "the git add printed splits at a space",
        "dotdiw",
        'git add %s && git commit" % shlex.quote(rel))\n',
        'git add %s && git commit" % rel)\n',
        ["test_dotdiw.py", "TheCommandsPrinted.test_the_git_add_after_formula_new_runs_as_printed"],
    ),
    (
        "the commit's command splits at a space",
        "dotdiw",
        '        shlex.quote(path) if request.get("path") else path,\n',
        "        path,\n",
        ["test_promise.py", "TheCalls.test_the_commit_is_refused"],
    ),
    (
        "the plan formula leaves a later phase's items ready",
        "track-items-plan-file.formula.toml",
        " Then `dep add` each item of a later phase to the phase before its own, because under some trackers a child does not take on its parent's needs",
        "",
        ["test_dotdiw.py", "ThePlanFormula.test_the_formula_writes_the_edge_and_verifies_it"],
    ),
    (
        "the plan formula takes the text out of the plan",
        "track-items-plan-file.formula.toml",
        "replace each checkbox with the item's issue id and keep the item's full text where it is, because not every tracker's `dotdiw show` prints a description.",
        "replace the checkbox sections with the item's issue id.",
        ["test_dotdiw.py", "ThePlanFormula.test_the_plan_file_keeps_each_items_text"],
    ),
    (
        "a local phase closes over its open items",
        "dotdiw",
        "    return needs + [c for c in children if c not in needs]\n",
        "    return needs\n",
        ["test_dotdiw.py", "ThePlanFormula.test_the_layout_keeps_the_order_under_local"],
    ),
    (
        "a check by path reads the installed file instead",
        "dotdiw",
        "    path = given or tracker_file(name)\n",
        "    path = tracker_file(name) or given\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_a_path_is_what_is_checked_when_the_name_is_also_installed",
        ],
    ),
    (
        "tracker new writes over a file",
        "dotdiw",
        '        with open(path, "x", encoding="utf-8") as fh:\n            fh.write(TRACKER_SKELETON',
        '        with open(path, "w", encoding="utf-8") as fh:\n            fh.write(TRACKER_SKELETON',
        [
            "test_dotdiw.py",
            "TheFileATrackerStartsFrom.test_what_it_refuses_is_one_line_and_writes_nothing",
        ],
    ),
    (
        "the starting file is edited by hand",
        "dotdiw",
        '    raise NotImplementedError("create_item")\n',
        "    pass\n",
        ["test_promise.py", "TheDoor.test_the_table_is_a_fresh_generation_from_the_idl"],
    ),
    (
        "a checkout on beads is told to install dotdiw again",
        "dotdiw",
        '"beads is not installed. Run: brew install beads"',
        '"dotdiw is not fully installed. Run: brew install adimpression/tap/dotdiw"',
        [
            "test_dotdiw.py",
            "WithoutTheBeadsBinary.test_choosing_beads_with_no_binary_writes_nothing",
        ],
    ),
    (
        "choosing beads with no binary goes on writing",
        "dotdiw",
        '    if made["status"] != "completed":\n        # Nothing was adopted, so there is nothing to declare work starts in.\n',
        '    if made["exitCode"] == 2:\n        # Nothing was adopted, so there is nothing to declare work starts in.\n',
        [
            "test_dotdiw.py",
            "WithoutTheBeadsBinary.test_choosing_beads_with_no_binary_writes_nothing",
        ],
    ),
    (
        "an operation that could not be tried says KeyError",
        "dotdiw",
        '            raise AssertionError("cannot be tried until operation.%s passes" % earlier)\n',
        "            raise KeyError(key)\n",
        [
            "test_dotdiw.py",
            "TheScenarioOnAnAdapterThatFails.test_a_later_operation_says_an_earlier_one_did_not_pass",
        ],
    ),
    (
        "the check runs on the checkout a hook is in",
        "dotdiw",
        'for k in git(["rev-parse", "--local-env-vars"]).split()',
        "for k in []",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_check_leaves_the_checkout_alone_when_git_dir_is_set",
        ],
    ),
    (
        "sys.exit on load ends the command",
        "dotdiw",
        "    except MODULE_MISTAKES as e:  # the module's mistake: one line, never a traceback\n",
        "    except Exception as e:  # the module's mistake: one line, never a traceback\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_module_that_exits_on_load_is_refused"],
    ),
    (
        "sys.exit in an operation ends the command",
        "dotdiw",
        "            hold_tracker_response(operation, name, response)\n        except MODULE_MISTAKES as e:\n",
        "            hold_tracker_response(operation, name, response)\n        except Exception as e:\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_an_operation_that_exits_fails_the_check"],
    ),
    (
        "sys.exit in an extra ends the command",
        "dotdiw",
        '        settle_exit_code("%s: the %s extra" % (name, extra), response)\n    except MODULE_MISTAKES as e:\n',
        '        settle_exit_code("%s: the %s extra" % (name, extra), response)\n    except Exception as e:\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_metrics_extra_that_exits_does_not_stop_the_work",
        ],
    ),
    (
        "init goes on after a tracker that did not open",
        "dotdiw",
        '    if made["status"] != "completed":\n        # Nothing was adopted, so there is nothing to declare work starts in.\n',
        '    if made["exitCode"] == 2 or made.get("reason") == "not-installed":\n        # Nothing was adopted, so there is nothing to declare work starts in.\n',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_init_stops_at_a_name_nothing_answers_to"],
    ),
    (
        "init says nothing when a store does not open",
        "dotdiw",
        '    elif response["status"] != "completed":\n        sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n    elif not response["created"]:\n',
        '    elif response["status"] != "completed":\n        pass\n    elif not response["created"]:\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_init_says_why_the_store_did_not_open_and_stops",
        ],
    ),
    (
        "a stock line replaces what the tracker said",
        "dotdiw",
        '            "summary": opened["summary"],\n            "workspace": ws,\n',
        '            "summary": "The tracker\'s init failed.",\n            "workspace": ws,\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_init_says_why_the_store_did_not_open_and_stops",
        ],
    ),
    (
        "an exit code left out stays out",
        "dotdiw",
        '        response["exitCode"] = 1 if failing else 0\n',
        "        pass\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_an_exit_code_left_out_is_read_from_the_status",
        ],
    ),
    (
        "an exit code against the status is believed",
        "dotdiw",
        "    elif failing == (code & 0xFF == 0):  # 256 is read as success by whatever ran this\n",
        "    elif False:\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_an_exit_code_against_the_status_is_refused"],
    ),
    (
        "an extra's exit code is not held",
        "dotdiw",
        '        settle_exit_code("%s: the %s extra" % (name, extra), response)\n',
        "",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_forward_extra_is_held_to_the_same_rule"],
    ),
    (
        "a module with nothing under the workspace is not adopted",
        "dotdiw",
        "    return adopted(ws) or (bool(name) and (name not in TRACKERS or is_loaded(TRACKERS[name])))\n",
        "    return adopted(ws)\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_module_that_keeps_nothing_under_the_workspace_is_adopted",
        ],
    ),
    (
        "a shipped tracker whose store is gone counts as adopted",
        "dotdiw",
        "    return adopted(ws) or (bool(name) and (name not in TRACKERS or is_loaded(TRACKERS[name])))\n",
        "    return adopted(ws) or bool(name)\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_shipped_tracker_with_no_store_is_still_not_adopted",
        ],
    ),
    (
        "a choice that was not written is reported as written",
        "dotdiw",
        '        if tracker_name(root) != name:\n            return {\n                "status": "failed",\n                "summary": NOT_WRITTEN % TRACKER_KEY,\n',
        '        if False:\n            return {\n                "status": "failed",\n                "summary": NOT_WRITTEN % TRACKER_KEY,\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_use_says_when_the_choice_could_not_be_written",
        ],
    ),
    (
        "a store that answers no path gives a traceback",
        "dotdiw",
        "        except MODULE_MISTAKES:  # a module's mistake must not stop another adapter answering\n",
        "        except OSError:\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_store_that_answers_no_path_is_no_traceback",
        ],
    ),
    (
        "a module says where it came from",
        "dotdiw",
        '        info["origin"], info["source"] = "loaded", path  # what the loader knows, not the module\n',
        '        info.setdefault("origin", "loaded")\n        info.setdefault("source", path)\n',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_module_cannot_say_it_shipped"],
    ),
    (
        "a failed create says nothing",
        "dotdiw",
        '    elif response["status"] != "completed":\n        sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n    elif response.get("workRef"):\n',
        '    elif response.get("workRef"):\n',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_failed_create_says_why"],
    ),
    (
        "a dataclass in a module fails to load",
        "dotdiw",
        "    sys.modules[loader.name] = module  # a dataclass looks its module up by name\n",
        "",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_module_may_use_the_whole_standard_library"],
    ),
    (
        "the check with nowhere to run gives a traceback",
        "dotdiw",
        '        except OSError as e:\n            return {\n                "status": "failed",\n                "summary": "The check has nowhere to run: %s" % e,\n',
        '        except ZeroDivisionError as e:\n            return {\n                "status": "failed",\n                "summary": "The check has nowhere to run: %s" % e,\n',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_the_check_with_nowhere_to_work_is_one_line"],
    ),
    (
        "python -O passes a check",
        "dotdiw",
        "        if not condition:\n            raise AssertionError(detail)  # not an assert: python -O must not pass a check\n",
        "        assert condition, detail\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_the_check_is_not_fooled_under_optimisation"],
    ),
    (
        "a file that gives no adapter runs again",
        "dotdiw",
        "    if given is None and name in LOAD_TRIED:\n        return False\n",
        "",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_file_that_is_no_adapter_runs_once_in_a_command",
        ],
    ),
    (
        "glob characters in the home hide a module",
        "dotdiw",
        'glob.glob(os.path.join(glob.escape(d), "*.py"))',
        'glob.glob(os.path.join(d, "*.py"))',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_glob_characters_in_the_home_hide_nothing"],
    ),
    (
        "an interface that is not a number reads as the same one",
        "dotdiw",
        "was written for tracker interface %r;",
        "was written for tracker interface %s;",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_number_that_is_not_a_number_says_so"],
    ),
    (
        "the scenario takes a need refused when it is already there",
        "dotdiw",
        'ask("add-need", id=held["c"], needs=held["b"])["status"] == "completed",',
        "True,",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario does not read scope",
        "dotdiw",
        '                {i["id"] for i in scoped.get("items") or []}\n                == {held["a"], held["c"], held["d"], held["e"]},\n',
        "                True,\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario does not read limit",
        "dotdiw",
        '        expect(len(ask("list-items", scope="all", limit=1).get("items") or []) == 1, "limit limits")\n',
        "",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario takes any status",
        "dotdiw",
        'ask("update-item", id=held["c"], status="no-such-status").get("reason") == "bad-status",',
        "True,",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario takes a poured root of any kind",
        "dotdiw",
        '        expect(shown["item"].get("kind") == "root", "the root is of kind root")\n',
        '        expect(True, "the root is of kind root")\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario takes a created item of kind root",
        "dotdiw",
        '(b["item"].get("kind", "task"), b["item"].get("priority")) == ("task", 2),',
        "True,",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "--at with nothing after it writes here",
        "dotdiw",
        '            if name and at != "":\n',
        "            if name:\n",
        ["test_dotdiw.py", "TheFileATrackerStartsFrom.test_at_with_nothing_after_it_is_refused"],
    ),
    (
        "steps from a tracker that is gone become placeholders",
        "dotdiw",
        '        if listed["status"] != "completed":\n            reason = "not-installed"',
        '        if False:\n            reason = "not-installed"',
        [
            "test_dotdiw.py",
            "WithoutTheBeadsBinary.test_steps_from_work_on_a_tracker_that_is_gone_says_so",
        ],
    ),
    (
        "a second open re-points a Jira checkout",
        "trackers/jira.py",
        '        (project_of(root) if not created else None)  # a second open changes nothing\n        or (request.get("prefix") or "").upper()\n',
        '        (request.get("prefix") or "").upper()\n        or (project_of(root) if not created else None)\n',
        ["test_jira.py", "TheHostedAdapter.test_a_second_open_changes_nothing"],
    ),
    (
        "the guide's table drifts from the starting file",
        "trackers/README.md",
        '"operation.describe-tracker": describe_tracker,',
        '"operation.describe-tracker": describe,',
        ["test_promise.py", "TheTrackerDoor.test_the_guide_fills_the_table_of_the_starting_file"],
    ),
    (
        "an old tree moves a checkout off its module",
        "dotdiw",
        "    if in_tree and not checkout_adopted(root) and not apply:\n",
        "    if in_tree and not adopted(ws) and not apply:\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_an_old_tree_does_not_move_a_checkout_off_its_module",
        ],
    ),
    (
        "the conventions are not checked under a module that keeps nothing",
        "dotdiw",
        '    if checkout_adopted(root):\n        if git(["ls-files", "-z", "--", ".beads"], root):\n',
        '    if adopted(workspace(root)):\n        if git(["ls-files", "-z", "--", ".beads"], root):\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_conventions_are_checked_under_a_module_that_keeps_nothing",
        ],
    ),
    (
        "the check of beads runs in the worker's directory",
        "dotdiw",
        "        os.chdir(scratch)\n",
        "",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_check_of_beads_leaves_the_checkout_as_it_was",
        ],
    ),
    (
        "a name only asked for adopts a checkout",
        "dotdiw",
        "    name = tracker_name(root)\n    return adopted(ws) or",
        '    name = tracker_name(root) or "acme"\n    return adopted(ws) or',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_name_only_asked_for_does_not_adopt_a_checkout",
        ],
    ),
    (
        "create drops what the adapter said",
        "dotdiw",
        '        "summary": "Named %s." % (work or "the work") if code == 0 else made["summary"],\n',
        '        "summary": "Named %s." % (work or "the work") if code == 0 else "The tracker refused the create.",\n',
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_failed_create_says_what_the_adapter_said"],
    ),
    (
        "a forward extra's failure says nothing",
        "dotdiw",
        '            sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n        else:\n            sys.stdout.write(',
        "            pass\n        else:\n            sys.stdout.write(",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_forward_extra_that_prints_nothing_is_shown",
        ],
    ),
    (
        "a forward extra's output is not shown",
        "dotdiw",
        '            sys.stdout.write(response.get("output") or "")\n',
        "            pass\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_forward_extra_that_prints_nothing_is_shown",
        ],
    ),
    (
        "a failure of use is said twice",
        "dotdiw",
        '    if request.get("quiet"):\n        return  # whoever asked quietly says what it has to say\n',
        "",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_failure_of_use_is_said_once"],
    ),
    (
        "a tracker that cannot answer gives placeholder steps",
        "dotdiw",
        '        if listed["status"] != "completed":\n            reason = "not-installed"',
        '        if listed.get("reason") == "not-installed":\n            reason = "not-installed"',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_steps_from_work_are_refused_when_the_tracker_cannot_answer",
        ],
    ),
    (
        "an exit code of 256 passes as a failure",
        "dotdiw",
        "    elif failing == (code & 0xFF == 0):  # 256 is read as success by whatever ran this\n",
        "    elif failing == (code == 0):\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_an_exit_code_git_would_read_as_zero_is_refused",
        ],
    ),
    (
        "a second init changes the prefix under local",
        "dotdiw",
        "\"INSERT OR IGNORE INTO meta (key, value) VALUES ('prefix', ?)\", (prefix,)",
        "\"INSERT OR REPLACE INTO meta (key, value) VALUES ('prefix', ?)\", (prefix,)",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_second_init_keeps_the_prefix_under_local"],
    ),
    (
        "a pin that was not written is said to be",
        "dotdiw",
        "            if tracker_name(root) == pinned:\n                done.append(\n",
        "            if True:\n                done.append(\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_choice_that_could_not_be_pinned_is_not_said_to_be",
        ],
    ),
    (
        "formula new takes a flag with nothing after it",
        "dotdiw",
        '        if at == "" or frm == "":\n            title = ""  # says how it is used, as no title does\n',
        "",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_formula_new_with_a_flag_and_nothing_after_it_is_refused",
        ],
    ),
    (
        "a priority that is no number gives a traceback",
        "dotdiw",
        '                    if field == "priority" and not value.isdigit():\n',
        "                    if False:\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_priority_that_is_no_number_is_one_line"],
    ),
    (
        "the scenario reads a parent only with scope all",
        "dotdiw",
        'closed not in {i["id"] for i in ask("list-items", parent=held["a"]).get("items") or []}\n            and not ask("list-items", parent=held["a"]).get("items"),\n',
        "True,\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "a broken close reads as a broken list",
        "dotdiw",
        '        closed = held["closed"]\n',
        '        closed = held.get("closed")\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_failed_close_does_not_read_as_a_failed_list",
        ],
    ),
    (
        "any refusal under a parent is called a missing parent",
        "trackers/jira.py",
        ' and e.status in (400, 404) and fetch(request["parent"]) is None:\n',
        " and e.status in (400, 404):\n",
        ["test_jira.py", "TheHostedAdapter.test_a_pour_jira_refuses_partway_is_one_line"],
    ),
    (
        "formula pour stops answering",
        "dotdiw",
        'if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("formula", "mol"):',
        'if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("mol",):',
        ["test_dotdiw.py", "TheWordFormulaPour.test_it_pours_the_formula"],
    ),
    (
        "mol pour stops working once there is formula pour",
        "dotdiw",
        'if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("formula", "mol"):',
        'if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("formula",):',
        ["test_dotdiw.py", "TheWordFormulaPour.test_both_spellings_print_the_same"],
    ),
    (
        "formula pour drops --json",
        "dotdiw",
        '                    "json": bool(fields.get("json")),\n',
        '                    "json": False,\n',
        ["test_dotdiw.py", "TheWordFormulaPour.test_json_after_the_formula_prints_the_record"],
    ),
    (
        "formula pour with no formula is not told how it is used",
        "dotdiw",
        'if argv[:2] == ["formula", "pour"] and (len(argv) < 3 or argv[2].startswith("-")):',
        "if False:",
        ["test_dotdiw.py", "TheWordFormulaPour.test_with_no_formula_it_says_how_it_is_used"],
    ),
    (
        "create teaches mol pour where it should say formula pour",
        "dotdiw",
        '        "  Run it: %s formula pour %s"\n',
        '        "  Run it: %s mol pour %s"\n',
        ["test_dotdiw.py", "TheWordFormulaPour.test_what_dotdiw_prints_teaches_it"],
    ),
    (
        "formula list teaches mol pour where it should say formula pour",
        "dotdiw",
        'print("\\nRun one: %s formula pour <id>" % PROG)',
        'print("\\nRun one: %s mol pour <id>" % PROG)',
        ["test_dotdiw.py", "TheWordFormulaPour.test_what_dotdiw_prints_teaches_it"],
    ),
    (
        "learn teaches mol pour where it should say formula pour",
        "dotdiw",
        "   Run a formula:  %(p)s formula pour <formula-id>\n",
        "   Run a formula:  %(p)s mol pour <formula-id>\n",
        ["test_dotdiw.py", "TheWordFormulaPour.test_what_dotdiw_prints_teaches_it"],
    ),
    (
        "the declaration says formula pour and rewrites every adopted checkout",
        "dotdiw",
        "    %(p)s mol pour <id>    instantiate one as tracked, ordered steps\n",
        "    %(p)s formula pour <id>    instantiate one as tracked, ordered steps\n",
        ["test_dotdiw.py", "TheWordFormulaPour.test_the_declaration_stays_as_0_7_0_wrote_it"],
    ),
    (
        "mol pour prints a notice beside formula pour",
        "dotdiw",
        '    if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("formula", "mol"):\n',
        '    if len(argv) > 2 and argv[1] == "pour" and argv[0] in ("formula", "mol"):\n'
        '        if argv[0] == "mol":\n'
        '            sys.stderr.write("mol pour is now formula pour\\n")\n',
        ["test_dotdiw.py", "TheWordFormulaPour.test_both_spellings_print_the_same"],
    ),
    (
        "learn claims you never type anything else",
        "dotdiw",
        "adds the fourth and puts the tracker behind one command, so you never type the\n"
        "tracker's own name.\n",
        "adds the fourth and puts all of them under one name, so you never type\nanything else.\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_learn_claims_only_the_trackers_own_name"],
    ),
    (
        "init does not say who a checked tracker acts as",
        "dotdiw",
        'if actor.get("verified"):',
        "if False:",
        ["test_dotdiw.py", "WhoATrackerActsAs.test_a_checked_name_is_said_once_at_init"],
    ),
    (
        "init names someone nobody checked",
        "dotdiw",
        'if actor.get("verified"):',
        "if actor:",
        ["test_dotdiw.py", "WhoATrackerActsAs.test_a_name_nobody_checked_is_not_said"],
    ),
    (
        "tracker use does not say who it acts as",
        "dotdiw",
        '    show_actor(response)\n    if response.get("previous"):\n',
        '    if response.get("previous"):\n',
        [
            "test_dotdiw.py",
            "WhoATrackerActsAs.test_a_checked_name_is_said_each_time_a_tracker_is_chosen",
        ],
    ),
    (
        "tracker use loses who the adoption asked",
        "dotdiw",
        '    actor = made.get("actor")\n',
        "    actor = None\n",
        [
            "test_dotdiw.py",
            "WhoATrackerActsAs.test_a_checked_name_is_said_each_time_a_tracker_is_chosen",
        ],
    ),
    (
        "tracker use asks nobody of a store already open",
        "dotdiw",
        '    if not made.get("created"):\n',
        "    if False:\n",
        ["test_jira.py", "TheHostedAdapter.test_tracker_use_names_the_account_and_never_its_email"],
    ),
    (
        "beads calls the name bd records checked",
        "dotdiw",
        'return {"name": name, "verified": False} if name else None',
        'return {"name": name, "verified": True} if name else None',
        ["test_dotdiw.py", "TheBeadsAdapter.test_it_says_who_bd_records_and_that_nobody_checked"],
    ),
    (
        "beads keeps the word me",
        "dotdiw",
        '            value = actor["name"] if actor else value\n',
        "            value = value\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_an_assignee_of_me_is_the_name_bd_records"],
    ),
    (
        "beads keeps the word me when it is typed with an equals sign",
        "dotdiw",
        '        out[at] = flag + "=" + value if at == i else value\n',
        "        out[at] = a if at == i else value\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_an_assignee_of_me_under_beads_is_the_name_bd_records",
        ],
    ),
    (
        "beads keeps the word me in an update as typed",
        "dotdiw",
        '    if args[:1] == ["update"]:\n',
        "    if False:\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_an_assignee_of_me_under_beads_is_the_name_bd_records",
        ],
    ),
    (
        "the record leaves the assignee out under local",
        "dotdiw",
        '        "assignee": row["assignee"],\n',
        "",
        ["test_dotdiw.py", "TheLocalAdapter.test_an_assignee_reads_back"],
    ),
    (
        "the record leaves the assignee out under beads",
        "dotdiw",
        '        "assignee": row.get("assignee"),\n',
        "",
        ["test_dotdiw.py", "TheBeadsAdapter.test_an_assignee_reads_back"],
    ),
    (
        "show hides who an item is assigned to",
        "dotdiw",
        'print("Assignee: %s" % item["assignee"])',
        "pass",
        ["test_dotdiw.py", "TheLocalCommandLine.test_show_says_who_an_item_is_assigned_to"],
    ),
    (
        "a move says nothing of the assignees it left",
        "dotdiw",
        '    left = response.get("assigneesLeft")\n',
        "    left = None\n",
        ["test_dotdiw.py", "WhoATrackerActsAs.test_a_move_says_how_many_assignees_it_left"],
    ),
    (
        "a move counts every item as having an assignee",
        "dotdiw",
        '"assigneesLeft": sum(1 for i in items if i.get("assignee")),',
        '"assigneesLeft": len(items),',
        ["test_dotdiw.py", "WhoATrackerActsAs.test_a_move_with_no_assignee_says_nothing_of_them"],
    ),
    (
        "jira sends the word me as an account id",
        "trackers/jira.py",
        'who = myself().get("accountId") if request["assignee"] == "me" else request["assignee"]',
        'who = request["assignee"]',
        ["test_jira.py", "TheHostedAdapter.test_an_assignee_of_me_is_the_account_behind_the_token"],
    ),
    (
        "jira shows the email address as the name",
        "trackers/jira.py",
        '"name": mine.get("displayName") or ident',
        '"name": mine.get("emailAddress") or ident',
        ["test_jira.py", "TheHostedAdapter.test_init_names_the_account_once_and_never_its_email"],
    ),
    (
        "jira does not ask for the assignee",
        "trackers/jira.py",
        'created,updated,comment,assignee,"',
        'created,updated,comment,"',
        ["test_jira.py", "TheHostedAdapter.test_an_assignee_of_me_is_the_account_behind_the_token"],
    ),
    (
        "a site that will not say who loses the tracker line of --version",
        "trackers/jira.py",
        '    except JiraError:\n        return None\n    ident = mine.get("accountId")\n',
        '    except ValueError:\n        return None\n    ident = mine.get("accountId")\n',
        ["test_jira.py", "TheHostedAdapter.test_a_site_that_will_not_say_who_leaves_the_line_out"],
    ),
    (
        "local answers a root as molecule",
        "dotdiw",
        '        "kind": "root" if row["kind"] in ("root", "molecule") else "task",\n',
        '        "kind": "molecule" if row["kind"] in ("root", "molecule") else "task",\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "an old store's molecule root reads as a task",
        "dotdiw",
        '        "kind": "root" if row["kind"] in ("root", "molecule") else "task",\n',
        '        "kind": "root" if row["kind"] == "root" else "task",\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_before_1_0_reads_its_molecule_roots_as_root",
        ],
    ),
    (
        "an old store's molecule root stays open after its last step",
        "dotdiw",
        '            and parent["kind"] in ("root", "molecule")\n',
        '            and parent["kind"] == "root"\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_before_1_0_reads_its_molecule_roots_as_root",
        ],
    ),
    (
        "a root local pours stays open after its last step",
        "dotdiw",
        '            and parent["kind"] in ("root", "molecule")\n',
        '            and parent["kind"] == "molecule"\n',
        ["test_dotdiw.py", "TheLocalAdapter.test_a_poured_root_closes_with_its_last_step"],
    ),
    (
        "beads answers its own type for a root",
        "dotdiw",
        '        "kind": "root" if row.get("issue_type") == "molecule" else "task",\n',
        '        "kind": row.get("issue_type") or "task",\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads makes its root an epic",
        "dotdiw",
        '    argv = ["create", "--title=" + request["title"], "--type=molecule", "--priority=2", "--json"]\n',
        '    argv = ["create", "--title=" + request["title"], "--type=epic", "--priority=2", "--json"]\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira answers a root as an epic",
        "trackers/jira.py",
        '    kind = "root" if "root" in labels else "task"\n',
        '    kind = "epic" if "root" in labels else "task"\n',
        ["test_jira.py", "TheHostedAdapter.test_it_passes_the_check_from_where_a_package_puts_it"],
    ),
    (
        "jira does not label its root",
        "trackers/jira.py",
        '        "labels": ["root"] if root else [],\n',
        '        "labels": [],\n',
        ["test_jira.py", "TheHostedAdapter.test_it_passes_the_check_from_where_a_package_puts_it"],
    ),
    (
        "a kind is passed to create-item",
        "dotdiw",
        '            "parent": request.get("parent"),\n        },\n    )\n    code = made.get("exitCode", 0 if made["status"] == "completed" else 1)\n',
        '            "parent": request.get("parent"),\n            "kind": "task",\n        },\n    )\n    code = made.get("exitCode", 0 if made["status"] == "completed" else 1)\n',
        ["test_promise.py", "TheTrackerDoor.test_create_item_takes_no_kind"],
    ),
    (
        "a move asks for the kind it read",
        "dotdiw",
        '                "title": item["title"],\n                "priority": item.get("priority"),\n',
        '                "title": item["title"],\n                "kind": item.get("kind"),\n                "priority": item.get("priority"),\n',
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "a file written for interface 1 loads",
        "dotdiw",
        "    if declared != TRACKER_INTERFACE or isinstance(declared, bool):\n",
        "    if declared not in (1, TRACKER_INTERFACE) or isinstance(declared, bool):\n",
        ["test_promise.py", "TheTrackerDoor.test_a_module_says_which_interface_it_was_written_for"],
    ),
    (
        "a module that does not say its interface loads",
        "dotdiw",
        "        declared = 1  # written",
        "        declared = TRACKER_INTERFACE  # written",
        ["test_promise.py", "TheTrackerDoor.test_a_module_says_which_interface_it_was_written_for"],
    ),
    (
        "the notice skips a parent built by hand",
        "dotdiw",
        '        if p.get("kind") == "root":\n            continue\n        if len(ks) < HANDMADE_STEPS:\n',
        '        if p.get("kind") in ("root", "task"):\n            continue\n        if len(ks) < HANDMADE_STEPS:\n',
        [
            "test_dotdiw.py",
            "TheLocalCommandLine.test_the_notice_names_a_parent_built_by_hand_and_never_a_root",
        ],
    ),
    (
        "the notice names a poured root",
        "dotdiw",
        '        if p.get("kind") == "root":\n            continue\n        if len(ks) < HANDMADE_STEPS:\n',
        "        if False:\n            continue\n        if len(ks) < HANDMADE_STEPS:\n",
        [
            "test_dotdiw.py",
            "TheLocalCommandLine.test_the_notice_names_a_parent_built_by_hand_and_never_a_root",
        ],
    ),
    (
        "a poured root's title seeds a new formula's examples",
        "dotdiw",
        '        if r.get("kind") == "root":\n            continue\n        t = " ".join(str(r.get("title") or "").split())\n',
        '        t = " ".join(str(r.get("title") or "").split())\n',
        [
            "test_dotdiw.py",
            "TheLocalCommandLine.test_formula_new_seeds_named_work_and_never_a_root",
        ],
    ),
    (
        "the scenario takes a step of any kind",
        "dotdiw",
        '            all(k.get("kind", "task") == "task" for k in shown.get("children") or []),\n',
        "            True,\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "verify-using is matched",
        "dotdiw",
        '        rows = [(f["words"], f["where"], f["desc"], " ".join(f["examples"])) for f in forms]\n',
        '        rows = [(f["words"], f["where"], f["desc"] + " " + " ".join(f.get("verifyUsing") or []), " ".join(f["examples"])) for f in forms]\n',
        ["test_dotdiw.py", "TheMeansToProveARun.test_the_means_are_never_run_or_matched"],
    ),
    (
        "a command in verify-using is run",
        "dotdiw",
        '        print("Verify using:")\n        for value in means:\n            print("  %s" % value)\n',
        '        print("Verify using:")\n        for value in means:\n            print("  %s" % value)\n            if value.startswith("run:"):\n                os.system(value[4:])\n',
        ["test_dotdiw.py", "TheMeansToProveARun.test_the_means_are_never_run_or_matched"],
    ),
    (
        "the means are not shown after a pour",
        "dotdiw",
        '    means = response.get("verifyUsing") or []\n',
        "    means = []\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_a_pour_shows_the_means_and_the_root_keeps_them",
        ],
    ),
    (
        "the formula's description is not handed to pour-steps",
        "dotdiw",
        '            "description": formula.get("desc") or None,\n',
        '            "description": None,\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_a_pour_shows_the_means_and_the_root_keeps_them",
        ],
    ),
    (
        "the means are not handed to pour-steps",
        "dotdiw",
        '            "verifyUsing": list(formula.get("verifyUsing") or []),\n        },\n',
        '            "verifyUsing": [],\n        },\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_a_pour_shows_the_means_and_the_root_keeps_them",
        ],
    ),
    (
        "local keeps no means on its root",
        "dotdiw",
        '                    request["title"],\n                    request.get("description"),\n                    json.dumps(means) if means else None,\n',
        '                    request["title"],\n                    request.get("description"),\n                    None,\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no means back",
        "dotdiw",
        '        item["verifyUsing"] = [str(m) for m in json.loads(kept)]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads keeps no means on a root it makes",
        "dotdiw",
        '    if means:\n        argv += ["--metadata=" + beads_means({}, means)]\n    code, out, err = beads_quiet(argv, root)\n    rows = beads_json(out) if code == 0 else []\n',
        '    if False:\n        argv += ["--metadata=" + beads_means({}, means)]\n    code, out, err = beads_quiet(argv, root)\n    rows = beads_json(out) if code == 0 else []\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads reads no means back",
        "dotdiw",
        '    means = (beads_own(row) or {}).get("verifyUsing")\n',
        "    means = None\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira keeps no means on its root",
        "trackers/jira.py",
        '            "verifyUsing": list(request.get("verifyUsing") or []),\n        },\n        root=True,\n',
        "        },\n        root=True,\n",
        ["test_jira.py", "TheHostedAdapter.test_it_passes_the_check_from_where_a_package_puts_it"],
    ),
    (
        "jira reads no means back",
        "trackers/jira.py",
        '    description, means = read_verify_using(\n        plain(f["description"]) if f.get("description") else None\n    )\n',
        '    description, means = (plain(f["description"]) if f.get("description") else None), []\n',
        ["test_jira.py", "TheHostedAdapter.test_it_passes_the_check_from_where_a_package_puts_it"],
    ),
    (
        "check misses a file git does not track",
        "dotdiw",
        '            if path not in tracked and not any(p.startswith(path + "/") for p in tracked):\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_check_holds_a_file_of_this_repository_to_being_tracked",
        ],
    ),
    (
        "check holds another repository's file to this one",
        "dotdiw",
        '            if repository_of(url[len("git+") :]) not in remotes:\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_check_holds_a_file_of_this_repository_to_being_tracked",
        ],
    ),
    (
        "a remote in scp form names another repository",
        "dotdiw",
        '    if not m:\n        m = re.match(r"(?:[^@/]*@)?([^:/]+):(.*)", url)\n',
        '    if False:\n        m = re.match(r"(?:[^@/]*@)?([^:/]+):(.*)", url)\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_check_holds_a_file_of_this_repository_to_being_tracked",
        ],
    ),
    (
        "a value longer than a line is read",
        "dotdiw",
        '    if "\\n" in value or "\\r" in value:\n',
        "    if False:\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_names_a_value_it_cannot_read"],
    ),
    (
        "a value in none of the forms is read",
        "dotdiw",
        '    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*://", value):\n        return None\n',
        "    if True:\n        return None\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_names_a_value_it_cannot_read"],
    ),
    (
        "run: with no command is read",
        "dotdiw",
        "        return None if value[4:].strip() else 'verify-using value \"run:\" names no command'\n",
        "        return None\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_names_a_value_it_cannot_read"],
    ),
    (
        "a repository named with no file is read",
        "dotdiw",
        '        if value.partition("#")[2].strip("/ "):\n            return None\n',
        "        if True:\n            return None\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_names_a_value_it_cannot_read"],
    ),
    (
        "a value that is not text is read",
        "dotdiw",
        '    if not isinstance(value, str) or not value.strip():\n        return "verify-using holds a value that is not text"\n',
        '    if False:\n        return "verify-using holds a value that is not text"\n',
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_names_a_value_it_cannot_read"],
    ),
    (
        "tracker check does not hold the round trip",
        "dotdiw",
        '            (shown["item"].get("description"), shown["item"].get("verifyUsing")) == (said, means),\n',
        "            True,\n",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "formula list leaves the means out of its JSON",
        "dotdiw",
        '                        **({"verifyUsing": f["verifyUsing"]} if f.get("verifyUsing") else {}),\n',
        "",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_formula_list_carries_them_in_json_and_keeps_its_line",
        ],
    ),
    (
        "the starting file's helper reads no means back",
        "dotdiw",
        "    return description + NEWLINE * 2 + VERIFY_HEADING\n",
        "    return description\n",
        ["test_promise.py", "TheTrackerDoor.test_every_copy_of_the_helper_reads_back_what_it_kept"],
    ),
    (
        "a move drops the description",
        "dotdiw",
        '                "description": whole.get("description"),\n',
        '                "description": None,\n',
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "a move drops the means",
        "dotdiw",
        '                "verifyUsing": list(whole.get("verifyUsing") or []) or None,\n',
        '                "verifyUsing": None,\n',
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "a move reads an item from the listing alone",
        "dotdiw",
        '        whole = shown["item"]\n',
        "        whole = item\n",
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "local keeps no means on an item it creates",
        "dotdiw",
        '                    parent,\n                    request.get("description"),\n                    json.dumps(means) if means else None,\n',
        '                    parent,\n                    request.get("description"),\n                    None,\n',
        ["test_dotdiw.py", "TheLocalAdapter.test_the_means_are_kept_in_a_column_of_their_own"],
    ),
    (
        "beads keeps no means on an item it creates",
        "dotdiw",
        '    if means:\n        argv += ["--metadata=" + beads_means({}, means)]\n    code, out, err = beads_quiet(argv, root)\n    if code != 0:\n',
        '    if False:\n        argv += ["--metadata=" + beads_means({}, means)]\n    code, out, err = beads_quiet(argv, root)\n    if code != 0:\n',
        ["test_dotdiw.py", "TheBeadsMetadata.test_the_means_are_kept_in_the_issues_metadata"],
    ),
    (
        "jira writes an issue's description raw",
        "trackers/jira.py",
        '    description = keep_verify_using(\n        request.get("description"), list(request.get("verifyUsing") or [])\n    )\n',
        '    description = request.get("description")\n',
        ["test_jira.py", "TheHostedAdapter.test_it_passes_the_check_from_where_a_package_puts_it"],
    ),
    (
        "the helper reads a description's own section as the means",
        "dotdiw",
        '    if not description or read_verify_using(description) == (description, []):\n        return description\n    return description + "\\n\\n" + VERIFY_HEADING\n',
        "    return description\n",
        ["test_promise.py", "TheTrackerDoor.test_every_copy_of_the_helper_reads_back_what_it_kept"],
    ),
    (
        "the helper takes the first section for the means",
        "dotdiw",
        '    at = text.rfind("\\n\\n" + VERIFY_HEADING)\n',
        '    at = text.find("\\n\\n" + VERIFY_HEADING)\n',
        ["test_promise.py", "TheTrackerDoor.test_every_copy_of_the_helper_reads_back_what_it_kept"],
    ),
    (
        "jira's helper reads a description's own section as the means",
        "trackers/jira.py",
        '    if not description or read_verify_using(description) == (description, []):\n        return description\n    return description + "\\n\\n" + VERIFY_HEADING\n',
        "    return description\n",
        ["test_promise.py", "TheTrackerDoor.test_every_copy_of_the_helper_reads_back_what_it_kept"],
    ),
    (
        "the benchmark compares no ids",
        "measurements/measure/rank_between.py",
        'ids = [f.get("formulaRef") for f in answer.get("surfaced") or []]',
        'ids = [f.get("formula") for f in answer.get("surfaced") or []]',
        ["test_promise.py", "TheRankingBenchmark.test_the_benchmark_compares_formula_ids"],
    ),
    (
        "the benchmark takes a ranking of nothing",
        "measurements/measure/rank_between.py",
        "        if not all(isinstance(i, str) and i for i in ids):\n",
        "        if False:\n",
        ["test_promise.py", "TheRankingBenchmark.test_the_benchmark_compares_formula_ids"],
    ),
    (
        "beads reads a value as an option",
        "dotdiw",
        "        i = at + 1\n",
        "        i += 1\n",
        ["test_dotdiw.py", "TheArgumentsBeadsIsGiven.test_a_value_is_never_read_as_an_option"],
    ),
    (
        "a create asks bd for a root",
        "dotdiw",
        '        if flag in ("-t", "--type") and value.strip().lower() == "molecule":\n',
        "        if False:\n",
        ["test_dotdiw.py", "TheArgumentsBeadsIsGiven.test_only_a_pour_makes_a_root"],
    ),
    (
        "an update asks bd for a root",
        "dotdiw",
        '        args, refused = beads_typed(args, request.get("root"))\n',
        '        args, refused = beads_typed(args, request.get("root"))[0], None\n',
        ["test_dotdiw.py", "TheArgumentsBeadsIsGiven.test_only_a_pour_makes_a_root"],
    ),
    (
        "the pass-through rewrites a typed description",
        "dotdiw",
        '            value = actor["name"] if actor else value\n        out[at] = flag + "=" + value if at == i else value\n',
        '            value = actor["name"] if actor else value\n        elif flag in ("-d", "--description"):\n            value = keep_verify_using(value, []) or ""\n        out[at] = flag + "=" + value if at == i else value\n',
        ["test_dotdiw.py", "TheArgumentsBeadsIsGiven.test_a_typed_description_reads_back_as_typed"],
    ),
    (
        "local storage reads a directory whose name starts with a dot",
        "dotdiw",
        '        dirs[:] = sorted(d for d in dirs if not d.startswith("."))\n',
        "        dirs[:] = sorted(dirs)\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_local_storage_leaves_out_dot_directories_and_symbolic_links",
        ],
    ),
    (
        "local storage follows a symbolic link",
        "dotdiw",
        '            if not name.endswith((".formula.toml", ".formula.json")) or os.path.islink(path):\n',
        '            if not name.endswith((".formula.toml", ".formula.json")):\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_local_storage_leaves_out_dot_directories_and_symbolic_links",
        ],
    ),
    (
        "local storage leaves out a formula git does not track",
        "dotdiw",
        "    rels = [os.path.relpath(p, root) for p in formula_files(root)]\n",
        '    rels = [os.path.relpath(p, root) for p in formula_files(root) if git(["ls-files", "--", p], root)]\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_an_uncommitted_formula_is_found_and_named_as_unshared",
        ],
    ),
    (
        "a provider's formula is listed without its suffix",
        "dotdiw",
        '                    "formulaRef": "%s-%s" % (ident, name),\n',
        '                    "formulaRef": ident,\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_formula_carries_its_suffix_and_says_where_it_comes_from",
        ],
    ),
    (
        "a list of local formulas says in this repo",
        "dotdiw",
        '        print("%d formula%s:" % (len(forms), "" if len(forms) == 1 else "s"))\n',
        '        print("%d formula%s in this repo:" % (len(forms), "" if len(forms) == 1 else "s"))\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_a_list_of_local_formulas_has_the_one_header"],
    ),
    (
        "a module without show loads as a provider",
        "dotdiw",
        '        callable(operations.get(k)) for k in ("describe", "list", "show")\n',
        '        callable(operations.get(k)) for k in ("describe", "list")\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_registration_refuses_in_one_line_and_registers_nothing",
        ],
    ),
    (
        "a provider that declares list alone is registered",
        "dotdiw",
        '    if "list" not in answers or "show" not in answers:\n',
        "    if False:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_registration_refuses_in_one_line_and_registers_nothing",
        ],
    ),
    (
        "a provider name of other characters is registered",
        "dotdiw",
        "    if not re.fullmatch(PROVIDER_NAME, name):\n",
        "    if False:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_registration_refuses_in_one_line_and_registers_nothing",
        ],
    ),
    (
        "a taken provider name is registered over",
        "dotdiw",
        "        return next((n for n in names if n.lower() == name.lower()), None)\n",
        "        return next((n for n in names if n == name + name), None)\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_registration_refuses_in_one_line_and_registers_nothing",
        ],
    ),
    (
        "a provider is registered over a clashing local formula",
        "dotdiw",
        '                if not f.get("provider") and f["id"].endswith("-" + name)\n',
        "                if False\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_registration_waits_for_a_clashing_local_formula_to_migrate",
        ],
    ),
    (
        "check is silent on a local formula that reads like a provider's",
        "dotdiw",
        '            if f["id"].endswith("-" + name):\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_check_names_a_local_formula_that_reads_like_a_provider_formula",
        ],
    ),
    (
        "a failing provider is left out without a word",
        "dotdiw",
        '            left_out.append(listed["summary"])\n            continue\n',
        "            continue\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_a_failing_provider_is_left_out_in_one_line"],
    ),
    (
        "a removed provider stays registered",
        "dotdiw",
        '        entry = registry["providers"].pop(name, None)\n',
        '        entry = registry["providers"].get(name)\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_the_providers_list_and_remove"],
    ),
    (
        "a provider's formula is listed as data without its provider",
        "dotdiw",
        '                        **({"provider": f["provider"]} if f.get("provider") else {}),\n',
        "",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_formula_carries_its_suffix_and_says_where_it_comes_from",
        ],
    ),
    (
        "learn leaves out registering a provider",
        "dotdiw",
        "  %(p)s formula provider register <name> <module> [--at <location>]\n",
        "",
        ["test_dotdiw.py", "TheFormulaProviders.test_learn_names_the_provider_commands"],
    ),
    (
        "the conventions say an uncommitted formula is not found",
        "dotdiw",
        "hold: it is\nfound on your file system alone, nobody else's `create` reaches it, and `check`\n",
        "hold: it does\nnot appear in `formula list`, nothing matches it against a title, and `check`\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_the_conventions_say_where_an_uncommitted_formula_is_found",
        ],
    ),
    (
        "each question in a run asks the providers again",
        "dotdiw",
        '        if name not in LISTED:\n            LISTED[name] = invoke("operation.list-provider-formulas", {"name": name})\n        listed = LISTED[name]\n',
        '        listed = invoke("operation.list-provider-formulas", {"name": name})\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_a_rebuilt_index_asks_no_provider_again"],
    ),
    (
        "a provider's id that is a path or a command is taken",
        "dotdiw",
        "            if not isinstance(ident, str) or not re.fullmatch(PROVIDER_FORMULA_ID, ident):\n",
        "            if not isinstance(ident, str):\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_id_outside_its_shape_leaves_the_provider_out",
        ],
    ),
    (
        "the command printed to pour runs what the id holds",
        "dotdiw",
        '        % (PROG, shlex.quote(response.get("pourRef") or top[0]["formulaRef"])),\n',
        '        % (PROG, response.get("pourRef") or top[0]["formulaRef"]),\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_the_command_printed_to_pour_quotes_the_id"],
    ),
    (
        "the notice prints a title the shell reads",
        "dotdiw",
        '            % (PROG, shell_word(p["title"]), shlex.quote(p["workRef"])),\n',
        '            % (PROG, \'"%s"\' % p["title"], p["workRef"]),\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_the_notice_quotes_the_title_it_prints"],
    ),
    (
        "the nudge prints text the shell reads",
        "dotdiw",
        '        command = "%s formula new %s" % (PROG, shell_word(short))\n',
        "        command = '%s formula new \"%s\"' % (PROG, short)\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_the_nudge_quotes_the_text_it_prints"],
    ),
    (
        "a file name resolves before an exact id",
        "dotdiw",
        '    tiers: list[Callable[[dict[str, Any]], bool]] = [\n        lambda f: f["id"] == ident and (not owner or f.get("provider") == owner)\n    ]\n',
        "    tiers: list[Callable[[dict[str, Any]], bool]] = []\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_an_exact_id_comes_before_a_file_name"],
    ),
    (
        "two formulas under one id resolve to the first",
        "dotdiw",
        "    if len(matches) > 1:\n",
        "    if False:\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_two_formulas_under_one_id_are_refused"],
    ),
    (
        "a refused show is handed to the tracker",
        "dotdiw",
        '            if shown["status"] != "blocked" or shown.get("reason") != "formula-not-found":\n',
        '            if shown["status"] != "blocked":\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_two_formulas_under_one_id_are_refused"],
    ),
    (
        "a removed provider's suffix is handed to the tracker",
        "dotdiw",
        '            for n in sorted(set(registry["providers"]) | set(registry["removed"]))\n',
        '            for n in sorted(set(registry["providers"]))\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_removed_providers_formula_is_never_handed_to_the_tracker",
        ],
    ),
    (
        "a suffix its provider does not serve is handed to the tracker",
        "dotdiw",
        '            if len(ident) > len(n) + 1 and ident.endswith("-" + n)\n',
        "            if False\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_removed_providers_formula_is_never_handed_to_the_tracker",
        ],
    ),
    (
        "a refused id reaches the tracker at pour",
        "dotdiw",
        '    if not found and r.get("reason") in (\n        "ambiguous",\n',
        '    if False and r.get("reason") in (\n        "ambiguous",\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_removed_providers_formula_is_never_handed_to_the_tracker",
        ],
    ),
    (
        "a removal forgets the name it removed",
        "dotdiw",
        '        registry["removed"] = sorted(set(registry["removed"]) | {name})\n',
        '        registry["removed"] = sorted(registry["removed"])\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_removed_providers_formula_is_never_handed_to_the_tracker",
        ],
    ),
    (
        "a registration keeps its name among the removed",
        "dotdiw",
        '        registry["removed"] = [n for n in registry["removed"] if n != name]\n',
        '        registry["removed"] = list(registry["removed"])\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_removed_providers_formula_is_never_handed_to_the_tracker",
        ],
    ),
    (
        "a registration keeps the run's provider lists",
        "dotdiw",
        "        write_registry(registry)\n    LISTED.clear()\n    return {\n",
        "        write_registry(registry)\n    return {\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_one_run_forgets_its_index_when_the_registry_changes",
        ],
    ),
    (
        "a malformed entry is read with the rest",
        "dotdiw",
        "            if not isinstance(examples, list) or not all(isinstance(e, str) for e in examples):\n",
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_malformed_list_leaves_the_provider_out_and_create_succeeds",
        ],
    ),
    (
        "the sharing check reads the index git keeps",
        "dotdiw",
        '        set(git(["ls-tree", "-z", "--name-only", "HEAD", "--", *local], root).split("\\0"))\n',
        '        set(git(["ls-files", "-z", "--", *local], root).split("\\0"))\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_check_names_a_formula_head_does_not_hold"],
    ),
    (
        "a registration writes without the registry's lock",
        "dotdiw",
        "    with registry_lock():\n        registry = read_registry()\n        taken = taken_in(",
        "    with contextlib.nullcontext():\n        registry = read_registry()\n        taken = taken_in(",
        ["test_dotdiw.py", "TheFormulaProviders.test_a_registration_waits_for_the_registry_lock"],
    ),
    (
        "a removal writes without the registry's lock",
        "dotdiw",
        "    with registry_lock():\n        registry = read_registry()\n        entry = ",
        "    with contextlib.nullcontext():\n        registry = read_registry()\n        entry = ",
        ["test_dotdiw.py", "TheFormulaProviders.test_a_registration_waits_for_the_registry_lock"],
    ),
    (
        "a registration writes over a registry it did not read",
        "dotdiw",
        "    with registry_lock():\n        registry = read_registry()\n        taken = taken_in(",
        '    with registry_lock():\n        registry = {"providers": {}, "removed": []}\n        taken = taken_in(',
        ["test_dotdiw.py", "TheFormulaProviders.test_two_registrations_at_once_keep_both"],
    ),
    (
        "a directory store is recorded as it was typed",
        "dotdiw",
        '        if isinstance(said, dict) and isinstance(said.get("location"), str) and said["location"]:\n',
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_directory_store_is_resolved_at_registration",
        ],
    ),
    (
        "a directory store that is gone answers no formulas",
        "dotdiw",
        "    if not location or not os.path.isdir(location):\n",
        "    if not location:\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_directory_store_is_resolved_at_registration",
        ],
    ),
    (
        "every lookup reads the provider's whole catalog",
        "dotdiw",
        '            ref = held["formulaRef"]\n',
        '            ref = held["formulaRef"]\n            invoke("operation.show-provider-formula", {"root": root, "name": name, "ident": ref[: -len(name) - 1]})\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_each_provider_is_asked_once_in_a_run"],
    ),
    (
        "the providers' list hides a registration that cannot answer",
        "dotdiw",
        '        if said.get("provider"):\n            providers.append(said["provider"])\n        else:\n',
        '        if said.get("provider"):\n            providers.append(said["provider"])\n        elif False:\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_a_registration_that_cannot_answer_is_listed"],
    ),
    (
        "local storage opens a FIFO as a formula",
        "dotdiw",
        "            if os.path.isfile(path):  # a FIFO or a device is never opened\n",
        "            if True:\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_local_storage_reads_regular_files_alone"],
    ),
    (
        "a provider's suffix falls back to a file name",
        "dotdiw",
        "    if not owner:\n        tiers += [\n",
        "    if True:\n        tiers += [\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_providers_suffix_never_falls_back_to_a_file_name",
        ],
    ),
    (
        "a path is matched by its file's name first",
        "dotdiw",
        '            lambda f: not f.get("provider") and f["rel"] == rel,\n',
        "            lambda f: False,\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_an_exact_path_comes_before_a_file_name"],
    ),
    (
        "check reads only the formulas that parse",
        "dotdiw",
        '    local = sorted({g["rel"] for g in forms if not g.get("provider")} | set(unparsed))\n',
        '    local = sorted({g["rel"] for g in forms if not g.get("provider")})\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_check_names_a_formula_that_does_not_parse"],
    ),
    (
        "check is silent on a formula that does not parse",
        "dotdiw",
        "        if rel in unparsed:\n",
        "        if False:\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_check_names_a_formula_that_does_not_parse"],
    ),
    (
        "the index keeps no file it could not parse",
        "dotdiw",
        "            unparsed.append(rel)\n",
        "            pass\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_check_names_a_formula_that_does_not_parse"],
    ),
    (
        "a run's index forgets the files it could not parse",
        "dotdiw",
        '            "unparsed": list(UNPARSED.get(root, [])),\n',
        '            "unparsed": [],\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_check_names_a_formula_that_does_not_parse"],
    ),
    (
        "a local formula takes a provider's reserved id",
        "dotdiw",
        '        lambda f: f["id"] == ident and (not owner or f.get("provider") == owner)\n',
        '        lambda f: f["id"] == ident\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_local_formula_never_takes_a_providers_suffix",
        ],
    ),
    (
        "check is silent on a local formula with a removed provider's suffix",
        "dotdiw",
        '    reserved = sorted(set(registry["providers"]) | set(registry["removed"]))\n',
        '    reserved = sorted(set(registry["providers"]))\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_local_formula_never_takes_a_providers_suffix",
        ],
    ),
    (
        "the pour hint names an id another formula answers to",
        "dotdiw",
        '            pour_ref = first["rel"]\n',
        '            pour_ref = first["id"]\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_the_pour_hint_pours_the_formula_it_shows"],
    ),
    (
        "the pour hint misses an id two formulas share",
        "dotdiw",
        '            or sum(1 for f in forms if f["id"] == first["id"]) > 1\n',
        "            or False\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_the_pour_hint_pours_the_formula_it_shows"],
    ),
    (
        "the pour hint is printed from the id alone",
        "dotdiw",
        '        % (PROG, shlex.quote(response.get("pourRef") or top[0]["formulaRef"])),\n',
        '        % (PROG, shlex.quote(top[0]["formulaRef"])),\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_the_pour_hint_pours_the_formula_it_shows"],
    ),
    (
        "a path hint is read as an option",
        "dotdiw",
        '            if pour_ref.startswith("-"):\n                pour_ref = "./" + pour_ref\n',
        '            if False:\n                pour_ref = "./" + pour_ref\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_the_pour_hint_is_never_read_as_an_option"],
    ),
    (
        "an id hint is read as an option",
        "dotdiw",
        '            or first["id"].startswith("-")\n',
        "            or False\n",
        ["test_dotdiw.py", "TheFormulaProviders.test_the_pour_hint_is_never_read_as_an_option"],
    ),
    (
        "a command other than init puts an earlier adoption right",
        "dotdiw",
        '        left = invoke("operation.undo-earlier-adoption", {"root": root, "tracker": tracker})\n',
        '        left = invoke("operation.undo-earlier-adoption", {"root": root, "tracker": tracker, "apply": True})\n',
        ["test_dotdiw.py", "Repair.test_only_init_puts_an_earlier_adoption_right"],
    ),
    (
        "a command runs while an earlier adoption is left",
        "dotdiw",
        '        if left["exitCode"] != 0:\n            return int(left["exitCode"])\n',
        '        if False:\n            return int(left["exitCode"])\n',
        ["test_dotdiw.py", "Repair.test_only_init_puts_an_earlier_adoption_right"],
    ),
    (
        "init leaves an earlier adoption as it was",
        "dotdiw",
        '    undone = invoke(\n        "operation.undo-earlier-adoption", {"root": root, "tracker": tracker, "apply": True}\n    )\n',
        '    undone = invoke(\n        "operation.undo-earlier-adoption", {"root": root, "tracker": tracker}\n    )\n',
        ["test_dotdiw.py", "Repair.test_repair_hands_the_hooks_back"],
    ),
    (
        "init adopts an in-tree tracker before it is put right",
        "dotdiw",
        '    undone = invoke(\n        "operation.undo-earlier-adoption", {"root": root, "tracker": tracker, "apply": True}\n    )\n    if undone["status"] != "completed":\n        return {"status": "failed", "summary": undone["summary"], "exitCode": 1}\n    made = invoke(\n        "operation.adopt-repository",\n        {"root": root, "prefix": request.get("prefix"), "tracker": tracker},\n    )\n',
        '    made = invoke(\n        "operation.adopt-repository",\n        {"root": root, "prefix": request.get("prefix"), "tracker": tracker},\n    )\n    undone = invoke(\n        "operation.undo-earlier-adoption", {"root": root, "tracker": tracker, "apply": True}\n    )\n    if undone["status"] != "completed":\n        return {"status": "failed", "summary": undone["summary"], "exitCode": 1}\n',
        ["test_dotdiw.py", "Repair.test_init_upgrades_an_in_tree_adoption"],
    ),
    (
        "a tree tracker not adopted stops nothing",
        "dotdiw",
        '            stopped = (\n                "the tracker kept in the tree could not be adopted under the home: %s"\n',
        '            stopped = None and (\n                "the tracker kept in the tree could not be adopted under the home: %s"\n',
        ["test_dotdiw.py", "Repair.test_init_stops_where_the_tree_tracker_cannot_be_adopted"],
    ),
    (
        "init adopts on after what was left stopped it",
        "dotdiw",
        '    if undone["status"] != "completed":\n',
        "    if False:\n",
        ["test_dotdiw.py", "Repair.test_init_stops_where_the_tree_tracker_cannot_be_adopted"],
    ),
    (
        "init says nothing when it stops",
        "dotdiw",
        '    if response["status"] in ("blocked", "failed"):\n        sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n        return\n    done, made = response["undone"], response.get("adopted")\n',
        '    if response["status"] == "blocked":\n        sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n        return\n    done, made = response["undone"], response.get("adopted")\n',
        ["test_dotdiw.py", "Repair.test_init_stops_where_the_tree_tracker_cannot_be_adopted"],
    ),
    (
        "the local upgrade changes a store unasked",
        "dotdiw",
        '        if not request.get("apply"):\n            return dict(\n                nothing,\n                summary="The store keeps the means to prove a run inside descriptions.",\n',
        '        if False:\n            return dict(\n                nothing,\n                summary="The store keeps the means to prove a run inside descriptions.",\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_before_3_0_is_brought_up_to_date_when_init_asks",
        ],
    ),
    (
        "the local upgrade leaves a section in its description",
        "dotdiw",
        '                if description != row["description"] or means:\n',
        "                if False:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_before_3_0_is_brought_up_to_date_when_init_asks",
        ],
    ),
    (
        "the beads upgrade moves nothing",
        "dotdiw",
        "        if not text or (description == text and not means):\n            continue\n",
        "        if True:\n            continue\n",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_workspace_poured_into_before_3_0_is_brought_up_to_date_when_init_asks",
        ],
    ),
    (
        "a store bd opens starts with its means unmoved",
        "dotdiw",
        "    beads_moved(store)\n    return {\n",
        "    return {\n",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_workspace_poured_into_before_3_0_is_brought_up_to_date_when_init_asks",
        ],
    ),
    (
        "undo-earlier-adoption never asks the adapter keeping the store",
        "dotdiw",
        "    if checkout_adopted(root) and stopped is None:\n        kept = invoke_extra(\n",
        "    if False:\n        kept = invoke_extra(\n",
        [
            "test_dotdiw.py",
            "TheLocalCommandLine.test_init_brings_a_store_an_earlier_version_kept_up_to_date",
        ],
    ),
    (
        "the beads upgrade moves an issue it marked again",
        "dotdiw",
        '        if own is not None and own.get("meansMoved"):\n',
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_an_upgrade_cut_short_is_taken_up_where_it_stopped",
        ],
    ),
    (
        "the beads upgrade marks no issue it moved",
        "dotdiw",
        '            "--metadata=" + beads_means(row, means, moved=True),\n',
        '            "--metadata=" + beads_means(row, means),\n',
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_an_upgrade_cut_short_is_taken_up_where_it_stopped",
        ],
    ),
    (
        "an upgrade that fails stops nothing",
        "dotdiw",
        '        elif apply and kept.get("reason") != "unsupported":\n',
        "        elif False:\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_init_stops_where_the_beads_store_cannot_be_brought_up_to_date",
        ],
    ),
    (
        "a beads record reads a dotdiw value of the issue's own as its own",
        "dotdiw",
        '    means = (beads_own(row) or {}).get("verifyUsing")\n',
        '    means = (beads_metadata(row).get(BEADS_KEY) or {}).get("verifyUsing")\n',
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is",
        ],
    ),
    (
        "the beads upgrade reads a dotdiw value of the issue's own as a mark",
        "dotdiw",
        '        if own is not None and own.get("meansMoved"):\n',
        '        if (beads_metadata(row).get(BEADS_KEY) or {}).get("meansMoved"):\n',
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is",
        ],
    ),
    (
        "the beads upgrade moves the means beside a value of the issue's own",
        "dotdiw",
        '        if own is None:\n            kept.append(str(row.get("id")))\n            continue\n',
        "",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is",
        ],
    ),
    (
        "the beads upgrade says nothing of an issue it left as given",
        "dotdiw",
        "        + ([beads_left_as_given(kept)] if kept else []),\n",
        "        + [],\n",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is",
        ],
    ),
    (
        "the beads adapter takes a dotdiw null of the issue's own for its own",
        "dotdiw",
        "    if BEADS_KEY not in held:\n",
        "    if held.get(BEADS_KEY) is None:\n",
        [
            "test_dotdiw.py",
            "TheBeadsMetadata.test_a_dotdiw_value_of_the_issues_own_is_left_as_it_is",
        ],
    ),
    (
        "the notice reads the first 300 items alone",
        "dotdiw",
        '        "operation.list-items", {"root": root, "tracker": request.get("tracker"), "scope": "all"}\n',
        '        "operation.list-items", {"root": root, "tracker": request.get("tracker"), "scope": "all", "limit": 300}\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_the_notice_the_past_titles_and_from_read_every_item",
        ],
    ),
    (
        "the past titles stop at 300 items",
        "dotdiw",
        '        "operation.list-items", {"root": root, "tracker": tracker, "scope": "all"}\n    )\n    if listed["status"] != "completed":\n        return []\n',
        '        "operation.list-items", {"root": root, "tracker": tracker, "scope": "all", "limit": 300}\n    )\n    if listed["status"] != "completed":\n        return []\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_the_notice_the_past_titles_and_from_read_every_item",
        ],
    ),
    (
        "formula new --from reads the first 300 items alone",
        "dotdiw",
        '        "operation.list-items", {"root": root, "tracker": tracker, "scope": "all"}\n    )\n    if listed["status"] != "completed":\n        return None\n',
        '        "operation.list-items", {"root": root, "tracker": tracker, "scope": "all", "limit": 300}\n    )\n    if listed["status"] != "completed":\n        return None\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_the_notice_the_past_titles_and_from_read_every_item",
        ],
    ),
    (
        "a pour under beads answers its step ids sorted",
        "dotdiw",
        '        ids[s["id"]] = str(rows[0].get("id"))\n    return {\n        "status": "completed",\n        "summary": "Poured %d steps under %s." % (len(ids), root_id),\n        "rootId": root_id,\n        "stepIds": [ids[s["id"]] for s in steps],\n',
        '        ids[s["id"]] = str(rows[0].get("id"))\n    return {\n        "status": "completed",\n        "summary": "Poured %d steps under %s." % (len(ids), root_id),\n        "rootId": root_id,\n        "stepIds": sorted(ids.values()),\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_a_pour_answers_its_steps_in_the_formulas_order",
        ],
    ),
    (
        "a pour under beads that fails after its root names nothing it made",
        "dotdiw",
        '                "summary": "Poured %d of %d steps under %s%s, and the next failed: %s"\n                % (\n                    len(ids),\n                    len(steps),\n                    root_id,\n                    " (%s)" % ", ".join(ids[x["id"]] for x in steps if x["id"] in ids)\n                    if ids\n                    else "",\n                    said,\n                ),\n',
        '                "summary": said,\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_a_pour_that_fails_after_its_root_names_it",
        ],
    ),
    (
        "beads create reads a title as a flag",
        "dotdiw",
        '        "create",\n        "--title=" + request["title"],\n        "--type=task",\n',
        '        "create",\n        request["title"],\n        "--type=task",\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_title_that_reads_like_a_flag_is_kept_as_given"],
    ),
    (
        "beads create reads a description as a flag",
        "dotdiw",
        '        argv += ["--parent=" + parent]\n    if description:\n        argv += ["--description=" + description]\n',
        '        argv += ["--parent=" + parent]\n    if description:\n        argv += [description]\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_title_that_reads_like_a_flag_is_kept_as_given"],
    ),
    (
        "beads pour reads the root's title as a flag",
        "dotdiw",
        '    argv = ["create", "--title=" + request["title"], "--type=molecule", "--priority=2", "--json"]\n',
        '    argv = ["create", request["title"], "--type=molecule", "--priority=2", "--json"]\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_title_that_reads_like_a_flag_is_kept_as_given"],
    ),
    (
        "beads pour reads a step's title as a flag",
        "dotdiw",
        '        argv = ["create", "--title=" + s["title"], "--parent=" + root_id, "--type=task", "--json"]\n',
        '        argv = ["create", s["title"], "--parent=" + root_id, "--type=task", "--json"]\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_title_that_reads_like_a_flag_is_kept_as_given"],
    ),
    (
        "beads pour reads the root's description as a flag",
        "dotdiw",
        '    means = list(request.get("verifyUsing") or [])\n    if description:\n        argv += ["--description=" + description]\n',
        '    means = list(request.get("verifyUsing") or [])\n    if description:\n        argv += [description]\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_title_that_reads_like_a_flag_is_kept_as_given"],
    ),
    (
        "local pours steps that share an id",
        "dotdiw",
        '    it, each needing the steps it names; all or nothing."""\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = shared_step_id(steps)\n',
        '    it, each needing the steps it names; all or nothing."""\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = None\n',
        ["test_dotdiw.py", "TheLocalAdapter.test_steps_that_share_an_id_pour_nothing"],
    ),
    (
        "beads pours steps that share an id",
        "dotdiw",
        '        return failed_as(PourStepsResponse, *BEADS_NO_WORKSPACE)\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = shared_step_id(steps)\n',
        '        return failed_as(PourStepsResponse, *BEADS_NO_WORKSPACE)\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = None\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_steps_that_share_an_id_pour_nothing"],
    ),
    (
        "a cut-short beads pour leaves out the steps it made",
        "dotdiw",
        '                    " (%s)" % ", ".join(ids[x["id"]] for x in steps if x["id"] in ids)\n                    if ids\n                    else "",\n',
        '                    "",\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_a_pour_that_fails_after_its_root_names_it",
        ],
    ),
    (
        "formula pour --json drops a pour cut short",
        "dotdiw",
        '    if request.get("json") and response.get("moleculeRef"):\n',
        '    if request.get("json") and response.get("moleculeRef") and response["status"] == "completed":\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_a_pour_that_fails_after_its_root_names_it",
        ],
    ),
    (
        "formula pour --json says nothing of a pour cut short",
        "dotdiw",
        '        print(json.dumps(answer, indent=2, ensure_ascii=False))\n        if response["status"] != "completed":\n',
        "        print(json.dumps(answer, indent=2, ensure_ascii=False))\n        if False:\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_a_pour_that_fails_after_its_root_names_it",
        ],
    ),
    (
        "jira pours steps that share an id",
        "trackers/jira.py",
        '        if s["id"] in seen:\n',
        "        if False:\n",
        ["test_jira.py", "TheTable.test_steps_that_share_an_id_pour_nothing"],
    ),
    (
        "a cut-short jira pour names no root",
        "trackers/jira.py",
        "            return cut_short(step)\n",
        "            return step\n",
        ["test_jira.py", "TheHostedAdapter.test_a_pour_jira_refuses_partway_is_one_line"],
    ),
    (
        "a Jira issue made and not read back keeps no key",
        "trackers/jira.py",
        "        return out, key\n",
        "        return out, None\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_pour_names_what_jira_made_and_could_not_read_back",
        ],
    ),
    (
        "a Jira pour whose root was not read back names no root",
        "trackers/jira.py",
        "        if root_id is None:\n            return made\n",
        "        if True:\n            return made\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_pour_names_what_jira_made_and_could_not_read_back",
        ],
    ),
    (
        "a cut-short Jira pour leaves out a step it made",
        "trackers/jira.py",
        '        if key is not None:\n            ids[s["id"]] = key\n        if step["status"] != "completed":\n            return cut_short(step)\n',
        '        if step["status"] != "completed":\n            return cut_short(step)\n        if key is not None:\n            ids[s["id"]] = key\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_pour_names_what_jira_made_and_could_not_read_back",
        ],
    ),
    (
        "a Jira create made and not read back hides its key",
        "trackers/jira.py",
        '        out["summary"] = "Jira made %s and could not read it back: %s" % (key, out["summary"])\n',
        '        out["summary"] = out["summary"]\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_create_names_what_jira_made_and_could_not_read_back",
        ],
    ),
    (
        "a pour hands the tracker a file",
        "dotdiw",
        '            "verifyUsing": list(formula.get("verifyUsing") or []),\n        },\n',
        '            "verifyUsing": list(formula.get("verifyUsing") or []),\n            "path": os.path.join(root, r["path"]) if found else None,\n        },\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_pour_hands_the_tracker_the_formula_and_no_file",
        ],
    ),
    (
        "a pour hands the tracker steps that share an id",
        "dotdiw",
        '    shared = shared_step_id(formula.get("steps") or [])\n',
        "    shared = None\n",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_formula_whose_steps_share_an_id_never_reaches_the_tracker",
        ],
    ),
    (
        "a pour reads its formula's file again",
        "dotdiw",
        "        if body\n        else {}\n    )\n",
        '        if body and not r.get("path")\n        else (load_formula(root, r["path"]) if found else None) or {}\n    )\n',
        ["test_promise.py", "TheTrackerDoor.test_a_pour_pours_the_formula_its_lookup_selected"],
    ),
    (
        "every operation shares the last one's reading of the formulas",
        "dotdiw",
        "    if DEPTH == 0:\n        INDEXES.clear()\n",
        "    if False:\n        INDEXES.clear()\n",
        ["test_promise.py", "TheTrackerDoor.test_every_pour_reads_the_formula_afresh"],
    ),
    (
        "create takes a flag of bd's own",
        "dotdiw",
        '        elif a.startswith("-") and a != "-":\n            return fields, words, "%s is not one of its flags" % a\n',
        '        elif a.startswith("-") and a != "-":\n            words.append(a)\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "a flag with no value after it takes nothing",
        "dotdiw",
        '                if i + 1 >= len(args) or args[i + 1].startswith("-") and args[i + 1] != "-":\n                    return fields, words, "%s needs a value" % a\n',
        '                if i + 1 >= len(args) or args[i + 1].startswith("-") and args[i + 1] != "-":\n                    break\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "create takes a second title",
        "dotdiw",
        "        elif len(words) >= positionals:\n",
        "        elif False:\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "create -q surfaces what rides along with the create",
        "dotdiw",
        '                quiet=quiet or json_out or bool(os.environ.get("DOTDIW_NO_HINTS")),\n',
        '                quiet=json_out or bool(os.environ.get("DOTDIW_NO_HINTS")),\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "a flag of create's takes the next flag for its value",
        "dotdiw",
        '                if i + 1 >= len(args) or args[i + 1].startswith("-") and args[i + 1] != "-":\n',
        "                if i + 1 >= len(args):\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "--tracker takes the next flag for its name",
        "dotdiw",
        '            if not given or given.startswith("-"):\n',
        "            if not given:\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "--tracker last runs on under a name of its own",
        "dotdiw",
        '            given = argv[i + 1] if i + 1 < len(argv) else ""\n',
        '            given = argv[i + 1] if i + 1 < len(argv) else "local"\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "--tracker= with no name falls to the default",
        "dotdiw",
        "            missing = missing or not name\n",
        "            missing = missing\n",
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "a --tracker given no name runs on",
        "dotdiw",
        '    if missing:\n        sys.stderr.write("%s: --tracker needs a value, as --tracker <name>.\\n" % PROG)\n',
        '    if False:\n        sys.stderr.write("%s: --tracker needs a value, as --tracker <name>.\\n" % PROG)\n',
        ["test_dotdiw.py", "TheLocalCommandLine.test_create_pour_and_init_read_their_own_flags"],
    ),
    (
        "a module written for interface 2 loads",
        "dotdiw",
        "    if declared != TRACKER_INTERFACE or isinstance(declared, bool):\n",
        "    if declared not in (2, TRACKER_INTERFACE) or isinstance(declared, bool):\n",
        ["test_promise.py", "TheTrackerDoor.test_a_module_says_which_interface_it_was_written_for"],
    ),
    (
        "a completed create carries no record",
        "dotdiw",
        '    if response["status"] == "completed":\n        for key in TRACKER_ANSWERS.get(operation, ()):\n',
        "    if False:\n        for key in TRACKER_ANSWERS.get(operation, ()):\n",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_create_or_a_pour_without_its_record_is_the_adapters_mistake",
        ],
    ),
    (
        "a provider's formula outside its shape is taken",
        "dotdiw",
        '        if not isinstance(ident, str) or not ident or not isinstance(title, str) or not title:\n            raise ValueError("a step has no id or no title")\n',
        '        if False:\n            raise ValueError("a step has no id or no title")\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_formula_outside_its_shape_is_refused",
        ],
    ),
    (
        "a provider module written for another interface loads",
        "dotdiw",
        '    if not isinstance(info, dict) or info.get("interface") != PROVIDER_INTERFACE:\n',
        "    if not isinstance(info, dict):\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_written_for_another_interface_is_refused",
        ],
    ),
    (
        "a pour drops the formula its lookup answered",
        "dotdiw",
        '    body = r.get("formula") if found else None\n    formula = (\n',
        "    body = None\n    formula = (\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_formula_is_data_and_nothing_is_written_for_it",
        ],
    ),
    (
        "formula show leaves a provider's means out",
        "dotdiw",
        '            "verify-using": body["verifyUsing"],\n',
        "",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_a_provider_formula_is_data_and_nothing_is_written_for_it",
        ],
    ),
    (
        "the lookup's answer has no room for a provider's formula",
        "dotdiw",
        '        "body": "FindAHeldProcedure",\n        "request": (\n            "ask", "correlationId", "formulaRef", "ident", "json", "root",\n            "sourceRefs",\n        ),\n        "requestRequired": (\n            "ask", "root",\n        ),\n        "response": (\n            "exitCode", "formula", "formulaCount", "formulaRef", "formulas",\n',
        '        "body": "FindAHeldProcedure",\n        "request": (\n            "ask", "correlationId", "formulaRef", "ident", "json", "root",\n            "sourceRefs",\n        ),\n        "requestRequired": (\n            "ask", "root",\n        ),\n        "response": (\n            "exitCode", "formulaCount", "formulaRef", "formulas",\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_the_lookup_answers_a_providers_formula_as_resolve_does",
        ],
    ),
    (
        "a provider's description is defaulted",
        "dotdiw",
        '    description = body.get("description")\n',
        '    description = body.get("description") or ""\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_nothing_a_provider_gives_is_replaced_by_a_default",
        ],
    ),
    (
        "a provider's verifyUsing is defaulted",
        "dotdiw",
        "    means = [] if means is None else means\n",
        "    means = means or []\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_nothing_a_provider_gives_is_replaced_by_a_default",
        ],
    ),
    (
        "a provider's steps are defaulted",
        "dotdiw",
        '    steps = body.get("steps")\n',
        '    steps = body.get("steps") or []\n',
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_nothing_a_provider_gives_is_replaced_by_a_default",
        ],
    ),
    (
        "a provider step's needs are defaulted",
        "dotdiw",
        "        needs = [] if needs is None else needs\n",
        "        needs = needs or []\n",
        [
            "test_dotdiw.py",
            "TheFormulaProviders.test_nothing_a_provider_gives_is_replaced_by_a_default",
        ],
    ),
    (
        "the lookup answers a local formula as its file reads now",
        "dotdiw",
        '        "formula": {\n            "description": found["desc"],\n            "verifyUsing": list(found["verifyUsing"]),\n            "steps": list(found["steps"]),\n        },\n',
        '        "formula": {\n            "description": (load_formula(root, found["rel"]) or found)["desc"],\n            "verifyUsing": list((load_formula(root, found["rel"]) or found)["verifyUsing"]),\n            "steps": list((load_formula(root, found["rel"]) or found)["steps"]),\n        },\n',
        ["test_promise.py", "TheTrackerDoor.test_a_pour_pours_the_formula_its_lookup_selected"],
    ),
    (
        "formula show prints a file in the tree as data",
        "dotdiw",
        '    body = r.get("formula")\n    if body and not r.get("path"):\n',
        '    body = r.get("formula")\n    if body:\n',
        ["test_dotdiw.py", "TheFormulaProviders.test_an_exact_path_comes_before_a_file_name"],
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
