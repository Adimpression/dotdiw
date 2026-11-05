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
        '{"accountId": request["assignee"]}',
        '{"name": request["assignee"]}',
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
        "a module that does not say its interface is refused",
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
        '{i["id"] for i in scoped.get("items") or []} == {held["a"], held["c"]},',
        "True,",
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
        'shown["item"].get("kind") in ("molecule", "epic"),',
        "True,",
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_the_scenario_holds_what_the_other_commands_rely_on",
        ],
    ),
    (
        "the scenario takes an item with no kind",
        "dotdiw",
        '(b["item"].get("kind"), b["item"].get("priority")) == ("task", 2),',
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
