# trackers

The adapters that are not inside dotdiw. `jira.py` is a worked example, an
adapter for a tracker hosted elsewhere, tested against a stub of its API. An
adapter of your own is written the same way, and this file says how to write it
and how to ship it.
`write-tracker-adapter.formula.toml` beside it holds the same steps, so
`dotdiw create "Write a tracker adapter for <name>"` surfaces them and
`dotdiw mol pour mol-write-tracker-adapter` tracks them.

## What an adapter is

One Python file, `<name>.py`, exposing one table, `TRACKER`. The name uses
lowercase letters, digits and hyphens and starts with a letter. dotdiw looks for
the file in `~/.dotdiw/trackers/`, then in `share/dotdiw/trackers/` beside the
`bin/` it runs from. It loads the file when `--tracker`, `DOTDIW_TRACKER`, a
checkout's choice or `dotdiw tracker use` names it, and `dotdiw tracker list`
loads every one it finds.
Before the module runs, two names are set on it: `dotdiw_workspace`, a
callable of one root that returns the directory under `~/.dotdiw/` keyed to
that checkout, where a store belongs; and `dotdiw_version`. The module
imports nothing from dotdiw, and dotdiw reads nothing from it but the table.

## The steps

**1. Start from the file dotdiw writes.** `dotdiw tracker new <name>` writes
`<name>.py` in the current directory, or in the one given with `--at`. It holds
the ten operations, each raising until you fill it, each docstring saying what
it takes and answers, and the table at the end. Keep that shape: one function
per operation, the table at the end, nothing printed anywhere. `jira.py` is a
whole adapter to read beside it.

**2. Fill the table.**

    TRACKER = {
        "info": {"name": "<name>", "version": "0.1.0", "interface": 1,
                 "nativeNeeds": True, "checkTarget": "scratch", "extras": []},
        "operations": {
            "operation.open-tracker": open_tracker,
            "operation.describe-tracker": describe_tracker,
            "operation.create-item": create_item,
            "operation.add-need": add_need,
            "operation.pour-steps": pour_steps,
            "operation.close-item": close_item,
            "operation.show-item": show_item,
            "operation.list-items": list_items,
            "operation.update-item": update_item,
            "operation.ready-items": ready_items,
        },
        "extras": {},
    }

`info` needs `name` and `version`; `origin` is set to `loaded` and `source` to
the file's path when the module is loaded. `interface` is the number of the
tracker interface the module was written for; without it dotdiw reads 1.
`nativeNeeds` says whether the tracker holds needs itself or the adapter keeps
them in a store of its own.
`checkTarget` is where `dotdiw tracker check` may create and close items:
`scratch` when the adapter can open a store in a throwaway workspace,
otherwise the one project or board the check may fill; without one the check
refuses to run. `extras` names what the adapter offers beyond the interface;
a simple adapter offers nothing.

`operations` holds the ten operations of the interface by their ids, and
nothing else, each a callable of exactly one parameter named `request`.
`extras` holds callables of one `request` by name for what the interface does
not cover: `beads` offers `forward` and `metrics-off`; without `forward`,
`dotdiw --help` prints the conventions and any command dotdiw does not own is
refused by name. `store`, a key you may add to the table, is a callable of one
`root` returning the path of the adapter's store under that checkout's
workspace; a checkout adopted before a choice was written is answered by the one
adapter holding a store there. An adapter may keep nothing under the workspace:
a checkout that chose it counts as adopted.

Registration refuses a table that lacks an operation, offers one outside the
ten, whose callables take anything but `request`, whose info lacks a name or a
version, or whose interface is one this dotdiw does not support.

**3. Answer in records.** Each operation takes one dict and returns one. The
door holds both to the types in `operation-idl.json` and raises on a field
outside them, so the fields are those and nothing more; `tracker` on the
response is the door's to stamp. It holds values too, down through records and
lists: a field holding the wrong kind of value, a value outside its enum, or a
completed answer without the record its operation returns is refused the same
way as a missing field. The module imports nothing from dotdiw, so
it cannot share the record classes dotdiw is typed by; `jira.py` annotates
its functions with plain `dict[str, Any]` records and is type-checked that
way, and an adapter of your own may do the same. Every response has `status`,
completed, blocked or failed, and a `summary`. A blocked or failed one may carry a
`reason` from the list the IDL gives that operation. `exitCode` may be left out,
and is then read from the status; one that contradicts it is refused. An item is a
record:
`id`, `title`, `status` of open, in_progress, blocked or closed, `kind` with
task when unsaid, `priority` with 0 the highest and 2 when unsaid, `parent`,
`reason` once closed, `needs`, `createdAt` and `updatedAt`. An edge is
`{"id": ..., "needs": ...}`.

What each operation must answer. The check tests most of this, and not all of
it:

- `open-tracker`, given `prefix`: the first open makes the store and answers
  `created` true with its `path`; a second changes nothing, `created` false.
- `describe-tracker`: `info` with name, version and origin, and `path` once
  the store is open.
- `create-item`, given `title`, `kind`, `priority`, `parent`, `description`
  and sometimes an `id`, which migrate asks for: honour the id, or give your
  own, and the id in the record is what counts. The record comes back with
  status open; a child carries its parent; an unknown parent is
  `parent-not-found`.
- `add-need`, given `id` and `needs`: the `edge` comes back; an unknown item
  is `item-not-found`; a cycle is `cycle`; a need already there answers
  completed, since a move that was interrupted asks for it again.
- `show-item`: the `item` with its `needs`, and its `children` as records;
  unknown is `item-not-found`.
- `list-items`, given `scope` of all or open, open when unsaid, `parent` for
  one parent's children, and `limit`: `items`.
- `ready-items`: the open items with no open need, as `items`.
- `close-item`, given `closeReason`: refused as blocked with `blockedBy`
  naming the open needs or the open children; completed names `closedIds`,
  and the record keeps its reason. A close the tracker did not make is a
  failure, not a completion. Closing the last step of a poured root may
  close the root too, named in `closedIds`, or leave it to a close of its
  own; either passes.
- `update-item`, given `title`, `status`, `priority`, `parent` or
  `assignee`: the record comes back; a status of closed is refused as
  `close-through-update`, since closing is close-item's, and a status the
  tracker cannot reach is `bad-status`.
- `pour-steps`, given `formulaRef`, `title` and `steps`, each `id`, `title`
  and `needs` naming step ids anywhere in the list: a root of kind molecule or
  epic with the steps as its children and the needs as edges between the new ids;
  `rootId` and `stepIds` in the given order. An empty list is `no-steps`, a
  need naming no step `step-not-found`, a cycle among the steps `cycle`, and
  each of those writes nothing.

Three rules are the adapter's, since the door decides none of them: a close
is refused while an open need or an open child exists; a poured root closes
once its steps have; an id asked for is honoured, or the record says which
id was given. `terminal` on open, create and pour is for an adapter that runs
a tracker's own command with the worker's terminal and answers `printed`
true; an adapter that answers in records leaves it alone, and the presenter
shows the record.

A mistake in the adapter is said in one line and never as a traceback: an
operation or extra that raises or exits, or an answer outside its type, is
refused naming the adapter, the operation and the error; a module that raises or
exits on load, or whose table is out of shape, is listed by `dotdiw tracker list`
as not loaded and refused in one line with the reason when the name is used. A
file with no `TRACKER` table is not an adapter, and is not listed.

**4. Keep credentials out.** Read them from the environment or from a file
under `~/.dotdiw/trackers/`, never from a repository; put none in a response
and print nothing. `jira.py` reads `JIRA_SITE`, `JIRA_EMAIL` and
`JIRA_API_TOKEN`, or `~/.dotdiw/trackers/jira.json` holding the same three.

**5. Prove it.** `dotdiw tracker check ./<name>.py` runs the scenario above on
the file where it sits, one result per operation, without installing it and with
nothing written beside it. The scenario fills the check target: under `scratch`,
a workspace made for the run and removed afterwards, never live work. Fix each
failing operation until ten of ten pass. Once the file is installed,
`dotdiw tracker list` shows its path and `dotdiw tracker check <name>` runs the
same scenario. A tracker over a network is checked against a stub of its API, as
`../test_jira.py` does for Jira, or against the one project or board it declares
for the check.

**6. Choose it.** `dotdiw init --tracker <name>` on a fresh checkout, `dotdiw
tracker use <name>` on an adopted one, and `dotdiw tracker migrate <from>
<name>` to move the work there; then a day of create, pour, ready and close
through it.

## Shipping it

A tracker ships as a package.

- **The name.** The package is named `dotdiw-tracker-<name>`, and so is its
  repository if it has its own. dotdiw never reads that name. It is there so
  people can find the tracker.
- **The file.** One file, `<name>.py`, that imports only the standard library,
  because it runs in dotdiw's own interpreter. A tracker written in another
  language ships a small module that calls its binary with JSON.
- **The place.** A package installs the file under `share/dotdiw/trackers/`.
  dotdiw checks its built-in adapters first, then `~/.dotdiw/trackers/`, then
  `share/`, so a copy in your home directory overrides a package's while you try
  a change. Copying the file to `~/.dotdiw/trackers/` works with no package at
  all.
- **The proof.** Compatible means `dotdiw tracker check` passes ten of ten.
  There is no central list of trackers to join. Run the check by path in your
  CI.
- **The interface.** `info.interface` in the table holds the number of the
  interface the file was written for. When dotdiw raises that number, it refuses
  a file written for the old one, in one line that names it, and the author ships
  a new version.
- **Trust.** An installed tracker's code runs with your rights whenever dotdiw
  loads it, and `dotdiw tracker list` loads every file it finds. A repository
  cannot make dotdiw run its code: dotdiw loads a file from one only when you
  pass its path to `dotdiw tracker check`, and the choice of tracker lives in
  `.git/config`, which is not committed.

A Homebrew formula, in a tap of your own:

    class DotdiwTrackerAcme < Formula
      desc "Acme tracker for dotdiw"
      homepage "https://example.invalid/dotdiw-tracker-acme"
      url "https://example.invalid/dotdiw-tracker-acme/archive/refs/tags/v0.1.0.tar.gz"
      sha256 "<the sha256 of that tarball>"
      license "Apache-2.0"

      depends_on "adimpression/tap/dotdiw"

      def install
        (share/"dotdiw/trackers").install "acme.py"
      end

      test do
        assert_match "acme passed", shell_output("dotdiw tracker check acme")
      end
    end

The package depends on dotdiw and never the other way, since Homebrew refuses a
cycle. A tracker over a network cannot reach its service under `brew test`, so
its test block runs `dotdiw tracker list`, looks for its name and for no
`did not load`, and its check runs in CI against a stub.

Jira is a registered trademark of Atlassian Pty Ltd.
