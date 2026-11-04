#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finish the IDL that `poa derive` wrote.

derive rewrites operation-idl.json from scratch every time, from the governed
source model alone. Three things it cannot know go in afterwards, and this is
the one place they go in, so the result is reproducible from the formula and
never edited by hand:

  poa/idl-additions.json   what the model does not carry: the witness contract
                           reference, the observability, report and summary
                           bindings, the update records for this binding, and
                           the record types the responses share
  poa/idl-patches.json     per-operation facts about the program: the real
                           command-line bindings in place of the generated
                           `poa invoke` fictions, the kinds the step-id
                           heuristic got wrong, the calls between operations
                           that the bodies actually make, the beads and git
                           calls that cross the product boundary, and the
                           request and response fields the bodies really use
  this file                drops the generated bindings, applies the two files,
                           rebuilds what must agree with them, the operation
                           call graph and the implementation bindings, and
                           writes two tables into dotdiw between their
                           markers: the door's, for every operation a body
                           answers, the body's name and the fields of its
                           request and response; and the tracker door's, for
                           every operation of the tracker interface, the
                           fields alone, since an adapter answers those

Standard library only, because dotdiw's world is the standard library and the
tests read the result.

    python3 poa/finish-idl.py [operation-idl.json]
"""

import json
import os
import sys
import textwrap
from typing import Any

Idl = dict[str, Any]

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IDL = os.path.join(ROOT, "operation-idl.json")
ADDITIONS = os.path.join(HERE, "idl-additions.json")
PATCHES = os.path.join(HERE, "idl-patches.json")

GENERATED_BINDING = "binding.cli-invoke-"
BINDING_MODULE = "promise_bindings"

DOTDIW = os.path.join(ROOT, "dotdiw")
DOOR_OPEN = "# >>> generated from operation-idl.json by poa/finish-idl.py; do not edit\n"
DOOR_CLOSE = "# <<< end generated\n"
TRACKER_OPEN = (
    "# >>> tracker door generated from operation-idl.json by poa/finish-idl.py; do not edit\n"
)
TRACKER_CLOSE = "# <<< end tracker door\n"
TYPES_OPEN = "# >>> types generated from operation-idl.json by poa/finish-idl.py; do not edit\n"
TYPES_CLOSE = "# <<< end types\n"
SCALARS = {"string": "str", "integer": "int", "boolean": "bool"}

# The operations of the tracker interface: the steps of this journey. An
# adapter answers them, so they have no body and sit in the inner table.
INNER_JOURNEY = "journey.answer-through-the-tracker"

# The id field of each list the additions may extend.
ID_FIELDS = {
    "types": "typeId",
    "updates": "changeId",
    "eventStructureContracts": "contractId",
    "observabilityBindings": "bindingId",
    "reportBindings": "reportId",
    "storySummaryBindings": "summaryId",
    "interfaceBindings": "bindingId",
    "openQuestions": "questionId",
    "projections": "projectionId",
}


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {item[key]: item for item in items}


def merge_list(idl: Idl, key: str, items: list[dict[str, Any]]) -> None:
    """Append, replacing an item that is already there under the same id."""
    field = ID_FIELDS[key]
    have = idl.setdefault(key, [])
    index = {item[field]: i for i, item in enumerate(have)}
    for item in items:
        if item[field] in index:
            have[index[item[field]]] = item
        else:
            index[item[field]] = len(have)
            have.append(item)


def call_kind(operation: dict[str, Any]) -> str:
    # The same rule derive uses, so a call it emitted and a call added here
    # get the same answer.
    sync = (operation.get("timing") or {}).get("syncExpectation")
    return "asynchronous" if sync == "asynchronous" else "synchronous"


def inner_operations(idl: Idl) -> list[dict[str, Any]]:
    """The tracker interface's operations, in the IDL's order."""
    return [
        op
        for op in idl["operations"]
        if any(d.get("sourceKind") == "gwt-step" for d in op.get("derivedFrom") or [])
        and (op.get("tracesTo") or {}).get("journeyIds") == [INNER_JOURNEY]
    ]


def implementation_bindings(idl: Idl, patches: dict[str, Any]) -> list[dict[str, Any]]:
    """One binding per body; per adapter for the tracker interface; and
    not-yet-implemented, pointing at the plan, until a phase lands it."""
    pending = patches.get("notYetImplemented") or {}
    adapters = patches.get("adapters") or []
    inner = {op["operationId"] for op in inner_operations(idl)}
    out = []
    for op in idl["operations"]:
        slug = op["operationId"].split(".", 1)[1]
        called = [c["operationId"] for c in op.get("calls") or []]
        if op["operationId"] in pending:
            out.append(
                {
                    "bindingId": "impl.%s" % slug,
                    "operationId": op["operationId"],
                    "implementationUnit": "%s::%s" % (BINDING_MODULE, op["name"]),
                    "implementationMode": "not-yet-implemented",
                    "privateHelpersUsed": False,
                    "calledOperationIds": called,
                    "notes": "Lands with %s; until then nothing routes to it and the "
                    "binding is a name." % pending[op["operationId"]],
                }
            )
        elif op["operationId"] in inner:
            for adapter in adapters:
                out.append(
                    {
                        "bindingId": "impl.%s-%s" % (adapter, slug),
                        "operationId": op["operationId"],
                        "implementationUnit": "%s::%s%s"
                        % (BINDING_MODULE, adapter.capitalize(), op["name"]),
                        "implementationMode": "external-product-call-only"
                        if adapter == "beads"
                        else "inline-body",
                        "privateHelpersUsed": False,
                        "calledOperationIds": called,
                        "notes": "The %s adapter's callable for this operation, "
                        "dotdiw::TRACKERS[%s][operations][%s], reached only through "
                        "the tracker door, invoke_tracker, by this operation's id; "
                        "promise_bindings.py re-exports it under this name for "
                        "import only, which is how the conformance harness calls "
                        "it." % (adapter, adapter, op["operationId"]),
                    }
                )
        else:
            out.append(
                {
                    "bindingId": "impl.%s" % slug,
                    "operationId": op["operationId"],
                    "implementationUnit": "%s::%s" % (BINDING_MODULE, op["name"]),
                    "implementationMode": "inline-body",
                    "privateHelpersUsed": False,
                    "calledOperationIds": called,
                    "notes": "The body is dotdiw::%s, reached only through the door, "
                    "invoke, by this operation's id; promise_bindings.py "
                    "re-exports it under this name for import only, which is "
                    "how the conformance harness calls it. test_promise.py "
                    "holds the body to the calls declared here and to the "
                    "door." % op["name"],
                }
            )
    return out


def finish(idl: Idl, additions: dict[str, Any], patches: dict[str, Any]) -> Idl:
    idl["interfaceBindings"] = [
        b
        for b in idl.get("interfaceBindings") or []
        if not b["bindingId"].startswith(GENERATED_BINDING)
    ]

    for key, items in additions.items():
        merge_list(idl, key, items)

    ops = by_id(idl["operations"], "operationId")
    for op_id, patch in patches["operations"].items():
        op = ops[op_id]  # an unknown operation is an error, loudly
        for k, v in patch.items():
            if k == "derivedFrom":
                # Once each, so that running this twice gives the same file.
                have = op.setdefault("derivedFrom", [])
                have.extend(item for item in v if item not in have)
            elif k == "tracesTo":
                op["tracesTo"].update(v)
            else:
                op[k] = v

    types = by_id(idl["types"], "typeId")
    for type_id, patch in patches.get("types", {}).items():
        t = types[type_id]
        fields = t.setdefault("fields", [])
        index = {f["name"]: i for i, f in enumerate(fields)}
        for f in patch.get("fields", []):
            if f["name"] in index:
                fields[index[f["name"]]] = f
            else:
                index[f["name"]] = len(fields)
                fields.append(f)

    idl["externalProductDependencies"] = patches["externalProductDependencies"]
    merge_list(idl, "interfaceBindings", patches["interfaceBindings"])
    merge_list(idl, "projections", patches.get("projections", []))

    # What has to agree with the calls above: poa check compares the two.
    idl["operationCallGraph"] = [
        {
            "fromOperationId": op["operationId"],
            "toOperationId": call["operationId"],
            "callKind": call_kind(op),
            "reason": call["callPurpose"],
        }
        for op in idl["operations"]
        for call in op.get("calls") or []
    ]
    idl["implementationBindings"] = implementation_bindings(idl, patches)
    return idl


def names_tuple(key: str, names: list[str]) -> str:
    """One table entry: a tuple of field names, wrapped to the line."""
    if not names:
        return '        "%s": (),\n' % key
    text = ", ".join('"%s"' % n for n in names) + ","
    out = '        "%s": (\n' % key
    for line in textwrap.wrap(text, width=67, break_long_words=False, break_on_hyphens=False):
        out += "            %s\n" % line
    return out + "        ),\n"


def door_source(idl: Idl) -> str:
    """The door's table: what dotdiw holds between the markers.

    Sorted by operation id and field name, so that the same IDL always gives
    the same text and a test can regenerate it and compare.
    """
    types = by_id(idl["types"], "typeId")
    statuses: tuple[str, ...] = ()
    for op in idl["operations"]:
        status = [f for f in types[op["responseType"]]["fields"] if f["name"] == "status"]
        values = tuple(status[0]["valueType"]["values"])
        assert statuses in ((), values), "response types disagree on status"
        statuses = values
    # Only what a body answers: not the tracker interface, and not an
    # operation whose binding is not-yet-implemented, which the door refuses
    # as unknown until its phase lands it.
    inner = {op["operationId"] for op in inner_operations(idl)}
    pending = {
        b["operationId"]
        for b in idl.get("implementationBindings") or []
        if b["implementationMode"] == "not-yet-implemented"
    }
    out = DOOR_OPEN
    out += "STATUSES = (%s)\n\n" % ", ".join('"%s"' % s for s in statuses)
    out += "# operation id -> the body's name, the fields of its request, the required\n"
    out += "# ones among them, and the same for its response.\n"
    out += "DOOR: dict[str, DoorSpec] = {\n"
    for op in sorted(idl["operations"], key=lambda o: o["operationId"]):
        if op["operationId"] in inner or op["operationId"] in pending:
            continue
        req = types[op["requestType"]]["fields"]
        resp = types[op["responseType"]]["fields"]
        out += '    "%s": {\n' % op["operationId"]
        out += '        "body": "%s",\n' % op["name"]
        out += names_tuple("request", sorted(f["name"] for f in req))
        out += names_tuple("requestRequired", sorted(f["name"] for f in req if f["required"]))
        out += names_tuple("response", sorted(f["name"] for f in resp))
        out += names_tuple("responseRequired", sorted(f["name"] for f in resp if f["required"]))
        out += "    },\n"
    out += "}\n"
    return out + DOOR_CLOSE


def tracker_door_source(idl: Idl) -> str:
    """The tracker door's table: the interface's operations and their fields,
    sorted like the door's. No body: an adapter answers each."""
    types = by_id(idl["types"], "typeId")
    out = TRACKER_OPEN
    out += "# operation id -> the fields of its request, the required ones among them,\n"
    out += "# and the same for its response. The registered adapter answers.\n"
    out += "TRACKER_DOOR: dict[str, TrackerDoorSpec] = {\n"
    for op in sorted(inner_operations(idl), key=lambda o: o["operationId"]):
        req = types[op["requestType"]]["fields"]
        resp = types[op["responseType"]]["fields"]
        out += '    "%s": {\n' % op["operationId"]
        out += names_tuple("request", sorted(f["name"] for f in req))
        out += names_tuple("requestRequired", sorted(f["name"] for f in req if f["required"]))
        out += names_tuple("response", sorted(f["name"] for f in resp))
        out += names_tuple("responseRequired", sorted(f["name"] for f in resp if f["required"]))
        out += '        "responseType": %s,\n' % class_name(op["responseType"])
        out += "    },\n"
    out += "}\n"
    return out + TRACKER_CLOSE


def class_name(type_id: str) -> str:
    """type.list-items-response -> ListItemsResponse."""
    return "".join(word.capitalize() for word in type_id.split(".", 1)[1].split("-"))


def literal_source(values: list[str], indent: str, room: int = 90) -> str:
    """Literal[...] over the values, wrapped to the line when they do not fit
    in the room the field's line leaves for them."""
    flat = "Literal[%s]" % ", ".join('"%s"' % v for v in values)
    if len(flat) <= room:
        return flat
    out = "Literal[\n"
    text = ", ".join('"%s"' % v for v in values) + ","
    for line in textwrap.wrap(
        text, width=88 - len(indent), break_long_words=False, break_on_hyphens=False
    ):
        out += "%s    %s\n" % (indent, line)
    return out + indent + "]"


def annotation_source(
    value_type: dict[str, Any], statuses: tuple[str, ...], indent: str, room: int = 90
) -> str:
    """The Python annotation for one IDL value type, given the room its line
    leaves for it."""
    kind = value_type["kind"]
    if kind == "scalar":
        return SCALARS[value_type["scalar"]]
    if kind == "enum-inline":
        values = list(value_type["values"])
        return "Status" if tuple(values) == statuses else literal_source(values, indent, room)
    if kind == "reference":
        return "str"  # an id of the object it names
    if kind == "type-ref":
        return class_name(value_type["typeId"])
    if kind == "list":
        return "list[%s]" % annotation_source(value_type["itemType"], statuses, indent, room - 6)
    if kind == "map":
        return "dict[%s, %s]" % (
            annotation_source(value_type["keyType"], statuses, indent),
            annotation_source(value_type["valueType"], statuses, indent),
        )
    raise ValueError("no annotation for a value of kind %s" % kind)


def types_source(idl: Idl) -> str:
    """The IDL's record types as TypedDicts: what dotdiw holds between the
    types markers. The shared records first, then each operation's request
    and response, in the IDL's order, so that the same IDL always gives the
    same text and a test can regenerate it and compare."""
    types = by_id(idl["types"], "typeId")
    statuses: tuple[str, ...] = ()
    for op in idl["operations"]:
        status = [f for f in types[op["responseType"]]["fields"] if f["name"] == "status"]
        statuses = tuple(status[0]["valueType"]["values"])
    records = [t for t in idl["types"] if t["kind"] == "record"]
    shared = [t for t in records if not t["typeId"].endswith(("-request", "-response"))]
    owned = [t for t in records if t["typeId"].endswith(("-request", "-response"))]
    out = TYPES_OPEN
    out += "# One class per record type of the IDL, the shared records first. A field the\n"
    out += "# IDL requires is Required; the rest may be absent or None, which the doors\n"
    out += "# read alike. An error type is the transport's, not a record a body answers\n"
    out += "# with, and has no class here.\n"
    out += "Status = %s\n" % literal_source(list(statuses), "")
    for t in shared + owned:
        out += "\n\nclass %s(TypedDict, total=False):\n" % class_name(t["typeId"])
        summary = " ".join((t.get("description") or t["name"]).split())
        lines = textwrap.wrap(summary, width=92, break_long_words=False, break_on_hyphens=False)
        if len(lines) == 1:
            out += '    """%s"""\n' % lines[0]
        else:
            out += '    """%s\n' % lines[0]
            for line in lines[1:]:
                out += "    %s\n" % line
            out += '    """\n'
        for f in t["fields"]:
            wrap = "Required[%s]" if f["required"] else "%s | None"
            room = 100 - len("    %s: " % f["name"]) - len(wrap % "")
            inner = annotation_source(f["valueType"], statuses, "    ", room)
            field = wrap % inner
            out += "    %s: %s\n" % (f["name"], field)
    return out + TYPES_CLOSE


def replace_region(text: str, open_marker: str, close_marker: str, body: str, path: str) -> str:
    assert text.count(open_marker) == 1 and text.count(close_marker) == 1, (
        "%s must hold the markers %r exactly once" % (path, open_marker.strip())
    )
    head, rest = text.split(open_marker, 1)
    tail = rest.split(close_marker, 1)[1]
    return head + body + tail


def write_door(idl: Idl, path: str = DOTDIW) -> bool:
    """Put both tables and the types between their markers in dotdiw; True when
    that changed it."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    after = replace_region(text, DOOR_OPEN, DOOR_CLOSE, door_source(idl), path)
    after = replace_region(after, TRACKER_OPEN, TRACKER_CLOSE, tracker_door_source(idl), path)
    after = replace_region(after, TYPES_OPEN, TYPES_CLOSE, types_source(idl), path)
    if after == text:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(after)
    return True


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else IDL
    idl = finish(load(path), load(ADDITIONS), load(PATCHES))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(idl, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(
        "finished %s: %d operations, %d interface bindings, %d call edges"
        % (
            os.path.relpath(path, ROOT),
            len(idl["operations"]),
            len(idl["interfaceBindings"]),
            len(idl["operationCallGraph"]),
        )
    )
    changed = write_door(idl)
    inner = {op["operationId"] for op in inner_operations(idl)}
    pending = {
        b["operationId"]
        for b in idl["implementationBindings"]
        if b["implementationMode"] == "not-yet-implemented"
    }
    print(
        "the doors in %s: %d operations with a body, %d of the tracker, %d not yet, "
        "%d record types, %s"
        % (
            os.path.relpath(DOTDIW, ROOT),
            len(idl["operations"]) - len(inner | pending),
            len(inner),
            len(pending - inner),
            sum(1 for t in idl["types"] if t["kind"] == "record"),
            "rewritten" if changed else "unchanged",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
