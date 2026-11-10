# trackers

The adapters that are not inside dotdiw. `jira.py` is a worked example, an
adapter for a tracker hosted elsewhere, tested against a stub of its API. An
adapter of your own is written the same way, and this file says how to write it
and how to ship it.
`write-tracker-adapter.formula.toml` beside it holds the same steps, so
`dotdiw create "Write a tracker adapter for <name>"` surfaces them and
`dotdiw formula pour mol-write-tracker-adapter` tracks them.

## What an adapter is

One Python file, `<name>.py`, exposing one table, `TRACKER`. The name uses
lowercase letters, digits and hyphens and starts with a letter.
Before the module runs, two names are set on it: `dotdiw_workspace`, a
callable of one root that returns the directory under `~/.dotdiw/` keyed to
that checkout, where a store belongs; and `dotdiw_version`. The module
imports nothing from dotdiw, and dotdiw reads nothing from it but the table.

## How dotdiw holds a tracker

**Registered, three ways.** Every one declares interface 3.

- In the home: `~/.dotdiw/trackers/<name>.py`, looked in first.
- From a package: `share/dotdiw/trackers/<name>.py` beside the `bin/` dotdiw
  runs from, where a `dotdiw-tracker-<name>` package installs it.
- By path, with `dotdiw tracker check ./<name>.py`: loaded for that check
  alone, and registered nowhere afterwards.

dotdiw loads the file when a request names it, and `dotdiw tracker list` loads
every one it finds.

**Chosen, by the first of four.** `--tracker <name>` on the command;
`DOTDIW_TRACKER`; the checkout's `dotdiw.tracker` in `.git/config`, which
`init --tracker` and `tracker use` write; the one adapter holding a store in
the checkout's workspace.

**Answering, in records.** One dict in and one out, for every operation: no
file, no words the worker typed and no terminal reach an adapter, and dotdiw
prints every answer from its record. Extras, by name, cover what the interface
does not.

**Where the work lives, three ways.**

- In a store under the checkout's workspace, the directory `dotdiw_workspace`
  returns: keyed to one checkout, shared by its worktrees, and nobody else's.
  No two people write the same item.
- In a hosted tracker, shared by everyone who reaches it, as `jira.py`'s is.
  `actor` says whose name the work goes under. dotdiw sends each change as it
  is asked and holds no claim on an item: nothing in the interface refuses an
  item someone else holds, and the tracker settles writes that cross.
- Split: a hosted tracker with `nativeNeeds` false, whose adapter keeps the
  needs in its store under the workspace. The items are everyone's, and each
  checkout's needs are its own.

The table does not say which of the three an adapter is.

## The steps

**1. Start from the file dotdiw writes.** `dotdiw tracker new <name>` writes
`<name>.py` in the current directory, or in the one given with `--at`. It holds
the ten operations, each raising until you fill it, each docstring saying what
it takes and answers, and the table at the end. Keep that shape: one function
per operation, the table at the end, nothing printed anywhere. `jira.py` is a
whole adapter to read beside it.

**2. Fill the table.**

    TRACKER = {
        "info": {"name": "<name>", "version": "0.1.0", "interface": 3,
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
tracker interface the module was written for, 3 for this dotdiw; without it
dotdiw reads 1, and a module written for 1 or 2 is refused in one line that names
it.
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
not cover. dotdiw calls three by name: `forward`, with every command it does
not own; `metrics-off`, the first time a run reaches the adapter, before
anything else is asked of it; and `upgrade`, for an adapter whose store an
earlier version of it kept another way. Every command but init, learn and
`--version` asks `upgrade` with no `apply`, and it answers `pending`, one line
for each thing left to bring up to date; init asks with `apply` true, and it
answers `done`, one line for each thing it brought up to date, or fails, which
stops init; asked again, it takes up where it stopped and leaves what it already
brought up to date as it is. Without `forward`, `dotdiw --help` prints the
conventions and any command dotdiw does not own is refused by name. `store`, a
key you may add to the table, is a callable of one `root` returning the path of
the adapter's store under that checkout's workspace; a checkout adopted before a
choice was written is answered by the one adapter holding a store there. An
adapter may keep nothing under the workspace: a checkout that chose it counts as
adopted.

Registration refuses a table that lacks an operation, offers one outside the
ten, whose callables take anything but `request`, whose info lacks a name or a
version, or whose interface is one this dotdiw does not support.

**3. Answer in records.** Each operation takes one dict and returns one. The
door holds both to the types in `operation-idl.json` and raises on a field
outside them, so the fields are those and nothing more; `tracker` on the
response is the door's to stamp. It holds values too, down through records and
lists: a field holding a value of the wrong type, a value outside its enum, or a
completed answer without the record its operation returns is refused the same
way as a missing field. The module imports nothing from dotdiw, so
it cannot share the record classes dotdiw is typed by; `jira.py` annotates
its functions with plain `dict[str, Any]` records and is type-checked that
way, and an adapter of your own may do the same. Every response has `status`,
completed, blocked or failed, and a `summary`. A blocked or failed one may carry a
`reason` from the list the IDL gives that operation. `exitCode` may be left out,
and is then read from the status; one that contradicts it is refused. An item is a
record:
`id`, `title`, `status` of open, in_progress, blocked or closed, `kind` of root
for the root a pour made and task for every other item, whatever the tracker
calls it, with task when unsaid, `priority` with 0 the highest and 2 when
unsaid, `parent`, `assignee` once someone is assigned, as the tracker shows
them, `reason` once closed, `needs`, `description` exactly as given,
`verifyUsing`, the means to prove a run that a poured root or a moved item
carries, `createdAt` and `updatedAt`. An edge is `{"id": ..., "needs": ...}`.

What each operation must answer. The check tests most of this, and not all of
it:

- `open-tracker`, given `prefix`: the first open makes the store and answers
  `created` true with its `path`; a second changes nothing, `created` false.
- `describe-tracker`: `info` with name, version and origin, and `path` once
  the store is open. An adapter that can say who it acts as adds `actor`:
  `name`, never an email address; `id` where the tracker has one; and
  `verified`, true only where the tracker checked credentials. `init` says a
  verified name once, and `tracker use` each time it chooses the tracker.
- `create-item`, given `title`, `priority`, `parent`, `description`, and from
  migrate an `id` and `verifyUsing`: honour the id, or give your own, and the id
  in the record is what counts. The record comes back with status open and kind
  task, since only a pour makes a root; a child carries its parent; an unknown
  parent is `parent-not-found`. The description and `verifyUsing` are kept as
  `pour-steps` keeps a root's, and come back exactly as given. A create the
  tracker made and could not read back fails, and its summary names the id it
  made.
- `add-need`, given `id` and `needs`: the `edge` comes back; an unknown item
  is `item-not-found`; a cycle is `cycle`; a need already there answers
  completed, since a move that was interrupted asks for it again.
- `show-item`: the `item` with its `needs`, and its `children` as records, and
  its `description` and `verifyUsing` exactly as `pour-steps` or `create-item`
  was given them. Unknown is `item-not-found`.
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
  tracker cannot reach is `bad-status`. An `assignee` of `me` is whoever the
  adapter acts as. Any other is the tracker's own id for a person, and one it
  does not know is `assignee-not-found`. Never search for a person by name: a
  wrong match assigns the wrong person.
- `pour-steps`, given `formulaRef`, `title`, `steps`, each `id`, `title` and
  `needs` naming step ids anywhere in the list, and the formula's
  `description` and `verifyUsing`: a root of kind root with the steps as its
  children, each of kind task, and the needs as edges between the new ids;
  `rootId` and `stepIds` in the given order. An empty list is `no-steps`, a
  need naming no step `step-not-found`, a cycle among the steps `cycle`, two
  steps with one id `duplicate-step`, and each of those writes nothing. The root keeps the description and
  `verifyUsing`, the means to prove the run, one line each; `show-item`
  returns both exactly as given, and how the adapter keeps them is its own. A
  tracker with a title and a description and nothing more keeps `verifyUsing`
  as the last section of the description: the starting file's
  `keep_verify_using` writes that section, and `read_verify_using` reads back
  exactly what it wrote, since a description that would read as holding the
  means gets an empty section after it. Pass every description you write
  through it, the means or none. A pour that fails after making its root --
  the means not kept, a step refused, or an item made and not read back -- is
  a failure that names the root and the steps it made, in `rootId`, `stepIds`
  and its summary.

Three rules are the adapter's, since the door decides none of them: a close
is refused while an open need or an open child exists; a poured root closes
once its steps have; an id asked for is honoured, or the record says which
id was given.

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
<name>` to move the work there, each item's description and means with it; then
a day of create, pour, ready and close through it.

## Shipping it

A tracker ships as a package.

- **The name.** The package is named `dotdiw-tracker-<name>`, and so is its
  repository if it has its own. dotdiw never reads that name. It is there so
  people can find the tracker.
- **The file.** One file, `<name>.py`, that imports only the standard library,
  because it runs in dotdiw's own interpreter. A tracker written in another
  language ships a small module that calls its binary with JSON.
- **The place.** A package installs the file under `share/dotdiw/trackers/`.
  A copy in your home directory overrides it while you try a change, and
  copying the file to `~/.dotdiw/trackers/` works with no package at all.
- **The proof.** Compatible means `dotdiw tracker check` passes ten of ten.
  There is no central list of trackers to join. Run the check by path in your
  CI.
- **The interface.** `info.interface` in the table holds the number of the
  interface the file was written for. When dotdiw raises that number, it refuses
  a file written for the old one, in one line that names it, and the author ships
  a new version. From 1.0.0, dotdiw spoke interface 2: an item's kind is root
  or task, `create-item` takes no kind, and a root keeps its description and
  `verifyUsing`. From 3.0.0, it speaks interface 3: the requests carry data
  alone, with no `path`, `arguments` or `terminal`, and the answers carry no
  `printed`; every create and pour answers its record. A file written for 1 or
  2 is refused.
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

Tell people to install it by naming both packages:

    brew install adimpression/tap/dotdiw <your-tap>/dotdiw-tracker-acme

Homebrew loads a dependency from a tap only if that formula is trusted, and naming
a formula in `brew install` trusts it. On a machine that never installed dotdiw by
name, your package alone is refused.

Jira is a registered trademark of Atlassian Pty Ltd.
