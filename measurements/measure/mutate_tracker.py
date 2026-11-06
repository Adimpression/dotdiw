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
        '{"accountId": who}',
        '{"name": who}',
        ["test_jira.py", "TheHostedAdapter.test_an_assignee_is_an_account_id"],
    ),
    (
        "a package's directory is not searched",
        "dotdiw",
        "    for prefix in prefixes:\n        shared = os.path.join(prefix, TRACKERS_SHARED)\n",
        "    for prefix in []:\n        shared = os.path.join(prefix, TRACKERS_SHARED)\n",
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
        "poa/finish-idl.py",
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
        '    elif response["status"] != "completed":\n        if not response.get("printed"):\n            sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n    elif not response["created"]:\n',
        '    elif response["status"] != "completed":\n        pass\n    elif not response["created"]:\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_init_says_why_the_store_did_not_open_and_stops",
        ],
    ),
    (
        "a stock line replaces what the tracker said",
        "dotdiw",
        '"summary": "The tracker\'s init failed." if opened.get("printed") else opened["summary"],',
        '"summary": opened["summary"] if opened.get("reason") else "The tracker\'s init failed.",',
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
        '    elif response["status"] != "completed" and not response.get("printed"):\n        sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n    elif response.get("workRef") and not response.get("printed"):\n',
        '    elif response.get("workRef") and not response.get("printed"):\n',
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
        "    if in_tree and not checkout_adopted(root):\n",
        "    if in_tree and not adopted(ws):\n",
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
        '        else "The tracker refused the create."\n        if made.get("printed")\n        else made["summary"],\n',
        '        else made["summary"]\n        if made.get("reason")\n        else "The tracker refused the create.",\n',
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
        "formula pour drops what is typed after the formula",
        "dotdiw",
        '"ident": argv[2], "arguments": argv[3:],',
        '"ident": argv[2], "arguments": [],',
        ["test_dotdiw.py", "TheWordFormulaPour.test_what_is_typed_after_the_formula_goes_along"],
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
        'print("  Run it: %s formula pour %s" % (PROG, top[0]["formulaRef"]), file=sys.stderr)',
        'print("  Run it: %s mol pour %s" % (PROG, top[0]["formulaRef"]), file=sys.stderr)',
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
        [
            "test_dotdiw.py",
            "TheBytesUnderBeads.test_the_seventeen_commands_print_what_0_6_0_printed",
        ],
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
        '    argv = ["create", request["title"], "-t", "molecule", "-p", "2", "--json"]\n',
        '    argv = ["create", request["title"], "-t", "epic", "-p", "2", "--json"]\n',
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
        '            "parent": request.get("parent"),\n            "arguments": args,\n            "terminal": True,\n',
        '            "parent": request.get("parent"),\n            "kind": "task",\n            "arguments": args,\n            "terminal": True,\n',
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
        "the means follow a pour's JSON",
        "dotdiw",
        '        and response["status"] == "completed"\n        and "--json" not in (request.get("arguments") or [])\n',
        '        and response["status"] == "completed"\n',
        ["test_dotdiw.py", "TheMeansToProveARun.test_under_beads_the_means_follow_its_own_output"],
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
        '            "verifyUsing": list(formula.get("verifyUsing") or []),\n            "path": os.path.join(root, r["path"]) if found else None,\n',
        '            "verifyUsing": [],\n            "path": os.path.join(root, r["path"]) if found else None,\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_a_pour_shows_the_means_and_the_root_keeps_them",
        ],
    ),
    (
        "local keeps no means on its root",
        "dotdiw",
        '                    request["title"],\n                    keep_verify_using(\n                        request.get("description"), list(request.get("verifyUsing") or [])\n                    ),\n',
        '                    request["title"],\n                    request.get("description"),\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no means back",
        "dotdiw",
        '    description, means = read_verify_using(row["description"])\n',
        '    description, means = row["description"], []\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads keeps no means on a root it makes",
        "dotdiw",
        '    if kept:\n        argv += ["-d", kept]\n',
        '    if False:\n        argv += ["-d", kept]\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads keeps no means after its own pour",
        "dotdiw",
        '        if root_id and kept != request.get("description"):\n',
        "        if False:\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_under_beads_the_means_follow_its_own_output"],
    ),
    (
        "beads reads no means back",
        "dotdiw",
        '    description, means = read_verify_using(row.get("description"))\n',
        '    description, means = row.get("description"), []\n',
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
        "a pour answered in JSON leaves its root without the means",
        "dotdiw",
        '            if answer and answer[0].get("new_epic_id"):\n',
        "            if False:\n",
        ["test_dotdiw.py", "TheMeansToProveARun.test_under_beads_the_means_follow_its_own_output"],
    ),
    (
        "a failed write of the means drops the root from the answer",
        "dotdiw",
        '                    "rootId": root_id,\n                    "stepIds": poured,\n',
        "",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_means_not_kept_fail_the_pour_naming_its_root",
        ],
    ),
    (
        "a failed write of the means passes for a pour",
        "dotdiw",
        '            code, _, err = beads_quiet(["update", root_id, "--description", kept or ""], root)\n            if code != 0:\n',
        '            code, _, err = beads_quiet(["update", root_id, "--description", kept or ""], root)\n            if False:\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_means_not_kept_fail_the_pour_naming_its_root",
        ],
    ),
    (
        "a failed pour that made a root says nothing of it",
        "dotdiw",
        '        not response.get("printed") or response.get("moleculeRef")\n',
        '        not response.get("printed")\n',
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_under_beads_means_not_kept_fail_the_pour_naming_its_root",
        ],
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
        "local writes a created item's description raw",
        "dotdiw",
        '                    parent,\n                    keep_verify_using(\n                        request.get("description"), list(request.get("verifyUsing") or [])\n                    ),\n',
        '                    parent,\n                    request.get("description"),\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads writes a created item's description raw",
        "dotdiw",
        '    description = keep_verify_using(\n        request.get("description"), list(request.get("verifyUsing") or [])\n    )\n    if parent:\n',
        '    description = request.get("description")\n    if parent:\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
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
        "a typed description is written raw under beads",
        "dotdiw",
        '        elif flag in ("-d", "--description"):\n',
        "        elif False:\n",
        ["test_dotdiw.py", "TheArgumentsBeadsIsGiven.test_a_typed_description_reads_back_as_typed"],
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
