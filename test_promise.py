#!/usr/bin/env python3
"""Does dotdiw keep to its operation algebra?

operation-idl.json names the operations, what each calls, and which tracker
and git commands each crosses the product boundary with. POA checks that file
against the governed source model; nothing in POA checks it against the
program except the gRPC conformance harness, which needs Buf. These tests
hold the program to the file without any of that, from the source alone.

    python3 -I test_promise.py

The sort of every top-level definition in `dotdiw` -- infrastructure, the
door, the tracker door, an adapter, the command-line interface, one
operation's helpers, or an operation -- is written here. It is the proof that
no behaviour is shared outside the operation algebra, and the test that fails
when a function is added without saying which of the seven it is.

The door is held too: its table is a fresh generation from the IDL, a body is
reached only through it, `main()` calls only it and infrastructure, nothing
behind it writes to the terminal, and it raises naming the operation and the
key when a request or a response steps outside its type.

So is the tracker door, the sixth sort: its table is the IDL's tracker
interface regenerated, an adapter is held to that shape before it can answer,
the adapter that answers is the request's, the workspace's or the default, an
unknown one is a failed response, and a key outside either type raises -- for
a shipped adapter; a loaded one's mistake is a failed response in one line.

And the adapters, the seventh: local, one sqlite file that runs nothing, and
beads, the one sort that names the binary, runs it and rewrites its name.
The bodies reach a tracker only through the tracker door; every bd command
the beads adapter runs is declared on the operation of the interface it
answers, or on the body its extra serves; and the terminal is touched by
the pass-through's runner alone.
"""

import ast
import copy
import importlib.machinery
import importlib.util
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "dotdiw")
IDL = os.path.join(HERE, "operation-idl.json")
BINDINGS = os.path.join(HERE, "promise_bindings.py")
CONTRACT = os.path.join(HERE, "contracts", "named-work-found-its-procedure.cesc.yaml")
FINISH = os.path.join(HERE, "poa", "finish-idl.py")
WATERMARKS = os.path.join(HERE, "events", "source-watermarks.yaml")
POA = os.path.expanduser("~/poa")

# Shared by any body and deciding nothing about the product: how to run git,
# resolving the checkout's workspace under the home and the adapter it chose,
# tokenising, the FTS storage, file parsing, and the witness log's append and
# read.
INFRASTRUCTURE = {
    "verify_unread",
    "keep_verify_using",
    "read_verify_using",
    "repository_of",
    "checkout_remotes",
    "failed_as",
    "steps_in_order",
    "git",
    "repo_root",
    "workspace",
    "forget_workspace",
    "tracker_name",
    "adopted",
    "checkout_adopted",
    "toks",
    "load_formula",
    "no_fts5",
    "Index",
    "hold_index",
    "held_index",
    "held_formula",
    "witness_on",
    "witness",
    "witnessed",
}

# The door: the one way an operation is invoked, holding the request and the
# response to their types and appending the witness from the response.
DOOR = {"DoorError", "DoorSpec", "invoke", "witness_from"}

# The tracker door: the one way an operation of the tracker interface is
# invoked, and the one way an adapter's extra is. The registry holds adapters
# to the interface's shape, the loader brings one in from the home by name,
# resolve_tracker says which one answers a request, and invoke_tracker holds
# both sides to their types.
TRACKER = {
    "TrackerDoorSpec",
    "TrackerTable",
    "settle_adapter",
    "record_kinds",
    "hold_value",
    "register_tracker",
    "tracker_dirs",
    "tracker_file",
    "load_tracker",
    "tracker_with_store",
    "resolve_tracker",
    "tracker_unknown",
    "is_loaded",
    "adapter_failed",
    "invoke_tracker",
    "hold_tracker_response",
    "settle_exit_code",
    "invoke_extra",
}

# The adapters that ship inside dotdiw: name -> its definitions. The beads
# adapter is the one sort that names the binary; its runners are below. The
# local adapter runs nothing: sqlite is the standard library, not a product.
ADAPTERS = {
    "beads": {
        "beads_find",
        "beads_store",
        "beads_env",
        "beads_quiet",
        "beads_partial",
        "beads_terminal",
        "beads_run",
        "beads_json",
        "beads_record",
        "beads_failed",
        "beads_actor",
        "beads_typed",
        "beads_open",
        "beads_describe",
        "beads_create",
        "beads_need",
        "beads_pour",
        "beads_close",
        "beads_show",
        "beads_list",
        "beads_update",
        "beads_ready",
        "beads_forward",
        "beads_metrics_off",
    },
    "local": {
        "local_store",
        "local_connect",
        "local_write",
        "local_refused",
        "local_now",
        "local_new_id",
        "local_fetch",
        "local_record",
        "local_blockers",
        "local_reaches",
        "local_closing",
        "local_open",
        "local_describe",
        "local_create",
        "local_need",
        "local_pour",
        "local_close",
        "local_show",
        "local_list",
        "local_update",
        "local_ready",
    },
}

# What each adapter's extras serve: the body that reaches the extra, and so
# the operation its tracker commands are declared on.
EXTRAS = {
    "forward": "operation.forward-to-the-tracker",
    "metrics-off": "operation.turn-metrics-off",
}

# The command line: parse the affordance, build the request, call the
# operation. Infrastructure and operations, nothing else, may be called here.
INTERFACE = {
    "extract_query",
    "extract_tracker",
    "main",
    "present",
    "show_teach",
    "show_index",
    "show_list",
    "show_show",
    "show_match",
    "show_notice",
    "show_check",
    "show_nudge",
    "show_write",
    "show_metrics",
    "show_undo",
    "show_declare",
    "show_report",
    "show_actor",
    "show_adopt",
    "show_name",
    "show_pour",
    "show_forward",
    "show_trackers",
    "show_use",
    "show_check_tracker",
    "show_migrate",
    "show_new_tracker",
}

# Module-level definitions that are part of exactly one operation's body.
HELPERS = {
    "WriteFormula": {"Titles", "slug", "past_titles", "steps_from"},
    "CheckTracker": {"conformance_scenario", "candidate_registered"},
}

# What runs a tracker or git command, and the dependency it crosses into.
# The tracker's runners belong to its adapter, and nothing else calls them.
RUNNERS = {
    "git": "product.git",
    "beads_quiet": "product.beads",
    "beads_terminal": "product.beads",
    "beads_run": "product.beads",
}


def load_idl():
    with open(IDL, encoding="utf-8") as fh:
        return json.load(fh)


NAME = {o["operationId"]: o["name"] for o in load_idl()["operations"]}


def record_class(type_id):
    """The class dotdiw defines for a record type: type.tracker-item -> TrackerItem."""
    return "".join(word.capitalize() for word in type_id.split(".", 1)[1].split("-"))


def function_for(operation_id):
    """The body's name is the IDL's name for the operation."""
    return NAME[operation_id]


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


FINISHER = load_module("finish_idl_for_sorts", FINISH)


def inner_ids(idl):
    """The tracker interface's operations: an adapter answers, no body."""
    return {o["operationId"] for o in FINISHER.inner_operations(idl)}


def pending_ids(idl):
    """Operations whose binding is not-yet-implemented: no body yet."""
    return {
        b["operationId"]
        for b in idl["implementationBindings"]
        if b["implementationMode"] == "not-yet-implemented"
    }


def bodies_of(idl):
    """Body name -> operation, for every operation a body in dotdiw answers."""
    skip = inner_ids(idl) | pending_ids(idl)
    return {o["name"]: o for o in idl["operations"] if o["operationId"] not in skip}


class Source:
    """What each top-level definition in dotdiw calls, read from its AST."""

    def __init__(self, path=SCRIPT):
        with open(path, encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read(), path)
        self.defs = {
            node.name: node
            for node in self.tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }

    def names_called(self, name):
        """Top-level names called anywhere in a definition, nested defs included."""
        out = set()
        for node in ast.walk(self.defs[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.defs:
                    out.add(node.func.id)
        return out

    def operations_invoked(self, name, door="invoke"):
        """Operation ids a definition invokes through a door, by literal id:
        the door's with invoke, the tracker door's with invoke_tracker, and
        an adapter's extras by name with invoke_extra. A definition that
        hands the door a name it composes -- the conformance scenario, one
        operation of the interface at a time -- reaches every operation id
        written in it."""
        out = set()
        for node in ast.walk(self.defs[name]):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == door
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                out.add(node.args[0].value)
        return out

    def composes_a_door_call(self, name, door):
        """Whether a definition hands the door a name it builds, not a literal."""
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == door
            and node.args
            and not isinstance(node.args[0], ast.Constant)
            for node in ast.walk(self.defs[name])
        )

    def operation_ids_written(self, name):
        """Every operation id written as a string in a definition."""
        return {
            n.value
            for n in ast.walk(self.defs[name])
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and re.fullmatch(r"operation\.[a-z0-9-]+", n.value)
        }

    def commands(self, name):
        """(runner, words) for every literal git([...]) or beads_quiet([...]) call.

        The words are the leading string constants of the list; a variable
        ends them, so git(["config", "--unset", HOOKS_KEY]) is config --unset.
        """
        out = []
        # argv = ["update", request["id"], "--json"] and then argv += ...:
        # the literal is the first assignment to the name.
        assigned = {}
        for node in ast.walk(self.defs[name]):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id not in assigned
            ):
                assigned[node.targets[0].id] = node.value
        for node in ast.walk(self.defs[name]):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in RUNNERS
                and node.args
            ):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in assigned:
                arg = assigned[arg.id]
            while isinstance(arg, ast.BinOp):  # ["diff", "--name-only", "--"] + rels
                arg = arg.left
            if isinstance(arg, ast.Name):  # whatever was given: the pass-through
                out.append((node.func.id, ["*"]))
                continue
            if not isinstance(arg, ast.List):
                out.append((node.func.id, ["*"]))
                continue
            words = []
            for elt in arg.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    words.append(elt.value)
                else:
                    break
            if words:
                out.append((node.func.id, words))
        return out


def body_of(source, operation):
    """The operation's function and the helpers that belong to its body."""
    return {operation} | HELPERS.get(operation, set())


def commands_of(source, operation):
    """Every literal git or tracker command a body runs, directly or through
    the infrastructure it calls: `workspace()` runs `git config --local
    --get` on the body's behalf, and the body declares it; so does the
    tracker door, which reads the workspace's adapter the same way."""
    return commands_within(source, body_of(source, operation))


def commands_within(source, parts):
    """The literal commands run by a set of definitions and the infrastructure
    and door functions they reach; an adapter's parts reach each other too."""
    parts = set(parts)
    adapters = set().union(*ADAPTERS.values())
    for _ in range(3):
        for part in list(parts):
            reach = (INFRASTRUCTURE | TRACKER | adapters) - set(RUNNERS)
            parts |= source.names_called(part) & reach
    out = []
    for part in parts:
        out.extend(source.commands(part))
    return out


def adapter_parts(module, source, name):
    """Operation id -> the adapter functions that answer it, the function in
    the table and what it calls among the adapter's own definitions; and
    the same for each extra, keyed by the operation the extra serves."""
    table = module.TRACKERS[name]
    out = {}
    for op, fn in table["operations"].items():
        out[op] = {fn.__name__}
    for extra, fn in (table.get("extras") or {}).items():
        out[EXTRAS[extra]] = {fn.__name__}
    return out


def every_adapter_parts(module, source):
    """The same, over every shipped adapter, merged."""
    out: dict[str, Any] = {}
    for name in ADAPTERS:
        for op, fns in adapter_parts(module, source, name).items():
            out.setdefault(op, set()).update(fns)
    return out


def same_command(declared, literal):
    """Whether a declared `verb flags` names the literal command in the source.

    One may carry a flag the other does not -- `-z` is in the code and not in
    the declaration, `--force` is in the declaration and after a variable in
    the code -- so the verb must agree and one flag set must contain the other.
    """
    if declared == ["*"]:
        return True
    if declared[0] != literal[0]:
        return False
    a, b = set(declared[1:]), set(literal[1:])
    return a <= b or b <= a


class TheSort(unittest.TestCase):
    """Every definition in dotdiw is one of eight things, and says which."""

    idl: dict[str, Any]
    source: Source
    operations: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        cls.idl = load_idl()
        cls.source = Source()
        cls.operations = bodies_of(cls.idl)

    def test_every_definition_is_sorted(self):
        helpers = set().union(*HELPERS.values())
        adapters = set().union(*ADAPTERS.values())
        records = {record_class(t["typeId"]) for t in self.idl["types"] if t["kind"] == "record"}
        expected = (
            INFRASTRUCTURE
            | INTERFACE
            | DOOR
            | TRACKER
            | adapters
            | helpers
            | records
            | set(self.operations)
        )
        self.assertEqual(
            set(self.source.defs),
            expected,
            "a top-level definition is not infrastructure, interface, "
            "the door, the tracker door, an adapter, an operation, "
            "one operation's helper, or a record type of the IDL",
        )

    def test_every_operation_is_one_function_taking_one_request(self):
        module = load_module("dotdiw_under_test", SCRIPT)
        for name in self.operations:
            fn: Any = getattr(module, name, None)
            self.assertTrue(callable(fn), "%s has no function" % name)
            self.assertEqual(list(inspect.signature(fn).parameters), ["request"], name)

    def test_bindings_resolve_to_those_functions(self):
        bindings = load_module("promise_bindings_under_test", BINDINGS)
        by_op: dict[str, list[Any]] = {}
        for b in self.idl["implementationBindings"]:
            by_op.setdefault(b["operationId"], []).append(b)
        self.assertEqual(set(by_op), {o["operationId"] for o in self.idl["operations"]})
        inner = inner_ids(self.idl)
        for op in self.idl["operations"]:
            b = by_op[op["operationId"]][0]
            if b["implementationMode"] == "not-yet-implemented":
                # A name and a plan, no body: nothing in dotdiw answers it yet.
                self.assertNotIn(op["name"], self.operations)
                self.assertIn("Phase", b["notes"])
                continue
            if op["operationId"] in inner:
                # One binding per shipped adapter, each the callable in that
                # adapter's table, reached only through the tracker door.
                module = load_module("dotdiw_for_bindings", SCRIPT)
                self.assertEqual(
                    {b["bindingId"] for b in by_op[op["operationId"]]},
                    {
                        "impl.%s-%s" % (name, op["operationId"].split(".", 1)[1])
                        for name in ADAPTERS
                    },
                )
                for b in by_op[op["operationId"]]:
                    unit_module, attr = b["implementationUnit"].split("::")
                    self.assertEqual(unit_module, "promise_bindings")
                    adapter = b["bindingId"].split(".", 1)[1].split("-", 1)[0]
                    self.assertEqual(attr, adapter.capitalize() + op["name"])
                    fn: Any = getattr(bindings, attr, None)
                    self.assertTrue(callable(fn), b["implementationUnit"])
                    self.assertEqual(list(inspect.signature(fn).parameters), ["request"])
                    self.assertEqual(fn.adapter, adapter)
                    answers = module.TRACKERS[adapter]["operations"][op["operationId"]]
                    self.assertIn(answers.__name__, ADAPTERS[adapter])
                    self.assertIn(
                        answers.__name__,
                        b["notes"].replace(
                            "dotdiw::TRACKERS[%s][operations][%s]" % (adapter, op["operationId"]),
                            answers.__name__,
                        ),
                    )
                    self.assertEqual(
                        b["implementationMode"],
                        "external-product-call-only" if adapter == "beads" else "inline-body",
                    )
                # And the interface's own name goes through the tracker door.
                fn = getattr(bindings, op["name"])
                self.assertEqual(list(inspect.signature(fn).parameters), ["request"])
                self.assertIsNone(fn.body)
                continue
            module, attr = b["implementationUnit"].split("::")
            self.assertEqual(module, "promise_bindings")
            self.assertEqual(b["implementationMode"], "inline-body")
            self.assertIs(b["privateHelpersUsed"], False)
            fn = getattr(bindings, attr, None)
            self.assertTrue(callable(fn), b["implementationUnit"])
            self.assertEqual(list(inspect.signature(fn).parameters), ["request"])
            self.assertEqual(
                fn.body,
                function_for(op["operationId"]),
                "%s is bound to the wrong body" % op["operationId"],
            )
            self.assertEqual(
                b["calledOperationIds"], [c["operationId"] for c in op.get("calls") or []]
            )
        self.assertEqual(set(bindings.BINDINGS), {o["name"] for o in self.idl["operations"]})
        # The table is not a copy of the bodies: calling through it runs them.
        out = bindings.CommitFormula({"root": HERE, "path": "x.formula.toml"})
        self.assertEqual(out["status"], "blocked")

    def test_infrastructure_calls_no_operation(self):
        """Nor does the door, which reaches a body only through its table; nor
        does an adapter, which reaches nothing above the tracker door."""
        adapters = set().union(*ADAPTERS.values())
        for name in INFRASTRUCTURE | DOOR | TRACKER | adapters:
            called = self.source.names_called(name)
            self.assertFalse(called & set(self.operations), "%s calls %s" % (name, called))
            self.assertFalse(called & set().union(*HELPERS.values()), name)
            self.assertFalse(called & INTERFACE, name)
        for name in adapters:
            called = self.source.names_called(name)
            self.assertFalse(called & (DOOR | TRACKER), "%s calls %s" % (name, called))

    def test_only_the_adapter_names_the_binary(self):
        """The plumbing of the tracker underneath -- finding it, running it,
        handing it its directory -- is referenced inside the beads adapter
        and nowhere else; the bodies reach a tracker only through the
        tracker door."""
        plumbing = {
            "beads_find",
            "beads_quiet",
            "beads_terminal",
            "beads_run",
            "beads_env",
            "beads_store",
            "BD_CONFIG",
            "INIT_FLAGS",
            "REINIT_FLAGS",
            "BEADS_STORE",
        }
        outside = set(self.source.defs) - ADAPTERS["beads"]
        for name in sorted(outside):
            used = {
                n.id
                for n in ast.walk(self.source.defs[name])
                if isinstance(n, ast.Name) and n.id in plumbing
            }
            self.assertEqual(used, set(), "%s reaches the tracker's plumbing: %s" % (name, used))
            literal = [
                n.value
                for n in ast.walk(self.source.defs[name])
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and n.value in ("BEADS_DIR", "bd")
            ]
            self.assertEqual(literal, [], "%s names the binary: %s" % (name, literal))
        doors = {"invoke_tracker", "invoke_extra"}
        for name in self.operations:
            reached = set()
            for part in body_of(self.source, name):
                reached |= self.source.names_called(part)
            self.assertFalse(
                reached & ADAPTERS["beads"], "%s reaches the adapter around the door" % name
            )
        for name in INTERFACE | INFRASTRUCTURE | DOOR:
            self.assertFalse(self.source.names_called(name) & ADAPTERS["beads"], name)
        # And both adapters are in the registry at import, named, shipped,
        # each saying where its store is; the beads adapter with its two
        # extras, the local one with none and no runner at all.
        module = load_module("dotdiw_adapter_registry", SCRIPT)
        self.assertEqual(set(module.TRACKERS), set(ADAPTERS))
        for name in ADAPTERS:
            info = module.TRACKERS[name]["info"]
            self.assertEqual((info["name"], info["origin"]), (name, "shipped"))
            self.assertTrue(callable(module.TRACKERS[name]["store"]))
        self.assertEqual(sorted(module.TRACKERS["beads"]["extras"]), sorted(EXTRAS))
        self.assertEqual(module.TRACKERS["local"]["extras"], {})
        self.assertEqual(module.DEFAULT_TRACKER, "local")
        for name in ADAPTERS["local"]:
            self.assertFalse(self.source.names_called(name) & set(RUNNERS), name)
            self.assertFalse(self.source.names_called(name) & ADAPTERS["beads"], name)
        self.assertEqual(set(doors) <= TRACKER, True)

    def test_each_helper_belongs_to_one_body(self):
        for owner, helpers in HELPERS.items():
            for helper in helpers:
                users = {
                    name
                    for name in self.source.defs
                    if helper in self.source.names_called(name) and name != helper
                }
                users -= helpers  # a body's parts may call each other
                self.assertEqual(users, {owner}, "%s is used by %s" % (helper, users))

    def test_the_interface_decides_nothing(self):
        """The command line calls infrastructure, itself, and the doors."""
        for name in INTERFACE:
            called = self.source.names_called(name)
            allowed = INFRASTRUCTURE | INTERFACE | {"invoke", "invoke_tracker"}
            self.assertTrue(called <= allowed, "%s calls %s" % (name, called - allowed))


class TheCalls(unittest.TestCase):
    """What each body calls is what the IDL says it calls, both ways."""

    idl: dict[str, Any]
    source: Source
    operations: dict[str, Any]
    dependencies: Any

    @classmethod
    def setUpClass(cls):
        cls.idl = load_idl()
        cls.source = Source()
        cls.operations = bodies_of(cls.idl)
        cls.dependencies = {d["dependencyId"]: d for d in cls.idl["externalProductDependencies"]}

    def body_calls(self, name):
        """What a body reaches: names it calls, and operations it invokes."""
        called = set()
        for part in body_of(self.source, name):
            called |= self.source.names_called(part)
            called |= {NAME[op] for op in self.source.operations_invoked(part)}
        return called

    def tracker_calls(self, name):
        """The operations of the tracker interface a body invokes through the
        tracker door, by literal id, and the extras it reaches by name."""
        ops, extras, composed = set(), set(), False
        parts = body_of(self.source, name)
        for part in parts:
            ops |= self.source.operations_invoked(part, "invoke_tracker")
            extras |= self.source.operations_invoked(part, "invoke_extra")
            composed = composed or self.source.composes_a_door_call(part, "invoke_tracker")
        if composed:
            # The conformance scenario names each operation it runs as a
            # string and hands the door the name: those are what it reaches.
            for part in parts:
                ops |= self.source.operation_ids_written(part)
        return ops, extras

    def test_declared_calls_match_the_body(self):
        for name, op in self.operations.items():
            in_body = self.body_calls(name) & set(self.operations)
            declared = {function_for(c["operationId"]) for c in op.get("calls") or []}
            declared &= set(self.operations)
            self.assertEqual(
                in_body,
                declared,
                "%s: body calls %s, IDL declares %s" % (name, sorted(in_body), sorted(declared)),
            )

    def test_the_tracker_is_reached_through_its_door_as_declared(self):
        """A body that declares an operation of the tracker interface invokes
        exactly that, through the tracker door by literal id, and nothing
        else of the interface; an extra is reached by the one body it
        serves. The orchestration of the inner journey declares them all and
        reaches them by the id its request carries."""
        inner = inner_ids(self.idl)
        extras_seen: dict[str, Any] = {}
        for name, op in self.operations.items():
            ops, extras = self.tracker_calls(name)
            declared = {c["operationId"] for c in op.get("calls") or []} & inner
            if name == "AnswerThroughTheTracker":
                self.assertEqual(declared, inner)
                self.assertIn("invoke_tracker", self.source.names_called(name))
                continue
            self.assertEqual(
                ops,
                declared,
                "%s: body reaches %s through the tracker door, "
                "IDL declares %s" % (name, sorted(ops), sorted(declared)),
            )
            for extra in extras:
                extras_seen.setdefault(extra, set()).add(op["operationId"])
        self.assertEqual(extras_seen, {extra: {op} for extra, op in EXTRAS.items()})

    def test_nothing_is_shared_outside_the_algebra(self):
        """A non-infrastructure name reached from two bodies is an operation."""
        users: dict[str, Any] = {}
        for name in self.operations:
            for called in self.body_calls(name) - INFRASTRUCTURE - DOOR - TRACKER:
                users.setdefault(called, set()).add(name)
        for called, bodies in users.items():
            if len(bodies) > 1:
                self.assertIn(
                    called,
                    self.operations,
                    "%s is shared by %s and is not an operation" % (called, sorted(bodies)),
                )

    def declared_words(self, name, op):
        """product id -> the declared commands, as word lists, checked against
        the dependencies the IDL names."""
        declared = [(c["dependencyId"], c["operationRef"]) for c in op.get("externalCalls") or []]
        words: dict[str, Any] = {}
        for dep, ref in declared:
            self.assertIn(dep, self.dependencies, "%s: unknown %s" % (name, dep))
            product, command = ref.split("::")
            self.assertEqual(product, self.dependencies[dep]["productId"], ref)
            words.setdefault(product, []).append(command.split())
        return words

    def crossings(self):
        """(name, operation, the literal commands run on its behalf): every
        body with what it and the infrastructure run, and every operation of
        the tracker interface with what the beads adapter runs to answer it,
        the extras counted on the body each serves."""
        module = load_module("dotdiw_for_crossings", SCRIPT)
        by_id = {o["operationId"]: o for o in self.idl["operations"]}
        parts = every_adapter_parts(module, self.source)
        for name, op in self.operations.items():
            literals = commands_of(self.source, name)
            literals += commands_within(self.source, parts.get(op["operationId"], set()))
            yield name, op, literals
        for op_id, fns in parts.items():
            if op_id in self.operations_by_id:
                continue
            yield "the adapters for %s" % op_id, by_id[op_id], commands_within(self.source, fns)

    @property
    def operations_by_id(self):
        return {o["operationId"]: o for o in self.operations.values()}

    def test_external_calls_are_declared_where_they_happen(self):
        """Every literal git or tracker command is declared on the operation it
        runs for: a body's own and its infrastructure's on the body, the
        beads adapter's on the operation of the interface it answers, and an
        extra's on the body it serves."""
        for name, op, literals in self.crossings():
            words = self.declared_words(name, op)
            for runner, literal in literals:
                product = RUNNERS[runner]
                self.assertTrue(
                    any(same_command(d, literal) for d in words.get(product, [])),
                    "%s runs %s %s and does not declare it" % (name, product, " ".join(literal)),
                )
        # No body runs the tracker itself: its crossings are git's, and the
        # tracker's are the adapter's, declared on the interface's operations.
        for name in self.operations:
            products = {RUNNERS[r] for r, _ in commands_of(self.source, name)}
            self.assertNotIn("product.beads", products, "%s runs the tracker itself" % name)

    def test_every_declared_external_call_has_evidence_in_the_body(self):
        for name, op, literals in self.crossings():
            for c in op.get("externalCalls") or []:
                product, command = c["operationRef"].split("::")
                declared = command.split()
                evidenced = any(
                    RUNNERS[r] == product and same_command(declared, lit) for r, lit in literals
                )
                self.assertTrue(
                    evidenced,
                    "%s declares %s and nothing runs it on its behalf" % (name, c["operationRef"]),
                )

    def test_only_the_adapter_runs_the_tracker_with_the_terminal(self):
        """The name-hiding happens inside the beads adapter, and the pass-
        through's runner is called from the adapter alone."""
        for name in self.source.defs:
            called = self.source.names_called(name)
            if called & {"beads_terminal", "beads_run", "beads_quiet", "beads_find"}:
                self.assertIn(name, ADAPTERS["beads"], "%s runs the tracker" % name)

    def test_the_commit_is_refused(self):
        module = load_module("dotdiw_under_test_2", SCRIPT)
        out = module.CommitFormula({"root": HERE, "path": "x.formula.toml"})
        self.assertEqual(out["status"], "blocked")
        self.assertIn("git add x.formula.toml", out["command"])
        spaced = module.CommitFormula({"root": HERE, "path": "a b/x.formula.toml"})
        self.assertEqual(shlex.split(spaced["command"])[:3], ["git", "add", "a b/x.formula.toml"])
        unnamed = module.CommitFormula({"root": HERE})
        self.assertIn("git add <the formula file> &&", unnamed["command"])
        self.assertEqual(self.source.commands("CommitFormula"), [])


class TheDoor(unittest.TestCase):
    """The one way in: generated from the IDL, the only route to a body, the
    only thing main() reaches an operation through; it raises naming the
    operation and the key, and nothing behind it writes to the terminal."""

    idl: dict[str, Any]
    source: Source
    operations: dict[str, Any]

    @classmethod
    def setUpClass(cls):
        cls.idl = load_idl()
        cls.source = Source()
        cls.operations = bodies_of(cls.idl)

    def test_the_interface_number_moves_by_decision(self):
        """A change to what a module has to answer stops the finisher until
        someone has decided whether to raise the number. A change to the words
        does not, and neither does a change outside the interface."""
        finish = load_module("finish_idl_under_test", FINISH)
        patches = finish.load(finish.PATCHES)
        self.assertEqual(
            finish.interface_digest(self.idl),
            patches["trackerInterface"]["digest"],
            "the interface's types changed; run python3 -I poa/finish-idl.py and decide",
        )
        self.assertIsNone(finish.interface_changed(self.idl, patches))

        def changed(type_id, change):
            idl = copy.deepcopy(self.idl)
            change(next(t for t in idl["types"] if t["typeId"] == type_id))
            return idl

        words = changed(
            "type.create-item-request", lambda t: t["fields"][0].update(summary="Other words.")
        )
        self.assertIsNone(finish.interface_changed(words, patches))
        elsewhere = changed(
            "type.write-formula-request",
            lambda t: t["fields"].append(
                {
                    "name": "more",
                    "valueType": {"kind": "scalar", "scalar": "string"},
                    "required": False,
                }
            ),
        )
        self.assertIsNone(finish.interface_changed(elsewhere, patches))
        for type_id in ("type.create-item-request", "type.tracker-item"):
            with self.subTest(type=type_id):
                added = changed(
                    type_id,
                    lambda t: t["fields"].append(
                        {
                            "name": "more",
                            "valueType": {"kind": "scalar", "scalar": "string"},
                            "required": False,
                        }
                    ),
                )
                said = finish.interface_changed(added, patches)
                self.assertIn(finish.interface_digest(added), said)
                self.assertIn("interface %d" % patches["trackerInterface"]["number"], said)

    def test_the_table_is_a_fresh_generation_from_the_idl(self):
        """The region between the markers is what finish-idl writes today."""
        finish = load_module("finish_idl_under_test", FINISH)
        with open(SCRIPT, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text.count(finish.DOOR_OPEN), 1)
        self.assertEqual(text.count(finish.DOOR_CLOSE), 1)
        start = text.index(finish.DOOR_OPEN)
        end = text.index(finish.DOOR_CLOSE) + len(finish.DOOR_CLOSE)
        self.assertEqual(
            text[start:end],
            finish.door_source(self.idl),
            "the door's table is not what operation-idl.json generates; "
            "run python3 -I poa/finish-idl.py",
        )
        self.assertEqual(text.count(finish.SKELETON_OPEN), 1)
        self.assertEqual(text.count(finish.SKELETON_CLOSE), 1)
        start = text.index(finish.SKELETON_OPEN)
        end = text.index(finish.SKELETON_CLOSE) + len(finish.SKELETON_CLOSE)
        self.assertEqual(
            text[start:end],
            finish.skeleton_source(self.idl),
            "the file a tracker starts from is not what operation-idl.json generates; "
            "run python3 -I poa/finish-idl.py",
        )
        self.assertEqual(text.count(finish.TRACKER_OPEN), 1)
        self.assertEqual(text.count(finish.TRACKER_CLOSE), 1)
        start = text.index(finish.TRACKER_OPEN)
        end = text.index(finish.TRACKER_CLOSE) + len(finish.TRACKER_CLOSE)
        self.assertEqual(
            text[start:end],
            finish.tracker_door_source(self.idl),
            "the tracker door's table is not what operation-idl.json generates; "
            "run python3 -I poa/finish-idl.py",
        )
        self.assertEqual(text.count(finish.TYPES_OPEN), 1)
        self.assertEqual(text.count(finish.TYPES_CLOSE), 1)
        start = text.index(finish.TYPES_OPEN)
        end = text.index(finish.TYPES_CLOSE) + len(finish.TYPES_CLOSE)
        self.assertEqual(
            text[start:end],
            finish.types_source(self.idl),
            "the types are not what operation-idl.json generates; run python3 -I poa/finish-idl.py",
        )
        # And the tables the program runs are the ones in the file.
        module = load_module("dotdiw_door_table", SCRIPT)
        self.assertEqual({spec["body"] for spec in module.DOOR.values()}, set(self.operations))
        self.assertEqual(set(module.TRACKER_DOOR), inner_ids(self.idl))
        # And every record type of the IDL is a class the program defines, with
        # the IDL's fields and no other.
        for t in self.idl["types"]:
            if t["kind"] != "record":
                continue
            cls = getattr(module, record_class(t["typeId"]))
            self.assertEqual(set(cls.__annotations__), {f["name"] for f in t["fields"]})
            self.assertEqual(
                cls.__required_keys__, {f["name"] for f in t["fields"] if f["required"]}
            )

    def test_a_body_is_reached_only_through_the_door(self):
        """No definition names a body. The door reaches one by the name in its
        table, a string; promise_bindings.py by the same name, from the IDL."""
        bodies = set(self.operations)
        named = [
            (node.lineno, node.id)
            for node in ast.walk(self.source.tree)
            if isinstance(node, ast.Name) and node.id in bodies
        ]
        self.assertEqual(named, [], "a body is named outside the door's table: %s" % named)
        table = [
            node
            for node in self.source.tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DOOR"
        ]
        self.assertEqual(len(table), 1, "one table")
        in_table = sorted(
            str(n.value)
            for n in ast.walk(table[0])
            if isinstance(n, ast.Constant) and n.value in bodies
        )
        self.assertEqual(in_table, sorted(bodies), "each body once, in the table")
        elsewhere = [
            (n.lineno, n.value)
            for node in self.source.tree.body
            if node is not table[0]
            for n in ast.walk(node)
            if isinstance(n, ast.Constant) and n.value in bodies
        ]
        self.assertEqual(elsewhere, [], "a body's name is written outside the table")

    def test_main_calls_only_infrastructure_and_the_door(self):
        """Routing is hand-written, reaches an operation only by its id through
        a door, and every id it reaches is one the IDL binds to the command
        line -- the tracker's description under --version included. Its own
        argument parsing is the one interface call it makes."""
        called = self.source.names_called("main")
        self.assertIn("invoke", called)
        beyond = (
            called
            - INFRASTRUCTURE
            - {"invoke", "invoke_tracker", "extract_query", "extract_tracker"}
        )
        self.assertEqual(beyond, set(), "main() calls %s" % sorted(beyond))
        doors = [
            node
            for node in ast.walk(self.source.defs["main"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("invoke", "invoke_tracker")
        ]
        self.assertTrue(doors, "main() invokes nothing")
        for node in doors:
            self.assertTrue(
                node.args and isinstance(node.args[0], ast.Constant),
                "line %d: main() invokes an operation it does not name" % node.lineno,
            )
        cli = {
            b["operationId"] for b in self.idl["interfaceBindings"] if b["interfaceKind"] == "cli"
        }
        reached = self.source.operations_invoked("main") | self.source.operations_invoked(
            "main", "invoke_tracker"
        )
        unbound = reached - cli
        self.assertEqual(unbound, set(), "main() invokes %s, bound to no command" % sorted(unbound))
        self.assertIn("operation.describe-tracker", reached)
        # What the interface shows is keyed by operation id, and each is one.
        module = load_module("dotdiw_interface", SCRIPT)
        self.assertEqual(set(module.SHOW) - set(NAME), set())

    def test_no_body_writes_to_the_terminal(self):
        """A body returns; what is shown is the presenter's. The one stream no
        response carries, the tracker's own, is the beads adapter's terminal
        runner's, and nothing else in the adapter touches the terminal
        either; nor does the door, which shows a response only through the
        presenter."""
        helpers = set().union(*HELPERS.values())
        adapters = set().union(*ADAPTERS.values()) - {"beads_terminal"}
        streams = {("sys", "stdout"), ("sys", "stderr"), ("sys", "stdin"), ("os", "write")}
        found = []
        for name in sorted(set(self.operations) | helpers | DOOR | TRACKER | adapters):
            for node in ast.walk(self.source.defs[name]):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("print", "input")
                ):
                    found.append("%s line %d: %s" % (name, node.lineno, node.func.id))
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr) in streams
                ):
                    found.append(
                        "%s line %d: %s.%s" % (name, node.lineno, node.value.id, node.attr)
                    )
        self.assertEqual(found, [], "\n".join(["a body writes to the terminal:"] + found))

    def test_the_door_raises_naming_the_operation_and_the_key(self):
        """A key outside either type is the project's mistake, not a worker's
        situation, so it raises rather than becoming a summary."""
        module = load_module("dotdiw_door", SCRIPT)
        self.assertTrue(issubclass(module.DoorError, TypeError))
        with self.assertRaises(module.DoorError) as held:
            module.invoke("operation.not-one", {})
        self.assertIn("operation.not-one", str(held.exception))
        op = "operation.name-the-work"
        with self.assertRaises(module.DoorError) as held:
            module.invoke(op, {"title": "x", "bogus": 1})
        self.assertIn(op, str(held.exception))
        self.assertIn('"bogus"', str(held.exception))
        with self.assertRaises(module.DoorError) as held:
            module.invoke(op, {"root": HERE})
        self.assertIn(op, str(held.exception))
        self.assertIn('"title"', str(held.exception))
        # The response is held the same way on the way out: a body that steps
        # outside its type is caught before anything is shown or logged.
        op = "operation.teach-the-conventions"
        original = module.TeachTheConventions
        self.addCleanup(setattr, module, "TeachTheConventions", original)
        for response, key in (
            ({"status": "completed", "summary": "s", "text": "t", "extra": 1}, '"extra"'),
            ({"status": "completed"}, '"summary"'),
            ({"status": "done", "summary": "s"}, '"done"'),
        ):
            module.TeachTheConventions = lambda request, out=response: out
            with self.assertRaises(module.DoorError) as held:
                module.invoke(op, {})
            self.assertIn(op, str(held.exception))
            self.assertIn(key, str(held.exception))
        # And a response inside its type comes back as it was.
        module.TeachTheConventions = original
        self.assertEqual(module.invoke(op, {})["status"], "completed")


def fake_adapter(module, name="fake", answers=None):
    """An adapter in the registry's shape whose every operation completes."""

    item = {"id": "x", "title": "X", "status": "open"}
    records: dict[str, dict[str, Any]] = {
        "operation.describe-tracker": {"info": {"name": name, "version": "0", "origin": "shipped"}},
        "operation.create-item": {"item": item},
        "operation.add-need": {"edge": {"id": "x", "needs": "y"}},
        "operation.pour-steps": {"rootId": "x", "stepIds": []},
        "operation.show-item": {"item": item},
        "operation.list-items": {"items": []},
        "operation.update-item": {"item": item},
        "operation.ready-items": {"items": []},
    }

    def callable_for(operation):
        def operation_(request):
            out = {"status": "completed", "summary": operation, "exitCode": 0}
            out.update(records.get(operation, {}))
            out.update((answers or {}).get(operation, {}))
            return out

        return operation_

    return {
        "info": {"name": name, "version": "0", "interface": 2, "origin": "shipped"},
        "operations": {op: callable_for(op) for op in module.TRACKER_DOOR},
    }


class TheTrackerDoor(unittest.TestCase):
    """The one way into the tracker interface: an adapter is held to the
    shape before it answers, the request names it or the workspace or the
    default does, an unknown one is a failed response, and a key outside
    either type raises naming the operation and the key."""

    def setUp(self):
        self.module = load_module("dotdiw_tracker_door", SCRIPT)
        self.root = tempfile.mkdtemp()  # no git here: no workspace choice
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(self.module.TRACKERS.clear)
        # The shipped adapter is in the registry at import; these tests are
        # about the door, so they start from an empty one.
        self.assertEqual(set(self.module.TRACKERS), set(ADAPTERS))
        self.module.TRACKERS.clear()

    def test_the_registry_holds_an_adapter_to_the_shape(self):
        m = self.module
        whole = fake_adapter(m)
        short = {"info": whole["info"], "operations": dict(whole["operations"])}
        gone = sorted(short["operations"])[0]
        del short["operations"][gone]
        with self.assertRaises(m.DoorError) as held:
            m.register_tracker("short", short)
        self.assertIn(gone, str(held.exception))
        extra = {"info": whole["info"], "operations": dict(whole["operations"])}
        extra["operations"]["operation.not-one"] = whole["operations"][gone]
        with self.assertRaises(m.DoorError) as held:
            m.register_tracker("extra", extra)
        self.assertIn("operation.not-one", str(held.exception))
        wrong = {"info": whole["info"], "operations": dict(whole["operations"])}
        wrong["operations"][gone] = lambda request, more: None
        with self.assertRaises(m.DoorError) as held:
            m.register_tracker("wrong", wrong)
        self.assertIn(gone, str(held.exception))
        nameless = {
            "info": {"version": "0", "interface": 2, "origin": "shipped"},
            "operations": whole["operations"],
        }
        with self.assertRaises(m.DoorError) as held:
            m.register_tracker("nameless", nameless)
        self.assertIn('"name"', str(held.exception))
        bad_extra = {
            "info": whole["info"],
            "operations": whole["operations"],
            "extras": {"forward": lambda: None},
        }
        with self.assertRaises(m.DoorError) as held:
            m.register_tracker("bad-extra", bad_extra)
        self.assertIn("forward", str(held.exception))
        self.assertEqual(set(m.TRACKERS), set())
        m.register_tracker("fake", whole)
        self.assertEqual(set(m.TRACKERS), {"fake"})

    def test_an_extra_is_reached_like_an_operation(self):
        """The chosen adapter answers its extras by name through the same
        resolution; one without the extra answers unsupported, an unknown
        adapter the same failed response as the door's."""
        m = self.module
        out = m.invoke_extra("forward", {"root": self.root})
        self.assertEqual((out["status"], out["reason"]), ("failed", "tracker-unknown"))
        plain = fake_adapter(m, "plain")
        m.register_tracker("plain", plain)
        out = m.invoke_extra("forward", {"root": self.root, "tracker": "plain"})
        self.assertEqual((out["status"], out["reason"]), ("failed", "unsupported"))
        self.assertIn("plain", out["summary"])
        rich = fake_adapter(m, "rich")
        rich["extras"] = {
            "forward": lambda request: {
                "status": "completed",
                "exitCode": 0,
                "summary": "ran",
                "output": request["arguments"],
            }
        }
        m.register_tracker("rich", rich)
        out = m.invoke_extra("forward", {"root": self.root, "tracker": "rich", "arguments": ["x"]})
        self.assertEqual((out["status"], out["output"]), ("completed", ["x"]))
        rich["extras"]["forward"] = lambda request: {"status": "done"}
        with self.assertRaises(m.DoorError) as held:
            m.invoke_extra("forward", {"root": self.root, "tracker": "rich"})
        self.assertIn("forward", str(held.exception))

    def test_create_item_takes_no_kind(self):
        """Only a pour makes a root, so a create carries no kind: the door
        refuses one, and naming the work asks for none."""
        m = self.module
        self.assertNotIn("kind", m.TRACKER_DOOR["operation.create-item"]["request"])
        table = fake_adapter(m)
        answer = table["operations"]["operation.create-item"]
        asked: list[dict[str, Any]] = []

        def create_item(request):
            asked.append(dict(request))
            return answer(request)

        table["operations"]["operation.create-item"] = create_item
        m.register_tracker("fake", table)
        with self.assertRaisesRegex(m.DoorError, '"kind" is not a field of its request'):
            m.invoke_tracker(
                "operation.create-item",
                {"root": self.root, "tracker": "fake", "title": "x", "kind": "task"},
            )
        out = m.NameTheWork(
            {"root": self.root, "tracker": "fake", "title": "Work", "arguments": []}
        )
        self.assertEqual(out["status"], "completed", out)
        self.assertEqual([r["title"] for r in asked], ["Work"])
        self.assertNotIn("kind", asked[0])

    def test_an_unknown_adapter_is_a_failed_response(self):
        m = self.module
        out = m.invoke_tracker("operation.create-item", {"root": self.root, "title": "x"})
        self.assertEqual((out["status"], out["reason"]), ("failed", "tracker-unknown"))
        self.assertIn(m.DEFAULT_TRACKER, out["summary"])
        m.register_tracker("fake", fake_adapter(m))
        out = m.invoke_tracker(
            "operation.create-item", {"root": self.root, "title": "x", "tracker": "nowhere"}
        )
        self.assertEqual(out["reason"], "tracker-unknown")
        self.assertIn("nowhere", out["summary"])
        self.assertIn("fake", out["summary"])

    def test_the_request_names_the_adapter_that_answers(self):
        m = self.module
        m.register_tracker(
            "one",
            fake_adapter(
                m,
                "one",
                {
                    "operation.ready-items": {
                        "items": [{"id": "one-1", "title": "One", "status": "open"}]
                    }
                },
            ),
        )
        m.register_tracker(
            "two",
            fake_adapter(
                m,
                "two",
                {
                    "operation.ready-items": {
                        "items": [{"id": "two-1", "title": "Two", "status": "open"}]
                    }
                },
            ),
        )
        for name in ("one", "two"):
            out = m.invoke_tracker("operation.ready-items", {"root": self.root, "tracker": name})
            self.assertEqual(out["items"][0]["id"], name + "-1")
        # The workspace's choice answers when the request names none.
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(
            ["git", "-C", self.root, "config", "--local", m.TRACKER_KEY, "two"], check=True
        )
        out = m.invoke_tracker("operation.ready-items", {"root": self.root})
        self.assertEqual(out["items"][0]["id"], "two-1")

    def test_a_workspace_with_one_store_and_no_choice_is_answered_by_that_adapter(self):
        """A workspace adopted before there was a choice: the one adapter
        holding a store under it answers; two stores or none, the default."""
        m = self.module
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(
            ["git", "-C", self.root, "config", "--local", m.WORKSPACE_KEY, "k" * 16], check=True
        )
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.environ["HOME"] = home
        self.addCleanup(os.environ.__setitem__, "HOME", os.path.expanduser("~"))
        ws = os.path.join(home, ".dotdiw", "k" * 16)
        os.makedirs(ws)
        for name in ("one", "two"):
            table = fake_adapter(
                m,
                name,
                {
                    "operation.ready-items": {
                        "items": [{"id": name + "-1", "title": name, "status": "open"}]
                    }
                },
            )
            table["store"] = (
                lambda n: (
                    lambda root: (
                        os.path.join(m.workspace(root), n + ".store") if m.workspace(root) else None
                    )
                )
            )(name)
            m.register_tracker(name, table)
        with self.assertRaises(m.DoorError):
            m.register_tracker("bad", dict(fake_adapter(m, "bad"), store=lambda: None))
        self.assertIsNone(m.tracker_with_store(self.root))
        out = m.invoke_tracker("operation.ready-items", {"root": self.root})
        self.assertEqual(
            (out["status"], out["reason"]),
            ("failed", "tracker-unknown"),
            "no store: the default, which this registry lacks",
        )
        open(os.path.join(ws, "two.store"), "w").close()
        self.assertEqual(m.tracker_with_store(self.root), "two")
        out = m.invoke_tracker("operation.ready-items", {"root": self.root})
        self.assertEqual(out["items"][0]["id"], "two-1")
        open(os.path.join(ws, "one.store"), "w").close()
        self.assertIsNone(m.tracker_with_store(self.root), "two stores: no guess")
        subprocess.run(
            ["git", "-C", self.root, "config", "--local", m.TRACKER_KEY, "one"], check=True
        )
        m.forget_workspace(self.root)
        out = m.invoke_tracker("operation.ready-items", {"root": self.root})
        self.assertEqual(out["items"][0]["id"], "one-1", "the recorded choice wins")

    def test_the_tracker_door_raises_naming_the_operation_and_the_key(self):
        m = self.module
        with self.assertRaises(m.DoorError) as held:
            m.invoke_tracker("operation.not-one", {})
        self.assertIn("operation.not-one", str(held.exception))
        op = "operation.create-item"
        with self.assertRaises(m.DoorError) as held:
            m.invoke_tracker(op, {"root": self.root, "title": "x", "bogus": 1})
        self.assertIn('"bogus"', str(held.exception))
        with self.assertRaises(m.DoorError) as held:
            m.invoke_tracker(op, {"root": self.root})
        self.assertIn('"title"', str(held.exception))
        # The adapter's answer is held the same way on the way out.
        for answer, key in (({"extra": 1}, '"extra"'), ({"status": "done"}, '"done"')):
            m.TRACKERS.clear()
            m.register_tracker("fake", fake_adapter(m, answers={op: answer}))
            with self.assertRaises(m.DoorError) as held:
                m.invoke_tracker(op, {"root": self.root, "title": "x", "tracker": "fake"})
            self.assertIn(op, str(held.exception))
            self.assertIn(key, str(held.exception))

    VALUES_OUTSIDE_THEIR_TYPE: tuple[Any, ...] = (
        ("operation.show-item", {"id": "x"}, {"item": "a string"}, '"item" is not a record'),
        ("operation.list-items", {}, {"items": "oops"}, '"items" is not a list'),
        (
            "operation.list-items",
            {},
            {"items": [{"id": "a", "title": "A"}]},
            '"items[0].status" is required',
        ),
        (
            "operation.list-items",
            {},
            {"items": [{"id": "a", "title": "A", "status": "nonsense"}]},
            '"items[0].status" is not one of open, in_progress, blocked, closed',
        ),
        (
            "operation.list-items",
            {},
            {"items": [{"id": 1, "title": "A", "status": "open"}]},
            '"items[0].id" is not a string',
        ),
        (
            "operation.show-item",
            {"id": "x"},
            {"item": {"id": "a", "title": "A", "status": "open", "bogus": 1}},
            '"item.bogus" is not a field of its record',
        ),
        (
            "operation.show-item",
            {"id": "x"},
            {"item": {"id": "a", "title": "A", "status": "open", "priority": True}},
            '"item.priority" is not an integer',
        ),
        (
            "operation.show-item",
            {"id": "x"},
            {"item": {"id": "a", "title": "A", "status": "open", "needs": ["b", 2]}},
            '"item.needs[1]" is not a string',
        ),
        (
            "operation.add-need",
            {"id": "x", "needs": "y"},
            {"edge": {"id": "a"}},
            '"edge.needs" is required',
        ),
        (
            "operation.close-item",
            {"id": "x"},
            {"status": "failed", "reason": "not-a-reason"},
            '"reason" is not one of',
        ),
        ("operation.update-item", {"id": "x"}, {"exitCode": "0"}, '"exitCode" is not an integer'),
        ("operation.show-item", {"id": "x"}, {"item": None}, 'a completed answer carries "item"'),
        ("operation.add-need", {"id": "x", "needs": "y"}, {"edge": None}, 'carries "edge"'),
        ("operation.list-items", {}, {"items": None}, 'a completed answer carries "items"'),
        ("operation.create-item", {"title": "T"}, {"item": None}, 'carries "item"'),
    )

    def test_a_value_outside_its_type_raises_from_a_shipped_adapter(self):
        m = self.module
        for operation, request, answer, words in self.VALUES_OUTSIDE_THEIR_TYPE:
            with self.subTest(answer=answer):
                m.TRACKERS.clear()
                m.register_tracker("fake", fake_adapter(m, answers={operation: answer}))
                with self.assertRaises(m.DoorError) as held:
                    m.invoke_tracker(operation, dict(request, root=self.root, tracker="fake"))
                self.assertIn(words, str(held.exception))
                self.assertIn(operation, str(held.exception))

    def test_a_value_outside_its_type_is_one_line_from_a_loaded_adapter(self):
        m = self.module
        for operation, request, answer, words in self.VALUES_OUTSIDE_THEIR_TYPE:
            with self.subTest(answer=answer):
                m.TRACKERS.clear()
                table = fake_adapter(m, answers={operation: answer})
                table["info"]["origin"] = "loaded"
                m.register_tracker("fake", table)
                out = m.invoke_tracker(operation, dict(request, root=self.root, tracker="fake"))
                self.assertEqual((out["status"], out["reason"]), ("failed", "adapter-failed"))
                self.assertIn(words, out["summary"])

    def test_a_record_holding_every_field_of_its_type_passes(self):
        m = self.module
        full = {
            "id": "a",
            "title": "A",
            "kind": "task",
            "status": "in_progress",
            "priority": 0,
            "parent": None,
            "reason": None,
            "needs": ["b"],
            "createdAt": "2026-11-04",
            "updatedAt": None,
        }
        m.register_tracker("fake", fake_adapter(m, answers={"operation.show-item": {"item": full}}))
        out = m.invoke_tracker(
            "operation.show-item", {"root": self.root, "tracker": "fake", "id": "a"}
        )
        self.assertEqual(out["item"], full)

    def test_a_create_or_a_pour_that_printed_itself_may_carry_no_record(self):
        """bd's own create with -q prints nothing to read an id from: the
        create happened, and the terminal has had all there is to say."""
        m = self.module
        m.register_tracker(
            "fake",
            fake_adapter(
                m,
                answers={
                    "operation.create-item": {"item": None, "printed": True},
                    "operation.pour-steps": {"rootId": None, "stepIds": [], "printed": True},
                },
            ),
        )
        made = m.invoke_tracker(
            "operation.create-item", {"root": self.root, "tracker": "fake", "title": "T"}
        )
        self.assertEqual(made["status"], "completed")
        poured = m.invoke_tracker(
            "operation.pour-steps",
            {"root": self.root, "tracker": "fake", "formulaRef": "m", "title": "m", "steps": []},
        )
        self.assertEqual(poured["status"], "completed")

    def test_the_orchestration_reaches_the_interface_by_id(self):
        m = self.module
        out = m.AnswerThroughTheTracker({"operation": "operation.not-one"})
        self.assertEqual((out["status"], out["reason"]), ("failed", "operation-not-of-the-tracker"))
        m.register_tracker(
            "fake",
            fake_adapter(
                m,
                answers={
                    "operation.ready-items": {
                        "items": [{"id": "fake-1", "title": "Fake", "status": "open"}]
                    }
                },
            ),
        )
        out = m.AnswerThroughTheTracker(
            {
                "operation": "operation.ready-items",
                "tracker": "fake",
                "root": self.root,
                "request": {},
            }
        )
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["response"]["items"][0]["id"], "fake-1")
        out = m.AnswerThroughTheTracker(
            {"operation": "operation.ready-items", "tracker": "nowhere", "root": self.root}
        )
        self.assertEqual(out["reason"], "tracker-unknown")

    def test_an_adapter_loads_from_the_home_by_name(self):
        m = self.module
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.environ["HOME"] = home
        self.addCleanup(os.environ.__setitem__, "HOME", os.path.expanduser("~"))
        trackers = os.path.join(home, ".dotdiw", "trackers")
        os.makedirs(trackers)
        with open(os.path.join(trackers, "mine.py"), "w", encoding="utf-8") as fh:
            fh.write("OPERATIONS = %r\n" % sorted(m.TRACKER_DOOR))
            fh.write(
                "def _answer(operation):\n"
                "    def operation_(request):\n"
                "        out = {'status': 'completed', 'summary': operation, 'exitCode': 0}\n"
                "        return dict(out, items=[])\n"
                "    return operation_\n"
                "TRACKER = {'info': {'name': 'mine', 'version': '1', 'interface': 2},\n"
                "           'operations': {op: _answer(op) for op in OPERATIONS}}\n"
            )
        self.assertFalse(m.load_tracker("../mine"))
        self.assertFalse(m.load_tracker("absent"))
        out = m.invoke_tracker("operation.ready-items", {"root": self.root, "tracker": "mine"})
        self.assertEqual(out["status"], "completed")
        info = m.TRACKERS["mine"]["info"]
        self.assertEqual(info["origin"], "loaded")
        self.assertTrue(info["source"].endswith("mine.py"))

    def test_a_module_says_which_interface_it_was_written_for(self):
        """Absent means 1, the number every module written before 1.0.0 was
        written for, and this tool speaks 2: a module that says nothing or says
        1 is refused by name when it loads, as is any other number this tool
        does not speak, and never halfway through an operation."""
        m = self.module
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.environ["HOME"] = home
        self.addCleanup(os.environ.__setitem__, "HOME", os.path.expanduser("~"))
        trackers = os.path.join(home, ".dotdiw", "trackers")
        os.makedirs(trackers)

        def module(name, declared):
            with open(os.path.join(trackers, name + ".py"), "w", encoding="utf-8") as fh:
                fh.write("OPERATIONS = %r\n" % sorted(m.TRACKER_DOOR))
                fh.write(
                    "def _answer(operation):\n"
                    "    def operation_(request):\n"
                    "        return {'status': 'completed', 'summary': operation, 'exitCode': 0}\n"
                    "    return operation_\n"
                    "TRACKER = {'info': {'name': %r, 'version': '1'%s},\n"
                    "           'operations': {op: _answer(op) for op in OPERATIONS}}\n"
                    % (name, ", 'interface': %r" % (declared,) if declared != "absent" else "")
                )

        module("unsaid", "absent")
        module("earlier", 1)
        module("said", m.TRACKER_INTERFACE)
        module("later", m.TRACKER_INTERFACE + 1)
        module("flag", True)
        self.assertTrue(m.load_tracker("said"))
        for name, declared in (("unsaid", 1), ("earlier", 1), ("later", m.TRACKER_INTERFACE + 1)):
            self.assertFalse(m.load_tracker(name), name)
            self.assertIn(
                "written for tracker interface %d; this dotdiw supports interface %d"
                % (declared, m.TRACKER_INTERFACE),
                m.LOAD_FAILED[name],
            )
        self.assertFalse(m.load_tracker("flag"))
        out = m.invoke_tracker("operation.ready-items", {"root": self.root, "tracker": "later"})
        self.assertEqual((out["status"], out["reason"]), ("failed", "adapter-failed"))
        self.assertTrue(out["summary"].startswith("later did not load from "), out["summary"])
        by_name = {t["name"]: t for t in m.ListTrackers({"root": self.root})["trackers"]}
        self.assertEqual(by_name["later"]["version"], "did not load")

    def test_the_guide_fills_the_table_of_the_starting_file(self):
        """Pasted into the file `tracker new` writes, the guide's table names
        what is there."""
        m = self.module
        with open(os.path.join(HERE, "trackers", "README.md"), encoding="utf-8") as fh:
            guide = fh.read()
        pairs = re.findall(r'"(operation\.[a-z-]+)": ([a-z_]+),', guide)
        self.assertEqual(len(pairs), 10)
        for operation, function in pairs:
            self.assertIn('"%s": %s,' % (operation, function), m.TRACKER_SKELETON)
            self.assertIn("def %s(request: Record)" % function, m.TRACKER_SKELETON)
        self.assertNotIn('"store": store', guide)

    def test_a_shipped_table_speaks_the_interface(self):
        m = self.module
        for table in (m.BEADS, m.LOCAL):
            self.assertEqual(table["info"]["interface"], m.TRACKER_INTERFACE)
        table = dict(m.LOCAL)
        table["info"] = dict(table["info"], interface=m.TRACKER_INTERFACE + 1)
        with self.assertRaisesRegex(m.DoorError, "written for tracker interface"):
            m.register_tracker("elsewhere", table)
        self.assertNotIn("elsewhere", m.TRACKERS)

    def test_every_copy_of_the_helper_reads_back_what_it_kept(self):
        """dotdiw's own helper, jira.py's and the starting file's keep the means
        as a description's last section and give back exactly what they were
        given: a description that looks like a section stays a description,
        and the means appended after one are the means."""
        m = self.module
        space: dict[str, Any] = {}
        exec(compile(m.TRACKER_SKELETON.replace("<NAME>", "acme"), "acme.py", "exec"), space)
        jira = load_module("jira_for_the_helper", os.path.join(HERE, "trackers", "jira.py"))
        descriptions = [
            None,
            "",
            "Ship it.",
            "Ship it.\n",
            "Verify using:",
            "Verify using:\n- x",
            "Verify using:\n- x\n\nVerify using:\n- y",
            "Ship it.\n\nVerify using:",
            "Ship it.\n\nVerify using:\n- x",
            "Ship it.\n\nVerify using:\nnot a means",
            "Ship it.\n\nVerify using:\n- x\n- ",
            "\n\nVerify using:\n- x",
        ]
        means = [[], ["run:make check"], ["run:make check", "https://example.invalid/runs/1"]]
        for name, keep, read in (
            ("dotdiw", m.keep_verify_using, m.read_verify_using),
            ("jira.py", jira.keep_verify_using, jira.read_verify_using),
            ("the starting file", space["keep_verify_using"], space["read_verify_using"]),
        ):
            for description in descriptions:
                for kept in means:
                    with self.subTest(helper=name, description=description, means=kept):
                        back, read_means = read(keep(description, kept))
                        self.assertEqual(read_means, kept)
                        self.assertEqual(back or None, description or None)

    def test_the_starting_file_is_in_the_registry_shape(self):
        m = self.module
        space: dict[str, Any] = {}
        exec(compile(m.TRACKER_SKELETON.replace("<NAME>", "acme"), "acme.py", "exec"), space)
        table = space["TRACKER"]
        self.assertEqual(table["info"]["interface"], m.TRACKER_INTERFACE)
        self.assertEqual(table["info"]["name"], "acme")
        self.assertEqual(set(table["operations"]), set(m.TRACKER_DOOR))
        table["info"].setdefault("origin", "loaded")
        m.register_tracker("acme", table)
        self.assertIn("acme", m.TRACKERS)

    def test_a_loaded_adapter_that_fails_is_refused_in_one_line(self):
        """An adapter under the home that raises inside an operation or an
        extra, or answers outside the interface, is its author's mistake and
        the worker's situation: a failed response naming it, never a
        traceback. A module that does not load is refused the same way and
        listed as such; a file that is no adapter is simply not one; and a
        shipped adapter's mistake still raises, held above."""
        m = self.module
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.environ["HOME"] = home
        self.addCleanup(os.environ.__setitem__, "HOME", os.path.expanduser("~"))
        trackers = os.path.join(home, ".dotdiw", "trackers")
        os.makedirs(trackers)
        with open(os.path.join(trackers, "boom.py"), "w", encoding="utf-8") as fh:
            fh.write("OPERATIONS = %r\n" % sorted(m.TRACKER_DOOR))
            fh.write(
                "def _answer(operation):\n"
                "    def operation_(request):\n"
                "        if operation == 'operation.create-item':\n"
                "            raise RuntimeError('the adapter has a bug')\n"
                "        if operation == 'operation.show-item':\n"
                "            return {'status': 'completed', 'summary': 'x', 'exitCode': 0, 'bogus': 1}\n"
                "        return {'status': 'completed', 'summary': operation, 'exitCode': 0}\n"
                "    return operation_\n"
                "def forward(request):\n"
                "    raise ValueError('no')\n"
                "TRACKER = {'info': {'name': 'boom', 'version': '1', 'interface': 2},\n"
                "           'operations': {op: _answer(op) for op in OPERATIONS},\n"
                "           'extras': {'forward': forward}}\n"
            )
        with open(os.path.join(trackers, "broken.py"), "w", encoding="utf-8") as fh:
            fh.write("def broken(:\n")
        with open(os.path.join(trackers, "helpers.py"), "w", encoding="utf-8") as fh:
            fh.write("VALUE = 1\n")
        out = m.invoke_tracker(
            "operation.create-item", {"root": self.root, "tracker": "boom", "title": "x"}
        )
        self.assertEqual(
            (out["status"], out["reason"], out["tracker"]), ("failed", "adapter-failed", "boom")
        )
        self.assertEqual(
            out["summary"], "boom failed inside create-item: RuntimeError: the adapter has a bug"
        )
        out = m.invoke_tracker(
            "operation.show-item", {"root": self.root, "tracker": "boom", "id": "x"}
        )
        self.assertEqual(out["reason"], "adapter-failed")
        self.assertIn('"bogus"', out["summary"])
        out = m.invoke_extra("forward", {"root": self.root, "tracker": "boom", "arguments": []})
        self.assertEqual((out["status"], out["reason"]), ("failed", "adapter-failed"))
        self.assertEqual(out["summary"], "boom failed inside forward: ValueError: no")
        out = m.invoke_tracker("operation.ready-items", {"root": self.root, "tracker": "broken"})
        self.assertEqual((out["status"], out["reason"]), ("failed", "adapter-failed"))
        self.assertTrue(out["summary"].startswith("broken did not load from "), out["summary"])
        self.assertIn("SyntaxError", out["summary"])
        out = m.invoke_tracker("operation.ready-items", {"root": self.root, "tracker": "helpers"})
        self.assertEqual(out["reason"], "tracker-unknown")
        by_name = {t["name"]: t for t in m.ListTrackers({"root": self.root})["trackers"]}
        self.assertEqual(by_name["broken"]["version"], "did not load")
        self.assertTrue(by_name["broken"]["source"].endswith("broken.py"))
        self.assertIn("boom", by_name)
        self.assertNotIn("helpers", by_name)


def have_bd():
    return shutil.which("bd") is not None


FORMULA = """formula = "mol-release-through-tap"
description = "Release a tagged version of the tool through the Homebrew tap: bump the formula, check the sha, install cleanly, and announce. Use when shipping a version to users."
examples = ["Release v0.2.1 through the tap", "Ship the next version through brew", "Cut a release and update the tap"]
version = 1
type = "workflow"

[[steps]]
id = "bump"
title = "Bump the formula to the new version"

[[steps]]
id = "install"
title = "Install cleanly from the tap"
needs = ["bump"]

[[steps]]
id = "announce"
title = "Announce the release"
needs = ["install"]
"""


@unittest.skipUnless(have_bd(), "bd is not installed")
class TheName(unittest.TestCase):
    """bd's name is in nothing dotdiw says (invariant.one-name-for-all-four).

    It may appear in the source only as the name of one of bd's own things:
    the executables, bd's config file, its formula directory, its state
    directory and the files it writes for agents. One sentence may name it, to
    a checkout that chose it: the line that says how to install it. Every other
    string literal that carries the word is a sentence a worker would read, and
    fails here with the line it is on. Docstrings are the maintainers' and are
    not read.
    """

    WORD = re.compile(r"(?i)(?<![a-z0-9_])(bd|beads)(?![a-z0-9_])")
    NAMES = {"bd", "beads", "beads is not installed. Run: brew install beads"}
    PATHS = ("~/.config/bd/config.yaml", "~/.beads/formulas", ".cursor/rules/beads.mdc", ".beads")

    def test_bd_is_named_only_as_a_thing_of_its_own(self):
        with open(SCRIPT, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), SCRIPT)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        said = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docstrings or node.value in self.NAMES:
                continue
            text = node.value
            for path in self.PATHS:
                text = text.replace(path, " ")
            if self.WORD.search(text):
                said.append("line %d: %r" % (node.lineno, node.value))
        self.assertEqual(said, [], "\n".join(["dotdiw names bd where a worker reads it:"] + said))


class TheWitnessLog(unittest.TestCase):
    """The events the contract watches come from a real run, and only when
    asked; under beads here, and under local below, where no tracker binary
    is on PATH at all."""

    TRACKER: str = "beads"
    PATH: str | None = None

    def setUp(self):
        if self.TRACKER == "beads" and not shutil.which("bd"):
            self.skipTest("bd is not installed")
        self.root = tempfile.mkdtemp(prefix="dotdiw-witness-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = tempfile.mkdtemp(prefix="dotdiw-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = dict(os.environ, HOME=self.home)
        self.env.pop("DOTDIW_WITNESS", None)
        for args in (
            ["init", "-q", "."],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "Test"],
            ["config", "beads.role", "maintainer"],
        ):
            subprocess.run(["git"] + args, cwd=self.root, capture_output=True)
        with open(
            os.path.join(self.root, "release-through-tap.formula.toml"), "w", encoding="utf-8"
        ) as fh:
            fh.write(FORMULA)
        with open(os.path.join(self.root, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# A project\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "the project as it stands"], cwd=self.root, capture_output=True
        )

    def dotdiw(self, *args, witness=False):
        env = dict(self.env, DOTDIW_WITNESS="1") if witness else self.env
        env = dict(env, DOTDIW_TRACKER=self.TRACKER)
        if self.PATH:
            env["PATH"] = self.PATH
        p = subprocess.run(
            [sys.executable, "-I", SCRIPT] + list(args),
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
        )
        return p.returncode, p.stdout + p.stderr

    def log_path(self):
        key = subprocess.run(
            ["git", "config", "--local", "--get", "dotdiw.workspace"],
            cwd=self.root,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return os.path.join(self.home, ".dotdiw", key, "witness.jsonl") if key else None

    def log(self):
        path = self.log_path()
        if not path or not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_off_by_default(self):
        code, out = self.dotdiw("init", "--prefix", "w")
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("create", "Release v0.3.0 through the tap")
        self.assertEqual(code, 0, out)
        self.assertIn("release-through-tap", out)
        self.assertIsNone(self.log(), "nothing asked for the log")

    def test_formula_pour_is_witnessed_as_a_pour(self):
        code, out = self.dotdiw("init", "--prefix", "w", witness=True)
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("create", "Release v0.3.0 through the tap", witness=True)
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("formula", "pour", "mol-release-through-tap", witness=True)
        self.assertEqual(code, 0, out)
        poured = [e for e in self.log() if e["label"] == "procedure_poured"]
        self.assertEqual(len(poured), 1)
        self.assertEqual(poured[0]["formulaId"], "mol-release-through-tap")
        self.assertEqual(poured[0]["workId"], self.log()[0]["workId"])

    def test_a_real_run_is_a_story_the_contract_calls_valid(self):
        code, out = self.dotdiw("init", "--prefix", "w", witness=True)
        self.assertEqual(code, 0, out)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, ".beads")),
            "nothing of the tracker's is in the tree; the log lives under the home",
        )

        code, out = self.dotdiw("create", "Release v0.3.0 through the tap", witness=True)
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("mol", "pour", "mol-release-through-tap", witness=True)
        self.assertEqual(code, 0, out)
        poured = [e for e in self.log() if e["label"] == "procedure_poured"]
        self.assertEqual(len(poured), 1)
        self.assertEqual(poured[0]["formulaId"], "mol-release-through-tap")
        self.assertEqual(poured[0]["workId"], self.log()[0]["workId"])
        steps = poured[0]["stepIds"]
        self.assertEqual(len(steps), 3)

        # Close the steps in the order their needs allow, then the root --
        # through dotdiw, which is the only place that sees it happen.
        code, listing = self.dotdiw("list", "--all", "--json", witness=True)
        rows = json.loads(listing)
        # The tracker's own JSON under beads, the interface's records under
        # local: the needs are read from whichever came.
        needs = {
            r["id"]: r.get("needs")
            if "needs" in r
            else [
                d["depends_on_id"]
                for d in (r.get("dependencies") or [])
                if d.get("type") == "blocks"
            ]
            for r in rows
            if r["id"] in steps
        }
        order, left = [], list(steps)
        while left:
            ready = [s for s in left if all(d in order for d in needs[s])]
            self.assertTrue(ready, "the poured steps have a cycle")
            order.extend(ready)
            left = [s for s in left if s not in ready]
        for step in order:
            code, out = self.dotdiw("close", step, witness=True)
            self.assertEqual(code, 0, out)
        code, out = self.dotdiw("close", poured[0]["moleculeId"], witness=True)
        self.assertEqual(code, 0, out)

        labels = [e["label"] for e in self.log()]
        self.assertEqual(
            labels,
            ["work_named", "formula_surfaced", "procedure_poured"]
            + ["step_closed"] * 3
            + ["molecule_closed"],
        )
        # Every event that an adapter answered says which one.
        for event in self.log():
            if event["label"] != "formula_surfaced":
                self.assertEqual(event.get("tracker"), self.TRACKER, event)
        p = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.root, capture_output=True, text=True
        )
        self.assertEqual(
            sorted(line[3:] for line in p.stdout.splitlines() if line.strip()),
            ["AGENTS.md", "CLAUDE.md"],
            "only the declaration is in the tree",
        )

        # Every field the observability bindings require is on every event.
        idl = load_idl()
        for binding in idl["observabilityBindings"]:
            for event in self.log():
                if event["label"] in binding["observedLabels"]:
                    for field in binding["requiredFields"]:
                        self.assertIn(field, event, "%s lacks %s" % (event["label"], field))
                    self.assertEqual(event["source"], binding["source"])

        if not os.path.exists(POA):
            self.skipTest(
                "POA is not on this machine; the log was checked against the bindings only"
            )
        p = subprocess.run(
            [
                POA,
                "match",
                "cesc",
                "--contract",
                CONTRACT,
                "--events",
                self.log_path(),
                "--watermarks",
                WATERMARKS,
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual([m["storyStatus"] for m in report["matches"]], ["valid"], report)

    def test_a_pour_of_what_never_surfaced_is_not_a_valid_story(self):
        with open(os.path.join(self.root, "other.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(
                FORMULA.replace("mol-release-through-tap", "mol-other-thing")
                .replace(
                    "Release a tagged version of the tool through the Homebrew tap",
                    "Rotate the signing keys of the build service",
                )
                .replace(
                    '"Release v0.2.1 through the tap", "Ship the next version through brew", "Cut a release and update the tap"',
                    '"Rotate the signing keys", "Renew the build service keys", "Key rotation for the build"',
                )
            )
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(
            ["git", "commit", "-qm", "another formula"], cwd=self.root, capture_output=True
        )
        code, out = self.dotdiw("init", "--prefix", "w", witness=True)
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("create", "Release v0.3.0 through the tap", witness=True)
        self.assertEqual(code, 0, out)
        code, out = self.dotdiw("mol", "pour", "mol-other-thing", witness=True)
        self.assertEqual(code, 0, out)
        poured = [e for e in self.log() if e["label"] == "procedure_poured"][0]
        # Attributed to the most recent named work, since nothing surfaced it.
        self.assertEqual(poured["workId"], self.log()[0]["workId"])
        if not os.path.exists(POA):
            self.skipTest("POA is not on this machine")
        p = subprocess.run(
            [
                POA,
                "match",
                "cesc",
                "--contract",
                CONTRACT,
                "--events",
                self.log_path(),
                "--watermarks",
                WATERMARKS,
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        report = json.loads(p.stdout)
        self.assertNotEqual([m["storyStatus"] for m in report["matches"]], ["valid"], report)


class TheWitnessLogUnderLocal(TheWitnessLog):
    """The same story, valid under the local adapter with no tracker binary
    on PATH: the contract does not care which adapter answered."""

    TRACKER = "local"
    PATH = "/usr/bin:/bin"


class TheProject(unittest.TestCase):
    """What pyproject.toml says of the tool agrees with the tool."""

    def test_the_version_line_is_the_project_version(self):
        """One version, in the tool; pyproject.toml repeats it and may not drift."""
        with open(os.path.join(HERE, "pyproject.toml"), "rb") as fh:
            project = tomllib.load(fh)["project"]
        module = load_module("dotdiw_version", SCRIPT)
        self.assertEqual(project["version"], module.VERSION)
        self.assertEqual(project["requires-python"], ">=3.11")


class TheRankingBenchmark(unittest.TestCase):
    """measure/rank_between.py compares what each version surfaces by the
    formulaRef of each formula, in order, and refuses a ranking that names
    none: lists of nothing compare equal to anything."""

    def test_the_benchmark_compares_formula_ids(self):
        bench = load_module(
            "rank_between_under_test",
            os.path.join(HERE, "measurements", "measure", "rank_between.py"),
        )
        tree = load_module("dotdiw_for_the_benchmark", SCRIPT)
        surfaced, _, count = bench.rankings(tree, HERE, ["Write a tracker adapter"])
        self.assertEqual(surfaced["Write a tracker adapter"][0], "mol-write-tracker-adapter")
        self.assertGreater(count, 0)

        class Nameless:
            @staticmethod
            def MatchFormulas(request):
                return {"surfaced": [{"formula": "mol-anything"}]}

            @staticmethod
            def DescribeAndCheck(request):
                return {"problems": [], "formulaCount": 1}

        with self.assertRaises(SystemExit):
            bench.rankings(Nameless, HERE, ["Anything"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
