#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The implementation bindings of operation-idl.json, resolvable by name.

POA resolves an implementation binding with importlib: `promise_bindings::
NameTheWork` is this module's attribute of that name, and must be a callable
taking one argument called `request`. Every body is in `dotdiw`, under the IDL's
own name; the tracker interface's operations are answered by an adapter in
dotdiw's registry, reached through the tracker door; this module defines
nothing but those names.

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
from types import ModuleType
from typing import Any, Protocol, cast

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "dotdiw")

# The operations of the tracker interface: no body of their own, an adapter
# answers each through the tracker door. Here each name is that operation
# through the door, invoke_tracker, the adapter resolved from the request;
# and per shipped adapter, <Adapter><Name> is the adapter's own callable in
# dotdiw's registry, which the IDL's per-adapter implementation bindings
# resolve to.
INTERFACE = {
    "OpenTracker": "operation.open-tracker",
    "DescribeTracker": "operation.describe-tracker",
    "CreateItem": "operation.create-item",
    "AddNeed": "operation.add-need",
    "PourSteps": "operation.pour-steps",
    "CloseItem": "operation.close-item",
    "ShowItem": "operation.show-item",
    "ListItems": "operation.list-items",
    "UpdateItem": "operation.update-item",
    "ReadyItems": "operation.ready-items",
}
ADAPTERS = ("beads", "local")

# The IDL's operation names; each is the body of that name in dotdiw, an
# operation of the tracker interface through the tracker door, or, while its
# binding is not-yet-implemented, a name with no body behind it yet.
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
    "AnswerThroughTheTracker",
    "ChooseATracker",
    "MoveAWorkspace",
    "OpenTracker",
    "DescribeTracker",
    "CreateItem",
    "AddNeed",
    "PourSteps",
    "CloseItem",
    "ShowItem",
    "ListItems",
    "UpdateItem",
    "ReadyItems",
    "ListTrackers",
    "UseTracker",
    "CheckTracker",
    "MigrateWorkspace",
)


class Binding(Protocol):
    """One name of the IDL as POA resolves it: a callable of one request that
    says which body in dotdiw it is, or which adapter's callable."""

    __name__: str
    body: str | None
    adapter: str

    def __call__(self, request: Any) -> Any: ...


def load_dotdiw(path: str = SCRIPT) -> ModuleType:
    """dotdiw as a module, loaded by path because it has no .py suffix."""
    if "dotdiw" in sys.modules:
        return sys.modules["dotdiw"]
    loader = importlib.machinery.SourceFileLoader("dotdiw", path)
    spec = importlib.util.spec_from_loader("dotdiw", loader)
    if spec is None:
        raise ImportError("%s cannot be loaded as dotdiw" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["dotdiw"] = module
    loader.exec_module(module)
    return module


def _bind(name: str) -> Binding:
    def operation(request: Any) -> Any:
        return getattr(load_dotdiw(), name)(request)

    operation.__name__ = operation.__qualname__ = name
    operation.__doc__ = "%s: the body of that name in dotdiw." % name
    bound = cast(Binding, operation)
    bound.body = name
    return bound


def _bind_interface(name: str, operation_id: str) -> Binding:
    def operation(request: Any) -> Any:
        return load_dotdiw().invoke_tracker(operation_id, request)

    operation.__name__ = operation.__qualname__ = name
    operation.__doc__ = "%s: %s through the tracker door." % (name, operation_id)
    bound = cast(Binding, operation)
    bound.body = None
    return bound


def _bind_adapter(adapter: str, name: str, operation_id: str) -> Binding:
    def operation(request: Any) -> Any:
        return load_dotdiw().TRACKERS[adapter]["operations"][operation_id](request)

    operation.__name__ = operation.__qualname__ = adapter.capitalize() + name
    operation.__doc__ = "%s: the %s adapter's callable for %s." % (
        operation.__name__,
        adapter,
        operation_id,
    )
    bound = cast(Binding, operation)
    bound.body = None
    bound.adapter = adapter
    return bound


for _name in BINDINGS:
    if _name in INTERFACE:
        globals()[_name] = _bind_interface(_name, INTERFACE[_name])
        for _adapter in ADAPTERS:
            _bound = _bind_adapter(_adapter, _name, INTERFACE[_name])
            globals()[_bound.__name__] = _bound
    else:
        globals()[_name] = _bind(_name)
__all__ = sorted(BINDINGS) + sorted(a.capitalize() + n for a in ADAPTERS for n in INTERFACE)
