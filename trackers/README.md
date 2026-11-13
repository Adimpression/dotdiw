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

**Registered, three ways.** Every one declares interface 4.

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
the eleven operations, each raising until you fill it, each docstring saying what
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

`operations` holds the eleven operations of the interface by their ids, and
nothing else, each a callable of exactly one parameter named `request`.
`extras` holds callables of one `request` by name for what the interface does
not cover. dotdiw calls four by name: `forward`, with every command it does
not own and does not refuse, and, for a close, a `mark` and the ids it is
`marked` to answer for: the close runs under a session of its own that the
tracker keeps, and the answer names, as `markedIds`, those ids that closed
under it; `read`, given the `arguments`, answering the `command` path, the
`words` and the `options` by their long names as the tracker itself will read
them, `command` null for a word the tracker knows no command by, or
`unreadable` where it cannot say -- without it, `forward` is given every
command as typed, and its closes and waits are not dotdiw's to check. dotdiw
reads each id a command names before it runs; a tracker that reads the id
again as it runs, as bd does, decides what a deletion between the two
writes, and bd writes the one item whose id begins with the deleted one's;
`metrics-off`, the first time a run reaches the adapter, before
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
carries, `step`, the id of the formula step a poured item was made for, its
`claim`, `{"statement": ..., "slots": [...]}`, the `values` recorded for it,
each `{"label": ..., "text": ...}`, and its `run`, the id of the root it was
poured under, `createdAt` and `updatedAt`. An edge is
`{"id": ..., "needs": ...}`.

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
  migrate an `id`, `verifyUsing`, `step`, `claim`, `values` and `run`, all
  kept and returned exactly as given: honour the id, or give your own, and the id
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
  was given them, and each item's and child's `step`, `claim`, `values` and
  `run` exactly as given. Unknown is `item-not-found`. The id is read as the
  tracker reads it, a short one as the full one, and the `item`'s own `id`
  says which it read. Where dotdiw asks for an id the tracker itself gave --
  one it listed, or an item's `run`, parent or need -- and the item that
  comes back carries another id, dotdiw takes the one asked for as not
  found: bd, asked for a root it holds no more, shows the one step left of
  it.
- `record-values`, given `id` and `values`, each `{"label": ..., "text": ...}`:
  each label given gets its value, replacing an earlier one where it stood; a
  label given with empty text is removed; every other label stays, in the order
  it was first recorded. Two writers of different labels at once both keep
  what they wrote, so never write back a set of values you read: keep each
  label apart, or each write. Each write is applied whole or not at all: a write cut short
  reads as it was, and writers of the same labels at once leave one write
  whole, never old values beside new ones. Where the tracker sets one field at
  a time, keep each write whole in a field of its own and read the writes in
  order, as the Jira adapter keeps each in an issue property named for when it
  was written. The record comes back as it now stands. Unknown is
  `item-not-found`. Write the values to the item of that very id. Where the
  only write that sets them reads an id the tracker holds nothing of as
  another item's, as bd's update does, answer every `record-values` as
  `unsupported` and write nothing, rather than risk another item's record:
  the beads adapter does, so a claim's values are not recorded under beads.
  Never guard such a write by first changing a field of the item, its
  assignee or any other: a write cut short leaves that change behind, and
  the field is part of the item's record. The values `create-item` is
  given, for a move, are the new item's own from the start, and every
  adapter keeps them.
- `list-items`, given `scope` of all or open, open when unsaid, `parent` for
  one parent's children, `run` for the items poured in the run under that
  root, whatever parent each stands under now, and `limit`, applied after the
  others: `items`. A run is how `dotdiw claim` reads a run back, since a step
  can be moved and the run it was poured in cannot. Every item is listed,
  those the tracker leaves out of its own lists unless asked included, since
  dotdiw holds a run to its rules from this list: a step it does not see
  stands open where no check sees it. For the same reason a listing is
  answered whole or fails: an answer of the tracker's that is no list of
  items, each with its id, is a failure, never a list of none. A module
  whose tracker's listing can leave an item out holds it to another account
  of each run that no edit of an item's own changes, as the beads adapter
  holds bd's list to bd's query of every item, reading each as an item of a
  run three ways at once: by dotdiw's run label, by the run its own
  metadata names, which only dotdiw writes, and by the ids under each
  root's, which bd keeps wherever an item is moved; and dotdiw refuses,
  through the pass-through, a command that takes that label off an item.
- `ready-items`: the open items with no open need, as `items`; an answer
  that is no list of them fails.
- `close-item`, given `closeReason`: refused as blocked with `blockedBy`
  naming the open needs, the open children, or the open items poured in its
  run, whatever parent they stand under now, so that a run closes after every
  step of it -- with the id read as the tracker reads it, a short one as the
  full one, and the full one named; an item shown whose id runs on past the
  one given, as bd shows a deleted root's step for the root's id, full or
  short, is no item of that id, and is `item-not-found`. Close the item in
  the write that holds the tracker's own rule, so that no item closes while
  what it waits on is open: never ask the rule in one write and close in
  another, since a need opened between the two goes unseen. Where the only
  close that holds the rule reads an id the tracker holds nothing of as
  another item's, as bd's does, read back what it closed: the beads adapter
  closes with bd's own close, under a session bd keeps on what it closes,
  so that an item bd closed in the place of one deleted as the close ran is
  named in `closedIds`, and as closed in its place, and the close fails.
  Completed names `closedIds`, and the record keeps its reason. A close the tracker did not make is a
  failure, not a completion. Closing the last step of a poured root may
  close the root too, and the root of the run the step was poured in,
  wherever the step stands, each named in `closedIds` after the step; or
  leave them to closes of their own. Either passes: through dotdiw, a close
  that leaves a root with nothing open is followed by the root's, under
  every adapter. A module whose tracker knows no run holds the rule after
  the close too, of the items as they stand then and on every path -- the
  item closed already or not, the tracker's close answered with an error or
  not, since what a close did is read from the tracker and not from how its
  command exited. What stands closed while what it waits on stands open is
  opened again: a root, whoever closed it -- the tracker may close one of
  its own accord when its last child closes -- and the item named, whose
  close is then `blocked`. It is written to by its whole id: a tracker that
  reads an id it holds nothing of as another item's, as bd reads a deleted
  root's as its only step's, is not handed that id to write, so that one
  deleted meanwhile opens no other item. Where the items cannot be read back
  whole -- a list that leaves out one listed before that the tracker still
  holds is not every item -- or one will not open again, the close fails,
  saying why, and naming in `closedIds` what it is known to have closed.
  Whether the tracker still holds an item is asked by its whole id, and an
  answer carrying another id is no item held: one another deleted as the
  close ran is no gap in the list. Where that one is the item named, nothing
  of it is read back: the rule is held of the rest all the same, and the
  close fails saying so, with no `item`. dotdiw itself refuses, at the
  command line and under any adapter, a parent or a need that would make an
  item wait on what waits on it, so a module need not, and holds the
  workspace's lock from that check through the write and on until the
  witness log has it, so that two dotdiw commands at once on one machine
  cannot each pass it, and the log has their closes in the order they were
  made; a module whose writes can hold the check, as the local adapter's
  transaction does, checks again inside the write and refuses as `cycle`,
  since writers on other machines, or outside dotdiw, are not held by that
  lock. An item another close had closed already is named closed already,
  not among the `closedIds` of this one; a close the module cannot tell from
  another's is not named this one's.
- `update-item`, given `title`, `status`, `priority`, `parent` or
  `assignee`: the record comes back; a status of closed is refused as
  `close-through-update`, since closing is close-item's, and a status the
  tracker cannot reach is `bad-status`; a `parent` that waits on the item
  may be `cycle`, as `close-item` says. An `assignee` of `me` is whoever the
  adapter acts as. Any other is the tracker's own id for a person, and one it
  does not know is `assignee-not-found`. Never search for a person by name: a
  wrong match assigns the wrong person. A `priority` is 0 to 4, 0 the
  highest; one outside is refused. Write every field to the item of that
  very id in one write, all of them or none, and a `parent` in the write
  that takes away the one the item has, so that two writers at once leave
  it under one: a parent taken away by a second write can be one another
  writer gave. An id the tracker holds no more is `item-not-found`. Where
  the only such write reads an id the tracker holds nothing of as another
  item's, as bd's update does, name the item it wrote: the beads adapter
  writes with bd's own update, whose answer names the item written, and
  fails naming that item where it is another, one deleted as the update
  ran.
- `pour-steps`, given `formulaRef`, `title`, `steps`, each `id`, `title`,
  `needs` naming step ids anywhere in the list, and a `claim` when the step
  declares one, which the item made for it keeps with the step's id and with
  the root's id as its `run`, and the formula's
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
failing operation until eleven of eleven pass. Once the file is installed,
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
- **The proof.** Compatible means `dotdiw tracker check` passes eleven of eleven.
  There is no central list of trackers to join. Run the check by path in your
  CI.
- **The interface.** `info.interface` in the table holds the number of the
  interface the file was written for. When dotdiw raises that number, it refuses
  a file written for the old one, in one line that names it, and the author ships
  a new version. From 1.0.0, dotdiw spoke interface 2: an item's kind is root
  or task, `create-item` takes no kind, and a root keeps its description and
  `verifyUsing`. From 3.0.0, it speaks interface 3: the requests carry data
  alone, with no `path`, `arguments` or `terminal`, and the answers carry no
  `printed`; every create and pour answers its record. From 4.0.0, it speaks
  interface 4: an item poured for a step keeps the step's id, its claim and
  its run, `record-values` sets a claim's values or declines them all as
  `unsupported`, `show-item`, `list-items` and
  `create-item` carry step, claim, values and run, `list-items` lists a run,
  and the check proves all four. A file written for 1, 2 or 3 is refused.
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
