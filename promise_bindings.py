#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The implementation bindings of operation-idl.json, resolvable by name.

POA resolves an implementation binding with importlib: `promise_bindings::
NameTheWork` is this module's attribute of that name, and must be a callable
taking one argument called `request`. Every body is in `dotdiw`; this module
defines nothing but the table from the IDL's names to those bodies.

Two facts shape it. `dotdiw` is a file without a .py suffix, so it is loaded
by path under the module name `dotdiw`. And `poa conform grpc-signatures`
resolves these names inside POA's own frozen interpreter, which has no
sqlite3 and no pty, so dotdiw cannot be imported there at all; each name here
is therefore a thin callable that loads dotdiw the first time it is called,
and conform proves the names and signatures while test_promise.py proves the
bodies behind them.
"""
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "dotdiw")

# IDL operation name -> the function in dotdiw that is its one body.
BINDINGS = {
    "StartNamedWork": "start_named_work",
    "NameTheWork": "name_the_work",
    "MatchFormulas": "match_formulas",
    "PourProcedure": "pour_procedure",
    "WriteAProcedureDown": "write_a_procedure_down",
    "NoticeHandmadeProcedures": "notice_handmade_procedures",
    "NudgeTowardsAFormula": "nudge_towards_a_formula",
    "WriteFormula": "write_formula",
    "DescribeAndCheck": "describe_and_check",
    "CommitFormula": "commit_formula",
    "AdoptARepository": "adopt_a_repository",
    "AdoptRepository": "adopt_repository",
    "DeclareConventions": "declare_conventions",
    "ReportWhatWasLeftUncommitted": "report_what_was_left_uncommitted",
    "UndoEarlierAdoption": "undo_earlier_adoption",
    "TurnMetricsOff": "turn_metrics_off",
    "RunATrackerCommand": "run_a_tracker_command",
    "ForwardToBeads": "forward_to_beads",
    "FindAHeldProcedure": "find_a_held_procedure",
    "IndexTheProject": "index_the_project",
    "ListFormulas": "list_formulas",
    "ShowFormula": "show_formula",
    "ResolveFormula": "resolve_formula",
    "LearnTheConventions": "learn_the_conventions",
    "TeachTheConventions": "teach_the_conventions",
}


def load_dotdiw(path=SCRIPT):
    """dotdiw as a module, loaded by path because it has no .py suffix."""
    if "dotdiw" in sys.modules:
        return sys.modules["dotdiw"]
    loader = importlib.machinery.SourceFileLoader("dotdiw", path)
    spec = importlib.util.spec_from_loader("dotdiw", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dotdiw"] = module
    loader.exec_module(module)
    return module


def _bind(name, body):
    def operation(request):
        return getattr(load_dotdiw(), body)(request)
    operation.__name__ = operation.__qualname__ = name
    operation.__doc__ = "%s: the body is dotdiw.%s." % (name, body)
    operation.body = body
    return operation


for _name, _body in BINDINGS.items():
    globals()[_name] = _bind(_name, _body)
__all__ = sorted(BINDINGS)
