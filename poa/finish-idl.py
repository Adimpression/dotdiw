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
                           writes the door's table into dotdiw between its
                           markers: for every operation, the body's name and
                           the fields of its request and response

Standard library only, because dotdiw's world is the standard library and the
tests read the result.

    python3 poa/finish-idl.py [operation-idl.json]
"""
import json
import os
import sys
import textwrap

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


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def by_id(items, key):
    return {item[key]: item for item in items}


def merge_list(idl, key, items):
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


def call_kind(operation):
    # The same rule derive uses, so a call it emitted and a call added here
    # get the same answer.
    sync = (operation.get("timing") or {}).get("syncExpectation")
    return "asynchronous" if sync == "asynchronous" else "synchronous"


def finish(idl, additions, patches):
    idl["interfaceBindings"] = [
        b for b in idl.get("interfaceBindings") or []
        if not b["bindingId"].startswith(GENERATED_BINDING)]

    for key, items in additions.items():
        merge_list(idl, key, items)

    ops = by_id(idl["operations"], "operationId")
    for op_id, patch in patches["operations"].items():
        op = ops[op_id]            # an unknown operation is an error, loudly
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
        {"fromOperationId": op["operationId"], "toOperationId": call["operationId"],
         "callKind": call_kind(op), "reason": call["callPurpose"]}
        for op in idl["operations"] for call in op.get("calls") or []]
    idl["implementationBindings"] = [
        {"bindingId": "impl.%s" % op["operationId"].split(".", 1)[1],
         "operationId": op["operationId"],
         "implementationUnit": "%s::%s" % (BINDING_MODULE, op["name"]),
         "implementationMode": "inline-body",
         "privateHelpersUsed": False,
         "calledOperationIds": [c["operationId"] for c in op.get("calls") or []],
         "notes": "The body is dotdiw::%s, reached only through the door, "
                  "invoke, by this operation's id; promise_bindings.py "
                  "re-exports it under this name for import only, which is "
                  "how the conformance harness calls it. test_promise.py "
                  "holds the body to the calls declared here and to the "
                  "door." % op["name"]}
        for op in idl["operations"]]
    return idl


def names_tuple(key, names):
    """One table entry: a tuple of field names, wrapped to the line."""
    if not names:
        return '        "%s": (),\n' % key
    text = ", ".join('"%s"' % n for n in names) + ","
    out = '        "%s": (\n' % key
    for line in textwrap.wrap(text, width=67, break_long_words=False,
                              break_on_hyphens=False):
        out += "            %s\n" % line
    return out + "        ),\n"


def door_source(idl):
    """The door's table: what dotdiw holds between the markers.

    Sorted by operation id and field name, so that the same IDL always gives
    the same text and a test can regenerate it and compare.
    """
    types = by_id(idl["types"], "typeId")
    statuses = None
    for op in idl["operations"]:
        status = [f for f in types[op["responseType"]]["fields"] if f["name"] == "status"]
        values = tuple(status[0]["valueType"]["values"])
        assert statuses in (None, values), "response types disagree on status"
        statuses = values
    out = DOOR_OPEN
    out += "STATUSES = (%s)\n\n" % ", ".join('"%s"' % s for s in statuses)
    out += "# operation id -> the body's name, the fields of its request, the required\n"
    out += "# ones among them, and the same for its response.\n"
    out += "DOOR = {\n"
    for op in sorted(idl["operations"], key=lambda o: o["operationId"]):
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


def write_door(idl, path=DOTDIW):
    """Put the table between the markers in dotdiw; True when that changed it."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.count(DOOR_OPEN) == 1 and text.count(DOOR_CLOSE) == 1, \
        "%s must hold the door's markers exactly once" % path
    head, rest = text.split(DOOR_OPEN, 1)
    tail = rest.split(DOOR_CLOSE, 1)[1]
    after = head + door_source(idl) + tail
    if after == text:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(after)
    return True


def main(argv):
    path = argv[1] if len(argv) > 1 else IDL
    idl = finish(load(path), load(ADDITIONS), load(PATCHES))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(idl, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("finished %s: %d operations, %d interface bindings, %d call edges"
          % (os.path.relpath(path, ROOT), len(idl["operations"]),
             len(idl["interfaceBindings"]), len(idl["operationCallGraph"])))
    changed = write_door(idl)
    print("the door in %s: %d operations, %s"
          % (os.path.relpath(DOTDIW, ROOT), len(idl["operations"]),
             "rewritten" if changed else "unchanged"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
