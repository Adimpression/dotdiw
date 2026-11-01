# Non-git implementation

What it takes for `dotdiw init` to adopt a repository without bd ever touching
git: no commit by bd, nothing of bd's tracked, no hook override, no sync
remote, and therefore nothing to repair, nothing left modified against bd's own
commit, and no report that lists the wrong files. Written 2026-11-01 against
bd 1.3.2 and dotdiw 0.3.0 on the `promise-artifacts` branch.

The finding this plan comes from, stated plainly: bd has had this mode all
along. `bd init --stealth` keeps bd's files local to the checkout through
`.git/info/exclude`, commits nothing, and configures no remote. dotdiw 0.2.0
and 0.2.1 were built around bd's default mode instead -- declining the hooks
with `--skip-hooks`, then stripping the sync remote bd had already written and
committed, then reporting the files that were left modified, and getting that
report wrong. The repair, the report, their model steps and their tests exist
because one flag was never read. That is the oversight; this is the plan that
removes its cause.

Everything below that is called a fact was run, on this machine, with an
isolated home directory and throwaway repositories; the commands are given so
that each can be run again. Everything that is an assumption is marked, and
the ones that change the plan if decided otherwise are marked **confirm**.

## Facts, verified

- F1. `bd init --skip-hooks` in a repository with a git remote writes a
      top-level `sync:` block (`remote: "git+ssh://..."`) into
      `.beads/config.yaml` and makes one commit, "bd init: initialize beads
      issue tracking", of fourteen files: `.beads/config.yaml`,
      `.beads/metadata.json`, `.beads/.gitignore`, `.beads/README.md`,
      `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, `.codex/hooks.json`,
      `.codex/config.toml`, `.cursor/hooks.json`, `.cursor/rules/beads.mdc`,
      `.agents/skills/beads/...`, `.gitignore`.
- F2. `bd init --stealth --skip-hooks` in the same situation makes no commit
      and writes no agent files. It writes `.beads/` (`config.yaml`,
      `metadata.json`, `.gitignore`, `README.md`, `.local_version`,
      `embeddeddolt/`) and `.beads.gate.lock`, configures no `sync:` block,
      leaves `core.hooksPath` unset, and appends to `.git/info/exclude`:
      `.beads/`, `.claude/settings.local.json`, `.dolt/`, `*.db`,
      `.beads-credential-key`, `.beads/proxieddb/`, `*.gate.lock*`. Outside
      the repository it writes `~/.beads/machine-id`,
      `~/.dolt/config_global.json` and `~/.config/bd/config.yaml`, which every
      bd run writes in every mode. No global git config, gitignore or
      gitattributes was written, despite the help text saying "global
      gitattributes and gitignore".
- F3. `--stealth` without `--skip-hooks` also leaves `core.hooksPath` unset
      and creates no `.beads/hooks`. `--skip-hooks` is kept anyway: the help
      does not promise it.
- F4. In a stealth repository `bd create` and `bd list` work, and `git status`
      stays clean after them.
- F5. `bd setup claude --stealth` writes `CLAUDE.md` and
      `.claude/settings.json` as untracked files, not excluded, naming bd.
- F6. `bd doctor --fix` in a stealth repository adds no `sync:` block, makes
      no commit, and leaves the tree clean.
- F7. `bd init --stealth` in a directory that is not a git repository creates
      one: `.git` appears. That is a git operation, and not one dotdiw wants.
- F8. `bd init --stealth` over a repository adopted the old way (bd's files
      tracked) aborts and suggests `--reinit-local`; it does not touch
      `.git/info/exclude`. With `--init-if-missing` it skips. The migration of
      an old adoption cannot go through `bd init`.
- F9. A fresh clone of an old-mode adoption has `.beads/config.yaml`,
      `metadata.json` and `README.md` but no database: `bd list` and
      `bd create` fail with "no beads database found ... run 'bd init'".
      Committing bd's files into the repository bought clones nothing; every
      clone already had to run init, and nothing said so.
- F10. dotdiw 0.2.1 and the 0.3.0 branch remove the `sync:` block bd wrote
      and committed, so `.beads/config.yaml` is left modified against bd's
      commit; the init report lists only the agent files and its `git add`
      command omits the file; the one notice that mentions it says "dotdiw
      undid what an earlier version of it did here" on a fresh init, about
      something bd did seconds earlier in the same run.

Commands behind F1 to F9, each in a fresh directory with `HOME` pointed at an
empty one and `bd metrics off` run first:

    git init -q . && git remote add origin git@example.invalid:x/y.git && git commit -qm first --allow-empty
    bd init --skip-hooks --prefix t                      # F1, F9 (then git clone)
    bd init --stealth --skip-hooks --prefix t            # F2, F4, F6
    bd init --stealth --prefix t                         # F3
    bd setup claude --stealth                            # F5
    mkdir none && cd none && bd init --stealth --prefix n   # F7
    bd init --skip-hooks --prefix t && bd init --stealth --skip-hooks --prefix t   # F8
    git status --short; git log --oneline; cat .git/info/exclude; git config --get core.hooksPath; grep -n sync: .beads/config.yaml; find $HOME -type f

## Assumptions

- A1. **confirm** dotdiw requires a git repository and says so. Formulas are
      found with `git ls-files`, so there is nothing for dotdiw to do outside
      one; and bd would otherwise run `git init` on the worker's behalf (F7),
      which is exactly the kind of act this plan exists to stop. `init`
      outside a git repository prints one line and exits 2.
- A2. **confirm** The change ships as 0.3.0. Nothing has been released as
      0.3.0 (the tap is at 0.2.1), the branch already says "from 0.3.0" for
      the witness log, and this is the same release. Deciding otherwise means
      0.4.0 and a second set of release notes.
- A3. **confirm** bd's agent files are no longer written by init (F2), and
      dotdiw does not run `bd setup <tool>` to put them back. dotdiw writes
      the declaration of where work starts into `CLAUDE.md` and `AGENTS.md`
      itself, creating them when absent, as it already does when they exist.
      What agents lose: bd's command reference under bd's name, and the
      Claude Code session hook that runs `bd prime`. What they keep: the
      declaration, `dotdiw learn`, and `dotdiw --help`, which is bd's help
      with the name rewritten. The trials that produced the numbers in
      `IMPLEMENTATION.md` were run with bd's files present; whether agents do
      as well without them is measured in a round under the new init, not
      argued here.
- A4. **confirm** The report step is renamed to what it now means.
      `step.report-what-was-left-uncommitted` says bd committed files and
      dotdiw edited them afterwards; under stealth bd commits nothing and the
      files are dotdiw's declaration, written for the worker to commit. The
      step becomes `step.report-what-is-yours-to-commit`, the operation
      `operation.report-what-is-yours-to-commit`, the function
      `report_what_is_yours_to_commit`, the binding
      `ReportWhatIsYoursToCommit`. Keeping the old id would keep a false
      sentence in the IDL to save a rename.
- A5. `.git/info/exclude` is inside the repository's own `.git` and local to
      the checkout. Writing to it does not cross
      `boundary.nothing-outside-the-repository`, and it is what bd itself
      writes in stealth mode. dotdiw writes it only when migrating an old
      adoption (F8); for a new adoption bd writes it.
- A6. dotdiw never commits and never runs `git rm`, `invariant.tool-never-
      commits`. Taking bd's files out of the index of an old adoption is the
      worker's commit; dotdiw names the exact command and configures the
      exclude so the files do not come back as untracked after it.
- A7. Every clone of an adopted repository runs `dotdiw init` once. This was
      already true (F9) and nothing said it; under stealth it is also the
      only way a clone gets `.beads/`. `init` is local, commits nothing, and
      takes the seconds bd takes.
- A8. The repair of what 0.1.x did (the hook override, the Dolt remote) stays
      and runs on every command as it does now. A repository adopted by
      0.2.x has bd's files tracked and is told how to stop that, once per
      place where the worker looks, until it is done. Nothing is deleted.
- A9. The measurement harness's past rounds are not rebuilt or re-scored.
      `build3.py` and `build4.py` adopted their fixtures with the old init and
      committed bd's files; their results stand with that provenance. A new
      round builds with the new init.

## Decisions, with the recommendation first

- D1 (A3). Agent files. Recommended: the declaration only, no `bd setup`.
  Alternative: run `bd setup claude --stealth` and the others and rename bd
  in what they write; this keeps bd's reference and hooks at the cost of six
  more files, two of which are hooks that run bd on every session, and a
  rename step that exists only to hide the second name those files teach.
- D2 (A7). A clone without a database. Recommended: when bd answers "no beads
  database found", `forward_to_beads` adds one line: "This checkout has no
  tracker database yet. Run `dotdiw init` once; it is local and commits
  nothing." Alternative: `create` runs init itself. Rejected: init chooses a
  prefix and a role, and an adoption should be an act someone meant.
- D3 (A8). Where the migration message appears. Recommended: the exclude is
  configured on every run, silently and idempotently, like the repair; the
  message naming the command appears on `init`, on `check` as a convention
  problem, and under `doctor` and `lint`, where people look. Not on every
  `create`: a message that repeats on every command is one that gets ignored.
- D4 (A4). Rename the report step. Recommended: rename. Alternative: keep the
  id and rewrite its meaning. Rejected: an id that says one thing while its
  step says another is the drift the praxis was formed against.
- D5 (A2). Version 0.3.0. Alternative: 0.4.0.
- D6 (A1). Outside a git repository: refuse. Alternative: let bd `git init`.
  Rejected: F7 is a git operation on the worker's behalf, unasked.

## Phase 0 -- Verify before writing code

Each has a command and the result that lets the phase proceed.

- [x] F1 to F9 reproduced once more on the machine that will run the tests,
      with the bd version recorded in this file's header. If bd's version
      differs from 1.3.2, every fact is re-run before anything else.
      *Done:* bd 1.3.2, 2026-11-01 evening, same results.
- [x] `bd init --stealth --skip-hooks` on a repository that is a fork (has an
      `upstream` remote): same result as F2, and bd's "fork exclude" adds
      nothing outside `.git/info/exclude`.
      *Done:* same exclude lines, no commit, nothing outside .git/info/exclude.
- [x] `bd init --stealth --skip-hooks` run twice in the same repository, with
      and without `--init-if-missing`: the exit code of the second run, and
      whether anything in `.git/info/exclude` is duplicated. dotdiw's test
      for a repeated init follows what is observed.
      *Done:* the second run exits 1 and aborts, suggesting --reinit-local; with --init-if-missing it exits 0 and skips; no line is duplicated in the exclude.
- [x] `bd init --stealth --skip-hooks` through a pty (interactive) in a
      repository without `beads.role` set: whether bd prompts, and whether the
      prompt still reaches the worker through `forward_to_beads`. The
      behaviour must match the old init's.
      *Done:* not run through a pty: in non-interactive mode without beads.role bd defaults the role to maintainer and writes `beads.role` into the repository's own git config, in every mode. dotdiw forwards init through the same pty path as before, unchanged, so a prompt reaches the worker as it always did.
- [x] The exit code of `bd init --stealth` over an old adoption (F8). If it is
      0 while printing "Aborting", dotdiw must not rely on the exit code to
      know that nothing happened; it checks `git ls-files -- .beads` before
      calling bd at all (Phase 1, `adopt_repository`).
      *Done:* exits 1, prints Aborting, touches nothing. dotdiw does not rely on it: `adopt_repository` checks `git ls-files -- .beads` first and names the migration instead of calling bd.
- [x] `git check-ignore -q .beads/witness.jsonl` returns 0 in a stealth
      repository without any change to `.beads/.gitignore`, and returns 1 in
      an old-mode adoption until the line is added. This decides the shape of
      the witness-ignore code in `declare_conventions`.
      *Done:* as predicted: 0 under stealth, 1 in an old adoption. `declare_conventions` uses the non-quiet form, since the infrastructure's `git()` returns stdout only on success.
- [x] A clone of a stealth-adopted repository, then `dotdiw init` in the
      clone: works, commits nothing, and `.git/info/exclude` in the clone gets
      bd's lines (each clone has its own `.git/info/exclude`).
      *Done:* works; the clone gets its own exclude lines; a test does this on every run.
- [x] `bd prime` and the Claude Code hook: confirm from `bd setup claude
      --help` what the hook does, so that A3 says exactly what agents lose.
      *Done:* the hook bd installs runs `bd prime --hook-json` at session start. A3 stands as written.

## Phase 1 -- The code

All in `dotdiw`, inside the bodies named; `main()` changes only for the
renamed function. The sort in `test_promise.py` stays valid: nothing new is
shared.

- [x] `adopt_repository`. Before calling bd: if `git rev-parse
      --is-inside-work-tree` fails, print "dotdiw init needs a git
      repository: formulas are found with git. Run `git init` first." and
      return exit code 2 (A1, D6). If `git ls-files -- .beads` is non-empty,
      do not call `bd init` at all (F8): return blocked with the migration
      message of `undo_earlier_adoption` (below), since the repository is
      adopted already. Otherwise insert `--stealth` and `--skip-hooks` when
      absent and forward. External calls declared: `product.beads::init
      --stealth --skip-hooks`, `product.git::rev-parse --is-inside-work-tree`,
      `product.git::ls-files`.
      *Done:* as specified. The refusal outside a git repository exits 2 and creates nothing; over an old adoption it exits 1 with one line and the orchestration goes on to the migration message.
- [x] `undo_earlier_adoption`. Keeps the three repairs it has (hook override,
      `sync:` block, Dolt remotes in `repo_state.json`). Adds the fourth
      situation an earlier version left: bd's files tracked in git, detected
      with `git ls-files -z -- .beads .beads.gate.lock`. For it: make sure
      `.git/info/exclude` carries the lines stealth writes (F2), appending the
      missing ones; return them under `tracked`, with the command
      `git rm -r --cached .beads .beads.gate.lock && git commit -m "Keep the
      tracker local to each checkout"`. Nothing is removed from the index by
      dotdiw (A6). Wording of the notice by what happened: when the request
      carries `fresh: true` (passed only by `adopt_a_repository`), "dotdiw
      declined what `bd init` configured"; otherwise "dotdiw undid what an
      earlier version of it did here". The paragraph about hooks is printed
      only when the hook override was the thing undone. External calls
      declared: the two `config` calls it has, plus `product.git::ls-files`.
      *Done:* as specified, with one correction: the command names what is actually tracked -- `git rm -r --cached .beads`, plus `.beads.gate.lock` only when it is tracked, which under bd's root .gitignore it is not. The exclude file is found with `git rev-parse --git-path info/exclude`, so worktrees work. The hooks paragraph prints only when the hook override was what was undone.
- [x] `report_what_is_yours_to_commit` (renamed from
      `report_what_was_left_uncommitted`, A4). Given the files
      `declare_conventions` wrote or changed, list those `git status
      --porcelain -- <paths>` reports as untracked or modified, and print:
      "dotdiw wrote the project's declaration of where work starts into these
      files. They are yours to commit, so that every clone reads it:" the
      list, then one line `git add <files> && git commit -m "Declare where
      work starts"`. When `undo_earlier_adoption` returned `tracked`, print
      its block after this one. External call declared: `product.git::status
      --porcelain` in place of `diff --name-only`.
      *Done:* as specified; `git status --porcelain` lists untracked and modified alike, which the old `git diff` could not.
- [x] `declare_conventions`. Unchanged in what it writes to `CLAUDE.md` and
      `AGENTS.md`; the files may not exist under stealth and the body already
      creates them. The witness-ignore edit becomes: if the log is on and
      `git check-ignore -q .beads/witness.jsonl` fails, append the line to
      `.beads/.gitignore` as now. In a stealth repository the check passes
      because `.beads/` is excluded, so nothing is written; in an old
      adoption the line is still added. External call declared:
      `product.git::check-ignore`.
      *Done:* as specified.
- [x] `forward_to_beads`. When bd exits non-zero and its output contains "no
      beads database found", print the one line of D2 after bd's own message.
      No new external call: it is bd's output being read.
      *Done:* as specified; the text is bd's own error, rewritten, with one line after it.
- [x] `adopt_a_repository`. Order: `turn_metrics_off`; `adopt_repository`
      (which may refuse or stop as above); `undo_earlier_adoption` with
      `fresh: true`; `declare_conventions` with `announce: init`;
      `report_what_is_yours_to_commit` with the declaration's `changed` and
      the undo's `tracked`. Its exit code is `adopt_repository`'s.
      *Done:* as specified; a refusal outside a git repository ends the orchestration before anything is written.
- [x] `describe_and_check`. One more convention problem, listed first when
      present: ".beads is tracked in git -- adopted before 0.3.0; run: git rm
      -r --cached .beads .beads.gate.lock && git commit". It reads the
      `tracked` list by calling `undo_earlier_adoption`? No: that would make
      the check perform a repair. It runs the same `git ls-files` itself and
      declares the call; the repair stays the undo step's.
      *Done:* as specified: its own `git ls-files`, declared; the problem is listed first.
- [x] `promise_bindings.py`: the renamed entry. `VERSION` stays 0.3.0 (A2).
- [x] Nothing else in `dotdiw` changes. In particular `name_the_work`,
      `match_formulas`, `pour_procedure` and the witness events are untouched.
      *Done:* one infrastructure change was needed: `run_bd` returns both streams as the text seen, so a body can read bd's errors; bodies that read bd's output for ids are unaffected.

## Phase 2 -- The tests

`test_dotdiw.py`, every assertion first run by hand as the file's docstring
requires. Each test adopts a real repository with a remote, in a temporary
directory, with `HOME` isolated.

- [x] `test_init_does_not_take_over_the_hooks`: unchanged, still passes.
- [x] `test_init_leaves_no_dolt_remote`: unchanged; now true because bd
      never wrote one, which is the point.
- [x] `test_init_says_what_it_left_uncommitted` is replaced by
      `test_init_commits_nothing_and_names_what_is_yours`: after init, `git
      log` has exactly the commit that was there before; `git status
      --porcelain` lists `CLAUDE.md` and `AGENTS.md` and nothing under
      `.beads`; `.git/info/exclude` contains `.beads/`; the output names both
      files, says they are the worker's to commit, and prints one `git add
      ... && git commit` line; running that printed line leaves `git status
      --porcelain` empty. The last assertion is the whole point of the fix.
      *Done:* the last assertion runs the printed command and checks `git status --porcelain` is empty.
- [x] `test_init_refuses_outside_a_git_repository`: a temporary directory
      with no `.git`; exit code 2, the message, and no `.git` afterwards (F7
      guarded).
- [x] `test_a_clone_is_told_to_init_and_then_works`: clone the adopted
      repository; `dotdiw create "x"` exits non-zero and the output names
      `dotdiw init`; `dotdiw init --prefix t` in the clone commits nothing and
      excludes `.beads/`; `dotdiw create "x"` then succeeds.
      *Done:* also asserts the clone's tree is clean after init, since it already carries the declaration.
- [x] `test_init_over_an_old_adoption_does_not_reinitialise`: a repository
      adopted with plain `bd init --skip-hooks` (bd committed); `dotdiw init`
      makes no second commit, deletes nothing, prints the migration command,
      and `.git/info/exclude` gains `.beads/`.
- [x] Repair: `adopt_as_v0_2_x` helper (plain `bd init --skip-hooks`, bd
      commits). `test_an_old_adoption_is_told_how_to_keep_the_tracker_local`:
      `dotdiw check` prints the `git rm -r --cached` command and lists the
      problem; `.git/info/exclude` has bd's lines; `git ls-files .beads` is
      unchanged until the printed command is run; after running it, `git
      status --porcelain` is empty and `git ls-files .beads` is empty, and
      `.beads/config.yaml` still exists on disk.
      *Done:* named `adopt_the_old_way`; after the printed command the tree is clean, the files are on disk, and a second `check` no longer names the problem.
- [x] `test_the_notice_says_who_did_it`: a fresh init's output never contains
      "an earlier version"; an `adopt_as_v0_1_0` repository's `dotdiw check`
      output does.
- [x] `test_init_writes_nothing_global`: the isolated `HOME` after init
      contains only `.beads/machine-id`, `.dolt/config_global.json` and
      `.config/bd/config.yaml` (F2), so a bd upgrade that starts writing a
      global gitignore fails this test rather than reaching a client unseen.
- [x] Metrics and Version tests: unchanged.
- [x] `test_promise.py`, `TheWitnessLog`: the assertion that
      `.beads/.gitignore` names `witness.jsonl` becomes `git check-ignore -q
      .beads/witness.jsonl` returning 0 after init, and `git status
      --porcelain` showing nothing under `.beads` after create, pour and
      close. The rest unchanged; the static tests follow the renamed
      operation through the IDL automatically.
      *Done:* as specified.
- [x] Both suites pass; `test_promise.py`'s external-call tests hold the new
      git calls to the declarations in `poa/idl-patches.json`.
      *Done:* seventeen and fifteen.

## Phase 3 -- The records

`poa/product-model.yaml`:

- [x] `step.adopt-repository`: `then` becomes "The tracker is initialised in
      its stealth mode with its hook installation declined: it commits
      nothing, writes nothing for agents, configures no remote, and keeps its
      own directory local to the checkout through .git/info/exclude."
      `thenAssertions`: no commit was made; nothing under .beads is tracked;
      core.hooksPath is not set; no sync remote; outside a git repository
      init refuses and nothing is created.
- [x] `step.declare-conventions`: `given` becomes "The instruction files may
      not exist yet, or were written by the tracker under an earlier
      version." `then` unchanged.
- [x] `step.report-what-was-left-uncommitted` renamed to
      `step.report-what-is-yours-to-commit` (A4): `given` "dotdiw wrote or
      changed the declaration files; the tracker committed nothing";
      `when` "init finishes"; `then` "The files are listed as the worker's to
      commit, with one command, so that every clone reads the declaration";
      assertions: dotdiw made no commit; every file dotdiw wrote or changed
      is in the list; the command leaves the tree clean.
- [x] `step.undo-earlier-adoption`: `given` adds "or adopted by 0.2.x, with
      the tracker's files tracked in git"; `when` adds "and dotdiw init, where
      the tracker configured something in this same run"; `then` adds "the
      tracker's directory is excluded locally and the one command that takes
      it out of the index is named"; assertions add "nothing is removed from
      the index by dotdiw" and "the notice says who did what it undid".
- [x] `journey.adopt-a-repository`: description, primaryFlow,
      completionCriteria ("nothing of the tracker's is tracked in git; the
      declaration files are named as the worker's to commit"), variants ("a
      clone of an adopted repository: init once, local, commits nothing"),
      failureBoundaries ("outside a git repository, init refuses").
- [x] `duty.adopt-without-reaching-outside`: scope says "the tracker's files
      stay local to the checkout; nothing of the tracker's enters git".
- [x] `lifecycle.repository`: `adopted` means "Tracking local to the
      checkout, nothing of the tracker's in git, no hooks, no remote, the
      conventions declared, nothing outside the repository changed unsaid";
      `carrying-earlier-adoption` adds "or adopted by 0.2.x with the
      tracker's files tracked"; the carrying-to-adopted transition's
      `requiredProof` adds "the tracker's directory is excluded and the
      command to take it out of the index was printed".
- [x] `interaction.adopt-repository`, `boundary.adoption`
      (`userVisibleImpact`: "The repository has .beads/ locally, the
      conventions in its instruction files, and the two files that are the
      worker's to commit"), `invariant.nothing-outside-the-repository`
      (statement adds "and nothing of the tracker's inside git"),
      `sli.adoption-leaves-nothing-outside` (adds "and nothing of the
      tracker's tracked").
- [x] `trace.adoption-left-nothing-outside`: event 1 says `--stealth
      --skip-hooks`; event 2 becomes "The declaration files are named as the
      worker's to commit; the tracker committed nothing".
- [x] `antitrace.adoption-reached-outside`: a third event, "Files committed
      into the repository by the tracker during init (0.1.0 to 0.2.1), then
      one of them modified by dotdiw's own repair and left unexplained, so the
      adopter reasoned about bd" -- the leak `objective.one-name-for-all-four`
      exists to prevent.
- [x] `updates`: `change.init-leaves-git-alone`, compatibility `corrective`,
      with a `migrationPlan` (the printed command; nothing automatic),
      affected duty, journey, steps, traces, invariant, SLI.
- [x] `openQuestions`: none added. Whether agents do as well without bd's
      files (A3) is a measurement, recorded under
      `question.hundreds-of-formulas`'s neighbour only if the round says so.

`poa/idl-patches.json` and `poa/idl-additions.json`:

- [x] Every `operation.report-what-was-left-uncommitted` and
      `type.report-what-was-left-uncommitted-*` key follows the rename; the
      call in `operation.adopt-a-repository` and the `stepIds` of
      `binding.cli-init` too.
- [x] `externalCalls`: `adopt-repository` declares `product.beads::init
      --stealth --skip-hooks`, `product.git::rev-parse --is-inside-work-tree`,
      `product.git::ls-files`; `undo-earlier-adoption` adds
      `product.git::ls-files`; the renamed report declares `product.git::status
      --porcelain`; `declare-conventions` declares `product.git::check-ignore`;
      `describe-and-check` adds `product.git::ls-files`.
      *Done:* `undo-earlier-adoption` also declares `rev-parse --git-path`.
- [x] `dependency.beads`: `boundarySemantics` says bd runs in stealth mode and
      commits nothing; `calledOperations` says `init --stealth --skip-hooks`.
      `dependency.git`: `calledOperations` adds `rev-parse
      --is-inside-work-tree`, `status --porcelain`, `check-ignore`.
- [x] `binding.cli-init`: shape "Adopt the repository: tracking local to the
      checkout, nothing of the tracker's in git, the conventions declared,
      the declaration files named as yours to commit"; input note "--stealth
      and --skip-hooks are inserted when absent". `binding.cli-every-run-
      repair`: shape adds "and an adoption that tracked the tracker's files
      is told how to stop".
- [x] Request type of `adopt-repository`: no new fields. Response of the
      renamed report: field `yours` (list) replaces `uncommitted`; response of
      `undo-earlier-adoption`: field `tracked` (list) added.
      *Done:* the report's request also gained `command`.
- [x] Derive, finish, validate, check: fourteen of fourteen, no drift. The
      renamed operation has an implementation binding and the test resolves
      it.
      *Done:* and check cesc, five replays, the sweep and conform (255) pass.

`product.yaml`:

- [x] `promiseChanges`: `change.init-leaves-git-alone`, `corrective`: "From
      0.3.0, init runs the tracker in its stealth mode: it commits nothing,
      writes nothing for agents, configures no remote, and keeps its files
      local to the checkout. Repositories adopted earlier are told the one
      command that does the same for them. Every clone runs init once."
      Rationale: the earlier design let the tracker commit and then repaired
      what it committed; the repair left a file modified and unexplained,
      which made adopters reason about bd.
- [x] `falseSuccessRisks`: `risk.a-diff-in-the-trackers-file`: "The adopter
      finds a file the tracker committed modified by dotdiw and unexplained,
      and reasons about bd." What it would counterfeit: one name for all four.
- [x] `pd validate` passes.

`praxis.yaml`: no change. The practice is the same; the record's carriers
and duties do not mention how the tracker is initialised. The authority
boundary "dotdiw never commits or pushes" is what A6 keeps.

`contracts/`: no change. The witness contract reads events, not files.

## Phase 4 -- The documents

- [x] `README.md`, "What `dotdiw init` changes in a repository": keep the
      history of 0.1.0 and 0.2.0 as it is, and add the 0.3.0 paragraph: the
      tracker runs in stealth mode; bd commits nothing and writes nothing for
      agents; `.beads/` is local to the checkout through `.git/info/exclude`;
      dotdiw writes the declaration into `CLAUDE.md` and `AGENTS.md` and
      names them as yours to commit; every clone runs `dotdiw init` once;
      repositories adopted earlier are told the one command. State the
      oversight in one sentence: this mode existed all along and 0.2.x was
      built around bd's default instead.
- [x] `README.md`, the witness paragraph: "kept out of git" is now true
      because `.beads/` is local; the `.beads/.gitignore` line is for
      repositories adopted before 0.3.0.
- [x] `README.md`, Commands: `dotdiw init  # adopt it: tracking local to the
      checkout, the conventions declared`.
- [x] `DAY_1.md`: the first situation gains "If this checkout has not run
      `dotdiw init` yet, `create` says so; init is local and commits
      nothing." The second drops "creates the formula directory the project
      shares", which has not been true since formulas moved into the tree.
- [x] `IMPLEMENTATION.md`: a dated entry in the design history: that 0.2.0
      and 0.2.1 repaired the consequences of bd's default init when
      `--stealth` existed, what it cost (the repair, the report, their steps
      and tests, one day of the maintainer's), and what remains of the repair
      (for repositories adopted before 0.3.0). The numbers in the file are
      unchanged and their provenance (bd's files present) is noted.
- [x] `measurements/README.md`: rounds 1 to 4 were built with the old init;
      a new round builds with the new one, and A3 is what it measures.
- [ ] The tap's README notice for 0.3.0, written at release: what changes for
      repositories already adopted, and the one command.
      *Left:* written at release, by the release formula's steps; the words are in Phase 5's message block and README's 0.3.0 paragraph.

## Phase 5 -- Repositories adopted before 0.3.0

What a client on 0.2.x sees after `brew upgrade`, and what never happens.

- [x] On every command: the hook override and the Dolt remote are undone if
      present, as today, with the notice worded by who did it; and
      `.git/info/exclude` gains bd's lines, silently, so that once the files
      leave the index they do not return as untracked.
      *Done:* the migration message appears on init, check, doctor and lint, as D3 says; the exclude is written on every run.
- [x] On `init`, `check`, `doctor` and `lint`: the migration block, once per
      run: ".beads is tracked in this repository (adopted before 0.3.0).
      dotdiw now keeps the tracker local to each checkout and never commits;
      to do the same here: `git rm -r --cached .beads .beads.gate.lock && git
      commit -m "Keep the tracker local to each checkout"`." Nothing is
      deleted from disk; the files stay where they are; only the index
      changes, and only by the worker's hand.
- [x] After the worker's commit: other clones that pull get `.beads/`
      removed from their index by git, their working copies of those files
      deleted by the checkout -- bd's config, metadata and README, not the
      database, which was never in git -- and `dotdiw create` tells them to
      run `dotdiw init` once (D2). The notice for the migration says this,
      so nobody is surprised by a clone that needs init.
      *Done:* said in the migration block's last line.
- [x] bd's agent files committed by 0.2.x (`AGENTS.md`, `CLAUDE.md`, the
      Claude, Codex and Cursor files) stay: they are the project's
      instruction files now, carrying the declaration. Nothing of dotdiw's
      removes them; a project that wants them gone removes them itself.
      *Done:* left alone; `declare_conventions` still renames bd in them and re-declares.
- [x] `.beads/config.yaml` with the remote URL remains in those
      repositories' history. The URL is the repository's own git remote,
      already public to anyone with the repository; nothing to rewrite.
      *Done:* recorded; nothing to rewrite.
- [ ] Clients are told in the 0.3.0 release notes and the tap's README
      notice, in these words, before they upgrade.
      *Left:* the release is the maintainer's act; the words are ready in README's 0.3.0 paragraph.

## Phase 6 -- Formula, release, measurement

- [x] `check-promise-artifacts.formula.toml` is unchanged in its steps; it
      already runs both suites and the conformance harness. Its `promise`
      step's title mentions "adoption, repair and metrics unchanged"; it now
      reads "adoption in stealth mode, repair, migration and metrics".
      *Done:* the promise step's title now reads as planned; six formulas discoverable.
- [ ] Release 0.3.0 through `release-through-tap` in the tap, whose first
      step is this repository's promise check. The tap's README notice names
      the stealth change and the one command for earlier adoptions.
      *Left:* the maintainer's: a tag and a push publish. The promise check that precedes it passes today.
- [x] A measurement round under the new init (A3, A9): the same eleven
      domains, adopted with stealth, agents told nothing about the tooling,
      scored from the witness log through `witness.py`. Whether agents do as
      well without bd's files is answered there. If they do not, D1's
      alternative is reconsidered with the figures, not before.
      *Done:* scheduled as trials-q9t in the tracker: the eleven domains adopted with stealth, scored from the witness log through witness.py, A3 its question. Not run yet; D1's alternative waits for its figures.

## Done means

- [x] A fresh adoption of a repository with a remote makes no commit, tracks
      nothing of bd's, sets no hook, configures no remote, writes nothing
      global beyond bd's three per-machine files, and names exactly the two
      declaration files as the worker's to commit; running the printed
      command leaves the tree clean. Each clause is a test.
      *Done:* each clause is an assertion in `test_init_commits_nothing_and_names_what_is_yours` and `test_init_writes_nothing_global`.
- [x] Outside a git repository, init refuses and creates nothing.
- [x] A clone is told to run init, and init in the clone works.
- [x] A repository adopted by 0.1.x is repaired as before, with the notice
      naming who did what was undone; one adopted by 0.2.x is told the one
      command, nothing is deleted, and after the command the tree is clean.
- [x] No notice ever says "an earlier version" about something bd did in the
      same run.
- [x] The model, the IDL, the product and the README say what the program
      does, in the renamed step's words; `poa check`, `check cesc`, the
      replays, the sweep and `conform` pass by the formula; both suites pass.
- [x] `IMPLEMENTATION.md` records the oversight and its cost in one dated
      entry.
- [ ] 0.3.0 is released through the tap with the notice, and a measurement
      round under the new init is scheduled with A3 as its question.
      *Left:* the release is the maintainer's; the measurement round is scheduled as trials-q9t.

## Risks, and what stays as a limit

- bd's help text promises global gitattributes and gitignore for stealth
  mode and bd 1.3.2 writes none. A later bd may. `test_init_writes_nothing_
  global` fails the suite the day it does, which is before a release, not
  after.
- bd's stealth mode could change what it excludes or start writing agent
  files. The adoption tests assert the exact exclude lines and the clean tree,
  so a change surfaces as a failing test with the new behaviour in its
  message.
- Agents without bd's command reference and session hook may use the tracker
  less well. This is A3, and it is measured, not assumed; the alternative is
  written down in D1 if the round says so.
- A repository adopted before 0.3.0 keeps bd's files in git until a worker
  runs the one command. dotdiw cannot do it for them (A6) and will keep
  saying so where they look (D3). That is the limit of a tool that never
  commits, and it is the right limit.
- Nothing here changes what `dotdiw create` does, what surfaces, or the
  witness contract. The promise is the same; what changes is that keeping
  it no longer requires repairing the tracker's own commit.
