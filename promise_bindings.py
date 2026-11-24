#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The implementation bindings of operation-idl.json, resolvable by name.

POA resolves an implementation binding with importlib: `promise_bindings::
NameTheWork` is this module's attribute of that name, and must be a callable
taking one argument called `request`. Every body is in `dotdiw`, under the IDL's
own name, and a name here asks dotdiw's door for the operation that body
answers, as a command does: the door begins the request a body runs in, so a
body called past it has none. The tracker interface's operations are answered
by an adapter in dotdiw's registry, reached through the tracker door; this
module defines nothing but those names.

Two facts shape it. `dotdiw` is a file without a .py suffix, so it is loaded
by path under the module name `dotdiw`. And `poa conform grpc-signatures`
resolves these names inside POA's own frozen interpreter, which has no
sqlite3 and no pty, so dotdiw cannot be imported there at all; each name here
is therefore a thin callable that loads dotdiw the first time it is called,
and conform proves the names and signatures while test_promise.py proves the
bodies behind them.

The callable declarations and their literal journey tags are generated from
the native IDL. They remain explicit so POA can inspect them without executing
the module. Journey markers attach metadata and return the same callable.
"""

import importlib.machinery
import importlib.util
import os
import sys
from collections.abc import Callable
from types import ModuleType
from typing import Any, Protocol, TypeVar, cast

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
    "RecordValues": "operation.record-values",
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
    "RecordValues",
    "ListTrackers",
    "UseTracker",
    "CheckTracker",
    "MigrateWorkspace",
    "ShipATracker",
    "WriteTracker",
    "AnswerThroughAFormulaProvider",
    "RegisterProvider",
    "DescribeProvider",
    "ListProviderFormulas",
    "ShowProviderFormula",
    "RemoveProvider",
    "RecordWhatAStepFound",
    "RecordClaim",
    "ReadRun",
    "CompareWhatWasRead",
)


class Binding(Protocol):
    """One name of the IDL as POA resolves it: a callable of one request that
    says which body in dotdiw it is, or which adapter's callable."""

    __name__: str
    body: str | None
    adapter: str
    __journey_ids__: tuple[str, ...]

    def __call__(self, request: Any) -> Any: ...


JourneyFunction = TypeVar("JourneyFunction", bound=Callable[..., Any])


def journey(journey_id: str) -> Callable[[JourneyFunction], JourneyFunction]:
    """Record source journey metadata while preserving the callable itself."""

    def annotate(function: JourneyFunction) -> JourneyFunction:
        function.__dict__["__journey_ids__"] = (
            *getattr(function, "__journey_ids__", ()),
            journey_id,
        )
        return function

    return annotate


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


# fmt: off
# >>> bindings generated from operation-idl.json by poa/generate-project.py; do not edit


@journey("journey.start-named-work")
def StartNamedWork(request: Any) -> Any:
    return load_dotdiw().invoke("operation.start-named-work", request)


@journey("journey.write-a-procedure-down")
def WriteAProcedureDown(request: Any) -> Any:
    return load_dotdiw().invoke("operation.write-a-procedure-down", request)


@journey("journey.adopt-a-repository")
def AdoptARepository(request: Any) -> Any:
    return load_dotdiw().invoke("operation.adopt-a-repository", request)


@journey("journey.run-a-tracker-command")
def RunATrackerCommand(request: Any) -> Any:
    return load_dotdiw().invoke("operation.run-a-tracker-command", request)


@journey("journey.find-a-held-procedure")
def FindAHeldProcedure(request: Any) -> Any:
    return load_dotdiw().invoke("operation.find-a-held-procedure", request)


@journey("journey.learn-the-conventions")
def LearnTheConventions(request: Any) -> Any:
    return load_dotdiw().invoke("operation.learn-the-conventions", request)


@journey("journey.answer-through-the-tracker")
def AnswerThroughTheTracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.answer-through-the-tracker", request)


@journey("journey.choose-a-tracker")
def ChooseATracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.choose-a-tracker", request)


@journey("journey.move-a-workspace")
def MoveAWorkspace(request: Any) -> Any:
    return load_dotdiw().invoke("operation.move-a-workspace", request)


@journey("journey.ship-a-tracker")
def ShipATracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.ship-a-tracker", request)


@journey("journey.answer-through-a-formula-provider")
def AnswerThroughAFormulaProvider(request: Any) -> Any:
    return load_dotdiw().invoke("operation.answer-through-a-formula-provider", request)


@journey("journey.record-what-a-step-found")
def RecordWhatAStepFound(request: Any) -> Any:
    return load_dotdiw().invoke("operation.record-what-a-step-found", request)


@journey("journey.start-named-work")
def NameTheWork(request: Any) -> Any:
    return load_dotdiw().invoke("operation.name-the-work", request)


@journey("journey.start-named-work")
def MatchFormulas(request: Any) -> Any:
    return load_dotdiw().invoke("operation.match-formulas", request)


@journey("journey.start-named-work")
def PourProcedure(request: Any) -> Any:
    return load_dotdiw().invoke("operation.pour-procedure", request)


@journey("journey.write-a-procedure-down")
def NoticeHandmadeProcedures(request: Any) -> Any:
    return load_dotdiw().invoke("operation.notice-handmade-procedures", request)


@journey("journey.write-a-procedure-down")
def NudgeTowardsAFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.nudge-towards-a-formula", request)


@journey("journey.write-a-procedure-down")
def WriteFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.write-formula", request)


@journey("journey.write-a-procedure-down")
def DescribeAndCheck(request: Any) -> Any:
    return load_dotdiw().invoke("operation.describe-and-check", request)


@journey("journey.write-a-procedure-down")
def CommitFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.commit-formula", request)


@journey("journey.adopt-a-repository")
def AdoptRepository(request: Any) -> Any:
    return load_dotdiw().invoke("operation.adopt-repository", request)


@journey("journey.adopt-a-repository")
def DeclareConventions(request: Any) -> Any:
    return load_dotdiw().invoke("operation.declare-conventions", request)


@journey("journey.adopt-a-repository")
def ReportWhatIsYoursToCommit(request: Any) -> Any:
    return load_dotdiw().invoke("operation.report-what-is-yours-to-commit", request)


@journey("journey.adopt-a-repository")
def UndoEarlierAdoption(request: Any) -> Any:
    return load_dotdiw().invoke("operation.undo-earlier-adoption", request)


@journey("journey.adopt-a-repository")
def TurnMetricsOff(request: Any) -> Any:
    return load_dotdiw().invoke("operation.turn-metrics-off", request)


@journey("journey.run-a-tracker-command")
def ForwardToTheTracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.forward-to-the-tracker", request)


@journey("journey.run-a-tracker-command")
def CompareWhatWasRead(request: Any) -> Any:
    return load_dotdiw().invoke("operation.compare-what-was-read", request)


@journey("journey.find-a-held-procedure")
def IndexTheProject(request: Any) -> Any:
    return load_dotdiw().invoke("operation.index-the-project", request)


@journey("journey.find-a-held-procedure")
def ListFormulas(request: Any) -> Any:
    return load_dotdiw().invoke("operation.list-formulas", request)


@journey("journey.find-a-held-procedure")
def ShowFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.show-formula", request)


@journey("journey.find-a-held-procedure")
def ResolveFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.resolve-formula", request)


@journey("journey.learn-the-conventions")
def TeachTheConventions(request: Any) -> Any:
    return load_dotdiw().invoke("operation.teach-the-conventions", request)


@journey("journey.answer-through-the-tracker")
def OpenTracker(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.open-tracker", request)


@journey("journey.answer-through-the-tracker")
def BeadsOpenTracker(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.open-tracker", request)


@journey("journey.answer-through-the-tracker")
def LocalOpenTracker(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.open-tracker", request)


@journey("journey.answer-through-the-tracker")
def DescribeTracker(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.describe-tracker", request)


@journey("journey.answer-through-the-tracker")
def BeadsDescribeTracker(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.describe-tracker", request)


@journey("journey.answer-through-the-tracker")
def LocalDescribeTracker(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.describe-tracker", request)


@journey("journey.answer-through-the-tracker")
def CreateItem(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.create-item", request)


@journey("journey.answer-through-the-tracker")
def BeadsCreateItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.create-item", request)


@journey("journey.answer-through-the-tracker")
def LocalCreateItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.create-item", request)


@journey("journey.answer-through-the-tracker")
def AddNeed(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.add-need", request)


@journey("journey.answer-through-the-tracker")
def BeadsAddNeed(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.add-need", request)


@journey("journey.answer-through-the-tracker")
def LocalAddNeed(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.add-need", request)


@journey("journey.answer-through-the-tracker")
def PourSteps(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.pour-steps", request)


@journey("journey.answer-through-the-tracker")
def BeadsPourSteps(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.pour-steps", request)


@journey("journey.answer-through-the-tracker")
def LocalPourSteps(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.pour-steps", request)


@journey("journey.answer-through-the-tracker")
def CloseItem(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.close-item", request)


@journey("journey.answer-through-the-tracker")
def BeadsCloseItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.close-item", request)


@journey("journey.answer-through-the-tracker")
def LocalCloseItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.close-item", request)


@journey("journey.answer-through-the-tracker")
def ShowItem(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.show-item", request)


@journey("journey.answer-through-the-tracker")
def BeadsShowItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.show-item", request)


@journey("journey.answer-through-the-tracker")
def LocalShowItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.show-item", request)


@journey("journey.answer-through-the-tracker")
def ListItems(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.list-items", request)


@journey("journey.answer-through-the-tracker")
def BeadsListItems(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.list-items", request)


@journey("journey.answer-through-the-tracker")
def LocalListItems(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.list-items", request)


@journey("journey.answer-through-the-tracker")
def UpdateItem(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.update-item", request)


@journey("journey.answer-through-the-tracker")
def BeadsUpdateItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.update-item", request)


@journey("journey.answer-through-the-tracker")
def LocalUpdateItem(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.update-item", request)


@journey("journey.answer-through-the-tracker")
def ReadyItems(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.ready-items", request)


@journey("journey.answer-through-the-tracker")
def BeadsReadyItems(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.ready-items", request)


@journey("journey.answer-through-the-tracker")
def LocalReadyItems(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.ready-items", request)


@journey("journey.answer-through-the-tracker")
def RecordValues(request: Any) -> Any:
    return load_dotdiw().invoke_tracker("operation.record-values", request)


@journey("journey.answer-through-the-tracker")
def BeadsRecordValues(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("beads", "operation.record-values", request)


@journey("journey.answer-through-the-tracker")
def LocalRecordValues(request: Any) -> Any:
    return load_dotdiw().invoke_adapter("local", "operation.record-values", request)


@journey("journey.choose-a-tracker")
def ListTrackers(request: Any) -> Any:
    return load_dotdiw().invoke("operation.list-trackers", request)


@journey("journey.choose-a-tracker")
def UseTracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.use-tracker", request)


@journey("journey.choose-a-tracker")
def CheckTracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.check-tracker", request)


@journey("journey.move-a-workspace")
def MigrateWorkspace(request: Any) -> Any:
    return load_dotdiw().invoke("operation.migrate-workspace", request)


@journey("journey.ship-a-tracker")
def WriteTracker(request: Any) -> Any:
    return load_dotdiw().invoke("operation.write-tracker", request)


@journey("journey.answer-through-a-formula-provider")
def RegisterProvider(request: Any) -> Any:
    return load_dotdiw().invoke("operation.register-provider", request)


@journey("journey.answer-through-a-formula-provider")
def DescribeProvider(request: Any) -> Any:
    return load_dotdiw().invoke("operation.describe-provider", request)


@journey("journey.answer-through-a-formula-provider")
def ListProviderFormulas(request: Any) -> Any:
    return load_dotdiw().invoke("operation.list-provider-formulas", request)


@journey("journey.answer-through-a-formula-provider")
def ShowProviderFormula(request: Any) -> Any:
    return load_dotdiw().invoke("operation.show-provider-formula", request)


@journey("journey.answer-through-a-formula-provider")
def RemoveProvider(request: Any) -> Any:
    return load_dotdiw().invoke("operation.remove-provider", request)


@journey("journey.record-what-a-step-found")
def RecordClaim(request: Any) -> Any:
    return load_dotdiw().invoke("operation.record-claim", request)


@journey("journey.record-what-a-step-found")
def ReadRun(request: Any) -> Any:
    return load_dotdiw().invoke("operation.read-run", request)
# <<< end bindings
# fmt: on


for _name in BINDINGS:
    _bound = cast(Binding, globals()[_name])
    _bound.body = None if _name in INTERFACE else _name
    if _name in INTERFACE:
        for _adapter in ADAPTERS:
            _bound = cast(Binding, globals()[_adapter.capitalize() + _name])
            _bound.body = None
            _bound.adapter = _adapter
__all__ = sorted(BINDINGS) + sorted(a.capitalize() + n for a in ADAPTERS for n in INTERFACE)
