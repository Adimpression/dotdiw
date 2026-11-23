"""Do the tests that hold the tracker door bite?

Each mutation below breaks one rule the tracker abstraction promises -- in
a copy of the working tree, never here -- and the test named for it must fail
on the broken copy. A mutation that survives is a rule nothing holds. Each
test is run first on the copy unbroken, and one that fails there catches
nothing: its mutations are counted as missed, never as caught. A mutation
of the witness contract is checked where the contract's checks run, by poa
replaying the one trace it should break, never by the test suite. The table
printed is the record; it goes in ../results/mutation-tracker.txt.

    python3 -I measure/mutate_tracker.py [-k substring]

Run from `measurements/`. bd must be on PATH for the beads mutations; the
others need no binary. The byte-identity mutation takes a minute. The copy of
the tree, and every store a test makes in it, is kept on a RAM disk made for
the run, as the suites that run bd keep theirs (suites.py), and on the disk
where none can be had or DOTDIW_TEST_ON_DISK is set.
"""

import importlib.util
import os
import shutil
import signal
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
        "    for key in response:\n"
        '        if key not in spec["response"]:\n'
        "            raise DoorError('%s: \"%s\" is not a field of its response' % (operation, key))\n"
        '    for key in spec["responseRequired"]:\n'
        "        if response.get(key) is None:\n"
        "            raise DoorError('%s: \"%s\" is required in its response and missing' % (operation, key))\n"
        '    if response["status"] not in STATUSES:\n'
        "        raise DoorError(\n"
        "            '%s: status \"%s\" is not one of %s'\n"
        '            % (operation, response["status"], ", ".join(STATUSES))\n'
        "        )\n"
        '    kinds = record_kinds(spec["responseType"])\n'
        "    for key, value in response.items():\n"
        "        hold_value(operation, key, value, kinds[key])\n"
        "    stamp_etags(kinds, response)\n",
        '    kinds = record_kinds(spec["responseType"])\n'
        "    for key, value in response.items():\n"
        "        hold_value(operation, key, value, kinds[key])\n"
        "    stamp_etags(kinds, response)\n",
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
        '                git(["config", "--local", TRACKER_KEY, pinned], root)\n                forget_workspace(root)\n                if tracker_name(root) == pinned:\n',
        "                forget_workspace(root)\n                if True:\n",
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
        '    root = request["root"]\n    etags = list(request.get("etags") or [])\n',
        '    root = request["root"]\n    beads_quiet(["list"], root)\n    etags = list(request.get("etags") or [])\n',
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
        '                for need in needs:\n                    out = written("operation.add-need"',
        '                for need in []:\n                    out = written("operation.add-need"',
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "the witness forgets which adapter answered",
        "dotdiw",
        '                title=request.get("title"),\n                startedAt=request_started(),\n                tracker=response.get("tracker"),\n            )\n',
        '                title=request.get("title"),\n                startedAt=request_started(),\n            )\n',
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
        '                        return refused(\n                            "the need of %s on %s" % (item["id"], need),\n                            out,\n                            (ids[need], ids[item["id"]]),\n                        )\n',
        "                        pass\n",
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
        '        opened = invoke_tracker(\n            "operation.open-tracker",\n            {"root": root, "tracker": name, "prefix": prefix},\n        )\n',
        '        git(["config", "--local", TRACKER_KEY, name], root)\n        opened = invoke_tracker(\n            "operation.open-tracker",\n            {"root": root, "tracker": name, "prefix": prefix},\n        )\n',
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
        '                "title": request["title"],\n                "description": request.get("description"),\n',
        '                "title": request["title"],\n',
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
        "    for key, value in response.items():\n"
        "        hold_value(operation, key, value, kinds[key])\n"
        "    stamp_etags(kinds, response)\n",
        "    stamp_etags(kinds, response)\n",
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
        'call("PUT", of(key, "assignee"), {"accountId": who})',
        'call("PUT", of(key, "assignee"), {"name": who})',
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
        "poa/generate-project.py",
        '    if digest == held["digest"]:\n',
        "    if True:\n",
        ["test_promise.py", "TheDoor.test_the_interface_number_moves_by_decision"],
    ),
    (
        "native contract semantics may be changed by application attachments",
        "poa/generate-project.py",
        "    if json.dumps({k: v for k, v in idl.items() if k not in ATTACHMENTS}, sort_keys=True) != native:\n",
        "    if False:\n",
        ["test_promise.py", "TheDoor.test_application_attachments_cannot_change_native_sections"],
    ),
    (
        "native contract legacy annotations are accepted",
        "poa/generate-project.py",
        '    if "operationTypes" in model or any(\n        "operation" in entry for key in ("journeys", "steps") for entry in model.get(key) or []\n    ):\n',
        "    if False:\n",
        ["test_promise.py", "TheDoor.test_legacy_operation_annotations_are_refused"],
    ),
    (
        "native contract types become an application attachment",
        "poa/generate-project.py",
        'ATTACHMENTS = frozenset((*ID_FIELDS, "implementationBindings"))\n',
        'ATTACHMENTS = frozenset((*ID_FIELDS, "implementationBindings", "types"))\n',
        ["test_promise.py", "TheDoor.test_application_attachments_cannot_change_native_sections"],
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
        "    return needs + [c for c in under if c not in needs]\n",
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
        '                "summary": opened["summary"],\n                "workspace": ws,\n',
        '                "summary": "The tracker\'s init failed.",\n                "workspace": ws,\n',
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
        '            if tracker_name(root) != name:\n                return {\n                    "status": "failed",\n                    "summary": NOT_WRITTEN % TRACKER_KEY,\n',
        '            if False:\n                return {\n                    "status": "failed",\n                    "summary": NOT_WRITTEN % TRACKER_KEY,\n',
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
        '        if response["status"] != "completed":\n            sys.stderr.write("%s: %s\\n" % (PROG, response["summary"]))\n        else:\n            sys.stdout.write(response.get("output") or "")\n',
        '        if response["status"] != "completed":\n            pass\n        else:\n            sys.stdout.write(response.get("output") or "")\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_forward_extra_that_prints_nothing_is_shown",
        ],
    ),
    (
        "a forward extra's output is not shown",
        "dotdiw",
        '        else:\n            sys.stdout.write(response.get("output") or "")\n        return\n    glyphs',
        "        else:\n            pass\n        return\n    glyphs",
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
        "                if tracker_name(root) == pinned:\n                    done.append(\n",
        "                if True:\n                    done.append(\n",
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
        '                who = (\n                    myself().get("accountId")\n                    if request["assignee"] == "me"\n                    else request["assignee"]\n                )',
        '                who = request["assignee"]',
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
        '        if parent and parent["kind"] in ("root", "molecule"):\n',
        '        if parent and parent["kind"] == "root":\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_before_1_0_reads_its_molecule_roots_as_root",
        ],
    ),
    (
        "a root local pours stays open after its last step",
        "dotdiw",
        '        if parent and parent["kind"] in ("root", "molecule"):\n',
        '        if parent and parent["kind"] == "molecule":\n',
        ["test_dotdiw.py", "TheLocalAdapter.test_a_poured_root_closes_with_its_last_step"],
    ),
    (
        "beads answers its own type for a root",
        "dotdiw",
        '        else "root"\n        if row.get("issue_type") == "molecule"\n        else "task"\n',
        '        else row.get("issue_type") or "task"\n',
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
        'else "root" if "root" in labels else "task"',
        'else "epic" if "root" in labels else "task"',
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
        '                "parent": request.get("parent"),\n            },\n        )\n    code = made.get("exitCode", 0 if made["status"] == "completed" else 1)\n',
        '                "parent": request.get("parent"),\n                "kind": "task",\n            },\n        )\n    code = made.get("exitCode", 0 if made["status"] == "completed" else 1)\n',
        ["test_promise.py", "TheTrackerDoor.test_create_item_takes_no_kind"],
    ),
    (
        "a move asks for the kind it read",
        "dotdiw",
        '                    "title": item["title"],\n                    "priority": item.get("priority"),\n',
        '                    "title": item["title"],\n                    "kind": item.get("kind"),\n                    "priority": item.get("priority"),\n',
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
        '                description=formula.get("desc") or None,\n',
        "                description=None,\n",
        [
            "test_dotdiw.py",
            "TheMeansToProveARun.test_a_pour_shows_the_means_and_the_root_keeps_them",
        ],
    ),
    (
        "the means are not handed to pour-steps",
        "dotdiw",
        '                verifyUsing=list(formula.get("verifyUsing") or []),\n            ),\n',
        "                verifyUsing=[],\n            ),\n",
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
        '    means = own.get("verifyUsing")\n',
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
        '                wholes[item["id"]] = shown["item"]\n',
        '                wholes[item["id"]] = item\n',
        [
            "test_tracker.py",
            "AMoveShowsEachItemItMakes.test_the_description_and_the_means_move_as_shown",
        ],
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
        '        argv += ["--metadata=" + beads_means({"metadata": given}, means)]\n',
        '        argv += ["--metadata=" + beads_means({"metadata": given}, [])]\n',
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
        "a root's type in capitals passes",
        "dotdiw",
        '        and str(given.get("type", "")).strip().lower() in BEADS_ROOT_TYPES\n',
        '        and str(given.get("type", "")).strip() in BEADS_ROOT_TYPES\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
    ),
    (
        "an update asks bd for a root",
        "dotdiw",
        '        reading.get("command") in (["update"], ["q"])\n',
        "        False\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
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
        '            "unparsed": list(scope.unparsed.get(root, [])),\n',
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
        '        if not request.get("apply"):\n            return dict(nothing, summary="The store is %s." % "; ".join(left), pending=left)\n',
        '        if False:\n            return dict(nothing, summary="The store is %s." % "; ".join(left), pending=left)\n',
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
        "    if checkout_adopted(root) and stopped is None:\n        # Brought up to date under the lock a write of an item holds from\n",
        "    if False:\n        # Brought up to date under the lock a write of an item holds from\n",
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
        '    own = beads_own(row) or {}\n    guard = own.get("guard") if isinstance(own.get("guard"), str) else None\n',
        '    own = beads_metadata(row).get(BEADS_KEY) or {}\n    guard = own.get("guard") if isinstance(own.get("guard"), str) else None\n',
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
        '    transaction (local_hold_calls)."""\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = shared_step_id(steps)\n',
        '    transaction (local_hold_calls)."""\n    steps = list(request.get("steps") or [])\n    if not steps:\n        return {\n            "status": "failed",\n            "reason": "no-steps",\n            "exitCode": 1,\n            "summary": "No steps to pour.",\n        }\n    shared = None\n',
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
        "        if named in seen:\n",
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
        '        out["summary"] = "Jira made %s and could not read it back: %s" % (key, out["summary"])\n        return out, key\n',
        '        out["summary"] = "Jira made %s and could not read it back: %s" % (key, out["summary"])\n        return out, None\n',
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
        '                verifyUsing=list(formula.get("verifyUsing") or []),\n            ),\n',
        '                verifyUsing=list(formula.get("verifyUsing") or []),\n                path=os.path.join(root, r["path"]) if found else None,\n            ),\n',
        [
            "test_dotdiw.py",
            "WhatAModuleGetsWrong.test_a_pour_hands_the_tracker_the_formula_and_no_file",
        ],
    ),
    (
        "a pour hands the tracker steps that share an id",
        "dotdiw",
        "    shared = shared_step_id(top)\n",
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
        "    finally:\n        SCOPE.reset(begun)\n        GATE.leave()\n",
        "    finally:\n        GATE.leave()\n",
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
        "a module written for the interface before this one loads",
        "dotdiw",
        "    if declared != TRACKER_INTERFACE or isinstance(declared, bool):\n",
        "    if declared not in (TRACKER_INTERFACE - 1, TRACKER_INTERFACE) or isinstance(declared, bool):\n",
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
        '        "body": "FindAHeldProcedure",\n        "visibility": "external-facing",\n        "request": (\n            "ask", "correlationId", "formulaRef", "ident", "json", "root",\n            "sourceRefs",\n        ),\n        "requestRequired": (\n            "ask", "root",\n        ),\n        "response": (\n            "exitCode", "formula", "formulaCount", "formulaRef", "formulas",\n',
        '        "body": "FindAHeldProcedure",\n        "visibility": "external-facing",\n        "request": (\n            "ask", "correlationId", "formulaRef", "ident", "json", "root",\n            "sourceRefs",\n        ),\n        "requestRequired": (\n            "ask", "root",\n        ),\n        "response": (\n            "exitCode", "formulaCount", "formulaRef", "formulas",\n',
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
        "    if means is None:\n"
        "        # A provider with title and description fields alone keeps the means\n",
        "    if not means:\n"
        "        # A provider with title and description fields alone keeps the means\n",
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
    (
        "a step's claim is kept off its step",
        "dotdiw",
        '                if claim is not None:\n                    step["claim"] = claim\n',
        "                if claim is not None:\n                    pass\n",
        ["test_promise.py", "AStepsClaim.test_a_claim_is_read_onto_its_step_in_the_formula_record"],
    ),
    (
        "a claim that is not a table is read",
        "dotdiw",
        '    if not isinstance(said, dict):\n        return None, "the claim of step %s is not a table" % step\n',
        '    if False:\n        return None, "the claim of step %s is not a table" % step\n',
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a claim is read with no statement",
        "dotdiw",
        '    if not isinstance(statement, str) or not statement.strip():\n        return None, "the claim of step %s has no statement" % step\n',
        '    if False:\n        return None, "the claim of step %s has no statement" % step\n',
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a key with no colon is read as a slot",
        "dotdiw",
        '        label = str(key)[:-1] if str(key).endswith(":") else None\n',
        '        label = str(key).rstrip(":")\n',
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a slot's label is not held to kebab-case",
        "dotdiw",
        "        if label is None or not CLAIM_LABEL.match(label):\n",
        "        if label is None:\n",
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a slot may hold a value",
        "dotdiw",
        "        if value != {}:\n",
        "        if False:\n",
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a placeholder may name no slot",
        "dotdiw",
        "        if name not in slots:\n            return None, (\n",
        "        if False:\n            return None, (\n",
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "check does not name a claim it cannot read",
        "dotdiw",
        '        for what in f.get("claimUnread") or []:\n            probs.append(("formula", f["rel"], what))\n',
        '        for what in []:\n            probs.append(("formula", f["rel"], what))\n',
        ["test_promise.py", "AStepsClaim.test_a_claim_that_cannot_be_read_is_left_off_and_named"],
    ),
    (
        "a provider's claim is left off its step",
        "dotdiw",
        '            step["claim"] = held_claim(ident, claim)\n',
        "            pass\n",
        ["test_promise.py", "AStepsClaim.test_a_providers_answer_carries_a_steps_claim"],
    ),
    (
        "a provider's claim is taken whatever keys it holds",
        "dotdiw",
        '    if not isinstance(said, dict) or set(said) - {"statement", "slots"}:\n',
        "    if not isinstance(said, dict):\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_claim_outside_its_shape_refuses_the_formula",
        ],
    ),
    (
        "a provider's claim may have no statement",
        "dotdiw",
        '    if not isinstance(statement, str) or not statement.strip():\n        raise ValueError("the claim of step %s has no statement" % step)\n',
        '    if False:\n        raise ValueError("the claim of step %s has no statement" % step)\n',
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_claim_outside_its_shape_refuses_the_formula",
        ],
    ),
    (
        "a provider's slots are not held to kebab-case",
        "dotdiw",
        "    if not isinstance(slots, list) or not all(\n        isinstance(s, str) and CLAIM_LABEL.match(s) for s in slots\n    ):\n",
        "    if not isinstance(slots, list) or not all(\n        isinstance(s, str) for s in slots\n    ):\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_claim_outside_its_shape_refuses_the_formula",
        ],
    ),
    (
        "a provider's claim may name a slot twice",
        "dotdiw",
        "    if len(set(slots)) != len(slots):\n",
        "    if False:\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_claim_outside_its_shape_refuses_the_formula",
        ],
    ),
    (
        "a provider's placeholder may name no slot",
        "dotdiw",
        "        if name not in slots:\n            raise ValueError(\n",
        "        if False:\n            raise ValueError(\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_claim_outside_its_shape_refuses_the_formula",
        ],
    ),
    (
        "a pour hands the tracker no claim",
        "dotdiw",
        '        out["claim"] = step["claim"]\n',
        "        pass\n",
        ["test_promise.py", "TheTrackerDoor.test_a_pour_hands_the_tracker_each_steps_claim"],
    ),
    (
        "local pours a step without its claim",
        "dotdiw",
        '                        json.dumps(s["claim"]) if s.get("claim") else None,\n',
        "                        None,\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local pours a step without its id",
        "dotdiw",
        '                        root_id,\n                        s["id"],\n',
        "                        root_id,\n                        None,\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no step back",
        "dotdiw",
        '        item["step"] = row["step"]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no claim back",
        "dotdiw",
        '        item["claim"] = json.loads(row["claim"])\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no values back",
        "dotdiw",
        '        item["values"] = json.loads(row["claim_values"])\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local creates an item without the values a move carries",
        "dotdiw",
        "                    json.dumps(values) if values else None,\n",
        "                    None,\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local records no values",
        "dotdiw",
        '                (json.dumps(values) if values else None, local_now(), request["id"]),\n',
        '                (None, local_now(), request["id"]),\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "a label given empty is kept",
        "dotdiw",
        "            if at is not None:\n                out.pop(at)\n",
        "            pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "a label given again is added twice",
        "dotdiw",
        '            out[at] = {"label": v["label"], "text": v["text"]}\n',
        '            out.append({"label": v["label"], "text": v["text"]})\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "labels not given are dropped",
        "dotdiw",
        '    out: list[ClaimValue] = [{"label": v["label"], "text": v["text"]} for v in held]\n',
        "    out: list[ClaimValue] = []\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "a store 3.0.0 made gets no place for claims",
        "dotdiw",
        '                for column in ("step", "claim", "claim_values", "run"):\n',
        "                for column in ():\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_store_made_by_3_0_takes_step_claims_when_init_asks",
        ],
    ),
    (
        "beads pours a step without its claim",
        "dotdiw",
        '        argv = ["create", "--title=" + s["title"], "--parent=" + root_id, "--type=task", "--json"]\n        poured: dict[str, Any] = {"step": s["id"], "run": root_id}\n        if s.get("claim"):\n            poured["claim"] = s["claim"]\n',
        '        argv = ["create", "--title=" + s["title"], "--parent=" + root_id, "--type=task", "--json"]\n        poured: dict[str, Any] = {"step": s["id"], "run": root_id}\n        if s.get("claim"):\n            pass\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads reads no claim back",
        "dotdiw",
        '        item["claim"] = own["claim"]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads reads no values back",
        "dotdiw",
        '        item["values"] = [{"label": label, "text": text} for _, label, text in kept]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads creates an item without what a move carries",
        "dotdiw",
        '    moved = {k: request[k] for k in ("step", "claim", "run", "within", "calls") if request.get(k)}\n',
        "    moved: dict[str, Any] = {}\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira pours a step without its claim",
        "trackers/jira.py",
        '                "claim": s.get("claim"),\n',
        '                "claim": None,\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira reads no values back",
        "trackers/jira.py",
        '        out["values"] = values\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira lists children without their claims",
        "trackers/jira.py",
        '        query = {"jql": jql, "maxResults": 100, "fields": FIELDS, "properties": PROPERTY}\n',
        '        query = {"jql": jql, "maxResults": 100, "fields": FIELDS}\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_poured_shows_its_claim_among_its_roots_children_as_a_search_reads_it",
        ],
    ),
    (
        "jira keeps no values",
        "trackers/jira.py",
        '        call("PUT", of(key, "properties", name), body)\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "a label not in kebab-case is recorded",
        "dotdiw",
        '    bad = [v["label"] for v in values if not CLAIM_LABEL.match(v["label"])]\n',
        "    bad: list[str] = []\n",
        ["test_promise.py", "AStepsRun.test_nothing_is_recorded_where_it_should_not_be"],
    ),
    (
        "a step with no claim takes values",
        "dotdiw",
        '        if not item.get("claim"):\n            return {\n                "status": "failed",\n                "reason": "no-claim",\n',
        '        if False:\n            return {\n                "status": "failed",\n                "reason": "no-claim",\n',
        ["test_promise.py", "AStepsRun.test_nothing_is_recorded_where_it_should_not_be"],
    ),
    (
        "a closed step takes values",
        "dotdiw",
        '        if item["status"] == "closed":\n            return {\n                "status": "failed",\n                "reason": "step-closed",\n',
        '        if False:\n            return {\n                "status": "failed",\n                "reason": "step-closed",\n',
        ["test_promise.py", "AStepsRun.test_nothing_is_recorded_where_it_should_not_be"],
    ),
    (
        "a step reads its own run as if it were the root",
        "dotdiw",
        '    if shown["status"] == "completed" and shown["item"].get("run"):\n',
        "    if False:\n",
        ["test_promise.py", "AStepsRun.test_values_are_recorded_and_the_run_read_back"],
    ),
    (
        "a value that is not simple fills the means",
        "dotdiw",
        "        return value if value is not None and CLAIM_SIMPLE.match(value) else None\n",
        "        return value\n",
        [
            "test_promise.py",
            "AStepsRun.test_a_value_that_is_not_simple_fills_the_claim_and_not_the_means",
        ],
    ),
    (
        "a placeholder left open is not named",
        "dotdiw",
        "            if m.group(0) not in left:\n                left.append(m.group(0))\n",
        "            pass\n",
        ["test_promise.py", "AStepsRun.test_values_are_recorded_and_the_run_read_back"],
    ),
    (
        "the journey answers no run",
        "dotdiw",
        '    if read.get("run"):\n        out["run"] = read["run"]\n',
        "    pass\n",
        ["test_promise.py", "AStepsRun.test_values_are_recorded_and_the_run_read_back"],
    ),
    (
        "claim reads nothing from standard input",
        "dotdiw",
        "        if not lines and not sys.stdin.isatty():\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_lines_on_standard_input_are_recorded_the_same_way",
        ],
    ),
    (
        "claim records a line that is not label: value",
        "dotdiw",
        "            if colon and CLAIM_LABEL.match(label.strip()):\n",
        "            if colon:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_line_that_is_not_label_value_refuses_the_whole_input",
        ],
    ),
    (
        "a pour names no claimed step",
        "dotdiw",
        '        if claim and made.get(s["id"]):\n',
        "        if False:\n",
        ["test_promise.py", "TheTrackerDoor.test_a_pour_names_each_claimed_step_it_made"],
    ),
    (
        "the pour prints no claim",
        "dotdiw",
        '    for c in response.get("claims") or [] if not request.get("json") else []:\n',
        "    for c in []:\n",
        ["test_dotdiw.py", "TheClaimCommand.test_the_pour_says_how_to_record_each_claim"],
    ),
    (
        "dotdiw's own commands answer no --help",
        "dotdiw",
        '    if helped and ("--help" in argv[1:] or "-h" in argv[1:]):\n',
        "    if False:\n",
        ["test_dotdiw.py", "TheHelpOfDotdiwsOwnCommands.test_each_own_command_answers_help"],
    ),
    (
        "a Jira issue whose claim was not kept hides its key",
        "trackers/jira.py",
        '            out["summary"] = "Jira made %s and could not keep its claim: %s" % (key, out["summary"])\n            return out, key\n',
        '            out["summary"] = "Jira made %s and could not keep its claim: %s" % (key, out["summary"])\n            return out, None\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_pour_whose_claim_jira_cannot_keep_names_what_it_made",
        ],
    ),
    (
        "a provider's description keeps its means",
        "dotdiw",
        '        kept, means = read_verify_using(description.rstrip("\\n"))\n',
        "        kept, means = description, []\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_descriptions_are_read_into_the_same_model",
        ],
    ),
    (
        "a step's description names no id",
        "dotdiw",
        '            told["id"] = line[len("Step ID:") :].strip()\n',
        "            pass\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_descriptions_are_read_into_the_same_model",
        ],
    ),
    (
        "a step's description names no needs",
        "dotdiw",
        '            told["needs"] = [n.strip() for n in line[len("Needs:") :].split(",") if n.strip()]\n',
        "            pass\n",
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_descriptions_are_read_into_the_same_model",
        ],
    ),
    (
        "a step's description holds no claim",
        "dotdiw",
        '            told["claim"] = {\n',
        '            told["unread"] = {\n',
        [
            "test_promise.py",
            "AStepsClaim.test_a_providers_descriptions_are_read_into_the_same_model",
        ],
    ),
    (
        "formula show answers a provider's claim in the record's form",
        "dotdiw",
        '                claim.update({"%s:" % label: {} for label in s["claim"]["slots"]})\n',
        '                claim["slots"] = s["claim"]["slots"]\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_formula_show_answers_a_providers_claim_in_the_form_a_file_takes",
        ],
    ),
    (
        "a means' placeholder splits at its first dot",
        "dotdiw",
        '        step, dot, label = inner.rpartition(".")\n',
        '        step, dot, label = inner.partition(".")\n',
        ["test_promise.py", "AStepsRun.test_a_step_id_with_a_dot_names_its_step_in_the_means"],
    ),
    (
        "check names no means placeholder",
        "dotdiw",
        "            if label not in claimed.get(step_id, []):\n",
        "            if False:\n",
        [
            "test_promise.py",
            "AStepsClaim.test_check_names_a_means_placeholder_that_names_no_claimed_slot",
        ],
    ),
    (
        "a run's steps are its root's children",
        "dotdiw",
        '    listed = invoke_tracker("operation.list-items", dict(where, scope="all", run=top["id"]))\n',
        '    listed = dict(shown, items=shown.get("children"))\n',
        ["test_promise.py", "AStepsRun.test_a_step_moved_in_from_another_run_is_left_out"],
    ),
    (
        "a move leaves the run behind",
        "dotdiw",
        '                "run": ids.get(whole["run"]) if whole.get("run") else None,\n',
        '                "run": None,\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_move_carries_the_claims_their_values_and_their_run",
        ],
    ),
    (
        "a move leaves the values behind",
        "dotdiw",
        '                "values": list(whole.get("values") or []) or None,\n',
        '                "values": None,\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_move_carries_the_claims_their_values_and_their_run",
        ],
    ),
    (
        "a move leaves the claim behind",
        "dotdiw",
        '                "claim": whole.get("claim"),\n',
        '                "claim": None,\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_move_carries_the_claims_their_values_and_their_run",
        ],
    ),
    (
        "local pours a step without its run",
        "dotdiw",
        '                        json.dumps(s["claim"]) if s.get("claim") else None,\n'
        "                        root_id,\n",
        '                        json.dumps(s["claim"]) if s.get("claim") else None,\n'
        "                        None,\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "local reads no run back",
        "dotdiw",
        '        item["run"] = row["run"]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads pours a step without its run",
        "dotdiw",
        '        argv = ["create", "--title=" + s["title"], "--parent=" + root_id, "--type=task", "--json"]\n        poured: dict[str, Any] = {"step": s["id"], "run": root_id}\n',
        '        argv = ["create", "--title=" + s["title"], "--parent=" + root_id, "--type=task", "--json"]\n        poured: dict[str, Any] = {"step": s["id"]}\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads reads no run back",
        "dotdiw",
        '        item["run"] = own["run"]\n',
        "        pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads puts every value under one key",
        "dotdiw",
        '    return BEADS_VALUE + label.replace("-", "_")\n',
        '    return BEADS_VALUE + "all"\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_claims_values_are_kept_under_keys_of_their_own"],
    ),
    (
        "jira pours a step without its run",
        "trackers/jira.py",
        '                "run": root_id,\n',
        '                "run": None,\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira reads no run back",
        "trackers/jira.py",
        '    for name in ("run", "within", "calls", "guard"):\n',
        '    for name in ("within", "calls", "guard"):\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira keeps every write under one property",
        "trackers/jira.py",
        '    return "%s%020d.%s" % (WRITE, moment, os.urandom(4).hex())\n',
        '    return WRITE + "0"\n',
        ["test_jira.py", "TheHostedAdapter.test_a_writer_of_other_labels_keeps_what_it_recorded"],
    ),
    (
        "jira shows a step without its values",
        "trackers/jira.py",
        '                full(i, project)\n                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search(\n                        "project = %s AND parent = %s',
        '                i\n                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search(\n                        "project = %s AND parent = %s',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_ready_gives_the_etag_show_and_list_give_for_an_issue_with_values",
        ],
    ),
    (
        "a step is read in the run of the parent it stands under",
        "dotdiw",
        '    if shown["status"] == "completed" and shown["item"].get("run"):\n        its_run = str(shown["item"]["run"])\n',
        '    if shown["status"] == "completed" and shown["item"].get("parent"):\n        its_run = str(shown["item"]["parent"])\n',
        [
            "test_promise.py",
            "AStepsRun.test_a_step_moved_away_is_read_in_the_run_it_was_poured_in",
        ],
    ),
    (
        "a step moved under another run's root is read in that run",
        "dotdiw",
        '    if shown["status"] == "completed" and shown["item"].get("run"):\n        its_run = str(shown["item"]["run"])\n',
        '    if shown["status"] == "completed" and shown["item"].get("parent"):\n        its_run = str(shown["item"]["parent"])\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_run_reads_only_the_steps_it_poured",
        ],
    ),
    (
        "a run is read from its root's children on the command line",
        "dotdiw",
        '    listed = invoke_tracker("operation.list-items", dict(where, scope="all", run=top["id"]))\n',
        '    listed = dict(shown, items=shown.get("children"))\n',
        ["test_dotdiw.py", "TheClaimCommand.test_a_run_reads_only_the_steps_it_poured"],
    ),
    (
        "local lists every item in a run",
        "dotdiw",
        '    if request.get("run") is not None:\n'
        '        where.append("run = ?")\n'
        '        args.append(request["run"])\n',
        "",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads lists every item in a run",
        "dotdiw",
        '        items = [i for i in items if i.get("run") == run][: limit or None]\n',
        "        items = items[: limit or None]\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira lists every item in a run",
        "trackers/jira.py",
        '                if run is None\n                or ((i.get("properties")',
        '                if True\n                or ((i.get("properties")',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira lists a step without its values",
        "trackers/jira.py",
        '                full(i, project)\n                for i in as_they_stand(\n                    request.get("root"), project, search(jql',
        '                i\n                for i in as_they_stand(\n                    request.get("root"), project, search(jql',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_with_values_and_no_step_lists_as_it_shows",
        ],
    ),
    (
        "migrate writes a step before the root of its run",
        "dotdiw",
        '                    or waits(item, "run")\n                    or waits(item, "within")\n',
        '                    or waits(item, "within")\n',
        ["test_dotdiw.py", "TheClaimCommand.test_a_move_writes_each_runs_root_before_its_steps"],
    ),
    (
        "migrate writes runs that wait on each other",
        "dotdiw",
        "                if not cut:\n                    stuck = sorted(",
        "                if not cut:\n                    cut = left\n                if False:\n                    stuck = sorted(",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_runs_that_wait_on_each_other_stop_the_move_unwritten",
        ],
    ),
    (
        "a root closes while a step of its run is open, under local",
        "dotdiw",
        '    return "(parent = ? OR run = ? OR ? IS NULL)"\n',
        '    return "(parent = ? OR NULL = ? OR ? IS NULL)"\n',
        ["test_dotdiw.py", "TheClaimCommand.test_a_run_closes_after_every_step_poured_in_it"],
    ),
    (
        "a root closes while a step of its run is open, under beads",
        "dotdiw",
        '        poured = [i for i, o in before.items() if ident in (o.get("run"), o.get("within"))]\n',
        "        poured = []\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_named_by_its_short_id_is_held_as_by_its_full_one",
        ],
    ),
    (
        "a root closes while a step of its run is open, under jira",
        "trackers/jira.py",
        '        if key in (own.get("run"), own.get("within")):\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_written_elsewhere_holds_a_close_by_what_a_search_finds",
        ],
    ),
    (
        "a molecule may close before any step of it",
        "contracts/named-work-found-its-procedure.cesc.yaml",
        "  - relationId: relation.a-step-closed-before-completed\n"
        "    before: step_closed\n"
        "    after: completed\n"
        "    quantifier: exists\n"
        "    meaning: enables\n"
        "    requiredEvidence:\n"
        "      anyOf:\n"
        "        - sameCaseKey\n",
        "",
        ["poa", "antitrace.run-closed-before-its-steps"],
    ),
    (
        "jira reads the writes newest first",
        "trackers/jira.py",
        "    names = sorted(k for k in properties if write_moment(k) is not None)\n",
        "    names = sorted((k for k in properties if write_moment(k) is not None), reverse=True)\n",
        ["test_jira.py", "TheHostedAdapter.test_a_write_is_read_after_every_write_the_step_held"],
    ),
    (
        "jira names a write for now, behind a later one",
        "trackers/jira.py",
        "    moment = max([time.time_ns() // 1000] + [m + 1 for m in moments])\n",
        "    moment = time.time_ns() // 1000\n",
        ["test_jira.py", "TheHostedAdapter.test_a_write_is_read_after_every_write_the_step_held"],
    ),
    (
        "jira keeps a label written empty",
        "trackers/jira.py",
        '                held.pop(str(v.get("label")), None)\n',
        "                pass\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "migrate leaves a parent it set late unset",
        "dotdiw",
        '            out = written("operation.update-item", {"id": ids[ident], "parent": ids[parent]})\n',
        '            out = {"status": "completed"}\n',
        ["test_dotdiw.py", "TheClaimCommand.test_a_root_under_its_own_step_keeps_that_parent"],
    ),
    (
        "migrate forgets which items wait for their parent",
        "dotdiw",
        '                if early:\n                    unparented.append(item["id"])\n',
        "",
        ["test_dotdiw.py", "TheClaimCommand.test_a_root_under_its_own_step_keeps_that_parent"],
    ),
    (
        "check looks in git for a file a claim names",
        "dotdiw",
        "            if CLAIM_PLACEHOLDER.search(path):\n"
        "                continue  # a claimed slot names it, so it is known once the run records it\n",
        "",
        ["test_dotdiw.py", "TheMeansToProveARun.test_check_leaves_a_file_a_claim_names_to_the_run"],
    ),
    (
        "the tracker door lets a request value outside its type",
        "dotdiw",
        '    kinds = record_kinds(spec["requestType"])\n'
        "    for key, value in request.items():\n"
        "        hold_value(operation, key, value, kinds[key], words=False)\n"
        "    name, adapter = resolve_tracker(request)\n",
        "    name, adapter = resolve_tracker(request)\n",
        [
            "test_promise.py",
            "TheTrackerDoor.test_a_request_value_outside_its_type_raises_before_an_adapter_answers",
        ],
    ),
    (
        "the tracker door holds an enum's word in a request to its words",
        "dotdiw",
        "        hold_value(operation, key, value, kinds[key], words=False)\n",
        "        hold_value(operation, key, value, kinds[key])\n",
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "the pass-through closes a root while a step of its run is open",
        "dotdiw",
        "                standing = what_stands_open(ident, before[ident], before, earlier, held)\n",
        "                standing = []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_the_command_line_holds_a_root_while_a_step_of_its_run_is_open",
        ],
    ),
    (
        "a root may come to wait on what waits on it",
        "dotdiw",
        "        if waiter == item or (waits is not None and waiter in waits):\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_edge_by_any_name_makes_a_root_wait_on_itself",
        ],
    ),
    (
        "what an item waits on leaves out its run",
        "dotdiw",
        "            for above in stands_under(i):\n",
        '            for above in (i.get("parent"),):\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_edge_by_any_name_makes_a_root_wait_on_itself",
        ],
    ),
    (
        "a need is never held at the command line",
        "dotdiw",
        '        return "checked", None, edge_pairs(words[0], needs.pop(), options.get("type")), []\n',
        '        return "as-it-is", None, [], []\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_edge_by_any_name_makes_a_root_wait_on_itself",
        ],
    ),
    (
        "local leaves the root of a moved step's run open",
        "dotdiw",
        '        for column in ("run", "within_item"):\n',
        '        for column in ("within_item",):\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_the_last_step_closes_the_root_of_its_run_wherever_it_stands",
        ],
    ),
    (
        "jira leaves the root of a moved step's run open",
        "trackers/jira.py",
        '        (item.get("run"), False),\n',
        "",
        [
            "test_jira.py",
            "TheHostedAdapter.test_the_last_step_closes_the_root_of_its_run_wherever_it_stands",
        ],
    ),
    (
        "local lists every item in an empty run",
        "dotdiw",
        '    if request.get("run") is not None:\n        where.append("run = ?")\n',
        '    if request.get("run"):\n        where.append("run = ?")\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "beads lists every item in an empty run",
        "dotdiw",
        "    if run is not None:\n"
        '        items = [i for i in items if i.get("run") == run][: limit or None]\n',
        '    if run:\n        items = [i for i in items if i.get("run") == run][: limit or None]\n',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "jira lists every item in an empty run",
        "trackers/jira.py",
        '                if run is None\n                or ((i.get("properties")',
        '                if not run\n                or ((i.get("properties")',
        ["test_tracker.py", "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter"],
    ),
    (
        "the log vouches for every close of a molecule",
        "dotdiw",
        '                        everyStepClosed=set(poured[ident].get("stepIds") or []) <= shut,\n',
        "                        everyStepClosed=True,\n",
        [
            "test_promise.py",
            "TheWitnessLogUnderLocal.test_a_root_closed_before_the_log_saw_every_step_is_no_valid_story",
        ],
    ),
    (
        "a molecule closed early completes its story",
        "contracts/named-work-found-its-procedure.cesc.yaml",
        "  - relationId: relation.every-step-closed-before-the-molecule\n"
        "    before: completed\n"
        "    after: closed_early\n"
        "    quantifier: exists\n"
        "    meaning: enables\n"
        "    requiredEvidence:\n"
        "      anyOf:\n"
        "        - sameCaseKey\n",
        "",
        ["poa", "antitrace.run-closed-with-a-step-unclosed"],
    ),
    (
        "the pass-through reports closed what its words name",
        "dotdiw",
        '            closed, notes = what_the_close_closed(\n                common, closing, every, out.get("markedIds"), out.get("exitCode", 1) != 0, holds\n            )\n',
        "            closed, notes = list(closing), []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_another_writer_made_first_is_not_this_ones",
        ],
    ),
    (
        "done closes a root unheld",
        "dotdiw",
        '    path = [word] if word in top["subcommands"] else beads_command([word], root)\n',
        '    path = [word] if word in top["subcommands"] else None\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "an option before the verb hides it",
        "dotdiw",
        '    while i < len(args) and args[i].startswith("-") and args[i] not in ("-", "--"):\n',
        "    while False:\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a short id is held as no item",
        "dotdiw",
        '            read[word] = str((shown.get("item") or {}).get("id") or word)\n',
        "            read[word] = word\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "an update to closed is no close",
        "dotdiw",
        '        return "checked", words if status == "closed" else None, edges, words\n',
        '        return "checked", None, edges, words\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a forced close passes an open child",
        "dotdiw",
        "        if i != ident and i not in earlier and ident in stands_under(o)\n",
        "        if i != ident and i not in earlier and ident in stands_under(o)[1:]\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a forced close passes an open need",
        "dotdiw",
        '    needs = [n for n in item.get("needs") or [] if n in standing and n not in earlier]\n',
        "    needs: list[str] = []\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a close runs where the tracker cannot be read",
        "dotdiw",
        '            elif listed.get("reason") not in TRACKER_CANNOT_ANSWER:\n                failed = dict(listed)\n                failed["summary"] = (\n                    "Nothing ran: what the tracker holds open could not be read',
        '            elif False:\n                failed = dict(listed)\n                failed["summary"] = (\n                    "Nothing ran: what the tracker holds open could not be read',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_does_not_run_where_the_tracker_cannot_be_read",
        ],
    ),
    (
        "a close by another command stands",
        "dotdiw",
        "        waiting = what_stands_open(ident, now[ident], standing, set(), held)\n        if waiting:\n",
        "        waiting = what_stands_open(ident, now[ident], standing, set(), held)\n        if False:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_what_a_close_closed_over_an_open_step_is_opened_again",
        ],
    ),
    (
        "the pass-through leaves the root of a run open",
        "dotdiw",
        "    follows = closes_that_follow(common, shut, {**before, **now}, standing, keep, held)\n",
        "    follows: list[Response] = []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_the_last_step_closes_the_root_of_its_run",
        ],
    ),
    (
        "a module's root is left open",
        "dotdiw",
        "            answers += closes_that_follow(common, closed, records, None, holds)\n",
        "",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_through_dotdiw_a_modules_root_closes_with_its_last_step",
        ],
    ),
    (
        "a parent no pour made closes with its last child",
        "dotdiw",
        '            if must_be_root and record.get("kind") != "root":\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_through_dotdiw_a_modules_root_closes_with_its_last_step",
        ],
    ),
    (
        "local waits by needs alone",
        "dotdiw",
        "        for nxt in needs + under:\n",
        "        for nxt in needs:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_root_and_its_step_cannot_come_to_wait_on_each_other",
        ],
    ),
    (
        "local takes a parent that waits on the item",
        "dotdiw",
        "            if parent and (parent == ident or parent in local_waiting(conn, ident, drop)):\n",
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_root_and_its_step_cannot_come_to_wait_on_each_other",
        ],
    ),
    (
        "local checks a need before its write",
        "dotdiw",
        '    ident, needs = request["id"], request["needs"]\n'
        "    try:\n"
        "        with local_write(conn):\n"
        "            for one in (ident, needs):\n"
        "                if not local_fetch(conn, one):\n"
        "                    return {\n"
        '                        "status": "failed",\n'
        '                        "reason": "item-not-found",\n'
        '                        "exitCode": 1,\n'
        '                        "summary": "%s names no item here." % one,\n'
        "                    }\n"
        "            if ident == needs or ident in local_waiting(conn, needs):\n",
        '    ident, needs = request["id"], request["needs"]\n'
        "    try:\n"
        "        early = local_waiting(conn, needs)\n"
        "        with local_write(conn):\n"
        "            for one in (ident, needs):\n"
        "                if not local_fetch(conn, one):\n"
        "                    return {\n"
        '                        "status": "failed",\n'
        '                        "reason": "item-not-found",\n'
        '                        "exitCode": 1,\n'
        '                        "summary": "%s names no item here." % one,\n'
        "                    }\n"
        "            if ident == needs or ident in early:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_parent_and_a_need_cannot_close_a_cycle_between_them",
        ],
    ),
    (
        "local checks a parent before its write",
        "dotdiw",
        '    try:\n        with local_write(conn):\n            if not local_fetch(conn, ident):\n                return {\n                    "status": "failed",\n                    "reason": "item-not-found",\n                    "exitCode": 1,\n                    "summary": "%s names no item here." % ident,\n                }\n            drop = [str(n) for n in request.get("dropNeeds") or []]\n            for need in drop:\n                held = local_fetch(conn, need)\n                if held is not None and "within_item" in held.keys():\n                    if held["within_item"] == ident:\n                        return {\n                            "status": "failed",\n                            "exitCode": 1,\n                            "summary": CALL_NEED_HELD % (ident, need),\n                        }\n            if parent and not local_fetch(conn, parent):\n                return {\n                    "status": "failed",\n                    "reason": "item-not-found",\n                    "exitCode": 1,\n                    "summary": "%s names no item here." % parent,\n                }\n            # Checked as the item will wait once the needs given to take off\n            # are off, so that a parent that waited on it only through one of\n            # them is no cycle; and nothing written where it is refused.\n            if parent and (parent == ident or parent in local_waiting(conn, ident, drop)):\n',
        '    try:\n        early = local_waiting(conn, ident, [str(n) for n in request.get("dropNeeds") or []])\n        with local_write(conn):\n            if not local_fetch(conn, ident):\n                return {\n                    "status": "failed",\n                    "reason": "item-not-found",\n                    "exitCode": 1,\n                    "summary": "%s names no item here." % ident,\n                }\n            drop = [str(n) for n in request.get("dropNeeds") or []]\n            for need in drop:\n                held = local_fetch(conn, need)\n                if held is not None and "within_item" in held.keys():\n                    if held["within_item"] == ident:\n                        return {\n                            "status": "failed",\n                            "exitCode": 1,\n                            "summary": CALL_NEED_HELD % (ident, need),\n                        }\n            if parent and not local_fetch(conn, parent):\n                return {\n                    "status": "failed",\n                    "reason": "item-not-found",\n                    "exitCode": 1,\n                    "summary": "%s names no item here." % parent,\n                }\n            # Checked as the item will wait once the needs given to take off\n            # are off, so that a parent that waited on it only through one of\n            # them is no cycle; and nothing written where it is refused.\n            if parent and (parent == ident or parent in early):\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_parent_and_a_need_cannot_close_a_cycle_between_them",
        ],
    ),
    (
        "a close that says nothing completes its story",
        "contracts/named-work-found-its-procedure.cesc.yaml",
        "    predicates:\n"
        "      - field: everyStepClosed\n"
        "        op: equals\n"
        "        value: true\n",
        "    predicates:\n"
        "      - field: everyStepClosed\n"
        "        op: notEquals\n"
        "        value: false\n",
        ["poa", "antitrace.run-closed-by-an-older-witness"],
    ),
    (
        "a close that says nothing is not closed early",
        "contracts/named-work-found-its-procedure.cesc.yaml",
        "    predicates:\n"
        "      - field: everyStepClosed\n"
        "        op: notEquals\n"
        "        value: true\n",
        "    predicates:\n"
        "      - field: everyStepClosed\n"
        "        op: equals\n"
        "        value: false\n",
        ["poa", "antitrace.run-closed-by-an-older-witness"],
    ),
    (
        "an item opened again is kept without its parent and its run",
        "dotdiw",
        "            standing[ident] = dict(now[ident], status=status)\n",
        '            standing[ident] = {"id": ident, "status": status}\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_what_a_close_closed_over_an_open_step_is_opened_again",
        ],
    ),
    (
        "a wait the tracker cannot show is taken for none",
        "dotdiw",
        '            if shown["status"] != "completed" and shown.get("reason") != "item-not-found":\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_wait_that_cannot_be_read_stops_the_need",
        ],
    ),
    (
        "a root the tracker cannot show is passed over",
        "dotdiw",
        '                if shown["status"] != "completed":\n'
        '                    if shown.get("reason") != "item-not-found":\n',
        '                if shown["status"] != "completed":\n                    if False:\n',
        [
            "test_dotdiw.py",
            "ThePlacesAModuleIsFound.test_through_dotdiw_a_modules_root_closes_with_its_last_step",
        ],
    ),
    (
        "a command dotdiw cannot check is asked of the tracker",
        "dotdiw",
        '    if name in TRACKER_REFUSED:\n        return "refused:%s" % word\n',
        "",
        [
            "test_dotdiw.py",
            "WithoutTheBeadsBinary.test_a_command_dotdiw_cannot_check_is_refused_with_or_without_the_binary",
        ],
    ),
    (
        "a subcommand that closes runs",
        "dotdiw",
        "    if name in TRACKER_SUBCOMMANDS_AS_IT_IS and sub in TRACKER_SUBCOMMANDS_AS_IT_IS[name]:\n",
        "    if name in TRACKER_SUBCOMMANDS_AS_IT_IS:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "an option that closes runs",
        "dotdiw",
        "    closing = [o for o in TRACKER_CLOSING_OPTIONS.get(name, ()) if options.get(o)]\n",
        "    closing: list[str] = []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "an update of what dotdiw keeps runs",
        "dotdiw",
        '        if kept:\n            return "refused:%s --%s" % (said, kept[0]), None, [], []\n',
        "",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "an update to a status of the tracker's own runs",
        "dotdiw",
        '        if isinstance(status, str) and status not in TRACKER_OPEN_STATUSES + ("closed",):\n',
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "a file of needs runs",
        "dotdiw",
        '        if "file" in options:\n            return "refused:%s --file" % said, None, [], []\n',
        "",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "a command the tracker knows runs unasked",
        "dotdiw",
        '    return "refused:%s" % said, None, [], []\n',
        '    return "as-it-is", None, [], []\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "a word the tracker does not know is refused",
        "dotdiw",
        '        return "as-it-is", None, [], []  # a word the tracker knows by no command\n',
        '        return "refused:it", None, [], []\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_command_dotdiw_cannot_check_is_refused_before_it_runs",
        ],
    ),
    (
        "a root the tracker closed during the close goes unlogged",
        "dotdiw",
        "        shut += [i for i in marked if i not in named and i in now and i in before]\n",
        "        shut += []\n",
        ["test_promise.py", "TheWitnessLog.test_a_real_run_is_a_story_the_contract_calls_valid"],
    ),
    (
        "a close not read back passes without a word",
        "dotdiw",
        "        return [], notes + [unread(ident, why) for ident in named]\n",
        "        return [], notes\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_closed_over_a_moved_step_opens_again_without_a_receipt",
        ],
    ),
    (
        "a close the tracker cannot list after passes without a word",
        "dotdiw",
        '        return [], [unread(ident, listed["summary"]) for ident in named]\n',
        "        return [], []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_what_a_close_closed_over_an_open_step_is_opened_again",
        ],
    ),
    (
        "the log takes another writer's close",
        "dotdiw",
        "        shut = [i for i in named if i in marked and i in now and i in before]\n",
        '        shut = [i for i in named if (now.get(i) or {}).get("status") == "closed"]\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_another_writer_made_first_is_not_this_ones",
        ],
    ),
    (
        "a need of any type but blocks is let through",
        "dotdiw",
        "    if kind in TRACKER_EDGES_WITHOUT_A_WAIT:\n        return []\n",
        '    if kind not in (None, "blocks"):\n        return []\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_edge_by_any_name_makes_a_root_wait_on_itself",
        ],
    ),
    (
        "an attached value is read as a switch",
        "dotdiw",
        '            beads_keep(options, long, arity, a[k + 2 :] if a[k + 1] == "=" else a[k + 1 :])\n',
        "            options[long] = True\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "the first value of an option stands",
        "dotdiw",
        "        options[long] = value\n",
        "        options.setdefault(long, value)\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a switch given false is taken for true",
        "dotdiw",
        "            options[long] = BEADS_SWITCH[value] if eq else True\n",
        "            options[long] = True\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a close naming no id runs",
        "dotdiw",
        "        if not words:\n"
        '            return "refused:%s with no id" % said, None, [], []\n'
        '        return "checked", words, [], []\n',
        '        return "checked", words, [], []\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "another store's close runs",
        "dotdiw",
        '    if elsewhere:\n        return "refused:%s --%s" % (said, elsewhere[0]), None, [], []\n',
        "",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "an option the tracker does not take is passed over",
        "dotdiw",
        "        if entry is None:\n"
        '            return "--%s is no option of the command." % name\n',
        "        if entry is None:\n            return j + 1\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "the checkout is not held while a close or a wait is checked and written",
        "dotdiw",
        "                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)\n",
        "                pass\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_two_commands_at_once_cannot_each_pass_the_check",
        ],
    ),
    (
        "options before the verb hide a root's type",
        "dotdiw",
        "    if args and (\n"
        '        request.get("mark") or args[0].startswith("-") or args[0] in ("update", "q", "label")\n'
        "    ):\n",
        '    if args and args[0] in ("update", "q", "label"):\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
    ),
    (
        "any close is taken for this one's",
        "dotdiw",
        '        if row.get("status") == "closed" and row.get("closed_by_session") == session\n',
        '        if row.get("status") == "closed"\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_another_writer_made_first_is_not_this_ones",
        ],
    ),
    (
        "a close another made first is taken for this one",
        "dotdiw",
        '        if row.get("status") == "closed" and row.get("closed_by_session") == session\n',
        '        if row.get("status") == "closed"\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_another_writer_made_first_is_not_this_ones",
        ],
    ),
    (
        "the tracker's own close, opened again, fails the command",
        "dotdiw",
        "        own = ident in named or why is not None\n",
        "        own = True\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_the_tracker_closes_over_a_moved_step_is_opened_again",
        ],
    ),
    (
        "a need named twice is checked as one",
        "dotdiw",
        "        if len(needs) > 1:\n"
        '            return "refused:%s naming more than one need" % said, None, [], []\n',
        "",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_every_way_of_closing_a_root_is_held"],
    ),
    (
        "a close's own session hides dotdiw's mark",
        "dotdiw",
        "    if args and (\n"
        '        request.get("mark") or args[0].startswith("-") or args[0] in ("update", "q", "label")\n'
        "    ):\n",
        '    if args and (args[0].startswith("-") or args[0] in ("update", "q", "label")):\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_the_last_step_closes_the_root_of_its_run",
        ],
    ),
    (
        "a close checks a run by the id as given, not as bd reads it",
        "dotdiw",
        '    ident = str(found[0].get("id"))\n    listed = beads_list({"root": root, "scope": "all"})\n',
        '    ident = request["id"]\n    listed = beads_list({"root": root, "scope": "all"})\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_named_by_its_short_id_is_held_as_by_its_full_one",
        ],
    ),
    (
        "a close not read back is taken for this one's",
        "dotdiw",
        "        marked = None if rows is None else beads_marked(rows, session)\n",
        "        marked = [ident] if rows is None else beads_marked(rows, session)\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_not_read_back_is_not_named_this_ones"],
    ),
    (
        "what a typed close closed against the rule is not held as its own close",
        "dotdiw",
        "        waiting = what_stands_open(ident, now[ident], standing, set(), held)\n        if waiting:\n",
        "        waiting = what_stands_open(ident, now[ident], standing, set(), held)\n        if False:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_step_opened_again_as_its_root_closes_blocks_that_close",
        ],
    ),
    (
        "a root another closed that will not open again passes the close",
        "dotdiw",
        "    if errored or left_open or gone or marked is None or unopened:\n",
        "    if errored or left_open or gone or marked is None:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_bd_closed_over_a_step_open_elsewhere_that_will_not_open_fails_the_close",
        ],
    ),
    (
        "a close not read back opens what it named again",
        "dotdiw",
        '        return [], [unread(ident, listed["summary"]) for ident in named]\n',
        "        for ident in named:\n"
        '            invoke_tracker("operation.update-item", dict(common, id=ident, status="open"))\n'
        '        return [], [unread(ident, listed["summary"]) for ident in named]\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_another_writer_made_first_is_not_this_ones",
        ],
    ),
    (
        "the checkout is let go before the log has the close",
        "dotdiw",
        "            if held and until_logged and scope is not None and scope.depth:\n",
        "            if False:\n",
        [
            "test_promise.py",
            "TheWitnessLogUnderLocal.test_two_closes_at_once_are_logged_in_the_order_they_closed",
        ],
    ),
    (
        "the run read before a close stands for the run after it",
        "dotdiw",
        '        now = {i["id"]: i for i in listed.get("items") or []}\n',
        '        now = {\n            i["id"]: i if i["id"] == ident or i.get("kind") == "root" else every.get(i["id"], i)\n            for i in listed.get("items") or []\n        }\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_bd_closes_is_held_to_its_run_as_it_stands_after_the_close",
        ],
    ),
    (
        "a root closed over a step of its run stands where no receipt is read",
        "dotdiw",
        "    for up in touched:\n",
        "    for up in []:\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_closed_over_a_moved_step_opens_again_without_a_receipt",
        ],
    ),
    (
        "a receipt that names nothing is taken for one that was read",
        "dotdiw",
        "    if any(beads_holds(i, root) is not False for i in dict.fromkeys(ids) if i not in rows):\n        return None\n",
        "    if False:\n        return None\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_closed_over_a_moved_step_opens_again_without_a_receipt",
        ],
    ),
    (
        "a close run again of what is closed reads nothing back",
        "dotdiw",
        "            if ident not in closing:\n                closing.append(ident)\n",
        "            if ident not in closing and ident in before:\n                closing.append(ident)\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_closed_over_a_moved_step_opens_again_without_a_receipt",
        ],
    ),
    (
        "a quick capture that cannot be read runs",
        "dotdiw",
        '        if reading["status"] != "completed" and reading.get("reason") not in TRACKER_CANNOT_ANSWER:\n',
        "        if False:\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
    ),
    (
        "every request shares one scope",
        "dotdiw",
        'SCOPE: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("scope", default=None)\n',
        'SCOPE: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("scope", default=Scope())\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_request_lets_go_of_no_lock_another_request_holds",
        ],
    ),
    (
        "bd is told its store and session through the process",
        "dotdiw",
        "    env = dict(os.environ)\n",
        "    env = os.environ\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_bd_is_given_its_store_and_session_by_each_run_never_by_the_process",
        ],
    ),
    (
        "a pinned root escapes the check before its close",
        "dotdiw",
        '            listed = invoke_tracker("operation.list-items", dict(common, scope="all"))\n',
        '            listed = invoke_tracker("operation.list-items", dict(common, scope="open"))\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_is_held_to_every_item_and_logs_only_its_own",
        ],
    ),
    (
        "an item closed before the command is taken for its close",
        "dotdiw",
        "        shut = [i for i in named if i in marked and i in now and i in before]\n",
        "        shut = [i for i in named if i in marked and i in now]\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_is_held_to_every_item_and_logs_only_its_own",
        ],
    ),
    (
        "a step named twice is logged twice",
        "dotdiw",
        "            if ident not in closing:\n                closing.append(ident)\n",
        "            closing.append(ident)\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_is_held_to_every_item_and_logs_only_its_own",
        ],
    ),
    (
        "a step bd lists only when asked stands unseen",
        "dotdiw",
        'BEADS_EVERY_ROW = ("--include-ephemeral", "--include-infra", "--include-gates")\n',
        "BEADS_EVERY_ROW: tuple[str, ...] = ()\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_step_bd_lists_only_when_asked_still_holds_its_root",
        ],
    ),
    (
        "bd's other name for the root's type passes",
        "dotdiw",
        'BEADS_ROOT_TYPES = ("molecule", "mol")\n',
        'BEADS_ROOT_TYPES = ("molecule",)\n',
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
    ),
    (
        "a short id names no children",
        "dotdiw",
        '        ["list", "--all", "--json", "-n", "0", *BEADS_EVERY_ROW, "--parent", ident],\n',
        '        ["list", "--all", "--json", "-n", "0", *BEADS_EVERY_ROW, "--parent", request["id"]],\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_short_id_is_read_as_bd_reads_it_for_children_too",
        ],
    ),
    (
        "a check of a tracker runs beside other requests",
        "dotdiw",
        "    with GATE.by_itself(), registered:\n",
        "    with registered:\n",
        ["test_dotdiw.py", "TheLocalAdapter.test_a_check_of_a_tracker_runs_alone_in_its_process"],
    ),
    (
        "a pass-through that reads no command is refused every command",
        "dotdiw",
        '        if "read" in extras:\n            return through_the_pass_through(common, argv, etags, terminal)\n',
        "        if True:\n            return through_the_pass_through(common, argv, etags, terminal)\n",
        ["test_dotdiw.py", "WhatAModuleGetsWrong.test_a_forward_extra_is_held_to_the_same_rule"],
    ),
    (
        "a root standing closed over open steps is left closed by a typed close",
        "dotdiw",
        "        if waiting:\n            opened(up, ",
        "        if False:\n            opened(up, ",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_run_again_sets_right_what_the_first_left"],
    ),
    (
        "a root another closed over open steps as a close ran stands closed",
        "dotdiw",
        "    touched += [i for i in before if i not in touched]\n",
        "    touched += []\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_another_closes_over_open_steps_as_a_close_runs_is_opened_again",
        ],
    ),
    (
        "a typed close opened again is answered as made",
        "dotdiw",
        "    elif held:\n        # The item named, opened again: what it waits on blocks its close.\n",
        "    elif False:\n        # The item named, opened again: what it waits on blocks its close.\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_step_opened_again_as_its_root_closes_blocks_that_close",
        ],
    ),
    (
        "what a close closed against the rule is opened as open, whatever it was",
        "dotdiw",
        '            opened(ident, before[ident]["status"], waiting, how)\n',
        '            opened(ident, "open", waiting, how)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_step_opened_again_as_its_root_closes_blocks_that_close",
        ],
    ),
    (
        "an answer of bd's that is no list is read as a listing of nothing",
        "dotdiw",
        '    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("id") for r in rows):\n',
        '    if not isinstance(rows, list):\n        return []\n    if not all(isinstance(r, dict) and r.get("id") for r in rows):\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_listing_that_is_no_list_of_rows_is_no_listing"],
    ),
    (
        "a row of bd's that is no object is read as an issue",
        "dotdiw",
        '    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("id") for r in rows):\n',
        '    if not isinstance(rows, list) or not all(not isinstance(r, dict) or r.get("id") for r in rows):\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_listing_that_is_no_list_of_rows_is_no_listing"],
    ),
    (
        "a row of bd's without an id is read as an issue",
        "dotdiw",
        '    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("id") for r in rows):\n',
        "    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_listing_that_is_no_list_of_rows_is_no_listing"],
    ),
    (
        "an answer of bd's that is no JSON is read as a listing of nothing",
        "dotdiw",
        "    except ValueError:\n        return None\n    if not isinstance(rows, list)",
        "    except ValueError:\n        return []\n    if not isinstance(rows, list)",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_listing_that_is_no_list_of_rows_is_no_listing"],
    ),
    (
        "a typed close runs on a listing that leaves out the item named",
        "dotdiw",
        "    if ident not in every:\n        return failed_as(\n            CloseItemResponse,",
        "    if False:\n        return failed_as(\n            CloseItemResponse,",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_listing_that_leaves_out_the_item_named_closes_nothing",
        ],
    ),
    (
        "a typed close holds the run to a listing that leaves out what the tracker holds",
        "dotdiw",
        "            if beads_holds(absent, root) is not False:\n",
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_listing_after_the_close_that_leaves_out_what_the_tracker_holds_is_no_listing",
        ],
    ),
    (
        "an item deleted as a typed close ran fails that close",
        "dotdiw",
        "            if beads_holds(absent, root) is not False:\n",
        "            if True:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_item_another_deletes_as_the_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "the item named, gone after its close, is taken for read back",
        "dotdiw",
        "    if errored or left_open or gone or marked is None or unopened:\n",
        "    if errored or left_open or marked is None or unopened:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_the_item_named_gone_after_its_close_is_not_read_back",
        ],
    ),
    (
        "the pass-through runs a close on a listing that leaves out the item named",
        "dotdiw",
        "            if ident not in every:\n                out.append(",
        "            if False:\n                out.append(",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_listing_that_leaves_out_what_a_close_names_is_no_listing",
        ],
    ),
    (
        "the pass-through holds the run to a listing that leaves out what the tracker holds",
        "dotdiw",
        '        if shown.get("reason") != "item-not-found":\n            why = "the tracker\'s list of every item leaves out %s, which it listed before." % absent\n',
        '        if False:\n            why = "the tracker\'s list of every item leaves out %s, which it listed before." % absent\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_listing_after_a_close_that_leaves_out_an_open_step_is_no_listing",
        ],
    ),
    (
        "an item deleted as a close ran fails the command",
        "dotdiw",
        '        if shown.get("reason") != "item-not-found":\n            why = "the tracker\'s list of every item leaves out %s, which it listed before." % absent\n',
        '        if True:\n            why = "the tracker\'s list of every item leaves out %s, which it listed before." % absent\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_an_item_another_deletes_as_a_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "an error of bd's close that names no refusal is answered without a read",
        "dotdiw",
        '            if refused.get("reason"):\n                return refused\n',
        "            if True:\n                return refused\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_bd_fails_after_making_still_holds_the_run",
        ],
    ),
    (
        "a close bd failed after making is answered as made",
        "dotdiw",
        "    if errored or left_open or gone or marked is None or unopened:\n",
        "    if left_open or gone or marked is None or unopened:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_bd_fails_after_making_still_holds_the_run",
        ],
    ),
    (
        "a close that left the item open is answered as made",
        "dotdiw",
        "    if errored or left_open or gone or marked is None or unopened:\n",
        "    if errored or gone or marked is None or unopened:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_bd_answers_and_does_not_make_is_no_close",
        ],
    ),
    (
        "a typed close not read back is answered as made",
        "dotdiw",
        "    if errored or left_open or gone or marked is None or unopened:\n",
        "    if errored or left_open or gone or unopened:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_not_read_back_is_not_named_this_ones",
        ],
    ),
    (
        "the item of a close bd failed is given as it stood before",
        "dotdiw",
        "            item = beads_record(printed[0]) if printed and not left_open else now[ident]\n",
        "            item = item if errored else now[ident]\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_bd_fails_after_making_still_holds_the_run",
        ],
    ),
    (
        "children that cannot be listed are shown as none",
        "dotdiw",
        "    children = beads_rows(listing)\n    if children is None:\n",
        "    children = beads_rows(listing) or []\n    if children is None:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_what_is_no_listing_is_no_empty_one_for_children_or_the_ready",
        ],
    ),
    (
        "a ready set that cannot be read is given as empty",
        "dotdiw",
        "    rows = beads_rows(out)\n    if rows is None:\n        return failed_as(ReadyItemsResponse,",
        "    rows = beads_rows(out) or []\n    if rows is None:\n        return failed_as(ReadyItemsResponse,",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_what_is_no_listing_is_no_empty_one_for_children_or_the_ready",
        ],
    ),
    (
        "a listing that cannot be read is given as empty",
        "dotdiw",
        "    rows = beads_rows(out)\n    if rows is None:\n        return failed_as(ListItemsResponse,",
        "    rows = beads_rows(out) or []\n    if rows is None:\n        return failed_as(ListItemsResponse,",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_listing_that_is_no_list_of_rows_is_no_listing"],
    ),
    (
        "an upgrade that reads no listing marks the workspace",
        "dotdiw",
        "    rows = beads_rows(out)\n    if rows is None:\n        return failed_as(dict,",
        "    rows = beads_rows(out) or []\n    if rows is None:\n        return failed_as(dict,",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_upgrade_that_reads_no_listing_moves_nothing_and_leaves_the_workspace_unmarked",
        ],
    ),
    (
        "an upgrade reads a plain listing",
        "dotdiw",
        '    code, out, err = beads_quiet(["list", "--all", "--json", "-n", "0", *BEADS_EVERY_ROW], root)\n',
        '    code, out, err = beads_quiet(["list", "--all", "--json", "-n", "0"], root)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_upgrade_reads_the_issues_a_plain_listing_leaves_out",
        ],
    ),
    (
        "children are listed under a parent that could not be shown",
        "dotdiw",
        '            if unshown.get("reason") != "item-not-found":\n                return failed_as(ListItemsResponse, "adapter-failed", unshown["summary"])\n',
        '            if False:\n                return failed_as(ListItemsResponse, "adapter-failed", unshown["summary"])\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_children_are_not_listed_under_a_parent_that_could_not_be_shown",
        ],
    ),
    (
        "a search page that holds no list of issues is read as an empty one",
        "trackers/jira.py",
        "        if not isinstance(issues, list):\n",
        "        issues = issues or []\n        if not isinstance(issues, list):\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_search_that_answers_no_list_of_issues_is_no_empty_one",
        ],
    ),
    (
        "a bound name runs its body outside a request",
        "promise_bindings.py",
        "        return dotdiw.invoke(asked, request)\n",
        "        return getattr(dotdiw, name)(request)\n",
        ["test_promise.py", "TheDoor.test_a_bound_name_is_a_request_of_its_own"],
    ),
    (
        "a root deleted as a typed close ran, shown as its step, is taken for held",
        "dotdiw",
        "        return ident in shown\n",
        "        return True\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_another_deletes_as_the_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "an item bd finds no more is not said to be gone",
        "dotdiw",
        '    return False if gone.get("reason") == "item-not-found" else None\n',
        "    return None\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_item_another_deletes_as_the_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "an item bd will not show is taken for gone",
        "dotdiw",
        '    return False if gone.get("reason") == "item-not-found" else None\n',
        "    return False\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_not_read_back_is_not_named_this_ones",
        ],
    ),
    (
        "an item bd holds and shows no row for is taken for gone",
        "dotdiw",
        "    if any(beads_holds(i, root) is not False for i in dict.fromkeys(ids) if i not in rows):\n",
        "    if any(beads_holds(i, root) is None for i in dict.fromkeys(ids) if i not in rows):\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_show_that_leaves_out_an_item_bd_holds_is_no_reading_of_it",
        ],
    ),
    (
        "marks the pass-through could not read are taken for none",
        "dotdiw",
        '        answer["markedIds"] = None if shown is None else beads_marked(shown, session)\n',
        '        answer["markedIds"] = [] if shown is None else beads_marked(shown, session)\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_closed_over_a_moved_step_opens_again_without_a_receipt",
        ],
    ),
    (
        "the item named, gone before it is read back, is taken for closed already",
        "dotdiw",
        "        gone = ident not in now or (rows is not None and ident not in rows)\n",
        "        gone = ident not in now\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_the_item_named_gone_before_its_session_is_read_is_not_read_back",
        ],
    ),
    (
        "the item named, gone after its close, stays an item as they stand",
        "dotdiw",
        "            now = {i: o for i, o in now.items() if i != ident}\n",
        "            now = dict(now)\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_named_gone_after_its_close_is_not_opened_again_in_its_steps_place",
        ],
    ),
    (
        "the item named, gone after its close, is answered as it stood before",
        "dotdiw",
        "            now = {i: o for i, o in now.items() if i != ident}\n            item = None\n",
        "            now = {i: o for i, o in now.items() if i != ident}\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_the_item_named_gone_after_its_close_is_not_read_back",
        ],
    ),
    (
        "the item named, gone after its close, is not said to be held no more",
        "dotdiw",
        '        said.append("%s The tracker holds it no more." % unread)\n',
        "        said.append(unread)\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_the_item_named_gone_after_its_close_is_not_read_back",
        ],
    ),
    (
        "a close of an item the tracker holds no more answers with an item",
        "dotdiw",
        '    if answer["status"] != "blocked" and item is not None:\n',
        '    if answer["status"] != "blocked":\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_the_item_named_gone_after_its_close_is_not_read_back",
        ],
    ),
    (
        "an item shown under another id is taken for the one asked for",
        "dotdiw",
        '    if shown["status"] != "completed" or other == ident:\n',
        "    if True:\n",
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_step_whose_root_is_gone_reads_no_run",
        ],
    ),
    (
        "an item shown under another id is a failure of the tracker",
        "dotdiw",
        '        "reason": "item-not-found",\n        "exitCode": 1,\n        "summary": "The tracker holds no item %s: asked for it, it shows %s." % (ident, other),\n',
        '        "reason": "adapter-failed",\n        "exitCode": 1,\n        "summary": "The tracker holds no item %s: asked for it, it shows %s." % (ident, other),\n',
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_close_closes_no_other_item_in_a_gone_roots_place",
        ],
    ),
    (
        "a step's run is read from the item shown in its gone root's place",
        "dotdiw",
        '        shown = shown_by_its_id(\n            its_run, invoke_tracker("operation.show-item", dict(where, id=its_run))\n        )\n',
        '        shown = invoke_tracker("operation.show-item", dict(where, id=its_run))\n',
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_step_whose_root_is_gone_reads_no_run",
        ],
    ),
    (
        "what an item waits on is read from the item shown in a gone one's place",
        "dotdiw",
        '            shown = shown_by_its_id(at, invoke_tracker("operation.show-item", dict(common, id=at)))\n',
        '            shown = invoke_tracker("operation.show-item", dict(common, id=at))\n',
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_need_is_not_refused_for_what_another_item_waits_on",
        ],
    ),
    (
        "a close closes the item shown in a gone root's place",
        "dotdiw",
        '                shown = shown_by_its_id(\n                    up, invoke_tracker("operation.show-item", dict(common, id=up))\n                )\n',
        '                shown = invoke_tracker("operation.show-item", dict(common, id=up))\n',
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_close_closes_no_other_item_in_a_gone_roots_place",
        ],
    ),
    (
        "a move copies the item shown in a listed one's place",
        "dotdiw",
        '                shown = shown_by_its_id(\n                    item["id"],\n                    invoke_tracker(\n                        "operation.show-item", {"root": root, "tracker": src, "id": item["id"]}\n                    ),\n                )\n',
        '                shown = invoke_tracker("operation.show-item", {"root": root, "tracker": src, "id": item["id"]})\n',
        [
            "test_dotdiw.py",
            "AnIdTheTrackerGaveIsReadWhole.test_a_move_copies_no_other_item_under_a_listed_id",
        ],
    ),
    (
        "a root deleted as a close ran, shown as its step, is a gap in the listing",
        "dotdiw",
        '        shown = shown_by_its_id(\n            absent, invoke_tracker("operation.show-item", dict(common, id=absent))\n        )\n',
        '        shown = invoke_tracker("operation.show-item", dict(common, id=absent))\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_another_deletes_as_a_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "a step named, gone after its close, is passed over",
        "dotdiw",
        '    notes += [\n        unread(ident, "the tracker holds it no more.")\n        for ident in named\n        if ident in before and ident not in now\n    ]\n',
        "    notes += []\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_step_named_gone_after_its_close_is_not_read_back",
        ],
    ),
    (
        "a step closed before the command and gone after it is a close left unread",
        "dotdiw",
        "        if ident in before and ident not in now\n",
        "        if ident not in now\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_step_closed_before_and_gone_after_is_no_close_unread",
        ],
    ),
    (
        "every step named that stood open is a close left unread",
        "dotdiw",
        "        if ident in before and ident not in now\n",
        "        if ident in before\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_root_another_deletes_as_a_close_runs_is_no_gap_in_the_listing",
        ],
    ),
    (
        "a reopen under beads reads a deleted root's id as its step's",
        "dotdiw",
        '    return beads_batch([["update", ident, "status=" + status]], root)\n',
        '    return beads_quiet(["update", ident, "--json", "-s", status], root)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_deleted_before_it_is_opened_again_opens_no_other_item",
        ],
    ),
    (
        "bd's word on stderr is read as its first line",
        "dotdiw",
        '    if not said and (err or "").lstrip().startswith("{"):\n',
        "    if False:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_root_deleted_before_it_is_opened_again_opens_no_other_item",
        ],
    ),
    (
        "a listing under beads that leaves out a step of a run is every item",
        "dotdiw",
        "        left_out = beads_left_out(rows, root)\n",
        "        left_out = None\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_step_left_out_of_every_listing_keeps_its_root_open",
        ],
    ),
    (
        "a pour under beads gives its steps no run label",
        "dotdiw",
        '        argv += ["--metadata=" + json.dumps({BEADS_KEY: poured}, ensure_ascii=False)]\n        argv += ["--labels=" + BEADS_RUN_LABEL]\n',
        '        argv += ["--metadata=" + json.dumps({BEADS_KEY: poured}, ensure_ascii=False)]\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_command_takes_the_run_label_off_a_step",
        ],
    ),
    (
        "the tracker door begins no request of its own",
        "dotdiw",
        "    with a_request():\n        return asked_of_the_tracker(operation, request)\n",
        "    return asked_of_the_tracker(operation, request)\n",
        [
            "test_dotdiw.py",
            "ABoundWriteWaitsWhileACheckRuns.test_a_bound_write_asked_during_a_check_lands_in_its_own_checkout",
        ],
    ),
    (
        "the pass-through takes a close that closed nothing for a close",
        "dotdiw",
        "    if not errored:\n        notes += [\n",
        "    if False:\n        notes += [\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_close_the_tracker_answers_without_closing_fails",
        ],
    ),
    (
        "a batch line under beads carries a second write in an id",
        "dotdiw",
        "            if not re.fullmatch(r'[^\\s\"\\\\#][^\\s\"\\\\]*', word):\n",
        '            if not re.fullmatch(r"(?s).+", word):\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_id_that_would_be_two_writes_in_a_batch_writes_nothing",
        ],
    ),
    (
        "an update bd wrote to another item in its place completes",
        "dotdiw",
        "            if wrote and ident not in wrote:\n                return failed_as(\n                    UpdateItemResponse,\n",
        "            if False:\n                return failed_as(\n                    UpdateItemResponse,\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_update_of_an_item_held_no_more_names_the_one_written",
        ],
    ),
    (
        "an update of an id bd reads as another's writes that other",
        "dotdiw",
        '        if whole["status"] != "completed":\n            return failed_as(UpdateItemResponse, "item-not-found", whole["summary"])\n',
        '        if False:\n            return failed_as(UpdateItemResponse, "item-not-found", whole["summary"])\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_update_of_an_item_held_no_more_names_the_one_written",
        ],
    ),
    (
        "a priority outside 0 to 4 is kept",
        "dotdiw",
        "    if priority is not None and not 0 <= priority <= 4:\n",
        "    if False:\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_priority_outside_0_to_4_is_refused"],
    ),
    (
        "a close reads a deleted root's id as its step's",
        "dotdiw",
        '    if whole["status"] != "completed":\n        return failed_as(CloseItemResponse, "item-not-found", whole["summary"])\n',
        '    if False:\n        return failed_as(CloseItemResponse, "item-not-found", whole["summary"])\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_of_a_root_held_no_more_closes_no_other"],
    ),
    (
        "a deleted root's short id is read as its step's",
        "dotdiw",
        '        or not (other.startswith(word) or "-" + word in other)\n',
        "        or not other.startswith(word)\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_of_a_root_held_no_more_closes_no_other"],
    ),
    (
        "a word bd reads as another item's names that item",
        "dotdiw",
        '        or not (other.startswith(word) or "-" + word in other)\n',
        "        or True\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_an_update_of_a_root_held_no_more_writes_no_other",
        ],
    ),
    (
        "the ids an update writes are not read before it runs",
        "dotdiw",
        '        return "checked", words if status == "closed" else None, edges, words\n',
        '        return "checked", words if status == "closed" else None, edges, []\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_an_update_of_a_root_held_no_more_writes_no_other",
        ],
    ),
    (
        "a claim writes by the word given, not the id it names",
        "dotdiw",
        '        "operation.record-values", dict(where, id=str(item["id"]), values=values)\n',
        '        "operation.record-values", dict(where, id=request["id"], values=values)\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_claim_is_recorded_on_the_step_named",
        ],
    ),
    (
        "a claim reads a deleted root's short id as its step's",
        "dotdiw",
        '        shown = shown_for_a_word(\n            request["id"], invoke_tracker(',
        '        shown = (lambda word, shown: shown)(\n            request["id"], invoke_tracker(',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_a_claim_is_recorded_on_the_step_named",
        ],
    ),
    (
        "a step of a run is found by its label alone",
        "dotdiw",
        '            BEADS_RUN_LABEL in (row.get("labels") or [])\n            or isinstance((beads_own(row) or {}).get("run"), str)\n            or ident in runs\n            or any(ident.startswith(n + ".") for n in runs)\n',
        '            BEADS_RUN_LABEL in (row.get("labels") or [])\n            or ident in runs\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_step_of_a_run_without_its_label_is_still_found_by_its_id",
        ],
    ),
    (
        "a command takes the run label off a step",
        "dotdiw",
        "    unlabelled = beads_label_kept(reading, root)\n",
        "    unlabelled = None\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_command_takes_the_run_label_off_a_step",
        ],
    ),
    (
        "labels given together are read as one",
        "dotdiw",
        "                out += [x.strip() for x in next(csv.reader([value]), [])]\n",
        "                out += [value]\n",
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_command_takes_the_run_label_off_a_step",
        ],
    ),
    (
        "a label remove of the run label runs",
        "dotdiw",
        ' or args[0] in ("update", "q", "label")\n',
        ' or args[0] in ("update", "q")\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_under_beads_no_command_takes_the_run_label_off_a_step",
        ],
    ),
    (
        "a run made in a move waits on a write after the create",
        "dotdiw",
        '    if moved.get("run"):\n        argv += ["--labels=" + BEADS_RUN_LABEL]\n',
        '    if moved.get("run"):\n        code, out, err = beads_quiet(["update", str(moved["run"]), "--json"], root)\n        if code != 0:\n            return beads_failed(CreateItemResponse, out, err, [])\n        argv += ["--labels=" + BEADS_RUN_LABEL]\n',
        [
            "test_dotdiw.py",
            "TheClaimCommand.test_a_closed_run_moves_into_beads_whole_though_bd_refuses_its_updates",
        ],
    ),
    (
        "a need under beads is given by bd's own reading of an id",
        "dotdiw",
        '    code, out, err = beads_batch([["dep", "add", request["id"], request["needs"]]], root)\n',
        '    code, out, err = beads_quiet(["dep", "add", request["id"], request["needs"]], root)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_need_of_an_item_held_no_more_is_given_to_no_other",
        ],
    ),
    (
        "a step of a run is found by its label or its id alone",
        "dotdiw",
        '            or isinstance((beads_own(row) or {}).get("run"), str)\n            or ident in runs\n',
        "            or ident in runs\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_step_made_under_another_item_without_its_label_is_found_by_its_run",
        ],
    ),
    (
        "a close is named this one's whoever made it",
        "dotdiw",
        '        if row.get("status") == "closed" and row.get("closed_by_session") == session\n',
        '        if row.get("status") == "closed"\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_another_made_first_is_named_closed_already",
        ],
    ),
    (
        "an item bd closed in the place of the one named goes unnamed",
        "dotdiw",
        "                    + [i for i in instead if i in now and i in before]\n",
        "                    + []\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_close_of_a_step_deleted_as_it_closes_names_the_sibling_bd_closed",
        ],
    ),
    (
        "bd's close is forced past its rule",
        "dotdiw",
        '        argv = ["close", ident, "--json"]\n        reason = request.get("closeReason")\n',
        '        argv = ["close", ident, "--json", "--force"]\n        reason = request.get("closeReason")\n',
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_bds_rule_refuses_writes_nothing"],
    ),
    (
        "a molecule bd closed with its last step goes unnamed",
        "dotdiw",
        '                        and o.get("kind") == "root"\n                        and i in now\n                        and now[i].get("status") == "closed"\n',
        "                        and False\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_molecule_bd_closes_with_its_last_step_is_named_after_it",
        ],
    ),
    (
        "the item is given as bd printed it, though it stands open",
        "dotdiw",
        "            item = beads_record(printed[0]) if printed and not left_open else now[ident]\n",
        "            item = beads_record(printed[0]) if printed else now[ident]\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_close_bd_answers_and_does_not_make_is_no_close"],
    ),
    (
        "beads writes a claim's values to the item bd shows",
        "dotdiw",
        '    whole = shown_by_its_id(ident, {"status": "completed", "item": found[0]})\n',
        '    whole = {"status": "completed"}\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_claims_values_go_to_no_other_item_than_the_one_named",
        ],
    ),
    (
        "beads takes values bd wrote to another item as recorded",
        "dotdiw",
        "        if wrote and ident not in wrote:\n            return failed_as(\n                RecordValuesResponse,\n",
        "        if False:\n            return failed_as(\n                RecordValuesResponse,\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_claims_values_go_to_no_other_item_than_the_one_named",
        ],
    ),
    (
        "beads numbers a label new to an item from the start",
        "dotdiw",
        "    last = max((n for n, _, _ in held), default=-1)\n",
        "    last = -1\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_claims_values_are_kept_under_keys_of_their_own"],
    ),
    (
        "beads keeps a label given empty and again in its place",
        "dotdiw",
        "    first = {label: n for n, label, _ in held if label not in emptied}\n",
        "    first = {label: n for n, label, _ in held}\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_claims_values_are_kept_under_keys_of_their_own"],
    ),
    (
        "beads moves a label given again to the end",
        "dotdiw",
        '        if v["label"] not in first:\n',
        "        if True:\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_claims_values_are_kept_under_keys_of_their_own"],
    ),
    (
        "beads keeps a label given empty",
        "dotdiw",
        '            flags.append("--unset-metadata=" + key)\n',
        "            pass\n",
        ["test_dotdiw.py", "TheBeadsAdapter.test_a_claims_values_are_kept_under_keys_of_their_own"],
    ),
    (
        "a claim the tracker declines is reported as its failure",
        "dotdiw",
        '            if recorded.get("reason") in ("item-not-found", "unsupported")\n',
        '            if recorded.get("reason") in ("item-not-found",)\n',
        ["test_promise.py", "AStepsRun.test_a_tracker_that_records_no_values_says_so"],
    ),
    (
        "a write on a stale read writes anyway",
        "dotdiw",
        "        if now != etag:\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_a_write_on_a_stale_read_writes_nothing",
        ],
    ),
    (
        "an item gone is taken as unchanged",
        "dotdiw",
        '            if shown.get("reason") == "item-not-found":\n                changed.append(etag)\n',
        '            if shown.get("reason") == "item-not-found":\n                pass\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_an_item_gone_has_changed",
        ],
    ),
    (
        "an ETag not in dotdiw's form is compared",
        "dotdiw",
        "        if form is None:\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_an_etag_that_is_none_of_dotdiws_is_refused_before_anything",
        ],
    ),
    (
        "the tracker door stamps no ETag",
        "dotdiw",
        "    stamp_etags(kinds, response)\n    settle_exit_code(operation, response)\n",
        "    settle_exit_code(operation, response)\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_every_read_of_an_unchanged_item_gives_one_etag",
        ],
    ),
    (
        "an item's ETag leaves a field out",
        "dotdiw",
        '    own = {k: v for k, v in record.items() if k != "etag"}\n',
        '    own = {k: v for k, v in record.items() if k not in ("etag", "assignee")}\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_any_change_to_an_item_changes_its_etag",
        ],
    ),
    (
        "a run's ETag leaves its items out",
        "dotdiw",
        "    held = [item_etag(root)] + sorted(item_etag(i) for i in items)\n",
        "    held = [item_etag(root)]\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_a_run_has_one_etag_over_every_item_poured_in_it",
        ],
    ),
    (
        "a claim takes no lock",
        "dotdiw",
        '    with held_for_writing(request.get("root"), request.get("tracker")) as held:\n',
        "    with contextlib.nullcontext(True) as held:\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_a_claim_waits_on_the_workspace_lock",
        ],
    ),
    (
        "a claim's values compare nothing",
        "dotdiw",
        '        if request.get("etags"):\n            compared = invoke(\n                "operation.compare-what-was-read", dict(where, etags=request["etags"])\n',
        '        if False:\n            compared = invoke(\n                "operation.compare-what-was-read", dict(where, etags=request["etags"])\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_values_on_a_stale_run_are_not_recorded",
        ],
    ),
    (
        "a create compares nothing",
        "dotdiw",
        '        if etags:\n            compared = invoke(\n                "operation.compare-what-was-read",\n                {"root": root, "tracker": request.get("tracker"), "etags": etags},\n',
        '        if False:\n            compared = invoke(\n                "operation.compare-what-was-read",\n                {"root": root, "tracker": request.get("tracker"), "etags": etags},\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_a_create_under_a_parent_holds_to_the_parents_etag",
        ],
    ),
    (
        "a write answered in records compares nothing",
        "dotdiw",
        "                return refusal(operation, [compared])\n        holds: list[str] = []\n        refused, _ = held_at_the_command_line(\n",
        "                pass\n        holds: list[str] = []\n        refused, _ = held_at_the_command_line(\n",
        [
            "test_dotdiw.py",
            "TheLocalAdapterHeldToWhatWasRead.test_a_write_on_a_stale_read_writes_nothing",
        ],
    ),
    (
        "a write checked under the pass-through compares nothing",
        "dotdiw",
        "                return refusal(operation, [compared])\n        every: dict[str, TrackerItem] | None = None\n",
        "                pass\n        every: dict[str, TrackerItem] | None = None\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_write_on_a_stale_read_writes_nothing",
        ],
    ),
    (
        "a command run as it is compares nothing",
        "dotdiw",
        "                    return refusal(None, [compared])\n            if reopened or dropped:\n",
        "                    pass\n            if reopened or dropped:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_command_passed_through_as_it_is_holds_to_its_etags",
        ],
    ),
    (
        "beads lists an item without its description",
        "dotdiw",
        '    argv = ["list", "--json", "-n", "0" if run is not None else str(limit)]\n',
        '    argv = ["list", "--json", "--brief", "-n", "0" if run is not None else str(limit)]\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_listing_holds_every_field_of_each_item",
        ],
    ),
    (
        "beads answers a write's time to the microsecond",
        "dotdiw",
        '        "createdAt": beads_held_time(row.get("created_at")),\n',
        '        "createdAt": row.get("created_at"),\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_record_a_write_answers_is_the_record_bd_holds",
        ],
    ),
    (
        "without a terminal, show runs as the tracker prints it",
        "dotdiw",
        '    return len(plain) == 1 if verb == "show" else not plain\n',
        "    return False\n",
        [
            "test_dotdiw.py",
            "ServedOverGrpcUnderBeads.test_a_write_on_a_stale_read_is_aborted_and_writes_nothing",
        ],
    ),
    (
        "gRPC answers a stale write as a response",
        "dotdiw",
        '        if response.get("reason") == "changed-since-read":\n            context.abort(grpc.StatusCode.ABORTED, response["summary"])\n',
        "",
        [
            "test_dotdiw.py",
            "ServedOverGrpc.test_a_write_on_a_stale_read_is_aborted_and_writes_nothing",
        ],
    ),
    (
        "gRPC lets a client say a terminal is there",
        "dotdiw",
        '        request.pop("terminal", None)\n',
        "",
        [
            "test_dotdiw.py",
            "ServedOverGrpcUnderBeads.test_a_client_never_has_a_terminal",
        ],
    ),
    (
        "gRPC projects an internal-only operation",
        "dotdiw",
        '    for spec in DOOR.values():\n        if spec["visibility"] == "internal-only":\n            continue\n',
        "    for spec in DOOR.values():\n        if False:\n            continue\n",
        [
            "test_promise.py",
            "TheGrpcProjection.test_the_operations_served_are_those_with_a_body_not_internal_only",
        ],
    ),
    (
        "a loaded tracker's lock is its checkout's",
        "dotdiw",
        "    if adapter is not None and is_loaded(adapter):\n",
        "    if False:\n",
        [
            "test_jira.py",
            "TwoCheckoutsOnOneProject.test_a_write_from_another_checkout_waits_then_finds_it_changed",
        ],
    ),
    (
        "two moves of one workspace run at once",
        "dotdiw",
        "    with held_at(os.path.join(ws, MIGRATION_LOCK)) as held:\n",
        "    with contextlib.nullcontext(True) as held:\n",
        [
            "test_jira.py",
            "OneMoveOfAWorkspaceAtATime.test_a_second_move_waits_and_makes_nothing_the_first_made",
        ],
    ),
    (
        "gRPC reads a value's empty text as none given",
        "dotdiw",
        "    for name in sorted(kind.__required_keys__ - out.keys()) if within else []:\n",
        "    for name in []:\n",
        [
            "test_dotdiw.py",
            "ServedOverGrpc.test_an_empty_text_in_a_value_is_given",
        ],
    ),
    (
        "a process keeps the checkout's choice for every request",
        "dotdiw",
        "    if stamp is not None and known is not None and known[0] == stamp:\n        return known[1]\n",
        "    if known is not None:\n        return known[1]\n",
        [
            "test_jira.py",
            "OneTrackerForARequest.test_a_choice_made_on_the_command_line_holds_for_the_next_request",
        ],
    ),
    (
        "a request finds the checkout's tracker again at each step",
        "dotdiw",
        "    held = scope.trackers if scope is not None else {}\n    if root not in held:\n",
        "    held = scope.trackers if scope is not None else {}\n    if True:\n",
        [
            "test_jira.py",
            "AWriteKeepsTheTrackerItResolved.test_a_tracker_found_by_its_store_holds_for_the_write",
        ],
    ),
    (
        "a choice written leaves the tracker the request found",
        "dotdiw",
        "        scope.workspaces.pop(root, None)\n        scope.trackers.pop(root, None)\n",
        "        scope.workspaces.pop(root, None)\n",
        [
            "test_jira.py",
            "OneAdoptionOfACheckoutAtATime.test_an_adoption_naming_no_tracker_keeps_the_one_chosen_meanwhile",
        ],
    ),
    (
        "an adoption keeps the key it read before it held the checkout",
        "dotdiw",
        '        forget_workspace(root)\n        prefix = request.get("prefix")\n',
        '        prefix = request.get("prefix")\n',
        [
            "test_dotdiw.py",
            "OneAdoptionOfACheckoutAtATime.test_a_second_adoption_finds_the_key_written_since_it_looked",
        ],
    ),
    (
        "two adoptions of a checkout run at once",
        "dotdiw",
        "    with held_at(lock, until_logged=False) as held:\n",
        "    with contextlib.nullcontext(True) as held:\n",
        [
            "test_dotdiw.py",
            "OneAdoptionOfACheckoutAtATime.test_a_second_adoption_waits_for_the_first_to_write_its_key",
        ],
    ),
    (
        "init writes an earlier version's choice unheld",
        "dotdiw",
        "        with held_at(adoption_lock(root), until_logged=False) as held:\n",
        "        with contextlib.nullcontext(True) as held:\n",
        [
            "test_dotdiw.py",
            "AnUpgradeKeepsAChoiceMadeMeanwhile.test_a_switch_while_init_holds_the_checkout_waits",
        ],
    ),
    (
        "init writes a choice without reading it again once it holds the checkout",
        "dotdiw",
        "            if held and tracker_name(root) is None:\n",
        "            if held:\n",
        [
            "test_dotdiw.py",
            "AnUpgradeKeepsAChoiceMadeMeanwhile.test_a_switch_before_init_holds_the_checkout_stands",
        ],
    ),
    (
        "an adoption told of its git directory through GIT_DIR locks another",
        "dotdiw",
        '    common = git(["rev-parse", "--git-common-dir"], root).strip()\n',
        '    common = os.path.dirname(checkout_config(root) or "")\n',
        [
            "test_dotdiw.py",
            "OneAdoptionOfACheckoutAtATime.test_an_adoption_told_the_git_directory_waits_all_the_same",
        ],
    ),
    (
        "a move opens its target unheld by an adoption",
        "dotdiw",
        "        with held_at(adoption_lock(root), until_logged=False) as adopting:\n",
        "        with contextlib.nullcontext(True) as adopting:\n",
        [
            "test_jira.py",
            "OneFirstOpenOfACheckoutsTracker.test_an_adoption_while_a_move_opens_jira_keeps_the_moves_project",
        ],
    ),
    (
        "a create under a parent given no ETags is made unheld",
        "dotdiw",
        '        if etags or request.get("parent")\n',
        "        if etags\n",
        [
            "test_jira.py",
            "WorkMadeUnderAnIssueWhileItCloses.test_a_child_named_while_its_parent_closes_waits",
        ],
    ),
    (
        "a pour makes its steps unheld",
        "dotdiw",
        '    with held_for_writing(root, request.get("tracker")) as held:\n',
        "    with contextlib.nullcontext(True) as held:\n",
        [
            "test_jira.py",
            "WorkMadeUnderAnIssueWhileItCloses.test_a_step_closed_while_its_pour_runs_waits",
        ],
    ),
    (
        "init brings a store up to date unheld",
        "dotdiw",
        '            held_for_writing(root, request.get("tracker"), until_logged=False)\n',
        "            contextlib.nullcontext(True)\n",
        [
            "test_dotdiw.py",
            "AnUpgradeWaitsForAWriteHeldToWhatItRead.test_init_waits_for_a_write_between_its_compare_and_its_write",
        ],
    ),
    (
        "a quick capture passed through runs unheld",
        "dotdiw",
        'TRACKER_HELD_AS_IT_IS = ("q", "reopen")\n',
        'TRACKER_HELD_AS_IT_IS = ("reopen",)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_quick_capture_under_an_issue_waits_for_its_close",
        ],
    ),
    (
        "a reopen passed through runs unheld",
        "dotdiw",
        'TRACKER_HELD_AS_IT_IS = ("q", "reopen")\n',
        'TRACKER_HELD_AS_IT_IS = ("q",)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_reopen_under_an_issue_waits_for_its_close",
        ],
    ),
    (
        "a command read whole is held by its first word",
        "dotdiw",
        '            asks, closing_words, edges, writes = what_the_command_asks(reading)\n            named = str((reading.get("command") or [""])[0])\n',
        "            asks, closing_words, edges, writes = what_the_command_asks(reading)\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapterHeldToWhatWasRead.test_a_reopen_under_an_issue_waits_for_its_close",
        ],
    ),
    (
        "a move writes to its target unheld",
        "dotdiw",
        "        with held_for_writing(root, dst) as writing:\n",
        "        with contextlib.nullcontext(True) as writing:\n",
        [
            "test_jira.py",
            "AMoveWritesUnderTheTargetsLock.test_a_resumed_move_cannot_write_between_a_compare_and_its_write",
        ],
    ),
    (
        "a move lets go of its target between its writes",
        "dotdiw",
        '        with held_for_writing(root, dst) as writing:\n            if not writing:\n                return {"status": "failed", "exitCode": 1, "summary": MOVE_BUSY % dst}\n            if told:\n                save()  # the stores it was told, kept though nothing is written\n\n            def written(operation: str, fields: dict[str, Any]) -> Response:\n                return invoke_tracker(operation, dict(fields, root=root, tracker=dst))\n',
        '        with contextlib.nullcontext(True) as writing:\n            if not writing:\n                return {"status": "failed", "exitCode": 1, "summary": MOVE_BUSY % dst}\n            if told:\n                save()  # the stores it was told, kept though nothing is written\n\n            def written(operation: str, fields: dict[str, Any]) -> Response:\n                with held_for_writing(root, dst, until_logged=False) as held:\n                    if not held:\n                        return dict(TRACKER_BUSY)\n                    return invoke_tracker(operation, dict(fields, root=root, tracker=dst))\n',
        [
            "test_jira.py",
            "AMoveWritesUnderTheTargetsLock.test_a_step_closed_before_the_move_makes_it_need_its_build_waits",
        ],
    ),
    (
        "a stopped move's step closes",
        "dotdiw",
        "    stopped = stopped_here(common) if closing_words else {}\n",
        "    stopped = {}\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_it_made_stays_unclosed_until_a_run_finishes_it",
        ],
    ),
    (
        "a stopped move's step closes through the pass-through",
        "dotdiw",
        "    stopped = stopped_here(common) if closing_words else {}\n",
        "    stopped = stopped_here(common) if closing_words and every is None else {}\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "a close with no pass-through is not held to a stopped move",
        "dotdiw",
        '            common, plain if operation == "operation.close-item" else None, edges, None, (), holds\n',
        "            common, None, edges, None, (), holds\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_it_made_stays_unclosed_until_a_run_finishes_it",
        ],
    ),
    (
        "ready gives a stopped move's steps",
        "dotdiw",
        '    if stopped:\n        items = [i for i in answer.get("items") or [] if i["id"] not in stopped]\n',
        '    if False:\n        items = [i for i in answer.get("items") or [] if i["id"] not in stopped]\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_it_made_stays_unclosed_until_a_run_finishes_it",
        ],
    ),
    (
        "a loaded tracker holds only this checkout's stopped moves",
        "dotdiw",
        '        os.path.join(os.path.expanduser(DOTDIW_HOME), "*")\n',
        "        ws\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_another_checkout_on_the_project_cannot_close_it_either",
        ],
    ),
    (
        "a shipped tracker holds no stopped move",
        "dotdiw",
        "        else ws\n    )\n",
        "        else os.devnull\n    )\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_under_local_the_checkouts_own_record_holds_it",
        ],
    ),
    (
        "a stopped move holds what it settled",
        "dotdiw",
        "        made = [str(m) for s, m in ids.items() if s not in settled]\n",
        "        made = [str(m) for s, m in ids.items()]\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_it_made_stays_unclosed_until_a_run_finishes_it",
        ],
    ),
    (
        "a close blocked by a move is said in bd's words",
        "dotdiw",
        '            if answer.get("reason") == "blocked" and answer.get("blockedBy"):\n',
        '            if answer.get("reason") == "blocked":\n',
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "jira names no issue it made and could not read back",
        "trackers/jira.py",
        "        out = dict(out, madeId=key)\n",
        "        out = dict(out)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_and_could_not_read_back_is_finished_not_made_again",
        ],
    ),
    (
        "a move forgets an item the target made and could not read back",
        "dotdiw",
        '                    if made.get("madeId"):\n',
        "                    if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_and_could_not_read_back_is_finished_not_made_again",
        ],
    ),
    (
        "a move takes an item made half for whole",
        "dotdiw",
        '                        unread.append(item["id"])\n',
        "                        pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "a move reads no item it made unread from its source",
        "dotdiw",
        '                if item["id"] in settled and not deleted:\n',
        '                if item["id"] in ids and not deleted:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_unfinished_item_is_taken_as_jira_shows_it_while_its_search_lags",
        ],
    ),
    (
        "a move finishes an item that holds not what its make gave",
        "dotdiw",
        "                if lacks:\n",
        "                if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "a move holds an item gone from the target",
        "dotdiw",
        '                if there.get("reason") == "item-not-found":\n                    if ids[ident] not in deleted:\n',
        "                if False:\n                    if ids[ident] not in deleted:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "a move keeps the id of an item gone from the target",
        "dotdiw",
        "                for ident in lost:\n                    forget(ident)\n",
        "                for ident in lost:\n                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "a move reads an item it finished back on every run",
        "dotdiw",
        '                unread.remove(ident)\n                (record.get("madeAs") or {}).pop(ident, None)\n                save()\n',
        '                (record.get("madeAs") or {}).pop(ident, None)\n                save()\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_and_could_not_read_back_is_finished_not_made_again",
        ],
    ),
    (
        "a move reads back no step",
        "dotdiw",
        'MADE_ONLY_BY_A_MAKE = ("description", "verifyUsing", "step", "claim", "run")\n',
        'MADE_ONLY_BY_A_MAKE = ("description", "verifyUsing", "claim", "run")\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "a move from a store with unfinished imports runs",
        "dotdiw",
        "            if half:\n",
        "            if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_from_jira_waits_for_the_move_into_it_to_finish",
        ],
    ),
    (
        "a move into another store holds items here",
        "dotdiw",
        '        if here and isinstance(record.get("store"), str) and record["store"] != here:\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_on_another_site_is_no_part_of_this_ones_move",
        ],
    ),
    (
        "a move records no store",
        "dotdiw",
        '        record["fromStore"], record["store"] = source_store, here\n',
        '        record["fromStore"], record["store"] = source_store, None\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_on_another_site_is_no_part_of_this_ones_move",
        ],
    ),
    (
        "a stopped move asks the tracker no store",
        "dotdiw",
        '    here = kept() if any(isinstance(r.get("store"), str) for r, _, _ in unsettled) else None\n',
        "    here = None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_on_another_site_is_no_part_of_this_ones_move",
        ],
    ),
    (
        "jira names no store",
        "trackers/jira.py",
        '        "storeId": "%s/projects/%s" % (cfg[0], project) if cfg is not None and project else None,\n',
        '        "storeId": None,\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_on_another_site_is_no_part_of_this_ones_move",
        ],
    ),
    (
        "a move records no checkout",
        "dotdiw",
        '        record["checkout"] = root\n',
        "        pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_and_could_not_read_back_is_finished_not_made_again",
        ],
    ),
    (
        "a stopped move says not where to run it again",
        "dotdiw",
        '            again = " in %s" % checkout\n',
        '            again = ""\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_it_made_stays_unclosed_until_a_run_finishes_it",
        ],
    ),
    (
        "ready reads unheld",
        "dotdiw",
        '        else held_for_writing(common.get("root"), common.get("tracker"), until_logged=False)\n    ) as held:\n',
        "        else contextlib.nullcontext(True)\n    ) as held:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_ready_reads_the_issues_and_the_record_at_one_moment",
        ],
    ),
    (
        "a pass-through's ready lists a stopped move's issues",
        "dotdiw",
        "            stopped = stopped_here(common) if ready else {}\n",
        "            stopped = {}\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "a pass-through's ready is refused whole while a move stands",
        "dotdiw",
        "            if stopped and read_in_records(argv):\n",
        "            if False:\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "a pass-through's ready with options runs while a move stands",
        "dotdiw",
        "            if stopped:\n                source, target, again = stopped[sorted(stopped)[0]]\n                said = READY_UNFINISHED % (\n",
        "            if False:\n                source, target, again = stopped[sorted(stopped)[0]]\n                said = READY_UNFINISHED % (\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "a move into another store reuses what it made there",
        "dotdiw",
        '        elsewhere = held_to("to", here)\n',
        "        elsewhere = None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_of_the_move_on_another_site_writes_nothing_there",
        ],
    ),
    (
        "a move finished in another store says to finish it",
        "dotdiw",
        "                    % (src, dst, some_of(unfinished), recorded, dst, where, dst, recorded)\n                    if unfinished\n",
        "                    % (src, dst, some_of(unfinished), recorded, dst, where, dst, recorded)\n                    if True\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_finished_on_one_site_writes_nothing_on_another",
        ],
    ),
    (
        "a move holds a record naming no store to the store named now",
        "dotdiw",
        "            recorded = record.get(key) or told\n",
        "            recorded = record.get(key) or told or now\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_store_is_held_to_one_only_once_told",
        ],
    ),
    (
        "a move takes an item not found for deleted",
        "dotdiw",
        "                    if ids[ident] not in deleted:\n                        return not_found(ident)\n                    lost.add(ident)\n",
        "                    lost.add(ident)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_cannot_find_is_held_until_it_reads_or_its_deletion_is_said",
        ],
    ),
    (
        "a move told of a deletion makes again what it reads",
        "dotdiw",
        '                if there.get("reason") == "item-not-found":\n                    if ids[ident] not in deleted:\n',
        '                if there.get("reason") == "item-not-found" or ids[ident] in deleted:\n                    if ids[ident] not in deleted:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_cannot_find_is_held_until_it_reads_or_its_deletion_is_said",
        ],
    ),
    (
        "a move hears no deletion",
        "dotdiw",
        '        deleted = set(request.get("deletedIds") or [])  # deleted in the target, the run is told\n',
        "        deleted: set[str] = set()\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "the journey drops the deletions",
        "dotdiw",
        '            "deletedIds": request.get("deletedIds"),\n',
        '            "deletedIds": None,\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "the command line drops --deleted",
        "dotdiw",
        "                if told is not None:\n                    told.append(value)\n",
        "                if told is not None:\n                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_made_without_its_step_is_made_again_once_deleted",
        ],
    ),
    (
        "jira asks no project of an issue",
        "trackers/jira.py",
        '    "description,project,statuscategorychangedate"\n',
        '    "description,statuscategorychangedate"\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira shows an issue of another project",
        "trackers/jira.py",
        'def jira_show(request: Request) -> Response:\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch_here(key, project)\n',
        'def jira_show(request: Request) -> Response:\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch(key)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira closes an issue of another project",
        "trackers/jira.py",
        'def jira_close(request: Request) -> Response:\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch_here(key, project)\n',
        'def jira_close(request: Request) -> Response:\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch(key)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira records values on an issue of another project",
        "trackers/jira.py",
        'def jira_record_values(request: Request) -> Response:\n    """operation.record-values: the values given, kept whole in one issue\n    property named after every write the issue holds, so that a write is\n    there whole or not at all and is read after them: a write cut short\n    reads as it was, writers of the same labels at once leave one write\n    whole, and a writer of other labels keeps what it recorded. Values more\n    than one property holds are kept in as few as hold them, a text longer\n    than one holds cut in pieces, each named after the one before and all\n    one write (keep_values), read whole or not at all."""\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch_here(key, project)',
        'def jira_record_values(request: Request) -> Response:\n    """operation.record-values: the values given, kept whole in one issue\n    property named after every write the issue holds, so that a write is\n    there whole or not at all and is read after them: a write cut short\n    reads as it was, writers of the same labels at once leave one write\n    whole, and a writer of other labels keeps what it recorded. Values more\n    than one property holds are kept in as few as hold them, a text longer\n    than one holds cut in pieces, each named after the one before and all\n    one write (keep_values), read whole or not at all."""\n    if config() is None:\n        return dict(NOT_CONFIGURED)\n    project, refused = opened(request.get("root"))\n    if refused or not project:\n        return refused or dict(NO_WORKSPACE)\n    key = request["id"]\n    try:\n        issue = fetch(key)',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira updates an issue of another project",
        "trackers/jira.py",
        '        issue = fetch_here(key, project)\n        if issue is None:\n            return {\n                "status": "failed",\n                "reason": "item-not-found",\n                "exitCode": 1,\n                "summary": "%s names no issue here." % key,\n            }\n        key = issue["key"]  # as Jira gives it, which reads a key in any case\n        drop =',
        '        issue = fetch(key)\n        if issue is None:\n            return {\n                "status": "failed",\n                "reason": "item-not-found",\n                "exitCode": 1,\n                "summary": "%s names no issue here." % key,\n            }\n        key = issue["key"]  # as Jira gives it, which reads a key in any case\n        drop =',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira sets a parent of another project",
        "trackers/jira.py",
        '            above = fetch_here(request["parent"], project)\n',
        '            above = fetch(request["parent"])\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira links an issue of another project",
        "trackers/jira.py",
        "            issue = fetch_here(one, project)\n",
        "            issue = fetch(one)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira closes the root another project's issue stands under",
        "trackers/jira.py",
        "        above = fetch_here(up, project)\n        if above is not None and (not must_be_root or",
        "        above = fetch(up) if must_be_root else fetch_here(up, project)\n        if above is not None and (not must_be_root or",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira closes the root another project's issue was poured in",
        "trackers/jira.py",
        "        above = fetch_here(up, project)\n        if above is not None and (not must_be_root or",
        "        above = fetch_here(up, project) if must_be_root else fetch(up)\n        if above is not None and (not must_be_root or",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "a move from another store reuses what it read",
        "dotdiw",
        '            elsewhere = held_to("from", source_store)\n',
        "            elsewhere = None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_stopped_move_from_one_site_finishes_from_it_alone",
        ],
    ),
    (
        "a move finished from another store says to finish it",
        "dotdiw",
        "                    % (src, dst, recorded, some_of(unfinished), src, where, src, recorded)\n                    if unfinished\n",
        "                    % (src, dst, recorded, some_of(unfinished), src, where, src, recorded)\n                    if True\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_from_one_site_is_no_move_from_another",
        ],
    ),
    (
        "a move records no store read from",
        "dotdiw",
        '        record["fromStore"], record["store"] = source_store, here\n',
        '        record["fromStore"], record["store"] = None, here\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_from_one_site_is_no_move_from_another",
        ],
    ),
    (
        "a move takes a store it is told over the record's",
        "dotdiw",
        "            recorded = record.get(key) or told\n",
        "            recorded = told or record.get(key)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_of_the_move_on_another_site_writes_nothing_there",
        ],
    ),
    (
        "a move keeps no store it is told",
        "dotdiw",
        '        told = bool(ids) and (record.get("fromStore"), record.get("store")) != (source_store, here)\n',
        "        told = False\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_told_its_store_keeps_it_though_nothing_is_written",
        ],
    ),
    (
        "a move hears the store told of the other side",
        "dotdiw",
        '                ("fromStore", src, request.get("fromStore"))\n',
        '                ("fromStore", src, request.get("toStore"))\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_told_its_store_keeps_it_though_nothing_is_written",
        ],
    ),
    (
        "a move names a store where the target names none",
        "dotdiw",
        "            where = now or STORE_UNNAMED\n",
        "            where = now\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_target_that_names_no_store_now_is_held_to_none",
        ],
    ),
    (
        "a move asks the store of the other side",
        "dotdiw",
        '                    ("read from", "--from-store") if side == "from" else ("wrote to", "--to-store")\n',
        '                    ("read from", "--from-store") if side == "to" else ("wrote to", "--to-store")\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_store_is_held_to_one_only_once_told",
        ],
    ),
    (
        "the journey drops the store written to",
        "dotdiw",
        '            "toStore": request.get("toStore"),\n',
        '            "toStore": None,\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_store_is_held_to_one_only_once_told",
        ],
    ),
    (
        "the journey drops the store read from",
        "dotdiw",
        '            "fromStore": request.get("fromStore"),\n',
        '            "fromStore": None,\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_told_its_store_keeps_it_though_nothing_is_written",
        ],
    ),
    (
        "the command line drops --to-store",
        "dotdiw",
        "                elif field:\n                    stores[field] = value\n",
        "                elif field:\n                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_store_is_held_to_one_only_once_told",
        ],
    ),
    (
        "the command line drops --from-store=",
        "dotdiw",
        '                option, eq, value = words[i].partition("=")\n',
        '                option, eq, value = words[i], "", ""\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_store_read_from_is_held_to_one_only_once_told",
        ],
    ),
    (
        "jira makes an issue under a parent of another project",
        "trackers/jira.py",
        "                above = fetch_here(request[field], project) if request.get(field) else None\n",
        "                above = fetch(request[field]) if request.get(field) else None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira makes an issue in a run of another project",
        "trackers/jira.py",
        '            for field in ("parent", "run", "within"):\n',
        '            for field in ("parent",):\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira checks no parent a create names",
        "trackers/jira.py",
        '    if config() is not None and (\n        request.get("parent") or request.get("run") or request.get("within")\n    ):\n',
        "    if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira counts only its project's children",
        "trackers/jira.py",
        '    found = {i["key"]: record(i) for i in search("parent = %s ORDER BY created ASC" % text(key))}\n',
        '    found = {\n        i["key"]: record(i)\n        for i in search(\n            "project = %s AND parent = %s ORDER BY created ASC" % (text(project), text(key))\n        )\n    }\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_checkout_on_another_project_reaches_no_issue_of_this_one",
        ],
    ),
    (
        "jira's ready takes another project's need for open",
        "trackers/jira.py",
        '        for n in sorted({n for i in items for n in i["needs"]} - set(status)):\n',
        "        for n in []:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_waiting_on_a_closed_issue_of_another_project_is_ready",
        ],
    ),
    (
        "jira's ready takes another project's need for closed",
        "trackers/jira.py",
        '            status[n] = record(issue)["status"] if issue is not None else "open"\n',
        '            status[n] = "closed"\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_waiting_on_a_closed_issue_of_another_project_is_ready",
        ],
    ),
    (
        "a move settles nothing before its closes",
        "dotdiw",
        '            done = [i["id"] for i in unsettled if i.get("status") != "closed" or i["id"] in relink]\n',
        "            done: list[str] = []\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_the_target_refuses_holds_only_what_is_closed",
        ],
    ),
    (
        "a move settles nothing as it closes",
        "dotdiw",
        '                        settle([item["id"]])\n                        open_there.discard(copy_id)\n                        save()\n',
        "                        pass\n",
        [
            "test_tracker.py",
            "AnInterruptedMove.test_a_finished_move_writes_nothing_again",
        ],
    ),
    (
        "a move holds what it is told the source deleted",
        "dotdiw",
        "            settled.extend(missing)\n",
        "            pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "a move says nothing of what it left as made",
        "dotdiw",
        '            if said.get("leftAsMade"):\n',
        "            if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "a move reads back only what it could not read",
        "dotdiw",
        "                if i in missing or i in byid and (i not in settled or ids[i] in deleted)\n",
        "                if i in unread and i in byid\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_deleted_in_jira_is_made_again_once_said",
        ],
    ),
    (
        "a move keeps what it is told was deleted",
        "dotdiw",
        "                    lost.add(ident)\n                    continue\n",
        "                    continue\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_deleted_in_jira_is_made_again_once_said",
        ],
    ),
    (
        "a move reads not whole what it makes again",
        "dotdiw",
        '                if item["id"] in settled and not deleted:\n',
        '                if item["id"] in settled:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_finished_issue_said_deleted_is_made_again",
        ],
    ),
    (
        "a move makes again a parent what it made stands under",
        "dotdiw",
        "                for ident in under:\n                    if ident not in unparented:\n                        unparented.append(ident)\n",
        "                for ident in under:\n                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_issues_in_the_run_of_a_deleted_one_are_made_again_with_it",
        ],
    ),
    (
        "a move makes again the root of a run it made",
        "dotdiw",
        "                if in_run:\n",
        "                if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_issues_in_the_run_of_a_deleted_one_are_made_again_with_it",
        ],
    ),
    (
        "a move says nothing of what it leaves out",
        "dotdiw",
        '            if said.get("leftOut"):\n',
        "            if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_says_what_it_leaves_out_of_another_project",
        ],
    ),
    (
        "a move says nothing of a parent it leaves out",
        "dotdiw",
        '                                ("parent", "stands under"),\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_says_what_it_leaves_out_of_another_project",
        ],
    ),
    (
        "jira puts a parent into a query as it is given",
        "trackers/jira.py",
        '            jql += " AND parent = %s" % text(under)\n',
        '            jql += " AND parent = %s" % under\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_listing_under_a_parent_reaches_no_other_project",
        ],
    ),
    (
        "jira lets a quote end a value in a query",
        "trackers/jira.py",
        '    return \'"%s"\' % value.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')\n',
        '    return \'"%s"\' % value.replace("\\\\", "\\\\\\\\")\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_listing_under_a_parent_reaches_no_other_project",
        ],
    ),
    (
        "jira lets a backslash end a value in a query",
        "trackers/jira.py",
        '    return \'"%s"\' % value.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')\n',
        "    return '\"%s\"' % value.replace('\"', '\\\\\"')\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_listing_under_a_parent_reaches_no_other_project",
        ],
    ),
    (
        "a move takes its listing's word for what is gone",
        "dotdiw",
        "            for ident in missing + aside + unlisted:\n",
        "            for ident in []:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_lists_late_stays_held_until_it_lists_it",
        ],
    ),
    (
        "a move leaves as made what the source may yet show",
        "dotdiw",
        "                elif ident in missing:\n",
        "                elif False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "a move hears of no deletion in the source",
        "dotdiw",
        '        source_gone = set(request.get("sourceGoneIds") or [])  # deleted there, as told\n',
        "        source_gone: set[str] = set()\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "the journey drops the deletions in the source",
        "dotdiw",
        '            "sourceGoneIds": request.get("sourceGoneIds"),\n',
        '            "sourceGoneIds": None,\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "the command line drops --source-gone=",
        "dotdiw",
        '                told = {"--deleted": deleted, "--source-gone": gone}.get(option)\n',
        '                told = {"--deleted": deleted, "--source-gone": deleted}.get(option)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "the command line takes --source-gone for --deleted",
        "dotdiw",
        '                told = {"--deleted": deleted, "--source-gone": gone}.get(option)\n',
        '                told = {"--deleted": deleted, "--source-gone": deleted}.get(option)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "a move records nothing gone",
        "dotdiw",
        "            gone.extend(missing)\n",
        "            pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_item_the_source_holds_no_more_stays_held_until_said",
        ],
    ),
    (
        "a move asks no need its listing lacks",
        "dotdiw",
        '                    {n for i in to_write for n in i.get("needs") or []}\n',
        "                    set()\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_jira_lists_late_stops_the_move_before_it_writes",
        ],
    ),
    (
        "a move asks no parent its listing lacks",
        "dotdiw",
        '                    | {i["parent"] for i in to_write if i.get("parent")}\n',
        "                    | set()\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_parent_jira_lists_late_stops_the_move_before_it_writes",
        ],
    ),
    (
        "a move takes an item as its listing has it",
        "dotdiw",
        '                items[n] = cast(TrackerItem, dict(item, **shown["item"]))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_takes_an_issue_as_jira_shows_it_not_as_its_search_has_it",
        ],
    ),
    (
        "a move reads back no finished item it is told was deleted",
        "dotdiw",
        "                if i in missing or i in byid and (i not in settled or ids[i] in deleted)\n",
        "                if i in missing or i in byid and i not in settled\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_finished_issue_said_deleted_is_made_again",
        ],
    ),
    (
        "a move leaves settled what waited on what it makes again",
        "dotdiw",
        "                        settled.remove(ident)\n                        relink.append(ident)\n",
        "                        pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_finished_issue_said_deleted_is_made_again",
        ],
    ),
    (
        "a move reads back nothing that stands on what it makes again",
        "dotdiw",
        "                for ident in sorted(set(waiting) | set(under)):\n",
        "                for ident in []:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_the_command_given_names_all_the_run_was_told",
        ],
    ),
    (
        "the command a refusal gives leaves out what the run was told",
        "dotdiw",
        '                + [given("--deleted", t) for t in sorted(deleted | set(more))]\n',
        '                + [given("--deleted", t) for t in sorted(set(more))]\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_the_command_given_names_all_the_run_was_told",
        ],
    ),
    (
        "a store splits in the command a refusal gives",
        "dotdiw",
        '                return "%s%s%s" % (flag, joined, shlex.quote(value))\n',
        '                return "%s%s%s" % (flag, joined, value)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_store_said_with_a_space_is_quoted_in_the_command_given",
        ],
    ),
    (
        "an id splits in the command a refusal gives",
        "dotdiw",
        '                + [given("--source-gone", t) for t in sorted(source_gone | set(more_gone))]\n',
        '                + ["--source-gone %s" % t for t in sorted(source_gone | set(more_gone))]\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_id_with_a_space_is_one_word_in_the_command_given",
        ],
    ),
    (
        "a move says nothing of a deletion it made nothing again of",
        "dotdiw",
        '            unheard = sorted(deleted - set(said.get("deletedHeard") or []))\n            if unheard:\n',
        '            unheard = sorted(deleted - set(said.get("deletedHeard") or []))\n            if False:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_says_what_it_was_told_and_had_nothing_to_do_of",
        ],
    ),
    (
        "a move says nothing of a source deletion it left nothing of",
        "dotdiw",
        '            unheard = sorted(source_gone - set(said.get("goneHeard") or []))\n            if unheard:\n',
        '            unheard = sorted(source_gone - set(said.get("goneHeard") or []))\n            if False:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_says_what_it_was_told_and_had_nothing_to_do_of",
        ],
    ),
    (
        "jira keeps no issue it makes",
        "trackers/jira.py",
        '    wrote(request.get("root"), key, request.get("parent"), request.get("run"))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_made_a_moment_ago_holds_its_parents_close_though_no_search_finds_it",
        ],
    ),
    (
        "jira keeps an issue without what it stands under",
        "trackers/jira.py",
        '    entry = {"site": cfg[0], "key": key, "above": sorted({a for a in above if a}), "at": now}\n',
        '    entry = {"site": cfg[0], "key": key, "above": [], "at": now}\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_made_a_moment_ago_holds_its_parents_close_though_no_search_finds_it",
        ],
    ),
    (
        "jira reads by key nothing it wrote of late",
        "trackers/jira.py",
        "    for k in reversed(again):\n",
        "    for k in []:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_made_a_moment_ago_holds_its_parents_close_though_no_search_finds_it",
        ],
    ),
    (
        "jira answers a root's close by a step a search has open",
        "trackers/jira.py",
        '            if k not in again and r["status"] != "closed":\n',
        '            if r["status"] != "closed":\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_closed_right_after_its_pour_leaves_the_root_open",
        ],
    ),
    (
        "jira keeps no issue it closes",
        "trackers/jira.py",
        '        wrote(checkout, key, item.get("parent"), item.get("run"), item.get("within"))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_closed_or_opened_a_moment_ago_is_read_as_it_stands",
        ],
    ),
    (
        "jira keeps no issue it opens again",
        "trackers/jira.py",
        '        wrote(request.get("root"), key, request.get("parent") or was.get("parent"), was.get("run"))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_closed_or_opened_a_moment_ago_is_read_as_it_stands",
        ],
    ),
    (
        "jira keeps an issue it moves without what it now stands under",
        "trackers/jira.py",
        '        wrote(request.get("root"), key, request.get("parent") or was.get("parent"), was.get("run"))\n',
        '        wrote(request.get("root"), key, was.get("parent"), was.get("run"))\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_moved_under_another_a_moment_ago_holds_that_ones_close",
        ],
    ),
    (
        "jira's listing lacks what it wrote a moment ago",
        "trackers/jira.py",
        "        if key in have or (under and under not in above):\n            continue\n",
        "        if True:\n            continue\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_made_a_moment_ago_is_listed_and_moved_though_no_search_finds_it",
        ],
    ),
    (
        "jira lists another project's issue it wrote",
        "trackers/jira.py",
        "        fresh = fetch_here(key, project)\n        if fresh is not None and not (under",
        "        fresh = fetch(key)\n        if fresh is not None and not (under",
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_issue_written_lately_and_moved_to_another_project_is_none_of_this_listing",
        ],
    ),
    (
        "jira forgets nothing it wrote",
        "trackers/jira.py",
        '            kept = [e for e in entries(fh) if e["at"] > now - RECENT_SECONDS]\n',
        "            kept = entries(fh)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_written_longer_ago_than_a_search_lags_is_kept_no_more",
        ],
    ),
    (
        "jira reads what it wrote longer ago than a search lags",
        "trackers/jira.py",
        '        if e.get("site") == cfg[0] and e["at"] > time.time() - RECENT_SECONDS:\n',
        '        if e.get("site") == cfg[0]:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_written_longer_ago_than_a_search_lags_is_kept_no_more",
        ],
    ),
    (
        "jira reads another site's writes as this one's",
        "trackers/jira.py",
        '        if e.get("site") == cfg[0] and e["at"] > time.time() - RECENT_SECONDS:\n',
        '        if e["at"] > time.time() - RECENT_SECONDS:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_written_longer_ago_than_a_search_lags_is_kept_no_more",
        ],
    ),
    (
        "jira reads a line that is no write",
        "trackers/jira.py",
        '        if isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)):\n',
        "        if True:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_written_longer_ago_than_a_search_lags_is_kept_no_more",
        ],
    ),
    (
        "a move asks the source of what the run says is gone from it",
        "dotdiw",
        "                if ident in source_gone:\n                    continue  # gone from the source, as the run is told, whatever it shows\n",
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_jira_shows_and_lists_no_more_is_gone_once_the_run_is_told",
        ],
    ),
    (
        "local's close closes in its wake what a move holds",
        "dotdiw",
        '            if item["id"] in keep or item["id"] in closed:\n',
        '            if item["id"] in closed:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed",
        ],
    ),
    (
        "local's close reads nothing to keep open",
        "dotdiw",
        '                list(request.get("keepOpen") or []),\n',
        "                [],\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed",
        ],
    ),
    (
        "the closes that follow close what a move holds",
        "dotdiw",
        "            if up in done or up in keep:\n",
        "            if up in done:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed",
        ],
    ),
    (
        "a close is told of nothing to keep open",
        "dotdiw",
        "                            keepOpen=holds or None,\n",
        "                            keepOpen=None,\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed",
        ],
    ),
    (
        "the guard says nothing of what a move holds",
        "dotdiw",
        "        holds.extend(sorted(stopped))\n",
        "        pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_root_stays_open_when_an_item_of_its_run_left_as_made_is_closed",
        ],
    ),
    (
        "jira's close closes in its wake what a move holds",
        "trackers/jira.py",
        '        if root["id"] in keep or root["id"] in closed or root["kind"] == "guard":\n',
        '        if root["id"] in closed or root["kind"] == "guard":\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_root_held_to_wait_on_an_issue_made_again_stays_open_in_the_wake_of_its_run",
        ],
    ),
    (
        "a root the tracker closed of its own accord, held by a move, stays closed",
        "dotdiw",
        "        if ident in kept and ident not in named and ident not in tried:\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_a_root_a_stopped_move_holds_stays_open_when_its_last_step_closes",
        ],
    ),
    (
        "the pass-through's close hands on nothing to keep open",
        "dotdiw",
        '                common, closing, every, out.get("markedIds"), out.get("exitCode", 1) != 0, holds\n',
        '                common, closing, every, out.get("markedIds"), out.get("exitCode", 1) != 0\n',
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_a_root_a_stopped_move_holds_stays_open_when_its_last_step_closes",
        ],
    ),
    (
        "the pass-through's guard says nothing of what a move holds",
        "dotdiw",
        "            common, closing_words, edges, every, writes, holds\n",
        "            common, closing_words, edges, every, writes\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_a_root_a_stopped_move_holds_stays_open_when_its_last_step_closes",
        ],
    ),
    (
        "beads' close reads nothing to keep open",
        "dotdiw",
        '        list(request.get("keepOpen") or []),\n        closes_held(pours_held(now, lambda g: beads_show',
        "        [],\n        closes_held(pours_held(now, lambda g: beads_show",
        [
            "test_tracker.py",
            "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter",
        ],
    ),
    (
        "jira holds a close to what stands under the key as it was typed",
        "trackers/jira.py",
        '        key = issue["key"]  # as Jira gives it, which reads a key in any case\n        item = record(issue)\n',
        "        item = record(issue)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_key_in_another_case_is_the_issue_it_names",
        ],
    ),
    (
        "jira links issues under the keys as they were typed",
        "trackers/jira.py",
        '            ends.append(str(issue["key"]))\n',
        "            ends.append(one)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_key_in_another_case_is_the_issue_it_names",
        ],
    ),
    (
        "jira makes an issue under its parent's key as it was typed",
        "trackers/jira.py",
        '                    request = dict(request, **{field: above["key"]})\n',
        "                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_key_in_another_case_is_the_issue_it_names",
        ],
    ),
    (
        "jira moves an issue under its parent's key as it was typed",
        "trackers/jira.py",
        '            request = dict(request, parent=above["key"])\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_key_in_another_case_is_the_issue_it_names",
        ],
    ),
    (
        "jira lists under a parent's key as it was typed",
        "trackers/jira.py",
        '            under = above["key"] if above is not None else under\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_key_in_another_case_is_the_issue_it_names",
        ],
    ),
    (
        "jira leaves a close cut short without its reason",
        "trackers/jira.py",
        '            if request.get("closeReason") and not item.get("reason"):\n',
        "            if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_cut_short_keeps_its_reason_on_the_next_run",
        ],
    ),
    (
        "jira writes a second reason on an issue closed with one",
        "trackers/jira.py",
        '            if request.get("closeReason") and not item.get("reason"):\n',
        '            if request.get("closeReason"):\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_cut_short_keeps_its_reason_on_the_next_run",
        ],
    ),
    (
        "jira puts a key into a path as it is given",
        "trackers/jira.py",
        '    parts = "".join("/" + urllib.parse.quote(part, safe="") for part in (key,) + more)\n',
        '    parts = "".join("/" + part for part in (key,) + more)\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_listing_under_a_parent_reaches_no_other_project",
        ],
    ),
    (
        "jira lists as a search has it what it wrote a moment ago",
        "trackers/jira.py",
        '        if issue["key"] in lately_written:\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_moved_under_another_a_moment_ago_is_listed_as_it_stands",
        ],
    ),
    (
        "a move asks no root of a run its listing lacks",
        "dotdiw",
        '                    | {i["run"] for i in to_write if i.get("run")}\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_the_root_of_a_run_jira_lists_late_stops_the_move_before_it_writes",
        ],
    ),
    (
        "a move says nothing of a run it leaves out",
        "dotdiw",
        '                                ("run", "is in the run of"),\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_says_what_it_leaves_out_of_another_project",
        ],
    ),
    (
        "the command a refusal gives leaves out the stores the run was told",
        "dotdiw",
        '                "--from-store": request.get("fromStore"),\n                "--to-store": request.get("toStore"),\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_each_command_given_names_the_stores_the_run_was_told",
        ],
    ),
    (
        "a move writes its status over what waited on what it makes again",
        "dotdiw",
        '                if item["id"] in relink:\n                    continue\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_closed_in_jira_stays_closed_when_its_need_is_made_again",
        ],
    ),
    (
        "a move keeps as to be linked again what it has linked again",
        "dotdiw",
        '            done = [i["id"] for i in unsettled if i.get("status") != "closed" or i["id"] in relink]\n',
        '            done = [i["id"] for i in unsettled if i.get("status") != "closed"]\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_closed_in_jira_stays_closed_when_its_need_is_made_again",
        ],
    ),
    (
        "a move takes off no need the source no longer shows",
        "dotdiw",
        '                if drop:\n                    out = written("operation.update-item", {"id": copy_id, "dropNeeds": drop})\n',
        '                if False:\n                    out = written("operation.update-item", {"id": copy_id, "dropNeeds": drop})\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_turned_round_in_jira_while_stopped_is_written_as_jira_shows_it",
        ],
    ),
    (
        "a move takes off no need written before a stop it did not record",
        "dotdiw",
        "                if fresh:\n                    linked.extend(fresh)\n                    save()\n",
        "                if False:\n                    linked.extend(fresh)\n                    save()\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_taken_off_in_jira_while_the_move_stands_stopped_is_taken_off_the_copy",
        ],
    ),
    (
        "local takes off no need it is told to",
        "dotdiw",
        '                conn.execute("DELETE FROM edges WHERE id = ? AND needs = ?", (ident, need))\n',
        "                pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_turned_round_in_jira_while_stopped_is_written_as_jira_shows_it",
        ],
    ),
    (
        "jira takes off no need it is told to",
        "trackers/jira.py",
        '                call(\n                    "DELETE",\n                    "/rest/api/3/issueLink/%s" % urllib.parse.quote(str(link["id"]), safe=""),\n                )\n',
        "                pass\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_it_is_listed_from_the_home_and_passes_the_check",
        ],
    ),
    (
        "beads takes off no need it is told to",
        "dotdiw",
        '            code, out, err = beads_batch([["dep", "remove", ident, n] for n in drop], root)\n',
        '            code, out, err = 0, "", ""\n',
        [
            "test_tracker.py",
            "EveryAdapterPresent.test_the_scenario_passes_on_every_adapter",
        ],
    ),
    (
        "a move writes no parent the source set while it stood stopped",
        "dotdiw",
        '                if above is not None and above != copy.get("parent"):\n',
        "                if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_parent_written_in_the_source_between_runs_reaches_the_copy",
        ],
    ),
    (
        "a move writes no title the source set while it stood stopped",
        "dotdiw",
        '                if item.get("title") and item["title"] != copy.get("title"):\n',
        "                if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_title_a_priority_and_values_written_between_runs_reach_the_copy",
        ],
    ),
    (
        "a move writes no priority the source set while it stood stopped",
        "dotdiw",
        '                if item.get("priority") is not None and item["priority"] != copy.get("priority"):\n',
        "                if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_title_a_priority_and_values_written_between_runs_reach_the_copy",
        ],
    ),
    (
        "a move writes no values the source recorded while it stood stopped",
        "dotdiw",
        '                for values in writes:\n                    out = written("operation.record-values"',
        '                for values in []:\n                    out = written("operation.record-values"',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_title_a_priority_and_values_written_between_runs_reach_the_copy",
        ],
    ),
    (
        "a move writes no status set back to open",
        "dotdiw",
        '                if want != "closed" and want != standing:\n',
        '                if want in ("in_progress", "blocked") and want != standing:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_status_set_back_to_open_between_runs_reaches_the_copy",
        ],
    ),
    (
        "a move's close leaves open nothing it has yet to close",
        "dotdiw",
        '                            "keepOpen": sorted(open_there - {ids[item["id"]]}),\n',
        '                            "keepOpen": [],\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_closed_run_root_keeps_its_own_close_reason_either_way",
        ],
    ),
    (
        "a stuck move names a close held by another of its own",
        "dotdiw",
        "                                back.get(b) not in held_up and not held_there(b)",
        "                                False",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_the_target_refuses_is_named_where_what_holds_it_is_not_held",
        ],
    ),
    (
        "what a run said is kept for no later run",
        "dotdiw",
        '            record["said"] = said\n',
        "            pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_left_out_is_said_by_the_run_that_finishes_after_a_stop_at_a_close",
        ],
    ),
    (
        "a move forgets nothing gone from both",
        "dotdiw",
        "                for ident in dropped:\n                    forget(ident)\n",
        "                for ident in dropped:\n                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_archived_need_whose_copy_was_deleted_is_left_out_once_both_are_said",
        ],
    ),
    (
        "a move shows no waiter its listing lacks",
        "dotdiw",
        '                    items.append(cast(TrackerItem, dict(shown["item"])))\n',
        "                    pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_archived_waiter_of_an_item_made_again_waits_on_the_new_copy",
        ],
    ),
    (
        "a create refused for a gone copy says nothing of it",
        "dotdiw",
        '                        gone_there = none_there(item.get("parent"), wholes[item["id"]].get("run"))\n',
        "                        gone_there = None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_parent_whose_copy_is_gone_from_jira_is_named_when_a_child_is_made_under_it",
        ],
    ),
    (
        "a move leaves as made a copy that is gone",
        "dotdiw",
        "                if i in missing or i in byid and (i not in settled or ids[i] in deleted)\n",
        "                if i in byid and (i not in settled or ids[i] in deleted)\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_copy_gone_from_local_of_an_issue_gone_from_jira_is_not_said_left_as_made",
        ],
    ),
    (
        "a move writes under another pair's record",
        "dotdiw",
        '        if (record.get("from"), record.get("to")) not in ((src, dst), (None, None)):\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_move_whose_record_another_move_keeps_under_its_name_writes_nothing",
        ],
    ),
    (
        "the command line runs a move on an option it does not know",
        "dotdiw",
        '                    if words[i].startswith("-") and words[i] != "-":\n',
        "                    if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_migrate_given_help_or_an_option_it_does_not_take_writes_nothing",
        ],
    ),
    (
        "bd's list --ready lists what a move holds",
        "dotdiw",
        '            or named == "list"\n',
        "            or False\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_what_a_stopped_move_holds_is_neither_listed_ready_nor_claimed",
        ],
    ),
    (
        "bd's close claims the next ready while a move stands",
        "dotdiw",
        "        if takes_the_next:\n            stopped = stopped_here(common)\n",
        "        if False:\n            stopped = stopped_here(common)\n",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_what_a_stopped_move_holds_is_neither_listed_ready_nor_claimed",
        ],
    ),
    (
        "jira reads a site spelled two ways as two",
        "trackers/jira.py",
        "    scheme, netloc = parts.scheme.lower(), parts.netloc.lower()\n",
        "    scheme, netloc = parts.scheme.lower(), parts.netloc\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_the_site_spelled_with_its_scheme_in_upper_case_holds_what_the_move_made",
        ],
    ),
    (
        "jira reads an editor's description as one run of text",
        "trackers/jira.py",
        '        said += ("" if n == 0 else "\\n" if listed_here else "\\n\\n") + text\n',
        "        said += text\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_description_written_in_jiras_editor_reads_as_it_was_written",
        ],
    ),
    (
        "jira shows the reason of an earlier close",
        "trackers/jira.py",
        "        if since is not None and made is not None and made < since:\n            continue\n",
        "",
        [
            "test_jira.py",
            "TheHostedAdapter.test_the_reason_an_issue_shows_is_that_of_its_latest_close",
        ],
    ),
    (
        "jira rewrites its journal in place",
        "trackers/jira.py",
        '                with open(temporary, "w", encoding="utf-8") as fh:\n                    fh.write("".join(json.dumps(e) + "\\n" for e in kept + [entry]))\n',
        '                with open(path, "w", encoding="utf-8") as fh:\n                    fh.write("".join(json.dumps(e) + "\\n" for e in kept + [entry]))\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_write_of_the_journal_that_fails_keeps_what_it_held",
        ],
    ),
    (
        "jira rewrites jira.json on every open",
        "trackers/jira.py",
        "    if created or project_of(root) != project:\n",
        "    if True:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_of_the_move_writes_jira_json_beside_it_and_only_where_it_changes",
        ],
    ),
    (
        "jira asks after a project key unquoted",
        "trackers/jira.py",
        '        call("GET", "/rest/api/3/project/%s" % urllib.parse.quote(project, safe=""))\n',
        '        call("GET", "/rest/api/3/project/%s" % project)\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_the_project_checked_is_the_key_kept_however_it_is_spelled",
        ],
    ),
    (
        "jira keeps every value of a make in each property",
        "trackers/jira.py",
        "                keep_values(key, values, {})",
        '                call("PUT", of(key, "properties", write_name({})), {"values": values})',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_values_too_long_for_one_property_are_kept_one_property_each",
        ],
    ),
    (
        "jira's cycle check follows needs alone",
        "trackers/jira.py",
        "        todo.extend([(n, None) for n in needs] + [(c, key) for c in sorted(children | poured)])",
        "        todo.extend([(n, None) for n in needs])",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_jira_refuses_a_need_that_would_wait_on_itself_through_a_parent_or_a_run",
        ],
    ),
    (
        "jira closes nothing in the wake of a close of a closed step",
        "trackers/jira.py",
        "            after = in_the_wake(checkout, project, item, keep, done_at)\n",
        "            after: list[str] = []\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_step_closed_again_after_a_close_cut_short_closes_its_root",
        ],
    ),
    (
        "a move given no checkout runs on none",
        "dotdiw",
        '    root = request.get("root")\n    if not root:\n        return {\n            "status": "failed",\n            "summary": "Nothing was moved: no checkout was given to move.",\n',
        '    root = request.get("root")\n    if False:\n        return {\n            "status": "failed",\n            "summary": "Nothing was moved: no checkout was given to move.",\n',
        [
            "test_jira.py",
            "TheHostedAdapterServed.test_a_move_given_no_root_is_answered_and_no_internal_error",
        ],
    ),
    (
        "the command to run once the source lists it drops what the run was told",
        "dotdiw",
        "                    summary = MOVE_UNLISTED % (src, ident, command(), command((), [ident]))\n",
        '                    summary = MOVE_UNLISTED % (src, ident, "%s tracker migrate %s %s" % (PROG, src, dst), command((), [ident]))\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_the_command_to_run_once_it_lists_it_names_what_the_run_was_told",
        ],
    ),
    (
        "a move takes away values only its copy holds",
        "dotdiw",
        '                if there_in_turn[k:] or ours_only:\n                    writes.append(\n                        [{"label": lb, "text": ""} for lb, _ in there_in_turn[k:]]\n                        + [{"label": lb, "text": ""} for lb in ours_only]',
        '                if there_in_turn[k:] or [lb for lb in values_there if lb not in values_now]:\n                    writes.append(\n                        [{"label": lb, "text": ""} for lb, _ in there_in_turn[k:]]\n                        + [{"label": lb, "text": ""} for lb in [lb for lb in values_there if lb not in values_now]]',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_values_recorded_on_a_step_the_move_holds_ask_for_no_deletion_of_it",
        ],
    ),
    (
        "a move takes values for what only a make writes",
        "dotdiw",
        'MADE_ONLY_BY_A_MAKE = ("description", "verifyUsing", "step", "claim", "run")\n',
        'MADE_ONLY_BY_A_MAKE = ("description", "verifyUsing", "step", "claim", "run", "values")\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_values_recorded_on_a_step_the_move_holds_ask_for_no_deletion_of_it",
        ],
    ),
    (
        "bd's own ready decides and runs unheld",
        "dotdiw",
        "            if etags or ready or named in TRACKER_HELD_AS_IT_IS or dropped\n",
        "            if etags or named in TRACKER_HELD_AS_IT_IS or dropped\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_bds_own_ready_and_a_move_into_beads_run_one_after_the_other",
        ],
    ),
    (
        "ready takes the lock its caller holds",
        "dotdiw",
        "        if locked\n        else held_for_writing(",
        "        if False\n        else held_for_writing(",
        [
            "test_dotdiw.py",
            "TheTrackerCommands.test_under_beads_an_issue_a_stopped_move_made_closes_once_it_is_finished",
        ],
    ),
    (
        "a move reads its source unheld",
        "dotdiw",
        "        with held_for_writing(root, src, until_logged=False) as reading:\n",
        "        with contextlib.nullcontext(True) as reading:\n",
        [
            "test_jira.py",
            "AMoveReadsNoPourHalfMade.test_a_move_while_a_pour_links_its_steps_waits",
        ],
    ),
    (
        "a move holds its source through its writes",
        "dotdiw",
        "        with held_for_writing(root, src, until_logged=False) as reading:\n",
        "        with held_for_writing(root, src) as reading:\n",
        ["test_tracker.py", "MovingBetweenAdapters.test_every_pair_and_back"],
    ),
    (
        "a served request is timed from the server's start",
        "dotdiw",
        '            scope.started = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")\n',
        "            pass\n",
        [
            "test_dotdiw.py",
            "AServedRequestStartsWhenAsked.test_each_request_is_timed_from_its_own_start",
        ],
    ),
    (
        "a server leaves gRPC's fork handlers on",
        "dotdiw",
        '    os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "false")\n',
        "    pass\n",
        [
            "test_dotdiw.py",
            "AServerForksQuietly.test_requests_that_fork_at_once_leave_stderr_quiet",
        ],
    ),
    (
        "local checks a parent as though no need were taken off",
        "dotdiw",
        "parent in local_waiting(conn, ident, drop)):",
        "parent in local_waiting(conn, ident)):",
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_a_need_taken_off_as_the_item_is_put_under_what_it_needed_is_no_cycle",
        ],
    ),
    (
        "local takes needs off an update it refuses",
        "dotdiw",
        '            drop = [str(n) for n in request.get("dropNeeds") or []]\n',
        '            drop = [str(n) for n in request.get("dropNeeds") or []]\n            for need in drop:\n                conn.execute("DELETE FROM edges WHERE id = ? AND needs = ?", (ident, need))\n',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_an_update_refused_keeps_the_needs_it_was_to_take_off",
        ],
    ),
    (
        "beads writes the parent before it takes needs off",
        "dotdiw",
        '        if drop:\n            # Each need taken off through bd\'s batch, which reads both ids\n            # whole, as add-need\'s are written -- before the parent is\n            # written, so that one that waited on the item only through\n            # such a need is no cycle.\n            code, out, err = beads_batch([["dep", "remove", ident, n] for n in drop], root)\n            if code != 0:\n                return beads_failed(UpdateItemResponse, out, err, refusals)\n        if flags:\n            code, out, err = beads_quiet(\n                ["update", ident, "--json"] + beads_typed(flags, root)[0], root\n            )\n            if code != 0:\n                if drop:\n                    # bd refused the rest: the needs taken off for it are\n                    # put back, so that a refused update writes none of it.\n                    beads_batch([["dep", "add", ident, n] for n in drop], root)\n                return beads_failed(UpdateItemResponse, out, err, refusals)\n            wrote = [str(r.get("id")) for r in beads_json(out)]\n            if wrote and ident not in wrote:\n                return failed_as(\n                    UpdateItemResponse,\n                    "item-not-found",\n                    "The tracker holds %s no more, and wrote the update to %s in its place."\n                    % (ident, wrote[0]),\n                )\n',
        '        if flags:\n            code, out, err = beads_quiet(\n                ["update", ident, "--json"] + beads_typed(flags, root)[0], root\n            )\n            if code != 0:\n                if drop:\n                    # bd refused the rest: the needs taken off for it are\n                    # put back, so that a refused update writes none of it.\n                    beads_batch([["dep", "add", ident, n] for n in drop], root)\n                return beads_failed(UpdateItemResponse, out, err, refusals)\n            wrote = [str(r.get("id")) for r in beads_json(out)]\n            if wrote and ident not in wrote:\n                return failed_as(\n                    UpdateItemResponse,\n                    "item-not-found",\n                    "The tracker holds %s no more, and wrote the update to %s in its place."\n                    % (ident, wrote[0]),\n                )\n        if drop:\n            # Each need taken off through bd\'s batch, which reads both ids\n            # whole, as add-need\'s are written -- before the parent is\n            # written, so that one that waited on the item only through\n            # such a need is no cycle.\n            code, out, err = beads_batch([["dep", "remove", ident, n] for n in drop], root)\n            if code != 0:\n                return beads_failed(UpdateItemResponse, out, err, refusals)\n',
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_need_taken_off_as_the_item_is_put_under_what_it_needed_is_no_cycle",
        ],
    ),
    (
        "beads keeps needs off an update bd refused",
        "dotdiw",
        "                if drop:\n                    # bd refused the rest",
        "                if False:\n                    # bd refused the rest",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_update_refused_keeps_the_needs_it_was_to_take_off",
        ],
    ),
    (
        "local takes no parent off",
        "dotdiw",
        '            if request.get("dropParent"):\n                sets.append("parent = NULL")',
        '            if False:\n                sets.append("parent = NULL")',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_an_item_taken_from_under_its_parent_stands_under_none",
        ],
    ),
    (
        "local writes an empty parent",
        "dotdiw",
        '    parent = request.get("parent") or None  # one given empty is none given',
        '    parent = request.get("parent")',
        [
            "test_dotdiw.py",
            "TheLocalAdapter.test_an_item_taken_from_under_its_parent_stands_under_none",
        ],
    ),
    (
        "the command line gives an empty parent as one",
        "dotdiw",
        '        if fields.get("parent") == "":\n            del fields["parent"]',
        '        if False:\n            del fields["parent"]',
        [
            "test_dotdiw.py",
            "TheLocalCommandLine.test_update_given_an_empty_parent_takes_the_item_from_under_its_parent",
        ],
    ),
    (
        "beads takes no parent off",
        "dotdiw",
        '        flags += ["--parent", ""]  # bd\'s update takes an empty parent as none',
        "        pass",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_an_item_taken_from_under_its_parent_stands_under_none",
        ],
    ),
    (
        "a move takes no parent off",
        "dotdiw",
        '                if not copy.get("parent") or (above and (above in ids or above in byid)):',
        "                if True:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_and_its_parent_that_change_places_while_stopped_change_places_in_local",
        ],
    ),
    (
        "a move takes off a need it never wrote",
        "dotdiw",
        "                drop = sorted((has & ours) - wanted)",
        "                drop = sorted((has & set(ids.values())) - wanted - {copy_id})",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_written_in_jira_between_held_copies_is_kept_and_said",
        ],
    ),
    (
        "a move says nothing of a need the target wrote",
        "dotdiw",
        '                    ["%s needs %s" % (copy_id, n) for n in sorted(has - wanted - ours)],',
        "                    [],",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_written_in_jira_between_held_copies_is_kept_and_said",
        ],
    ),
    (
        "a move writes no need the copy lost",
        "dotdiw",
        '                needs = [n for n in item.get("needs") or [] if n in ids and ids[n] not in has]',
        '                needs = [\n                    n\n                    for n in item.get("needs") or []\n                    if n in ids and [item["id"], n] not in linked and ids[n] not in has\n                ]',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_taken_off_a_held_copy_in_jira_is_written_again",
        ],
    ),
    (
        "a move says a copy keeps what it no longer does",
        "dotdiw",
        "            held[what] = list(values)\n            if not held[what]:\n                del held[what]",
        "            held[what] = sorted(set(held.get(what) or []) | set(values))\n            if not held[what]:\n                del held[what]",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_a_run_said_was_kept_as_made_is_said_no_more_once_the_copy_matches",
        ],
    ),
    (
        "a move reads an unread copy against the source now",
        "dotdiw",
        "                if isinstance(gave, dict):",
        "                if False:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_unread_copy_holding_what_it_was_given_is_finished_though_the_source_changed",
        ],
    ),
    (
        "a move writes values out of the source's order",
        "dotdiw",
        "                if there_in_turn[k:] or ours_only:",
        "                if ours_only:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_label_recorded_again_while_stopped_reaches_the_copy_in_the_sources_order",
        ],
    ),
    (
        "a move names no gone parent copy in its update",
        "dotdiw",
        '                            gone_there = none_there(item.get("parent"), ident)',
        "                            gone_there = None",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_parent_whose_copy_is_gone_from_jira_is_named_when_a_held_copy_is_put_under_it",
        ],
    ),
    (
        "a stuck move names a close held up behind one of its own",
        "dotdiw",
        "                            if at not in held_up and on & held_up:",
        "                            if False:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_stuck_close_named_is_none_whose_blocker_waits_on_one_through_its_run",
        ],
    ),
    (
        "a move takes a relink item for an unfinished one",
        "dotdiw",
        "                if i not in settled and i not in in_listing and i not in dropped and i not in relink",
        "                if i not in settled and i not in in_listing and i not in dropped",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_archived_waiter_held_to_wait_on_an_item_made_again_is_relinked_after_a_stop",
        ],
    ),
    (
        "a move shows no archived item it made when told of a deletion",
        "dotdiw",
        "                and (a in relink or (a in settled and (deleted or a in unparented)))",
        "                and (a in relink or (a in settled and a in unparented))",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_archived_child_of_an_item_made_again_stands_under_the_new_copy",
        ],
    ),
    (
        "a record naming no pair stays unpaired",
        "dotdiw",
        '        record["from"], record["to"] = src, dst',
        "        pass",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_names_no_pair_holds_what_its_stopped_run_made",
        ],
    ),
    (
        "a move keeps not where it runs",
        "dotdiw",
        '        if record.get("checkout") != root:\n            record["checkout"] = root\n            if ids:\n                save()\n',
        '        if record.get("checkout") != root:\n            record["checkout"] = root\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_from_where_the_checkout_was_moved_keeps_that_place_though_it_stops_early",
        ],
    ),
    (
        "a record that is no object is read as one",
        "dotdiw",
        '        if not isinstance(record, dict):\n            return {"status": "failed", "exitCode": 1, "summary": MOVE_NO_RECORD % path}',
        '        if not isinstance(record, (dict, list, str, int, float)):\n            return {"status": "failed", "exitCode": 1, "summary": MOVE_NO_RECORD % path}',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_that_holds_no_object_is_refused_and_left_as_it_is",
        ],
    ),
    (
        "a move takes an empty told id",
        "dotdiw",
        "        if any(\n            not str(w)",
        "        if any(\n            False",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_id_the_run_is_told_is_one_a_command_it_gives_can_take",
        ],
    ),
    (
        "a dashed told id reads as an option",
        "dotdiw",
        '                joined = "=" if value.startswith("-") else " "',
        '                joined = " "',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_id_the_run_is_told_is_one_a_command_it_gives_can_take",
        ],
    ),
    (
        "jira takes needs off before it reaches the status",
        "trackers/jira.py",
        '        status = (issue.get("fields") or {}).get("status") or {}\n        way = None\n',
        '        for link in (issue.get("fields") or {}).get("issuelinks") or []:\n            other = str((link.get("inwardIssue") or {}).get("key") or "").upper()\n            if (link.get("type") or {}).get("name") == "Blocks" and other in drop:\n                call("DELETE", "/rest/api/3/issueLink/%s" % link["id"])\n        status = (issue.get("fields") or {}).get("status") or {}\n        way = None\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_update_refused_for_its_status_keeps_the_needs_it_was_to_take_off",
        ],
    ),
    (
        "jira checks no parent for a cycle",
        "trackers/jira.py",
        '            if above["key"] == key or reaches(',
        "            if False and reaches(",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_parent_that_waits_on_the_issue_is_refused_unless_the_need_it_waits_through_comes_off",
        ],
    ),
    (
        "jira's cycle check reaches no child of another project",
        "trackers/jira.py",
        '        children = {i["key"] for i in search("parent = %s" % text(key))} | {',
        "        children = set() | {",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_jira_refuses_a_need_that_would_wait_on_itself_through_another_projects_child",
        ],
    ),
    (
        "jira keeps the default port",
        "trackers/jira.py",
        "    if default and netloc.endswith(default):",
        "    if False:",
        [
            "test_jira.py",
            "TheTable.test_a_site_spelled_with_the_port_its_scheme_takes_is_the_same_site",
        ],
    ),
    (
        "jira takes no issue from under its parent",
        "trackers/jira.py",
        '        if request.get("dropParent") and was.get("parent"):',
        "        if False:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_issue_taken_from_under_its_parent_stands_under_none",
        ],
    ),
    (
        "jira reads a link card, a mention or an emoji as nothing",
        "trackers/jira.py",
        '            elif kind in ("inlineCard", "blockCard", "embedCard"):\n                out.append(str(attrs(leaf).get("url") or ""))\n            elif kind in ("mention", "emoji", "status", "placeholder"):',
        '            elif False:\n                out.append(str(attrs(leaf).get("url") or ""))\n            elif False:',
        [
            "test_jira.py",
            "TheHostedAdapter.test_what_jiras_editor_keeps_as_a_node_of_its_own_reads_as_its_text",
        ],
    ),
    (
        "jira reads an action item as paragraphs",
        "trackers/jira.py",
        '            if entry.get("type") in ("taskItem", "decisionItem"):\n                said.append(inline(entry))  # what an action item holds is inline',
        "            if False:\n                said.append(inline(entry))",
        [
            "test_jira.py",
            "TheHostedAdapter.test_what_jiras_editor_keeps_as_a_node_of_its_own_reads_as_its_text",
        ],
    ),
    (
        "jira reads a nested list as more of the list",
        "trackers/jira.py",
        '            lines.append("  " * depth + mark + "\\n".join(said))',
        '            lines.append(mark + "\\n".join(said))',
        [
            "test_jira.py",
            "TheHostedAdapter.test_what_jiras_editor_keeps_as_a_node_of_its_own_reads_as_its_text",
        ],
    ),
    (
        "jira lists an issue with values as a search has it",
        "trackers/jira.py",
        '    if issue.get("whole") or not (own.get("step") or own.get("values")):',
        '    if issue.get("whole") or not own.get("step"):',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_an_issue_with_values_and_no_step_lists_as_it_shows",
        ],
    ),
    (
        "jira records values all in one property",
        "trackers/jira.py",
        '        if writes and len(json.dumps({"values": writes[-1] + [piece]})) <= room:',
        "        if writes:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_values_too_long_for_one_property_recorded_while_stopped_reach_the_copy",
        ],
    ),
    (
        "jira closes a root opened again in the wake of a close of a closed step",
        "trackers/jira.py",
        '        if (\n            since is not None\n            and changed is not None\n            and changed > since\n            and stood_open_since(root["id"], since) is not True\n        ):',
        "        if False:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_of_a_closed_step_leaves_a_root_opened_again_since_open",
        ],
    ),
    (
        "a move says nothing of a close reason a copy keeps",
        "dotdiw",
        '                            if (closed_as.get("reason") or None) != (item.get("reason") or None)',
        "                            if False",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_close_reason_changed_in_local_while_stopped_is_said_kept_as_the_copy_has_it",
        ],
    ),
    (
        "a move opens a copy closed with another reason",
        "dotdiw",
        '                if want != "closed":\n                    aspect(copy_id, "reason", [])  # open, as the source shows it\n',
        '                if want != "closed":\n                    aspect(copy_id, "reason", [])  # open, as the source shows it\n                elif standing == "closed" and (copies.get(item["id"]) or {}).get("reason") != item.get(\n                    "reason"\n                ):\n                    written("operation.update-item", {"id": copy_id, "status": "open"})\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_copy_closed_without_its_reason_is_finished_where_it_stands",
        ],
    ),
    (
        "a move keeps a parent the source moved to one it leaves out",
        "dotdiw",
        '                if not copy.get("parent") or (above and (above in ids or above in byid)):',
        '                if not copy.get("parent") or above:',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_held_copy_whose_parent_is_moved_to_one_left_out_stands_under_none",
        ],
    ),
    (
        "a move relinks only what it wrote",
        "dotdiw",
        '                    | {\n                        i\n                        for i in ids\n                        if i not in lost and lost & set((byid.get(i) or {}).get("needs") or [])\n                    }\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_found_written_on_a_copy_waits_on_the_new_copy_of_what_it_needs",
        ],
    ),
    (
        "a move keeps what it said of a copy made again",
        "dotdiw",
        "            of_copies.pop(ids[ident], None)\n",
        "            pass\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_was_said_of_a_copy_made_again_goes_with_it",
        ],
    ),
    (
        "a move saves what it said only while it says something",
        "dotdiw",
        '            if of_copies:\n                said["copies"] = of_copies\n            else:\n                said.pop("copies", None)\n            record["said"] = said',
        '            if of_copies:\n                said["copies"] = of_copies\n                record["said"] = said\n            else:\n                said.pop("copies", None)',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_a_run_that_stops_takes_back_is_said_no_more",
        ],
    ),
    (
        "a move reads a record of any shape",
        "dotdiw",
        "        misshapen = record_misshapen(record)\n",
        "        misshapen = None\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_whose_field_is_not_as_a_move_keeps_it_moves_nothing",
        ],
    ),
    (
        "a move keeps not where it runs before it reads the source",
        "dotdiw",
        '        if record.get("checkout") != root:\n            record["checkout"] = root\n            if ids:\n                save()\n',
        '        if record.get("checkout") != root:\n            record["checkout"] = root\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_run_from_a_moved_checkout_keeps_its_place_though_it_stops_reading_the_source",
        ],
    ),
    (
        "a move names nothing it keeps in a cycle refused",
        "dotdiw",
        "                    if kept:\n                        summary += MOVE_KEPT_IN_THE_WAY",
        "                    if False:\n                        summary += MOVE_KEPT_IN_THE_WAY",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_cycle_refused_names_what_the_move_keeps_that_closes_it",
        ],
    ),
    (
        "dotdiw takes no need off",
        "dotdiw",
        '    elif verb == "dep" and plain[:1] == ["remove"] and len(plain) == 3:',
        "    elif False:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_cycle_refused_names_what_the_move_keeps_that_closes_it",
        ],
    ),
    (
        "a move keeps a value it wrote that the source took off",
        "dotdiw",
        "                    if lb not in values_now and lb in (labels_of.get(ident) or [])",
        "                    if False",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_value_the_move_wrote_and_the_source_took_off_is_taken_off_the_copy",
        ],
    ),
    (
        "a move forgets a copy told deleted that stands",
        "dotdiw",
        '                    if there["status"] == "completed" and there.get("item"):\n                        still_there.append(ident)',
        "                    if False:\n                        still_there.append(ident)",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_copy_told_deleted_that_stands_is_left_as_made_and_kept",
        ],
    ),
    (
        "a move shows what was to stand under an item made again only when told",
        "dotdiw",
        "                and (a in relink or (a in settled and (deleted or a in unparented)))",
        "                and (a in relink or (a in settled and deleted))",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_what_stood_under_an_item_made_again_stands_under_it_after_a_stop",
        ],
    ),
    (
        "jira leaves a person written on a parent it could not take off",
        "trackers/jira.py",
        "                if refusal is not None:\n                    put_back()",
        "                if refusal is not None:\n                    pass",
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_update_refused_writes_none_of_what_it_was_given",
        ],
    ),
    (
        "jira writes the rest over a parent it kept",
        "trackers/jira.py",
        '            if kept is not None and kept.get("parent"):',
        "            if False:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_update_refused_writes_none_of_what_it_was_given",
        ],
    ),
    (
        "jira's cycle check reaches no child of another project's issue",
        "trackers/jira.py",
        '        children = {i["key"] for i in search("parent = %s" % text(key))} | {',
        "        children = set() | {",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_need_that_would_wait_on_itself_through_another_projects_subtask_is_refused",
        ],
    ),
    (
        "jira reads a write cut short between its properties",
        "trackers/jira.py",
        '        group = write.get("group")\n        if isinstance(group, str):\n            parts = write.get("of")\n            if not isinstance(parts, int) or there.get(group, 0) < parts:\n                continue  # a part is missing: none of it\n            gathered.setdefault(group, []).extend(values)\n            if write.get("part") != parts - 1:\n                continue  # read where its last part is\n            values = gathered.pop(group)\n',
        '        group = write.get("group")\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_write_of_values_more_than_one_property_holds_is_read_whole_or_not_at_all",
        ],
    ),
    (
        "jira cuts no value too long for a property",
        "trackers/jira.py",
        "        if len(json.dumps(v)) <= room:",
        "        if True:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_write_of_values_more_than_one_property_holds_is_read_whole_or_not_at_all",
        ],
    ),
    (
        "jira lists another project's issue read whole",
        "trackers/jira.py",
        '    return fetch_here(issue["key"], project)  # None where it is the project\'s no more',
        '    return fetch(issue["key"]) or issue',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_listed_issue_moved_to_another_project_is_none_of_this_checkouts",
        ],
    ),
    (
        "jira takes a root moved on while open for one opened again",
        "trackers/jira.py",
        '            and stood_open_since(root["id"], since) is not True\n',
        "",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_close_of_a_closed_step_closes_a_root_moved_on_while_it_stood_open",
        ],
    ),
    (
        "jira journals no need it writes",
        "trackers/jira.py",
        '            wrote(request.get("root"), ident, waiting.get("parent"), waiting.get("run"))\n',
        "",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_need_written_a_moment_ago_is_listed_though_no_search_has_it",
        ],
    ),
    (
        "jira reads an action item as an item of a bulleted list",
        "trackers/jira.py",
        '                mark = "[x] " if attrs(entry).get("state") == "DONE" else "[ ] "',
        '                mark = "- [x] " if attrs(entry).get("state") == "DONE" else "- [ ] "',
        [
            "test_jira.py",
            "TheHostedAdapter.test_what_jiras_editor_keeps_as_a_node_of_its_own_reads_as_its_text",
        ],
    ),
    (
        "jira reads a write in parts where each part stands",
        "trackers/jira.py",
        '            if write.get("part") != parts - 1:\n                continue  # read where its last part is\n            values = gathered.pop(group)\n',
        "            values = gathered.pop(group)\n",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_write_of_values_more_than_one_property_holds_is_read_whole_or_not_at_all",
        ],
    ),
    (
        "a move takes a need it found written for one it did not write",
        "dotdiw",
        '                fresh = [\n                    [item["id"], n]\n                    for n in item.get("needs") or []\n                    if n in ids and [item["id"], n] not in linked\n                ]',
        '                fresh = [[item["id"], n] for n in needs if [item["id"], n] not in linked]',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_found_written_on_a_copy_is_taken_off_when_the_source_takes_it_off",
        ],
    ),
    (
        "jira ready reads an issue with values as its search has it",
        "trackers/jira.py",
        '                full(i, project)\n                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search("project = %s ORDER BY created ASC" % text(project)),',
        '                i\n                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search("project = %s ORDER BY created ASC" % text(project)),',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_ready_gives_the_etag_show_and_list_give_for_an_issue_with_values",
        ],
    ),
    (
        "jira puts back nothing it wrote",
        "trackers/jira.py",
        "            for path, body in reversed(undo):",
        "            for path, body in []:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_update_whose_transition_jira_refuses_writes_none_of_the_rest",
        ],
    ),
    (
        "jira takes needs off before the transition it may be refused",
        "trackers/jira.py",
        '            if way is not None:\n                try:\n                    call("POST", of(key, "transitions"), {"transition": {"id": way}})\n                except JiraError as e:\n                    if e.status != 400:\n                        raise\n                    put_back()\n                    return {\n                        "status": "failed",\n                        "reason": "bad-status",\n                        "exitCode": 1,\n                        "summary": "Jira refused %s the way to %s: %s" % (key, wanted, e.text),\n                    }\n        except JiraError:\n            put_back()\n            raise\n        # Each need given to take off, its link deleted: the issue waits on\n        # it no more.\n        for link in now.get("issuelinks") or []:\n            other = str((link.get("inwardIssue") or {}).get("key") or "").upper()\n            if (link.get("type") or {}).get("name") == "Blocks" and other in drop:\n                call(\n                    "DELETE",\n                    "/rest/api/3/issueLink/%s" % urllib.parse.quote(str(link["id"]), safe=""),\n                )\n',
        '            for link in now.get("issuelinks") or []:\n                other = str((link.get("inwardIssue") or {}).get("key") or "").upper()\n                if (link.get("type") or {}).get("name") == "Blocks" and other in drop:\n                    call("DELETE", "/rest/api/3/issueLink/%s" % link["id"])\n            if way is not None:\n                try:\n                    call("POST", of(key, "transitions"), {"transition": {"id": way}})\n                except JiraError as e:\n                    if e.status != 400:\n                        raise\n                    put_back()\n                    return {\n                        "status": "failed",\n                        "reason": "bad-status",\n                        "exitCode": 1,\n                        "summary": "Jira refused %s the way to %s: %s" % (key, wanted, e.text),\n                    }\n        except JiraError:\n            put_back()\n            raise\n',
        [
            "test_jira.py",
            "TheHostedAdapter.test_an_update_whose_transition_jira_refuses_writes_none_of_the_rest",
        ],
    ),
    (
        "jira closes a root done when its step closed and opened since",
        "trackers/jira.py",
        '    if then and then[-1] == "done":',
        "    if False:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_root_done_when_its_step_closed_and_opened_since_is_left_as_it_stands",
        ],
    ),
    (
        "local takes any priority",
        "dotdiw",
        "    if priority is not None and not 0 <= int(priority) <= 4:",
        "    if False:",
        ["test_dotdiw.py", "TheLocalAdapter.test_a_priority_outside_0_to_4_is_refused"],
    ),
    (
        "jira takes any priority",
        "trackers/jira.py",
        '    if request.get("priority") is not None and not 0 <= int(request["priority"]) <= 4:',
        "    if False:",
        ["test_jira.py", "TheHostedAdapter.test_a_priority_outside_0_to_4_is_refused"],
    ),
    (
        "the guard holds nothing of a record naming no pair",
        "dotdiw",
        '            record.get("to") is None\n            and record.get("from") is None\n            and named.endswith("-to-" + name)',
        "            False",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_naming_no_pair_holds_what_its_stopped_run_made_before_any_run",
        ],
    ),
    (
        "the guard trusts the shape of a record's settled",
        "dotdiw",
        "        settled = {s for s in listed if isinstance(s, str)} if isinstance(listed, list) else set()",
        "        settled = set(listed or [])",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_record_with_a_field_not_as_a_move_keeps_it_is_no_traceback_on_close_or_ready",
        ],
    ),
    (
        "a stuck move reads nothing of what holds a close in the target",
        "dotdiw",
        "                                back.get(b) not in held_up and not held_there(b)",
        "                                back.get(b) not in held_up",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_stuck_close_named_is_one_whose_blocker_waits_on_no_close_the_move_holds",
        ],
    ),
    (
        "a move names nothing that closes a cycle as the target holds it",
        "dotdiw",
        "                    way = way_there(*cycle) if cycle is not None else None",
        "                    way = None",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_cycle_closed_by_a_need_a_copy_left_as_made_keeps_is_named",
        ],
    ),
    (
        "a move says what an earlier run said of a copy it does not read back",
        "dotdiw",
        "            for copy_id in [c for c in of_copies if c not in looked_at]:",
        "            for copy_id in []:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_need_taken_off_as_a_cycle_refused_asks_is_said_kept_no_more",
        ],
    ),
    (
        "jira reads the whole project for every need",
        "trackers/jira.py",
        '        if now["kind"] == "root" or own.get("runRoot"):',
        "        if True:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_need_and_a_pour_read_no_more_of_a_large_project_than_they_reach",
        ],
    ),
    (
        "jira checks a pour's own needs for a cycle",
        "trackers/jira.py",
        '            edge = linked_to({"root": root, "id": ids[s["id"]], "needs": ids[n]}, fresh=True)',
        '            edge = linked_to({"root": root, "id": ids[s["id"]], "needs": ids[n]}, fresh=False)',
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_need_and_a_pour_read_no_more_of_a_large_project_than_they_reach",
        ],
    ),
    (
        "jira reads again what was written lately in another project",
        "trackers/jira.py",
        '        if not key.upper().startswith(project.upper() + "-"):',
        "        if False:",
        [
            "test_jira.py",
            "TheHostedAdapter.test_a_listing_reads_again_none_of_what_was_written_lately_in_another_project",
        ],
    ),
    (
        "jira marks no run's root",
        "trackers/jira.py",
        '        if not own.get("runRoot"):\n            try:',
        "        if False:\n            try:",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_jira_refuses_a_need_that_would_wait_on_itself_through_a_parent_or_a_run",
        ],
    ),
    (
        "jira takes an open child no lookup reads for closed",
        "trackers/jira.py",
        '        if fresh is None and k in found and found[k]["status"] != "closed":\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_a_search_has_open_and_no_lookup_reads_holds_its_parents_close",
        ],
    ),
    (
        "jira closes a root in the wake past an open step no lookup reads",
        "trackers/jira.py",
        '        if fresh is None and k in found and found[k]["status"] != "closed":\n',
        '        if fresh is None and k in found and found[k]["status"] != "closed" and not first:\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_step_a_search_has_open_and_no_lookup_reads_keeps_its_root_open",
        ],
    ),
    (
        "jira's ready reads a search as it has what was written a moment ago",
        "trackers/jira.py",
        '                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search("project = %s ORDER BY created ASC" % text(project)),\n                )\n',
        '                for i in search("project = %s ORDER BY created ASC" % text(project))\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_ready_reads_what_was_written_a_moment_ago_as_show_does",
        ],
    ),
    (
        "jira's ready gives last what it read by key",
        "trackers/jira.py",
        '        items.sort(key=lambda i: (i["createdAt"] or "", i["id"]))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_ready_reads_what_was_written_a_moment_ago_as_show_does",
        ],
    ),
    (
        "jira's show gives the children as a search has them",
        "trackers/jira.py",
        '                for i in as_they_stand(\n                    request.get("root"),\n                    project,\n                    search(\n                        "project = %s AND parent = %s ORDER BY created ASC"\n                        % (text(project), text(key))\n                    ),\n                    key,\n                )\n',
        '                for i in search(\n                    "project = %s AND parent = %s ORDER BY created ASC"\n                    % (text(project), text(key))\n                )\n',
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_show_gives_the_children_a_listing_under_the_issue_gives_though_a_search_lags",
        ],
    ),
    (
        "jira's show gives last the children it read by key",
        "trackers/jira.py",
        '        children.sort(key=lambda c: (c["createdAt"] or "", c["id"]))\n',
        "",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_show_gives_the_children_a_listing_under_the_issue_gives_though_a_search_lags",
        ],
    ),
    (
        "jira's cycle check follows a child taken from under it a moment ago",
        "trackers/jira.py",
        '        if (\n            unsure\n            and now is not None\n            and via\n            not in (\n                now.get("parent"),\n                now.get("run"),\n                now.get("within"),\n            )\n        ):\n',
        "        if False:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_taken_from_under_an_issue_a_moment_ago_closes_no_cycle_through_it",
        ],
    ),
    (
        "jira's cycle check reaches a child written of late unread",
        "trackers/jira.py",
        "        if key == target and not unsure:\n",
        "        if key == target:\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_taken_from_under_an_issue_a_moment_ago_closes_no_cycle_through_it",
        ],
    ),
    (
        "jira's cycle check reads again a child nothing wrote of late",
        "trackers/jira.py",
        "        unsure = via is not None and key in lately",
        "        unsure = via is not None",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_a_child_taken_from_under_an_issue_a_moment_ago_closes_no_cycle_through_it",
        ],
    ),
    (
        "a calling step that declares a claim is poured",
        "dotdiw",
        '        if s.get("claim"):\n            return [], (\n                "call-with-claim",\n',
        '        if False:\n            return [], (\n                "call-with-claim",\n',
        [
            "test_dotdiw.py",
            "AStepThatCallsAFormula.test_a_calling_step_that_declares_a_claim_pours_nothing",
        ],
    ),
    (
        "a call that names no formula is poured",
        "dotdiw",
        '        if r["status"] != "completed" or not r.get("formula"):\n',
        "        if False:\n",
        ["test_dotdiw.py", "AStepThatCallsAFormula.test_a_reference_to_no_formula_pours_nothing"],
    ),
    (
        "calls that go round are poured",
        "dotdiw",
        "        if reached in seen:\n",
        "        if False:\n",
        ["test_dotdiw.py", "AStepThatCallsAFormula.test_a_formula_that_calls_itself_pours_nothing"],
    ),
    (
        "a called formula's needs are not read before the pour",
        "dotdiw",
        '            steps_in_order(list(body["steps"]))\n',
        "            pass\n",
        [
            "test_dotdiw.py",
            "AStepThatCallsAFormula.test_a_called_formula_whose_needs_name_no_step_pours_nothing",
        ],
    ),
    (
        "a pour that calls a formula is asked of a tracker that does not pour calls",
        "dotdiw",
        '        if not info.get("nests"):\n',
        "        if False:\n",
        [
            "test_dotdiw.py",
            "APourThatCallsInProcess.test_a_tracker_that_does_not_pour_calls_is_asked_nothing",
        ],
    ),
    (
        "a call's steps wait on nothing its calling step needs",
        "dotdiw",
        "            if within is not None and not needs:\n                needs = list(gate)\n",
        "            pass\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_a_calling_steps_needs_hold_back_its_call_at_any_depth",
        ],
    ),
    (
        "a call within a call waits on nothing that holds back the call it stands within",
        "dotdiw",
        "                    key,\n                    needs,\n                )\n",
        "                    key,\n                    [],\n                )\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_a_calling_steps_needs_hold_back_its_call_at_any_depth",
        ],
    ),
    (
        "a call's values fill the run's own means",
        "dotdiw",
        '            found.setdefault(within, {})[kid["step"]] = own\n',
        '            found.setdefault(None, {})[kid["step"]] = own\n            found.setdefault(within, {})[kid["step"]] = own\n',
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_two_calls_of_one_formula_keep_their_claims_and_means_apart",
        ],
    ),
    (
        "two calls of one formula fill each other's means",
        "dotdiw",
        "        by_step = found.get(within, {})\n",
        "        by_step = {k: v for f in found.values() for k, v in f.items()}\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_two_calls_of_one_formula_keep_their_claims_and_means_apart",
        ],
    ),
    (
        "a claimed step a call poured names no call",
        "dotdiw",
        '            if within is not None:\n                c["within"] = within\n',
        "            pass\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_two_calls_of_one_formula_keep_their_claims_and_means_apart",
        ],
    ),
    (
        "the local tracker keeps no calling step on a step poured within it",
        "dotdiw",
        '                            ids[str(s["within"])] if s.get("within") else None,\n',
        "                            None,\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_three_levels_are_one_run_and_close_up_to_the_root",
        ],
    ),
    (
        "under the local tracker a calling step does not need what is poured within it",
        "dotdiw",
        '                        (ids[str(s["within"])], ident),\n',
        "                        (ident, ident),\n",
        ["test_dotdiw.py", "TheTrackerCommands.test_list_use_and_check_under_local"],
    ),
    (
        "the close of a call's last item closes nothing up, under beads",
        "dotdiw",
        '        for up, must_be_root in zip(stands_under(item), (True, False, False), strict=True):\n            if up:\n                reached[str(up)] = reached.get(str(up), True) and must_be_root\n        for i, o in (standing or {}).items():\n            if o.get("calls") and ident in (o.get("needs") or []):\n                reached[i] = False\n',
        "        for up, must_be_root in zip(stands_under(item)[:2], (True, False), strict=True):\n            if up:\n                reached[str(up)] = reached.get(str(up), True) and must_be_root\n        for i, o in (standing or {}).items():\n            if False:\n                reached[i] = False\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderBeads.test_three_levels_are_one_run_and_close_up_to_the_root",
        ],
    ),
    (
        "dotdiw closes a pour's guard",
        "dotdiw",
        '            if a_guard(ident) and (\n                every[ident].get("status") == "closed" or not known_whole(ident, every)\n            ):\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "under beads a pour's guard is a need",
        "dotdiw",
        '        "needs": [n for n in needs if n and n != guard],\n',
        '        "needs": [n for n in needs if n],\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "under beads a pour's guard is given no run",
        "dotdiw",
        '            "--metadata=" + json.dumps({BEADS_KEY: {"kind": "guard", "run": root_id}}),\n',
        '            "--metadata=" + json.dumps({BEADS_KEY: {"kind": "guard"}}),\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "under beads a whole pour leaves its guard open",
        "dotdiw",
        '    code, out, err = beads_quiet(["close", guard, "--reason", "poured whole", "--json"], root)\n',
        '    code, out, err = beads_quiet(["show", guard, "--json"], root)\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "a move gives a step poured within a call the calling step's old id",
        "dotdiw",
        '                    "within": ids.get(whole["within"]) if whole.get("within") else None,\n',
        '                    "within": whole.get("within"),\n',
        ["test_jira.py", "ACallMoves.test_a_job_that_calls_a_formula_moves_whole"],
    ),
    (
        "a pour that did not finish is moved",
        "dotdiw",
        "            for g, pour in sorted(pours.items()):\n",
        "            for g, pour in []:\n",
        ["test_jira.py", "ACallMoves.test_a_pour_that_did_not_finish_moves_nothing"],
    ),
    (
        "a call moves into a tracker that does not keep calls",
        "dotdiw",
        '            ).get("nests"):\n                return {\n',
        '            ).get("nests") and False:\n                return {\n',
        ["test_jira.py", "ACallMoves.test_a_call_moves_into_no_tracker_that_does_not_keep_calls"],
    ),
    (
        "jira closes a pour's guard",
        "trackers/jira.py",
        '        if item["kind"] == "guard" and item["status"] == "closed":\n            return {\n',
        "        if False:\n            return {\n",
        ["test_jira.py", "APourUnderJiraCutShort.test_a_whole_pour_closes_its_guard"],
    ),
    (
        "jira closes a root or calling step its guard holds",
        "trackers/jira.py",
        "        if holds and g not in out:\n            out.append(g)\n",
        "        if False:\n            out.append(g)\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "under jira a calling step does not need what is poured within it",
        "trackers/jira.py",
        '            if s.get("within"):\n                edges.append((own["within"], made))\n',
        "            pass\n",
        [
            "test_jira.py",
            "NestedPoursUnderJira.test_three_levels_are_one_run_and_close_up_to_the_root",
        ],
    ),
    (
        "a calling step's need of its call is taken off under a pass-through",
        "dotdiw",
        '        if (records.get(need) or {}).get("within") == waiter:\n',
        "        if False:\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderBeads.test_a_calling_steps_need_of_its_call_is_not_taken_off",
        ],
    ),
    (
        "the local tracker takes off a calling step's need of its call",
        "dotdiw",
        '                    if held["within_item"] == ident:\n',
        "                    if False:\n",
        ["test_dotdiw.py", "TheTrackerCommands.test_list_use_and_check_under_local"],
    ),
    (
        "jira takes off a calling step's need of its call",
        "trackers/jira.py",
        '            if held_need is not None and record(held_need).get("within") == key:\n',
        "            if False:\n",
        ["test_jira.py", "TheHostedAdapter.test_it_is_listed_from_the_home_and_passes_the_check"],
    ),
    (
        "a pour's guard is written by a reopen or an update",
        "dotdiw",
        "        if ident is not None and a_guard(ident):\n",
        "        if False:\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "a calling step whose need closes last stays open under beads",
        "dotdiw",
        '            if o.get("calls") and ident in (o.get("needs") or []):\n',
        "            if False:\n",
        [
            "test_dotdiw.py",
            "NestedPoursUnderBeads.test_a_calling_step_whose_need_closes_last_closes",
        ],
    ),
    (
        "a calling step whose need closes last stays open under the local tracker",
        "dotdiw",
        '                "WHERE e.needs = ? AND i.calls IS NOT NULL ORDER BY i.created_at, i.id",\n',
        '                "WHERE e.needs = ? AND 0 ORDER BY i.created_at, i.id",\n',
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_a_calling_step_whose_need_closes_last_closes",
        ],
    ),
    (
        "a calling step whose need closes last stays open under jira",
        "trackers/jira.py",
        '            if needing is not None and record(needing).get("calls"):\n',
        "            if False:\n",
        ["test_jira.py", "NestedPoursUnderJira.test_a_calling_step_whose_need_closes_last_closes"],
    ),
    (
        "jira gives the items of a guarded pour ready",
        "trackers/jira.py",
        '    held = {k for p in pours.values() for k in p["holds"]}\n',
        "    held: set[str] = set()\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "under jira a calling step is made without its guard",
        "trackers/jira.py",
        '                own["guard"] = guard\n',
        "                pass\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_whole_pour_closes_its_guard",
        ],
    ),
    (
        "a move keeps what stands within a calling step it lost",
        "dotdiw",
        '                        or (byid.get(i) or {}).get("within") in lost\n',
        "                        or False\n",
        [
            "test_jira.py",
            "AStoppedMoveHoldsWhatItMade.test_issues_within_a_deleted_calling_step_are_made_again_with_it",
        ],
    ),
    (
        "jira's create forgets the item it made when it cannot read it back",
        "trackers/jira.py",
        "            try:\n                out = dict(out, item=record(held(key)))\n            except JiraError as e:\n",
        "            if True:\n                out = dict(out, item=record(held(key)))\n            if False:\n",
        ["test_jira.py", "ACallMoves.test_a_move_whose_read_back_fails_makes_nothing_twice"],
    ),
    (
        "a calling step whose claim cannot be read is poured",
        "dotdiw",
        '                        step["claim"] = {"statement": "", "slots": []}\n',
        "                        pass\n",
        [
            "test_dotdiw.py",
            "AStepThatCallsAFormula.test_a_calling_step_whose_claim_cannot_be_read_pours_nothing",
        ],
    ),
    (
        "beads names a guard twice in what holds a close",
        "dotdiw",
        '            and before[guard].get("kind") == "guard"\n            and guard not in poured\n',
        '            and before[guard].get("kind") == "guard"\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "a field added to a record is numbered before those a release served",
        "dotdiw",
        "    etag: str | None\n    within: str | None\n    calls: str | None\n    guard: str | None\n",
        "    within: str | None\n    calls: str | None\n    guard: str | None\n    etag: str | None\n",
        ["test_promise.py", "TheGrpcProjection.test_every_field_released_keeps_its_number"],
    ),
    (
        "jira gives ready a pour whose guard no read shows closed",
        "trackers/jira.py",
        '            if issue is not None and record(issue)["status"] == "closed":\n',
        '            if issue is None or record(issue)["status"] == "closed":\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_no_read_confirms_closed_holds_ready_and_a_move",
        ],
    ),
    (
        "a move carries a pour whose guard no read shows closed",
        "dotdiw",
        '            elif shown.get("reason") != "item-not-found":\n                unread = str(',
        '            elif shown.get("reason") == "item-not-found":\n                continue\n            else:\n                unread = str(',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_no_read_confirms_closed_holds_ready_and_a_move",
        ],
    ),
    (
        "calls that go round are told by the id each formula declares",
        "dotdiw",
        '        return "file:%s" % resolved["path"]\n',
        '        return "provider:%s" % resolved.get("formulaRef")\n',
        [
            "test_dotdiw.py",
            "AStepThatCallsAFormula.test_two_formulas_of_one_id_call_each_other_by_path",
        ],
    ),
    (
        "bd that would not start raises",
        "dotdiw",
        '    try:\n        p = subprocess.run([bd] + list(args), capture_output=True, text=True, env=env)\n    except OSError as e:\n        return 126, "", "%s: %s" % (BEADS_UNSTARTED, e.strerror or e)\n',
        "    p = subprocess.run([bd] + list(args), capture_output=True, text=True, env=env)\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_value_too_long_to_hand_bd_is_the_adapters_failure",
        ],
    ),
    (
        "bd that would not start is no adapter's failure",
        "dotdiw",
        "    if reason is None and BEADS_UNSTARTED in text:\n",
        "    if False:\n",
        [
            "test_dotdiw.py",
            "TheBeadsAdapter.test_a_value_too_long_to_hand_bd_is_the_adapters_failure",
        ],
    ),
    (
        "jira gives ready a pour whose guard no longer reads as one",
        "trackers/jira.py",
        '        if listed is not None:\n            if listed["status"] == "closed":\n                continue\n',
        '        if listed is not None:\n            if listed["status"] == "closed" or listed["kind"] != "guard":\n                continue\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_no_read_confirms_closed_holds_ready_and_a_move",
        ],
    ),
    (
        "a move carries a pour whose guard no longer reads as one",
        "dotdiw",
        '        if listed is not None:\n            if listed.get("status") == "closed":\n                continue\n',
        '        if listed is not None:\n            if listed.get("status") == "closed" or listed.get("kind") != "guard":\n                continue\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_no_read_confirms_closed_holds_ready_and_a_move",
        ],
    ),
    (
        "a provider's step's call is dropped",
        "dotdiw",
        '            step["formula"] = called.strip()\n',
        "            pass\n",
        ["test_promise.py", "AStepsCall.test_a_providers_answer_carries_a_steps_call"],
    ),
    (
        "a step's Formula: line is not read",
        "dotdiw",
        '            told["formula"] = line[len("Formula:") :].strip()\n',
        "            pass\n",
        ["test_promise.py", "AStepsCall.test_a_providers_answer_carries_a_steps_call"],
    ),
    (
        "check names no calling step that declares a claim",
        "dotdiw",
        '                elif "claim" in s:\n',
        "                elif False:\n",
        [
            "test_dotdiw.py",
            "AStepThatCallsAFormula.test_check_names_what_a_pour_would_refuse_of_a_call",
        ],
    ),
    (
        "a formula that is not text is read as one",
        "dotdiw",
        '                step["formula"] = called.strip() if isinstance(called, str) else ""\n',
        '                step["formula"] = called.strip() if isinstance(called, str) else str(called)\n',
        ["test_dotdiw.py", "AStepThatCallsAFormula.test_a_formula_that_is_not_text_pours_nothing"],
    ),
    (
        "a provider's formula is shown without its calls",
        "dotdiw",
        '                step["formula"] = s["formula"]\n',
        "                pass\n",
        [
            "test_promise.py",
            "AStepsCall.test_the_directory_provider_answers_a_steps_call_and_show_prints_it",
        ],
    ),
    (
        "a pour's JSON lists no calls",
        "dotdiw",
        '        if called:\n            answer["calls"] = [\n',
        '        if False:\n            answer["calls"] = [\n',
        [
            "test_dotdiw.py",
            "NestedPoursUnderLocal.test_three_levels_are_one_run_and_close_up_to_the_root",
        ],
    ),
    (
        "a pour does not mark its root whole",
        "dotdiw",
        '                {"metadata": {BEADS_KEY: {"guard": guard, "whole": True}}},\n',
        '                {"metadata": {BEADS_KEY: {"guard": guard}}},\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "the mark of a root whole drops its means",
        "dotdiw",
        '                {"metadata": {BEADS_KEY: {"guard": guard, "whole": True}}},\n                list(request.get("verifyUsing") or []),\n',
        '                {"metadata": {BEADS_KEY: {"guard": guard, "whole": True}}},\n                [],\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "beads reads no root whole",
        "dotdiw",
        '    if own.get("whole") is True:\n        item["whole"] = True\n',
        "",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pour_closes_its_guard_and_shows_it_nowhere",
        ],
    ),
    (
        "jira marks no root whole",
        "trackers/jira.py",
        '        call("PUT", of(root_id, "properties", PROPERTY), {"guard": guard, "whole": True})\n',
        "",
        ["test_jira.py", "APourUnderJiraCutShort.test_a_whole_pour_closes_its_guard"],
    ),
    (
        "jira reads no root whole",
        "trackers/jira.py",
        '    if own.get("whole") is True:\n        out["whole"] = True\n',
        "",
        ["test_jira.py", "APourUnderJiraCutShort.test_a_whole_pour_closes_its_guard"],
    ),
    (
        "a root that reads whole holds its pour",
        "dotdiw",
        '        live = [r for r in roots if r in every and every[r].get("whole") is not True]\n        if not live and not (standing and roots):\n            continue\n        unread: str | None = None\n',
        "        live = [r for r in roots if r in every]\n        if not live and not (standing and roots):\n            continue\n        unread: str | None = None\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_whole_pours_guard_deleted_by_housekeeping_holds_nothing",
        ],
    ),
    (
        "a root the tracker no longer lists holds its pour",
        "dotdiw",
        '        live = [r for r in roots if r in every and every[r].get("whole") is not True]\n        if not live and not (standing and roots):\n            continue\n        unread: str | None = None\n',
        '        live = [r for r in roots if r not in every or every[r].get("whole") is not True]\n        if not live and not (standing and roots):\n            continue\n        unread: str | None = None\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_step_of_a_finished_run_reopened_after_housekeeping_closes",
        ],
    ),
    (
        "jira: a root that reads whole holds its pour",
        "trackers/jira.py",
        '        live = [r for r in roots if r in every and every[r].get("whole") is not True]\n',
        "        live = [r for r in roots if r in every]\n",
        ["test_jira.py", "APourUnderJiraCutShort.test_a_whole_pours_guard_deleted_holds_nothing"],
    ),
    (
        "jira holds a root or calling step on the guard of a whole pour",
        "trackers/jira.py",
        '            run_root.get("whole") is not True\n            if run_root is not None\n',
        "            True\n            if run_root is not None\n",
        ["test_jira.py", "APourUnderJiraCutShort.test_a_whole_pours_guard_deleted_holds_nothing"],
    ),
    (
        "a root or calling step closes while its pour is not known to be whole",
        "dotdiw",
        "    by_pour = (held or {}).get(ident)\n",
        "    by_pour = None\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_deleted_outside_dotdiw_still_holds_its_pour",
        ],
    ),
    (
        "a close through dotdiw holds no pour not known to be whole after it",
        "dotdiw",
        "    held = closes_held(pours)\n    shut, notes, standing = held_to_the_run(named, shut, before, now, reopen, keep, held)\n",
        "    held: dict[str, str] = {}\n    shut, notes, standing = held_to_the_run(named, shut, before, now, reopen, keep, held)\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_root_bd_closes_once_its_guard_is_deleted_is_opened_again",
        ],
    ),
    (
        "beads' close-item holds no pour not known to be whole",
        "dotdiw",
        "        if pour and pour not in poured:\n            poured.append(pour)\n",
        "",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_deleted_outside_dotdiw_still_holds_its_pour",
        ],
    ),
    (
        "beads gives ready what a pour not known to be whole holds",
        "dotdiw",
        '    items = [i for i in items if i.get("kind") != "guard" and i["id"] not in held]\n',
        '    items = [i for i in items if i.get("kind") != "guard"]\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_edges_to_the_guard_taken_off_outside_dotdiw_give_nothing_ready",
        ],
    ),
    (
        "the tracker's own ready runs for a pour not known to be whole",
        "dotdiw",
        "                given = ready_the_tracker_may_give(common, argv)\n",
        "                given = None\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_no_ready_gives_what_a_pour_cut_short_made",
        ],
    ),
    (
        "bd's ready of one molecule runs for a pour it holds",
        "dotdiw",
        "    else:\n        texts(answer)\n    return out\n",
        "    else:\n        pass\n    return out\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_no_ready_gives_what_a_pour_cut_short_made",
        ],
    ),
    (
        "a close claims the next ready item while a pour is not known to be whole",
        "dotdiw",
        '            if pours:\n                return refusal(\n                    operation,\n                    [\n                        {\n                            "status": "failed",\n                            "reason": "unsupported-command",\n                            "exitCode": 1,\n                            "summary": CLOSE_NEXT_POUR_HELD\n',
        '            if False:\n                return refusal(\n                    operation,\n                    [\n                        {\n                            "status": "failed",\n                            "reason": "unsupported-command",\n                            "exitCode": 1,\n                            "summary": CLOSE_NEXT_POUR_HELD\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_close_takes_no_next_item_while_a_pour_is_held",
        ],
    ),
    (
        "dotdiw closes a guard while its pour is not known to be whole",
        "dotdiw",
        '                every[ident].get("status") == "closed" or not known_whole(ident, every)\n            ):\n                out.append(',
        '                every[ident].get("status") == "closed" or False\n            ):\n                out.append(',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_that_no_longer_reads_as_one_is_closed_by_no_one_but_its_pour",
        ],
    ),
    (
        "dotdiw closes no guard of a pour known to be whole",
        "dotdiw",
        '                every[ident].get("status") == "closed" or not known_whole(ident, every)\n            ):\n                out.append(',
        '                every[ident].get("status") == "closed" or True\n            ):\n                out.append(',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "a guard that no longer reads as one is written",
        "dotdiw",
        '        return (records.get(ident) or {}).get("kind") == "guard" or ident in pours\n',
        '        return (records.get(ident) or {}).get("kind") == "guard"\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_that_no_longer_reads_as_one_is_closed_by_no_one_but_its_pour",
        ],
    ),
    (
        "a need taken off is read with no listing",
        "dotdiw",
        "                refused, _ = held_at_the_command_line(\n                    common, None, [], listed_now, reopened, [], dropped\n                )\n",
        "                refused, _ = held_at_the_command_line(\n                    common, None, [], None, reopened, [], dropped\n                )\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_that_no_longer_reads_as_one_is_closed_by_no_one_but_its_pour",
        ],
    ),
    (
        "an edge is written to or from a guard",
        "dotdiw",
        "        guarded = [i for i in (waiter, item) if a_guard(i)]\n",
        "        guarded: list[str] = []\n",
        ["test_dotdiw.py", "APourUnderBeadsCutShort.test_nothing_is_put_under_or_tied_to_a_guard"],
    ),
    (
        "bd's quick create makes an item under a guard",
        "dotdiw",
        '            elif path == ["q"] and isinstance((reading.get("options") or {}).get("parent"), str):\n',
        "            elif False:\n",
        ["test_dotdiw.py", "APourUnderBeadsCutShort.test_nothing_is_put_under_or_tied_to_a_guard"],
    ),
    (
        "create makes an item under a guard",
        "dotdiw",
        '        guarded = parent_a_guard(root, request.get("tracker"), request.get("parent"))\n',
        "        guarded = None\n",
        ["test_dotdiw.py", "APourUnderBeadsCutShort.test_nothing_is_put_under_or_tied_to_a_guard"],
    ),
    (
        "jira closes a guard that no longer reads as one",
        "trackers/jira.py",
        "            else bool(namers) and guarded_still(item, namers)\n",
        "            else False\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_that_no_longer_reads_as_one_is_closed_by_no_one_but_its_pour",
        ],
    ),
    (
        "jira closes a guard while its pour is not known to be whole",
        "trackers/jira.py",
        "            not whole_by_its_run(item)\n",
        "            False\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "jira holds a calling step on no guard of its run",
        "trackers/jira.py",
        '        guards += [\n            r["key"]\n            for r in rows\n',
        '        guards += [\n            r["key"]\n            for r in []\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_calling_step_waits_on_its_runs_guard_whatever_names_it",
        ],
    ),
    (
        "a pour cut at its guard's close is not told the way out",
        "dotdiw",
        '        elif rooted["status"] == "completed" and (rooted.get("item") or {}).get("whole") is True:\n',
        "        elif False:\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "a guard made alone is said to hold",
        "dotdiw",
        "        if not root_id:\n            summary = summary.rstrip() + (\n",
        "        if False:\n            summary = summary.rstrip() + (\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "jira closes a guard given no run yet",
        "trackers/jira.py",
        "    if not isinstance(run, str) or not run:\n        return False\n    fetched = fetch(run)\n",
        "    if not isinstance(run, str) or not run:\n        return True\n    fetched = fetch(run)\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_guard_whose_root_no_search_finds_yet_is_not_closed",
        ],
    ),
    (
        "dotdiw closes a guard no root of which is known",
        "dotdiw",
        '    return bool(roots) and all((every.get(r) or {}).get("whole") is True for r in roots)\n',
        '    return all((every.get(r) or {}).get("whole") is True for r in roots)\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_stopped_after_any_write_leaves_nothing_able_to_complete",
        ],
    ),
    (
        "a parent the tracker cannot read takes an item",
        "dotdiw",
        '            if shown.get("reason") in ("item-not-found",) + TRACKER_CANNOT_ANSWER:\n                return None  # the create names it no item, and says so\n',
        "            if True:\n                return None  # the create names it no item, and says so\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_parent_that_cannot_be_read_takes_no_item",
        ],
    ),
    (
        "a guard the listing shows is read again before a create is refused",
        "dotdiw",
        "    if not (parent in every and guarded(parent, every[parent])):\n",
        "    if True:\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_parent_that_cannot_be_read_takes_no_item",
        ],
    ),
    (
        "bd's own ready is refused while bd still holds every pour",
        "dotdiw",
        "        hit = [i for i in held if i in names or _BD_WORD.sub(PROG, i) in names]\n",
        "        hit = held\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_cut_short_that_bd_still_holds_leaves_its_ready_alone",
        ],
    ),
    (
        "jira takes a root a search lists and no lookup reads for gone",
        "trackers/jira.py",
        '            else run_key in {r["key"] for r in rows}\n',
        "            else False\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_root_a_search_lists_and_no_lookup_reads_holds_its_pour",
        ],
    ),
    (
        "jira closes a guard whose root no lookup reads",
        "trackers/jira.py",
        '        if fetched is None or record(fetched).get("whole") is not True:\n            return True\n',
        '        if fetched is not None and record(fetched).get("whole") is not True:\n            return True\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_root_a_search_lists_and_no_lookup_reads_holds_its_pour",
        ],
    ),
    (
        "an open guard of a whole pour holds nothing",
        "dotdiw",
        '        live = [r for r in roots if r in every and every[r].get("whole") is not True]\n        if not live and not (standing and roots):\n            continue\n        unread: str | None = None\n',
        '        live = [r for r in roots if r in every and every[r].get("whole") is not True]\n        if not live:\n            continue\n        unread: str | None = None\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_cut_at_its_guards_close_moves_once_the_guard_closes",
        ],
    ),
    (
        "jira: an open guard of a whole pour holds nothing",
        "trackers/jira.py",
        "        if not live and not (standing and roots):\n",
        "        if not live:\n",
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_root_marked_whole_holds_its_run_while_its_guard_stands_open",
        ],
    ),
    (
        "jira holds no root or calling step on an open guard of a whole pour",
        "trackers/jira.py",
        '            holds = as_read["status"] != "closed" and (as_read["kind"] == "guard" or live)\n',
        '            holds = as_read["status"] != "closed" and live\n',
        [
            "test_jira.py",
            "APourUnderJiraCutShort.test_a_root_marked_whole_holds_its_run_while_its_guard_stands_open",
        ],
    ),
    (
        "a close a held pour refuses gives no way out",
        "dotdiw",
        '                    guard = held.get(ident) or ""\n                    if guard in standing:\n',
        '                    guard = ""\n                    if guard in standing:\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_guard_deleted_outside_dotdiw_still_holds_its_pour",
        ],
    ),
    (
        "a ready option that only narrows bd's is refused while a pour is held",
        "dotdiw",
        '        "limit",\n        "max-rows",\n        "metadata-field",\n        "mol",\n',
        '        "max-rows",\n        "metadata-field",\n        "mol",\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_cut_short_that_bd_still_holds_leaves_its_ready_alone",
        ],
    ),
    (
        "the quiet run asks bd's default ready, not the command given",
        "dotdiw",
        '    ran = quietly(argv if asked_as_json else ["--json", *argv])\n',
        '    ran = quietly(["--json", "ready"])\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_bds_ready_runs_only_where_the_very_command_gives_nothing_held",
        ],
    ),
    (
        "a ready with an option dotdiw does not know to only read is run while a pour is held",
        "dotdiw",
        "    if unknown:\n        return refused(READY_POUR_OPTION",
        "    if False:\n        return refused(READY_POUR_OPTION",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_bds_ready_runs_only_where_the_very_command_gives_nothing_held",
        ],
    ),
    (
        "a ready whose quiet answer cannot be read runs while a pour is held",
        "dotdiw",
        "    if answer is None:\n        return refused(unread)\n    given = gives(named_in(answer))\n",
        "    if answer is None:\n        return None\n    given = gives(named_in(answer))\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_bds_ready_runs_only_where_the_very_command_gives_nothing_held",
        ],
    ),
    (
        "a ready item that only mentions a held item holds bd's ready back",
        "dotdiw",
        "    if isinstance(answer, list):\n        ids(answer)\n",
        "    if False:\n        ids(answer)\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_cut_short_that_bd_still_holds_leaves_its_ready_alone",
        ],
    ),
    (
        "bd's ready asked as JSON is answered from a second run",
        "dotdiw",
        "    if given is not None or asked_as_json:\n        return given or dict(ran, printed=False)\n",
        "    if given is not None:\n        return given\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_what_bds_ready_gives_is_the_very_answer_that_was_checked",
        ],
    ),
    (
        "what bd's ready printed as text is given unread",
        "dotdiw",
        '    given = gives(words | {w.rstrip(".") for w in words})\n',
        "    given = None\n",
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_what_bds_ready_gives_is_the_very_answer_that_was_checked",
        ],
    ),
    (
        "bd's human respond and dismiss run as they are",
        "dotdiw",
        '    "human": ("", "list", "stats"),\n',
        '    "human": ("", "list", "stats", "respond", "dismiss"),\n',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_no_command_run_as_it_is_closes_what_a_close_would_not",
        ],
    ),
    (
        "a listing that is no ready is held as one while a pour is held",
        "dotdiw",
        '(named == "list" and options.get("ready") is not True)',
        '(named == "list" and "ready" not in options)',
        [
            "test_dotdiw.py",
            "APourUnderBeadsCutShort.test_a_pour_cut_short_that_bd_still_holds_leaves_its_ready_alone",
        ],
    ),
    (
        "a reopen or a need taken off that cannot be read runs",
        "dotdiw",
        '        elif named != "q" and reading.get("reason") not in TRACKER_CANNOT_ANSWER:\n',
        "        elif False:\n",
        ["test_dotdiw.py", "TheClaimCommand.test_under_beads_only_a_pour_makes_a_root"],
    ),
]


POA = os.path.expanduser(os.environ.get("DOTDIW_POA", "~/poa"))
CONTRACT = os.path.join("contracts", "named-work-found-its-procedure.cesc.yaml")


def run_check(copy, suite, test):
    """One test of a suite run on the copy; or, where the suite is poa, the
    copy's witness contract replaying one of its traces, passing where poa
    says the trace replays as the contract expects."""
    if suite == "poa":
        p = subprocess.run(
            [POA, "replay", "trace", "--contract", os.path.join(copy, CONTRACT), "--trace", test],
            capture_output=True,
            text=True,
        )
        p.returncode = 0 if p.returncode == 0 and "status: pass" in p.stdout else 1
        return p
    return subprocess.run(
        [sys.executable, "-I", suite, test], cwd=copy, capture_output=True, text=True
    )


def without_bytecode(copy):
    """The copy's cached bytecode gone. A cache holds the mtime of its source
    to the second, and its size: a mutation as long as the text it replaces,
    written in the second the run before compiled the file, would run as that
    cache has it, unbroken, and be counted a miss."""
    for here, dirs, _ in os.walk(copy):
        dirs[:] = [d for d in dirs if d != ".git"]
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(here, "__pycache__"), ignore_errors=True)
            dirs.remove("__pycache__")


def copy_of_repo():
    """The working tree as it stands -- the tracked files, and the untracked
    ones git does not ignore, such as a trace not yet committed -- in a
    temporary directory, with the release tag's history kept for the byte
    test."""
    out = tempfile.mkdtemp(prefix="dotdiw-mutate-")
    subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "-q", ROOT, out], check=True)
    files = subprocess.run(
        ["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    for rel in files:
        if not rel:
            continue
        src, dst = os.path.join(ROOT, rel), os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy(src, dst)
    return out


def the_suites():
    """suites.py, read from the tree: the RAM disk its runs keep their temp
    directories on is the one this run keeps its copy on."""
    spec = importlib.util.spec_from_file_location(
        "suites_for_breaks", os.path.join(ROOT, "suites.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv):
    # A run stopped by SIGTERM takes its RAM disk away too, as one stopped by ^C.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    with the_suites().on_a_ram_disk() as place:
        sys.stderr.write(
            "temp directories %s\n"
            % ("on a RAM disk, %s" % place.path if place.ram else "on the disk: %s" % place.why)
        )
        return run(argv)


def run(argv):
    only = argv[argv.index("-k") + 1] if "-k" in argv else ""
    copy = copy_of_repo()
    bites, misses = [], []
    unbroken = {}  # each test's exit on the copy as it stands, run once
    try:
        for name, rel, old, new, (suite, test) in MUTATIONS:
            if only and only not in name:
                continue
            # A test that fails before anything is broken catches nothing:
            # its failure is the copy's, not the mutation's.
            if (suite, test) not in unbroken:
                unbroken[(suite, test)] = run_check(copy, suite, test)
            if unbroken[(suite, test)].returncode != 0:
                misses.append(name)
                tail = (unbroken[(suite, test)].stdout + unbroken[(suite, test)].stderr)[-300:]
                print("BASE   %-58s %s %s fails unbroken: %s" % (name, suite, test, tail))
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
            without_bytecode(copy)
            started = time.perf_counter()
            p = run_check(copy, suite, test)
            took = time.perf_counter() - started
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            without_bytecode(copy)
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
