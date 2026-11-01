#!/usr/bin/env python3
"""Does dotdiw keep to its operation algebra?

operation-idl.json names the operations, what each calls, and which beads and
git commands each crosses the product boundary with. POA checks that file
against the governed source model; nothing in POA checks it against the
program except the gRPC conformance harness, which needs Buf. These tests
hold the program to the file without any of that, from the source alone.

    python3 -I test_promise.py

The sort of every top-level definition in `dotdiw` -- infrastructure, the
command-line interface, one operation's helpers, or an operation -- is written
here. It is the proof that no behaviour is shared outside the operation
algebra, and the test that fails when a function is added without saying
which of the four it is.
"""

import ast
import importlib.machinery
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "dotdiw")
IDL = os.path.join(HERE, "operation-idl.json")
BINDINGS = os.path.join(HERE, "promise_bindings.py")
CONTRACT = os.path.join(HERE, "contracts", "named-work-found-its-procedure.cesc.yaml")
WATERMARKS = os.path.join(HERE, "events", "source-watermarks.yaml")
POA = os.path.expanduser("~/poa")

# Shared by any body and deciding nothing about the product: how to run git
# and bd, the pty plumbing, resolving the checkout's tracker under the home,
# tokenising, the FTS storage, file parsing, and the witness log's append and
# read.
INFRASTRUCTURE = {
    "find_bd", "git", "repo_root", "workspace", "beads_dir", "adopted",
    "bd_quiet", "_hold_partial", "run_bd", "toks", "load_formula", "no_fts5",
    "Index", "witness_on", "witness", "witnessed",
}

# The command line: parse the affordance, build the request, call the
# operation. Infrastructure and operations, nothing else, may be called here.
INTERFACE = {"extract_query", "main"}

# Module-level definitions that are part of exactly one operation's body.
HELPERS = {
    "write_formula": {"Titles", "slug", "past_titles", "steps_from"},
}

# Infrastructure that runs a tracker or git command, and the dependency it
# crosses into.
RUNNERS = {"git": "product.git", "bd_quiet": "product.beads"}


def function_for(operation_id):
    return operation_id.split(".", 1)[1].replace("-", "_")


def load_idl():
    with open(IDL, encoding="utf-8") as fh:
        return json.load(fh)


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


class Source:
    """What each top-level definition in dotdiw calls, read from its AST."""

    def __init__(self, path=SCRIPT):
        with open(path, encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read(), path)
        self.defs = {node.name: node for node in self.tree.body
                     if isinstance(node, (ast.FunctionDef, ast.ClassDef))}

    def names_called(self, name):
        """Top-level names called anywhere in a definition, nested defs included."""
        out = set()
        for node in ast.walk(self.defs[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.defs:
                    out.add(node.func.id)
        return out

    def commands(self, name):
        """(runner, words) for every literal git([...]) or bd_quiet([...]) call.

        The words are the leading string constants of the list; a variable
        ends them, so git(["config", "--unset", HOOKS_KEY]) is config --unset.
        """
        out = []
        for node in ast.walk(self.defs[name]):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in RUNNERS and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.BinOp):        # ["diff", "--name-only", "--"] + rels
                arg = arg.left
            if not isinstance(arg, ast.List):
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
    """Every literal git or bd command a body runs, directly or through the
    infrastructure it calls: `workspace()` runs `git config --local --get`
    on the body's behalf, and the body declares it."""
    out = []
    parts = set(body_of(source, operation))
    for part in list(parts):
        parts |= source.names_called(part) & (INFRASTRUCTURE - set(RUNNERS))
    for part in parts:
        out.extend(source.commands(part))
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
    """Every definition in dotdiw is one of four things, and says which."""

    @classmethod
    def setUpClass(cls):
        cls.idl = load_idl()
        cls.source = Source()
        cls.operations = {function_for(o["operationId"]): o for o in cls.idl["operations"]}

    def test_every_definition_is_sorted(self):
        helpers = set().union(*HELPERS.values())
        expected = INFRASTRUCTURE | INTERFACE | helpers | set(self.operations)
        self.assertEqual(set(self.source.defs), expected,
                         "a top-level definition is not infrastructure, interface, "
                         "an operation, or one operation's helper")

    def test_every_operation_is_one_function_taking_one_request(self):
        module = load_module("dotdiw_under_test", SCRIPT)
        for name in self.operations:
            fn = getattr(module, name, None)
            self.assertTrue(callable(fn), "%s has no function" % name)
            self.assertEqual(list(inspect.signature(fn).parameters), ["request"], name)

    def test_bindings_resolve_to_those_functions(self):
        bindings = load_module("promise_bindings_under_test", BINDINGS)
        by_op = {b["operationId"]: b for b in self.idl["implementationBindings"]}
        self.assertEqual(set(by_op), {o["operationId"] for o in self.idl["operations"]})
        for op in self.idl["operations"]:
            b = by_op[op["operationId"]]
            module, attr = b["implementationUnit"].split("::")
            self.assertEqual(module, "promise_bindings")
            self.assertEqual(b["implementationMode"], "inline-body")
            self.assertIs(b["privateHelpersUsed"], False)
            fn = getattr(bindings, attr, None)
            self.assertTrue(callable(fn), b["implementationUnit"])
            self.assertEqual(list(inspect.signature(fn).parameters), ["request"])
            self.assertEqual(fn.body, function_for(op["operationId"]),
                             "%s is bound to the wrong body" % op["operationId"])
            self.assertEqual(b["calledOperationIds"],
                             [c["operationId"] for c in op.get("calls") or []])
        self.assertEqual(set(bindings.BINDINGS), {o["name"] for o in self.idl["operations"]})
        # The table is not a copy of the bodies: calling through it runs them.
        out = bindings.CommitFormula({"root": HERE, "path": "x.formula.toml"})
        self.assertEqual(out["status"], "blocked")

    def test_infrastructure_calls_no_operation(self):
        for name in INFRASTRUCTURE:
            called = self.source.names_called(name)
            self.assertFalse(called & set(self.operations), "%s calls %s" % (name, called))
            self.assertFalse(called & set().union(*HELPERS.values()), name)

    def test_each_helper_belongs_to_one_body(self):
        for owner, helpers in HELPERS.items():
            for helper in helpers:
                users = {name for name in self.source.defs
                         if helper in self.source.names_called(name)
                         and name != helper}
                users -= helpers                       # a body's parts may call each other
                self.assertEqual(users, {owner}, "%s is used by %s" % (helper, users))

    def test_the_interface_decides_nothing(self):
        """main() calls infrastructure and operations only."""
        for name in INTERFACE:
            called = self.source.names_called(name)
            allowed = INFRASTRUCTURE | INTERFACE | set(self.operations)
            self.assertTrue(called <= allowed, "%s calls %s" % (name, called - allowed))


class TheCalls(unittest.TestCase):
    """What each body calls is what the IDL says it calls, both ways."""

    @classmethod
    def setUpClass(cls):
        cls.idl = load_idl()
        cls.source = Source()
        cls.operations = {function_for(o["operationId"]): o for o in cls.idl["operations"]}
        cls.dependencies = {d["dependencyId"]: d for d in cls.idl["externalProductDependencies"]}

    def body_calls(self, name):
        called = set()
        for part in body_of(self.source, name):
            called |= self.source.names_called(part)
        return called

    def test_declared_calls_match_the_body(self):
        for name, op in self.operations.items():
            in_body = self.body_calls(name) & set(self.operations)
            declared = {function_for(c["operationId"]) for c in op.get("calls") or []}
            self.assertEqual(in_body, declared, "%s: body calls %s, IDL declares %s"
                             % (name, sorted(in_body), sorted(declared)))

    def test_nothing_is_shared_outside_the_algebra(self):
        """A non-infrastructure name reached from two bodies is an operation."""
        users = {}
        for name in self.operations:
            for called in self.body_calls(name) - INFRASTRUCTURE:
                users.setdefault(called, set()).add(name)
        for called, bodies in users.items():
            if len(bodies) > 1:
                self.assertIn(called, self.operations,
                              "%s is shared by %s and is not an operation" % (called, sorted(bodies)))

    def test_external_calls_are_declared_where_they_happen(self):
        for name, op in self.operations.items():
            declared = [(c["dependencyId"], c["operationRef"]) for c in op.get("externalCalls") or []]
            for dep, ref in declared:
                self.assertIn(dep, self.dependencies, "%s: unknown %s" % (name, dep))
                product, command = ref.split("::")
                self.assertEqual(product, self.dependencies[dep]["productId"], ref)
            words = {}
            for dep, ref in declared:
                words.setdefault(self.dependencies[dep]["productId"], []).append(ref.split("::")[1].split())
            for runner, literal in commands_of(self.source, name):
                product = RUNNERS[runner]
                self.assertTrue(
                    any(same_command(d, literal) for d in words.get(product, [])),
                    "%s runs %s %s and does not declare it" % (name, product, " ".join(literal)))
            # A step that forwards decides which tracker command runs, and says
            # so; an orchestration hands the worker's command on and decides
            # nothing, so the crossing is forward-to-beads's own.
            if ("forward_to_beads" in self.body_calls(name) and name != "forward_to_beads"
                    and op["kind"] != "orchestration"):
                self.assertTrue(words.get("product.beads"),
                                "%s forwards to beads and declares no beads call" % name)

    def test_every_declared_external_call_has_evidence_in_the_body(self):
        for name, op in self.operations.items():
            literals = commands_of(self.source, name)
            forwards = "forward_to_beads" in self.body_calls(name) or name == "forward_to_beads"
            for c in op.get("externalCalls") or []:
                product, command = c["operationRef"].split("::")
                declared = command.split()
                evidenced = any(RUNNERS[r] == product and same_command(declared, lit)
                                for r, lit in literals)
                if product == "product.beads" and forwards:
                    evidenced = True
                self.assertTrue(evidenced, "%s declares %s and nothing in its body runs it"
                                % (name, c["operationRef"]))

    def test_only_forward_to_beads_runs_bd_with_the_terminal(self):
        """The name-hiding happens in exactly one body."""
        for name in self.source.defs:
            if "run_bd" in self.source.names_called(name):
                self.assertEqual(name, "forward_to_beads", name)

    def test_the_commit_is_refused(self):
        module = load_module("dotdiw_under_test_2", SCRIPT)
        out = module.commit_formula({"root": HERE, "path": "x.formula.toml"})
        self.assertEqual(out["status"], "blocked")
        self.assertIn("git add x.formula.toml", out["command"])
        self.assertEqual(self.source.commands("commit_formula"), [])


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
class TheWitnessLog(unittest.TestCase):
    """The events the contract watches come from a real run, and only when asked."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dotdiw-witness-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = tempfile.mkdtemp(prefix="dotdiw-home-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = dict(os.environ, HOME=self.home)
        self.env.pop("DOTDIW_WITNESS", None)
        for args in (["init", "-q", "."], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "Test"], ["config", "beads.role", "maintainer"]):
            subprocess.run(["git"] + args, cwd=self.root, capture_output=True)
        with open(os.path.join(self.root, "release-through-tap.formula.toml"), "w",
                  encoding="utf-8") as fh:
            fh.write(FORMULA)
        with open(os.path.join(self.root, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# A project\n")
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "the project as it stands"], cwd=self.root,
                       capture_output=True)

    def dotdiw(self, *args, witness=False):
        env = dict(self.env, DOTDIW_WITNESS="1") if witness else self.env
        p = subprocess.run([sys.executable, "-I", SCRIPT] + list(args), cwd=self.root,
                           env=env, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def log_path(self):
        key = subprocess.run(["git", "config", "--local", "--get", "dotdiw.workspace"],
                             cwd=self.root, capture_output=True, text=True).stdout.strip()
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

    def test_a_real_run_is_a_story_the_contract_calls_valid(self):
        code, out = self.dotdiw("init", "--prefix", "w", witness=True)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".beads")),
                         "nothing of the tracker's is in the tree; the log lives under the home")

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
        needs = {r["id"]: [d["depends_on_id"] for d in (r.get("dependencies") or [])
                           if d.get("type") == "blocks"] for r in rows if r["id"] in steps}
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
        self.assertEqual(labels, ["work_named", "formula_surfaced", "procedure_poured"]
                         + ["step_closed"] * 3 + ["molecule_closed"])
        p = subprocess.run(["git", "status", "--porcelain"], cwd=self.root,
                           capture_output=True, text=True)
        self.assertEqual(sorted(l[3:] for l in p.stdout.splitlines() if l.strip()),
                         ["AGENTS.md", "CLAUDE.md"], "only the declaration is in the tree")

        # Every field the observability bindings require is on every event.
        idl = load_idl()
        for binding in idl["observabilityBindings"]:
            for event in self.log():
                if event["label"] in binding["observedLabels"]:
                    for field in binding["requiredFields"]:
                        self.assertIn(field, event, "%s lacks %s" % (event["label"], field))
                    self.assertEqual(event["source"], binding["source"])

        if not os.path.exists(POA):
            self.skipTest("POA is not on this machine; the log was checked against the bindings only")
        p = subprocess.run([POA, "match", "cesc", "--contract", CONTRACT, "--events",
                            self.log_path(),
                            "--watermarks", WATERMARKS, "--json"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual([m["storyStatus"] for m in report["matches"]], ["valid"], report)

    def test_a_pour_of_what_never_surfaced_is_not_a_valid_story(self):
        with open(os.path.join(self.root, "other.formula.toml"), "w", encoding="utf-8") as fh:
            fh.write(FORMULA.replace("mol-release-through-tap", "mol-other-thing")
                     .replace("Release a tagged version of the tool through the Homebrew tap",
                              "Rotate the signing keys of the build service")
                     .replace('"Release v0.2.1 through the tap", "Ship the next version through brew", "Cut a release and update the tap"',
                              '"Rotate the signing keys", "Renew the build service keys", "Key rotation for the build"'))
        subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "another formula"], cwd=self.root, capture_output=True)
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
        p = subprocess.run([POA, "match", "cesc", "--contract", CONTRACT, "--events",
                            self.log_path(),
                            "--watermarks", WATERMARKS, "--json"],
                           capture_output=True, text=True)
        report = json.loads(p.stdout)
        self.assertNotEqual([m["storyStatus"] for m in report["matches"]], ["valid"], report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
