#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finish the IDL that `poa derive` wrote.

derive rewrites operation-idl.json from scratch every time, from the governed
source model alone. Three things it cannot know go in afterwards, and this is
the one place they go in, so the result is reproducible from the formula and
never edited by hand:

  poa/idl-additions.json   what the model does not carry: the witness contract
                           reference, the observability, report and summary
                           bindings, and the update records for this binding
  poa/idl-patches.json     per-operation facts about the program: the real
                           command-line bindings in place of the generated
                           `poa invoke` fictions, the kinds the step-id
                           heuristic got wrong, the calls between operations
                           that the bodies actually make, the beads and git
                           calls that cross the product boundary, and the
                           request and response fields the bodies really use
  this file                drops the generated bindings, applies the two files,
                           and rebuilds what must agree with them: the
                           operation call graph and the implementation bindings

Standard library only, because dotdiw's world is the standard library and the
tests read the result.

    python3 poa/finish-idl.py [operation-idl.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IDL = os.path.join(ROOT, "operation-idl.json")
ADDITIONS = os.path.join(HERE, "idl-additions.json")
PATCHES = os.path.join(HERE, "idl-patches.json")

GENERATED_BINDING = "binding.cli-invoke-"
BINDING_MODULE = "promise_bindings"

# The id field of each list the additions may extend.
ID_FIELDS = {
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
                op.setdefault("derivedFrom", []).extend(v)
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
         "notes": "One inline body in dotdiw, re-exported under this name by "
                  "promise_bindings.py; test_promise.py holds the body to the "
                  "calls declared here."}
        for op in idl["operations"]]
    return idl


def main(argv):
    path = argv[1] if len(argv) > 1 else IDL
    idl = finish(load(path), load(ADDITIONS), load(PATCHES))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(idl, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("finished %s: %d operations, %d interface bindings, %d call edges"
          % (os.path.relpath(path, ROOT), len(idl["operations"]),
             len(idl["interfaceBindings"]), len(idl["operationCallGraph"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
