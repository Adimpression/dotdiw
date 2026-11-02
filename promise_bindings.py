#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The implementation bindings of operation-idl.json, resolvable by name.

POA resolves an implementation binding with importlib: `promise_bindings::
NameTheWork` is this module's attribute of that name, and must be a callable
taking one argument called `request`. Every body is in `dotdiw`, under the IDL's
own name; this module defines nothing but the list of those names.

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

# The IDL's operation names; each is the body of that name in dotdiw.
BINDINGS = (
    "StartNamedWork",
    "WriteAProcedureDown",
    "AdoptARepository",
    "RunATrackerCommand",
    "FindAHeldProcedure",
    "LearnTheConventions",
    "NameTheWork",
    "MatchFormulas",
    "PourProcedure",
    "NoticeHandmadeProcedures",
    "NudgeTowardsAFormula",
    "WriteFormula",
    "DescribeAndCheck",
    "CommitFormula",
    "AdoptRepository",
    "DeclareConventions",
    "ReportWhatIsYoursToCommit",
    "UndoEarlierAdoption",
    "TurnMetricsOff",
    "ForwardToTheTracker",
    "IndexTheProject",
    "ListFormulas",
    "ShowFormula",
    "ResolveFormula",
    "TeachTheConventions",
)


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


def _bind(name):
    def operation(request):
        return getattr(load_dotdiw(), name)(request)
    operation.__name__ = operation.__qualname__ = name
    operation.__doc__ = "%s: the body of that name in dotdiw." % name
    operation.body = name
    return operation


for _name in BINDINGS:
    globals()[_name] = _bind(_name)
__all__ = sorted(BINDINGS)
