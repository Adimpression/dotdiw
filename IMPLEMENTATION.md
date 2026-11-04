# Implementation

## The command

- [x] Rename `beads-suggest.py` to `dotdiw`. Drop `bd-shim.sh` and `install.sh`
      — day 0 replaces both.
- [x] `dotdiw <anything>` forwards to bd unchanged, so no task ever requires
      typing `bd`.
- [x] `dotdiw create "<title>"` runs the create, then ranks the project's
      formulas against the title and prints the top three.

## Hiding bd

- [x] Run bd under a pty so interactive prompts still work.
- [x] Rewrite `bd` to `dotdiw` in stdout and stderr. The hints are compiled in
      — `Run with --force to proceed.`, `Run: bd doctor --fix`, `To reinitialize
      beads, run: bd init` — and argv[0] does not change them.
- [x] Rename `bd` in the files bd writes for agents to read -- AGENTS.md,
      CLAUDE.md, the Cursor rules and hooks, the skill. An agent reads the
      file, so the stream rewrite never reaches it. bd writes them again on
      setup, doctor --fix and upgrades, so `dotdiw create` re-applies it.
- [ ] Check what `bd serve` puts in error payloads. If the same strings come
      through the API, server mode buys nothing over the rewrite.

## Discovery

- [x] Retrieve with SQLite's FTS5, which the interpreter already ships: bm25()
      ranking and a porter stemmer. Nothing hand-rolled and nothing installed.
      A word is now worth what it is distinctive, not one point like every
      other word, and "failing" reaches "fail".
- [x] Rank and show the top three.
- [x] Find formulas with `git ls-files '*.formula.toml'`. Anywhere in the tree,
      next to whatever they are about. The suffix is the convention, not the
      directory.
- [x] Fold the path into the matchable text.
      `services/billing/release.formula.toml` matches on "billing" and
      "release" without the description repeating them.
- [x] `bd cook` takes the path, so nothing is copied or linked into `.beads/`.
- [x] Index the project's own tracked text beside the formulas -- up to 300
      files, 100KB each -- and never return it. It is there so bm25 can see
      which words are everyday ones here. Against four documents of prose
      "version" was distinctive enough to pull the release formula up for a Go
      toolchain bump; against twenty-two it is not.
- [x] Silence is a fraction, not a score: show a formula when it accounts for
      at least 0.15 of what is distinctive about the title, measured as the
      share of the title's word weights the formula holds. bm25's scale depends
      on how much text a project has, so no absolute threshold means the same
      thing in two projects -- FLOOR = 2.0 was calibrated on a documented
      project and silenced every match in a project with one formula and one
      README, where bm25's idf is zero by construction. Ordering is bm25's.
- [x] Stop list is function words only. Nothing with meaning belongs on it --
      "down" was on it, and it was the outage formula's best word.
- [x] Leave-one-out self-test: take the example out of the index before
      searching for it, and put it back after. Leave it in and the test proves
      only that an indexed string can find itself.

Measured on a simulated four-formula project, seventeen titles none of the
formulas were written against: eleven of twelve real titles retrieved, all of
them at rank one, and four of five unrelated titles left in silence. The
previous scorer got eleven, ten at rank one, and three of five. What is left
is one miss and one false hit, both of them the author's words rather than the
ranking: "Checkout is failing for everyone" reaches nothing because the outage
formula says down, outage and pager but never fails, and "Write unit tests for
the parser" reaches the migration formula. `examples` is where a project fixes
both.

The same four formulas against four more documents of the project's own
release, on-call, database and secrets prose -- the hard case, where a project
documents itself in its formulas' vocabulary -- score identically: eleven of
twelve and four of five. A one-formula project with a two-line README retrieves
five of five, where the absolute threshold retrieved none of them.

That "four of five" is five negatives, and it flattered the rule. Measured
again on thirty-three -- three titles naming real work the formula set does not
cover, in each of eleven projects -- nineteen are left silent and fourteen
retrieve something that does not apply: hiring a kitchen hand reaches the
add-a-dish formula, getting the sprayer through its test reaches calving. Two
in five, not one in five.

It does not tune out. Every step up the threshold buys silence at about one
lost retrieval per coincidence suppressed: at 0.40, thirty-two of thirty-three
go quiet but forty-one of a hundred and twenty-eight examples stop finding
their own formula. Requiring two shared query words rather than one is the same
curve in different clothes -- 107 retrieving and 26 quiet, indistinguishable
from simply raising the threshold to 0.25, and on the original fixture it costs
two retrievals and buys nothing. At three formulas per project there is no
setting that both retrieves and stays quiet, so 0.15 stands on the trade it was
chosen for: a coincidence costs a glance, silence costs the mechanism. It is
untested at the hundreds of formulas this is for.

## What fifteen blind agents did with it

Five domains -- a ramen shop, an animal shelter, a one-module library, an edge
fleet, a company secretary -- each as three repos: not started, started without
any of this, started with it. One agent per repo, told the domain job and
nothing about the tooling, on a small model. Ground truth from a log of every
invocation and the repo diffs, not from what the agents said they did.

Not one of the ten runs in a project that had not adopted it invoked `dotdiw`
once, though it was on PATH throughout. Everything this achieves comes from what
`init` writes into the repo; being installed does nothing on its own.

All five runs in a project that had adopted it used it heavily, 18 to 67
invocations each -- and every one of them went wrong in the same two ways.

- [x] Declare where work starts, in the files agents read. Zero of five began
      with `create`. They opened with `--help`, `prime` or `list`, then
      enumerated `formula list`. Discovery fires on `create` and fired for none
      of them: with three formulas, browsing substitutes, and at the hundreds
      this is for, browsing finds nothing. The cause was that nothing ever wrote
      the convention down -- `init` renamed bd inside AGENTS.md and CLAUDE.md
      and left them stating bd's conventions and nothing about where work
      begins. `init` now writes the declaration into both, between markers so it
      survives bd rewriting those files, and `check` fails without it.
- [x] Answer `formula list` about the project. bd answers it about its own two
      search paths, so in a project whose formulas sit next to what they are
      about it says "No formulas found" -- true of `.beads/formulas`, false of a
      repo holding three formulas `check` calls discoverable. It was the first
      thing every agent reached for, sixteen calls across the five, and all five
      believed it and moved the formulas into `.beads/formulas/`, writing the
      breach of natural placement permanently into the repo. One committed it:
      "dotdiw only looks for formulas under .beads/formulas, so the two formulas
      at the repo root were invisible to it."
- [x] Pour from where the formula lives. `mol pour <id>` cooks by path first
      when bd does not know the id, so a formula never has to be moved or
      linked. `cook <id>` resolves to the file too. The chain was already
      sound -- `create` surfaces it, `cook --persist` registers it, `mol pour`
      gives tracked steps -- so the relocations were caused by signposting, not
      by a missing capability.
- [x] Print the durable handoff. `create` used to suggest `cook --persist &&
      mol wisp create`, whose wisp is ephemeral and never synced via git: that
      is management and sharing both given up at the moment of instantiation.
      It prints `mol pour <id>` now.
- [x] Check the conventions where someone actually looks. No agent ran `check`
      or `learn`. They ran bd's `doctor` and `lint`, so those two now carry the
      convention check as well.
- [x] Nudge at the point capture happens. Nobody in any of the fifteen wrote a
      formula. The instinct is plainly there -- the unadopted runs left
      `docs/adding-a-dish.md`, `docs/standing-procedures.md`, `docs/patching.md`
      and whole runbook trees -- but three of the five adopted runs reached for
      `remember` instead. `remember` now says, when what is being remembered
      reads like a procedure, that a formula can be matched and poured and a
      memory can be neither.

The same fifteen were run again against the fixed build, same prompts, same
paths, fresh agents. Nothing was relocated: five of five left their formulas
where they belonged, against none of five before. `formula list` went from
sixteen calls that all answered "No formulas found" to seven that all answered
truthfully. All five used `create` for the work, where before two did and never
as the entry point, and all five ran `check`, which none had. Four of five
poured the right formula without moving it. Issues created went from 6, 6, 1,
12, 13 to 7, 7, 7, 10, 10 -- the run that managed one issue before now pours a
whole procedure.

Two things did not move. Four of five still list the formulas before they
`create`, so the formula is found by browsing and not by surfacing -- harmless
at three, useless at the hundreds this is for. Replaying each run's own title
shows the browse was redundant: every one retrieves its formula at rank one, so
discovery alone would have carried all five. And nobody wrote a formula, in any
of the fifteen, in either round. The `remember` nudge fired three times and
changed nothing.

## Capture

Declaration is the capability a project is meant to exercise constantly --
every procedure worth repeating is one more formula -- and across thirty runs
it was exercised zero times. The instinct was never missing: the runs that
never adopted any of this wrote `docs/adding-a-dish.md`,
`docs/standing-procedures.md`, `docs/patching.md` and whole runbook trees. What
was missing was a way to land it in a format that can be matched and poured.

- [x] Make writing one cost a command. `formula new "<what it is for>"` writes
      the file: the id, a description seeded with the title and marked TODO,
      the examples, and placeholder steps. The expensive part of declaring a
      procedure was never the thinking, it was the TOML -- and prose was free.
      `check` rejects a file that still says TODO, so a scaffold counts as
      started and not as done.
- [x] Take the steps from the work itself. `formula new "..." --from <id>`
      reads an issue's children and the `blocks` edges between them and writes
      them out as steps in the order they were done. The highest-fidelity
      capture there is: the procedure as carried out, not as remembered
      afterwards.
- [x] Notice the undeclared procedure, structurally. Pouring a formula leaves
      a molecule behind; a parent that is not a molecule, with three or more
      children and at least one dependency among them, is that same shape built
      by hand. The procedure exists, in the tracker, where nothing can match it
      against a title or pour it again. `create`, `check`, `doctor` and `lint`
      all name it and print the `--from` line that converts it, and the notice
      stops once a formula reaches that title -- which is what writing it down
      means. This cannot misfire: the DAG is either there or it is not.
- [x] Say it in the declaration. The convention block in AGENTS.md and
      CLAUDE.md now names `formula new` and says to reach for it the moment you
      notice you are repeating yourself. Every fix that moved behaviour in the
      second round was one that landed in those two files; the one runtime
      nudge converted none of the three times it fired.
- [x] Point `remember` at the command. It used to say a formula would be
      better and leave the reader to `learn`; it prints the `formula new` line
      with the title already in it.

A fifth mechanism was built, measured, and dropped: matching a new title
against the titles the project has already used, to notice a procedure being
repeated before anyone writes it down. On 824 pairs of example titles drawn
from six projects -- same formula counted as the same procedure, different
formula as different -- it recovers 34 of 216 real pairs at a threshold of
0.20, and the operational rule (two or more earlier titles) then fires
correctly for 7 of 72 titles and wrongly for 5. At 0.40 it is precise and never
fires at all. The reason is structural rather than fixable: a formula is
reachable from a title because it aggregates a name, a path, a description and
several deliberately-varied examples, while two bare titles have only
themselves. "Production is down" and "The pager went off for auth 500s" are the
same procedure and share no word. So repetition is not lexically detectable
between titles, and the threshold survives only where a wrong answer is cheap
-- seeding a new formula's examples from earlier titles, in a file its author
is already editing, at 0.25.

The structural notice is the one shipped in its place, and it is the stronger
claim: it is a fact about the repository rather than a guess at what two
sentences have in common. It has since fired twice in the wild, both times
correctly, on the two runs that built a six-step DAG by hand -- but both had
already written the formula, so it has never yet been the thing that caused one
to be written. `--from` has never been run by an agent at all.

Discovery is unchanged by all of this: the same four-formula project scores
eleven of twelve, the self-documenting variant the same, and the real
repository's own fixtures report identically.

## What forty-four more agents did with it

Eleven domains this time -- the first five plus a vinyl pressing plant, a GP
practice, a seed bank, a mobile app team, a mixed farm and a county record
office -- each as three repos, thirty-three runs, 275 logged invocations. One
agent per repo on a small model, told the domain job and nothing about the
tooling, with the run's state absent from every path and one repo per parent
directory.

The three fixes that landed in the instruction files held at eleven projects.
All eleven adopted runs used `create` for the work, all eleven ran `check`,
all eleven poured the right formula, and not one moved a formula into
`.beads/formulas`. In the twenty-two projects that had not adopted it, zero
invocations -- twenty-two of twenty-two now, where it was ten of ten.

Two behaviours are worth recording for their own sake. One run edited a formula
in place and improved it: bumped the version, added a whole step for
reassigning the absent clinician's inbox with a dependency edge, sharpened
three step titles with the practice's own rules, and it still passes `check`.
Another opened an issue titled "Add a preparation step to the mol-calving
formula" and tracked the improvement rather than making it. Formulas being
edited in place is a thing the spec asks for and nothing had yet shown.

What did not move is `create` as the entry point: zero of eleven opened with
it, and eight of eleven listed the formulas first. They open with `ready`,
`prime`, `--help` or `--version`. The declaration says to start with `create`
and nobody does; what they do is reach it eventually, which is enough at three
formulas and will not be at three hundred.

## Capture, measured where it could fire

The thirty-three runs could not test capture, and neither could the fifteen
before them. Twenty-two of the thirty `create` titles the adopted runs actually
typed retrieved an existing formula -- the jobs were built that way so that
discovery had something to find. Authoring was never the right move, so zero
authored is not evidence about capture. That is a flaw in the trial, not a
finding about the tool, and it explains the earlier zero as well.

So: an eleventh-hour fourth state, the same adopted projects given work none of
their formulas covers -- hiring a kitchen hand, answering an FOI request,
regenerating an accession, taking on a new customer. Eight of eleven wrote a
formula, nine formulas in all, against zero of thirty-three where one already
existed. Every one passed every content rule -- description long enough, three
or more examples, each example retrieving its own formula, no scaffold marker
left -- and every one sat in a natural place in the tree. Only two reached for
`formula new`; two more read its help and wrote the TOML by hand, and four
wrote it by hand without looking. The scaffold is a minority path. What did the
work was the declaration naming formulas as the vehicle, which is the same
lever that moved everything in the round before.

- [x] Let the project's own declaration satisfy bd's git policy. All nine of
      those formulas were uncommitted, which by this design's own rule means
      the project held none of them. The cause was a contradiction in one file:
      bd's instruction files carry a "Conservative (default)" profile saying not
      to run git commits unless explicitly asked, and the declaration appended
      below it asks for exactly one. The stricter sentence won every time -- one
      agent wrote a note saying the formula was uncommitted so nobody could find
      or pour it, opened a child issue for the commit, and still did not commit.
      Saying in the declaration that the commit is the last step of writing the
      formula moved it to three of nine. Putting the exception inside bd's own
      sentence, through the escape hatch bd already wrote into it, moved it to
      seven of nine: eight formulas committed, every repository's `check`
      clean, and a formula written and committed by one agent retrieved at rank
      one from a different title afterwards.

Those three figures -- none, three, seven -- are three passes over the same
eleven fixtures with the same prompts and fresh agents each time, so each is
one sample of eleven from a stochastic model and the trend is worth more than
any of the points. The two that still did not commit both read the no-git line
from `prime` rather than from the file.

## Above four formulas, which is the number this is for

Every measurement above used two to four formulas per project. The design is
for hundreds. Pooling every formula written across the trials -- the eleven
domains' fixtures, the nine blind agents authored, acme's, and trial1's
example-less ones as distractors -- gives 56 distinct formulas and 163 example
titles in one repository, with all 123 prose documents as one fixed background
so that formula count is the only thing varying. Random subsets at each count,
eight per point:

      formulas    recall@3    uncovered titles left silent
         3          0.95                0.84
         8          0.96                0.52
        12          0.96                0.38
        20          0.96                0.27
        30          0.96                0.17
        44          0.93                0.06
        56          0.93                0.03

Retrieval scales and silence does not. The right formula still comes back in
the top three against fifty-five competitors almost exactly as often as
against two. But by fifty-six formulas, thirty-two of the thirty-three titles
naming work that nothing covers retrieve something anyway. Extrapolated, a
project with hundreds of procedures answers every title with three formulas,
and some of them will be wrong every time.

This is not the threshold being badly chosen. With N formulas there are N
chances for one to clear a fixed fraction by coincidence, so the obvious
replacement is to judge the best match against the others for the same title
rather than against a constant -- for work the project really holds a procedure
for, one formula should stand far above the rest. Measured at z >= 1.5, 2.0 and
2.5 over the same grid, it does not help: silence at fifty-six formulas is 0.03,
0.03 and 0.12, and the one setting that buys anything costs recall and turns
erratic (0.64 at eight formulas).

The reason is in the hits themselves, and they are not errors:

    "Replace the waiting room chairs"   -> drain-node       0.45
    "Repair the gate into Mill Field"   -> spray-window     0.44
    "Sell the old grain trailer"        -> share-transfer   0.22

`drain-node` says "replace" and "waiting", because draining a node means
replacing it and waiting for connections to finish. `spray-window` names Mill
Field. `share-transfer` says "sell". Each shares the title's genuinely
distinctive words, so each is the right document by word overlap and the wrong
procedure for the work. No threshold and no distributional test separates them,
because there is nothing in the words to separate.

So the design holds at tens of procedures and its silence property fails at
hundreds. That matters beyond a noisy hint: a false hit at `create` is what
stops anyone learning that nothing covers their work, which is what suppressed
formula authoring when the formula already existed -- zero of thirty-three
there, eight of eleven where nothing covered the job. At scale that suppression
becomes permanent.

Two caveats on the measurement. The 56 are pooled from eleven unrelated
domains, so a kitchen-hand title competes against archive and farm formulas;
that is the easy case for silence, and it still failed, so one organisation's
own three hundred procedures should be worse rather than better. And nothing
here tests the harm directly -- that three wrong suggestions at `create`
degrade an agent's behaviour is inferred from the capture result, not measured
at scale.

Telling "replace a chair" from "replace a node" needs something that reads the
title rather than counting its words.

### A correction to the numbers above

Eleven of the thirty-three negatives were not negatives. They were written when
each project held three formulas, as titles naming work none of them covered;
pooling then added the nine formulas blind agents had written -- for exactly
those jobs. So the first negative of every project had become a positive, and
both the table above and the outlier sweep were counting correct retrievals as
failures. Re-measured on the twenty-two that are still uncovered, bm25 reads
0.88 silence at three formulas and 0.05 at fifty-six, against 0.84 and 0.03;
recall is unchanged at 0.94 and 0.93. The collapse is real and the correction
does not soften it, but the figures in the committed table are the
contaminated ones and these are the ones to use.

## Whether a local model closes it

The spec forbids per-person configuration, so an API key is out, but a model
on the machine is a day-0 install like beads and git and is permitted. Two
kinds qualify: one that scores, and one that judges. Only the first was
tested. Tested with nomic-embed-text-v1.5 Q8_0 through
llama.cpp, on the same pooled corpus, the same 163 positives under
leave-one-out and the same 22 clean negatives. The cutoff is swept rather than
chosen.

The first attempt mean-pooled one string per formula -- name, directory,
description and every example concatenated -- which dilutes: a title close to
one example is averaged against three it has nothing to do with. Scoring each
formula by its closest part instead cut the uncovered titles' 90th-percentile
best match from 0.810 to 0.639, against a real-title median of 0.663. That is
the measurement worth reporting, and at fifty-six formulas it reads:

                        recall@3   silence
      bm25, 0.15          0.93      0.05
      embeddings, 0.55    0.85      0.09
      embeddings, 0.60    0.74      0.50
      embeddings, 0.65    0.55      0.91

At recall parity with bm25 there is no improvement: 0.85 and 0.09 against 0.93
and 0.05. But the 0.65 row is the first rule measured here whose silence does
not collapse -- 1.00 at three formulas, 0.91 at fifty-six, nearly flat across
the range where every other rule falls off a cliff. It costs 38 points of
recall to get there.

So embedding similarity works, and it forces a choice: find 93 per cent of the
procedures that apply and never be silent, or find 55 per cent and be silent
nine times in ten. A hybrid does not escape
it either -- bm25 shortlisting and the embedding cutoff filtering cannot
recover a formula the cutoff rejects, and rejecting the right formula is where
the recall goes.

What separates the two options is not accuracy but kind. A cutoff on a
similarity score is the same instrument that failed as COVERAGE, as the
two-word rule, and as the outlier test; it fails the same way each time because
the two populations overlap and no point on a line separates overlapping
distributions. A model asked "do any of these apply?" returns a decision, and
"none" is an answer rather than a number someone has to cut.

That second kind was not tested, and the spec does not rule it out. A local
instruct model installs exactly as the embedding model does -- `depends_on`
through brew, once per machine, nothing configured per person -- and it
judges rather than scores. So the open question is not whether the
configuration constraint has to be relaxed. It is whether a judging model,
local and permitted, gives recall and silence together where no scoring rule
has. Until that is measured, nothing here supports a claim about the limit of
what the spec allows.

Caveats. One model, one quantisation, mean pooling within each part, and the
document formulation turned out to matter a great deal -- the first attempt was
materially worse than the second, so a third might be better again. The 56
formulas are pooled from eleven unrelated domains, which favours silence. And
nothing here measures whether 0.55 recall is worse in practice than 0.05
silence; that depends on what a missed procedure costs against what a wrong
suggestion costs, which is a question about a project and not about a ranker.

## dotdiw learn

- [x] `dotdiw learn` prints everything a human needs to do all four right with
      no one to ask. One section per capability, each ending in the exact
      command to type.
- [x] Management: work starts with `dotdiw create "<title>"`. That is the whole
      convention — state, dependencies and ordering follow from it.
- [x] Declaration: a formula is TOML — a description, steps, and `needs` edges
      between them. Show one complete formula, small enough to read in full.
- [x] Sharing: commit the formula. Git distributes it; there is nothing else to
      publish and nowhere else to put it.
- [x] Discovery: it fires on `dotdiw create` and matches the title against
      descriptions, so the description is the mechanism, not a label on one.
      Show a description that failed and the rewrite that fixed it.

## Enforcing the conventions

- [x] Formula path. Any directory, but it must be committed. Untracked means
      invisible, which is the sharing convention made mechanical.
- [x] Warn when bd can see a formula dotdiw cannot — one in `~/.beads/formulas/`
      works for its author and for nobody else.
- [x] Description. Reject the four-word name. It has to be a sentence naming
      the situation, carrying the clause that says when to use it.
- [x] Example titles. Each formula carries several, phrased the way people
      actually title work. bd tolerates the extra top-level field.
- [x] Retrieval self-test. Run each example title through the ranker and fail
      any formula its own examples do not retrieve in the top three.
- [x] `dotdiw create` runs the check quietly and prints only failures, so the
      moment that fires for discovery is the moment that enforces.

## Day 0

- [x] Write the brew formula, `depends_on "beads"`.
- [x] Verify PATH from a login shell, a non-login shell, and a spawned
      subprocess.

## Day 1

- [x] `dotdiw init` for a project without it: initialise beads. Formulas need
      no directory of their own.
- [x] Bare `dotdiw` prints what `dotdiw learn` prints, so the command teaches
      whoever found it on the machine.
- [x] Update SPEC.md, which still said `bd create`. Rewritten as a spec: it
      names no tool at all.

## What `init` changed in a repository, by version

Kept here from the README, where it stood until 0.4.1: an adopter wants what
`init` does now, and this is what it did.

- v0.1.0 said nothing is configured per project; in fact `init` called `bd
  init`, and bd created `.beads/`, its issue database, and committed its own
  files; set `core.hooksPath` to `<repo>/.beads/hooks`, copying the hooks
  already in `.git/hooks` into that directory and appending its own block, so
  hooks present at adoption kept running and hooks added to `.git/hooks`
  afterwards did not, since git reads one hook directory; configured a Dolt
  remote aimed at the repository's git remote, so the issue database was
  pushed into the repository with its full history; and left bd's telemetry
  enabled, which ships on by default.
- v0.2.0 declined the hooks, removed the Dolt remote, and said what it did.
  Any invocation in a repository adopted by v0.1.0 also put both back and
  printed what it undid. Nothing was deleted and no history was rewritten;
  hooks that existed at adoption went on running, and a hook added after
  adoption was skipped until the repair, so commits made in between did not
  see it.
- v0.2.1 turned bd's anonymous usage metrics off before running any bd
  command: `bd metrics off`, which writes `metrics.disabled: true` to
  `~/.config/bd/config.yaml`, per machine, on every run, so `bd metrics on`
  does not hold.
- v0.3.0 ran bd in its stealth mode, which commits nothing and configures no
  remote, but still kept `.beads/` in the working tree.
- v0.4.0 moved the tracker's state under the home: one key in the checkout's
  `.git/config`, `bd init --stealth --skip-hooks --skip-agents` under
  `~/.dotdiw/<key>/`, told where through `BEADS_DIR`. bd's init records its
  role beside the key, `beads.role=maintainer`, the answer it would otherwise
  prompt for; dotdiw neither writes nor reads it. The dated entries below
  have the detail.

## 2026-11-01: init in bd's stealth mode

- [x] `bd init --stealth` commits nothing, writes nothing for agents,
      configures no remote, and keeps `.beads/` local to the checkout through
      `.git/info/exclude`. 0.2.0 and 0.2.1 used bd's default init with
      `--skip-hooks`, removed the sync remote afterwards, and reported the
      files left modified; that report did not include `.beads/config.yaml`,
      the file the removal had changed.
- [x] From 0.3.0 `init` runs `bd init --stealth --skip-hooks`. bd commits
      nothing; dotdiw writes the declaration into `CLAUDE.md` and `AGENTS.md`
      and names them as the worker's to commit; the printed command leaves the
      tree clean, and a test runs it. Outside a git repository init refuses
      (bd would otherwise `git init` on the worker's behalf). A clone is told
      to run init once -- which was always needed, since bd's database was
      never in git, and never said.
- [x] Repositories adopted by 0.1.x are repaired as before; those adopted by
      0.2.x are told the one command, `git rm -r --cached .beads && git
      commit`, on init, check, doctor and lint, with the exclude written so the
      files stay out once gone. dotdiw never runs it.
- [x] What stays of the repair: the hook override and the Dolt remote for
      0.1.x adoptions, and the notice, now worded by who did what it undid.
      The numbers above were measured with bd's agent files present, renamed;
      whether agents do as well without them is the next round's question.

## 2026-11-01: the tracker's state leaves the repository

- [x] `init` keys the checkout with one line in its own `.git/config`,
      `dotdiw.workspace`, and runs `bd init --stealth --skip-hooks
      --skip-agents` under `~/.dotdiw/<key>/`, told where through `BEADS_DIR`;
      every command sets the same, so bd never sees the repository. The
      repository holds only the formulas and the declaration. Two facts the
      design rests on: `BEADS_DIR` alone does not stop the sync remote and
      `--stealth` does; and a tracker can be made under the home while an old
      `.beads/` still sits in the tree, after which bd with `BEADS_DIR` uses
      the new one and never the old.
- [x] The key survives a move, worktrees share it, clones do not: a clone runs
      `init` once, which every version in fact required and none said.
- [x] A repository adopted by any earlier version is upgraded by its first
      command, with its prefix read from the in-tree metadata; its tasks are
      not carried over, which is said once together with the command that
      removes the unused copy. dotdiw neither runs that command nor edits the
      copy; only the hooks-path repair of v0.1.0 remains, because it decides
      which hooks git runs.
- [x] Measured: a create under the home costs what it cost in the tree,
      0.40 s for bd's part. Whether agents do as well without bd's agent files
      is the question of the next round.

## 2026-11-01: the tracker is not named

- [x] Nothing dotdiw prints names bd or beads. The install line when the
      tracker is missing is Day 0's command; the metrics notice names the
      tracker and the file; `--version` reports `tracker <number>`, the
      number taken from bd's own version string; the rename lines say how many
      files now name dotdiw; the formula problem line says the tracker finds
      it. The name survives only inside the paths of bd's own files on the
      machine, `~/.config/bd/config.yaml` and `.beads/`.
- [x] The `--version` line had breached `invariant.one-name-for-all-four`,
      which says bd's name is not in the version reported, and nothing checked
      it. `test_promise.py` now reads every string literal in `dotdiw` and
      allows the word only inside those paths and as the executables' names;
      `test_dotdiw.py` runs the three messages that changed shape.
- [x] The README says what `init` does now and names no dependency; the
      history by version is above. The dependency is declared where
      declarations belong: `carrier.beads` in `product.yaml`,
      `boundary.dotdiw-to-beads` in the model, `depends_on "beads"` in the
      tap's formula.

## 2026-11-02: every operation through one door

- [x] Every operation is invoked through one door, `invoke`, by its id and
      with a request. The door's table is generated from `operation-idl.json`
      into `dotdiw`, between markers, by `poa/finish-idl.py`, which says
      whether that changed the file. The request is held to its type on the
      way in and the response to its own on the way out; a key outside
      either raises, naming the operation and the key, because that is the
      project's mistake and not a worker's situation.
- [x] The types are true. The request types carry what the bodies decide by
      and the response types what the terminal and the witness read, as four
      shared record types and typed fields; the in-memory index and the
      parsed formulas travel in no response. Sixty-four types, sixty before.
- [x] No body prints and no body writes the witness log. The door appends
      the log from the response and shows the response as its operation
      returns, through the presenter `main()` installs; a transport without
      a terminal installs none and runs the same bodies. The tracker's own
      stream is the one thing shown that no response carries, and the
      forward step is marked terminal-bound.
- [x] Nothing a worker sees changes: seventeen commands against 0.4.1 print
      the same bytes, the tracker's random ids normalised. `test_dotdiw.py`
      is unchanged and passes.
- [x] `test_promise.py` holds the door from the source and the IDL: the
      table is a fresh generation, a body is reached only through the door,
      `main()` calls only infrastructure and the door and invokes only
      operations the IDL binds to the command line, nothing behind the door
      touches a stream, and the door raises naming the operation and the
      key. Each test fails on a mutation of `dotdiw`.
- [x] The create path stays under one second: 0.893 s through the door
      against 0.922 s on 0.4.1, back to back on an idle machine, the tracker
      alone 0.45 s in both. The harness and the runs are under
      `measurements/`.
- [x] The record: `invariant.one-door` in the model, upheld by every
      operation; the door as a projection of kind `python-dispatcher`; the
      change `change.every-operation-through-one-door`, with no migration
      since nothing a worker sees changes. `promise_bindings.py` stays the
      import-only shim the conformance harness calls through.

## 2026-11-03: the tracker behind a door of its own

- [x] What dotdiw asks of a tracker is an interface of the IDL: ten
      operations -- open, describe, create, add a need, pour steps, close,
      show, list, update, ready -- with typed requests and responses, and a
      second door, `invoke_tracker`, generated into `dotdiw` between its own
      markers by the same finisher. The adapter that answers is chosen per
      request, else by `dotdiw.tracker` in the checkout's `.git/config`, else
      by the one store the workspace holds, else `local`. An unknown name is
      a failed response that lists the registered ones.
- [x] Two adapters ship inside the file. `local` is one sqlite file,
      `~/.dotdiw/<key>/dotdiw.sqlite`, items, edges and meta, ids
      `<prefix>-<four of a-z0-9>`; it composes a pour itself and closes a
      poured root when its last step closes. `beads` is the tracker of every
      version before, moved inside an adapter with everything that existed
      only to contain it: the two runners, the pty, the stream rewrite, the
      stealth flags, the metrics file, `BEADS_DIR`. Open, create and pour
      run its own commands with the worker's terminal when the request
      carries one, so its bytes are its own; everything else answers quietly
      through its JSON. Nothing outside the adapter runs the binary, and
      `test_promise.py` holds that from the source.
- [x] The default is `local` for a new adoption. A checkout adopted by 0.4.0
      or 0.5.0 holds a beads store and no choice: its first 0.6.0 command
      writes `dotdiw.tracker = beads` and says so once. Under beads the
      twenty commands print the bytes 0.5.0 printed, ids normalised;
      `--version` gained the tracker line and `learn` the tracker paragraph.
- [x] Under the store dotdiw brings, `list`, `ready`, `show`, `close`,
      `update` and `dep add` are answered from its records in the shape the
      tracker printed; `--help`, `-h` and `help` print the conventions text,
      as bare `dotdiw` does, since the tracker's help is the pass-through's
      to give; any other command is refused in one line.
- [x] `dotdiw tracker list`, `use`, `check` and `migrate`; `init --tracker`;
      `--tracker` and `DOTDIW_TRACKER` for one command. A migration lists
      the source, creates parents before children, keeps an id where the
      target accepts it and records the mapping in
      `~/.dotdiw/<key>/migration-<from>-to-<to>.json` where it does not,
      adds the needs, sets the statuses and closes in passes; run again it
      moves nothing, and the source is never written.
- [x] A tracker that is not on the machine is a module under
      `~/.dotdiw/trackers/<name>.py` exposing `TRACKER`. `trackers/jira.py`
      is one: Jira Cloud over its REST API, issue links as needs, credentials
      from the environment or its own file under the home, proved against a
      stub in `test_jira.py` and never run against a live site.
- [x] `trackers/README.md` says how an adapter is written: the module and
      the two names it is handed, the table and what registration refuses,
      the records and what the check expects of each operation, the three
      rules that are the adapter's, credentials, the check, the choice and
      the one file to ship. `trackers/write-tracker-adapter.formula.toml`
      holds the same steps, so naming the work surfaces them; `dotdiw check`
      finds seven formulas. The README at the root does not point there.
- [x] A loaded adapter's mistake is the worker's situation, not the
      project's: an operation or extra that raises, or an answer outside
      the interface, is a failed response in one line naming the adapter,
      the operation and the error, `adapter-failed` in every tracker
      response's reasons; a module under the home that raises on load, or
      whose table is out of shape, is listed by `tracker list` as not
      loaded and refused by name with the reason. A shipped adapter's
      mistake raises as before. Found by trying it: a raising adapter had
      printed a traceback.
- [x] One scenario defines an adapter. `test_tracker.py` runs it, the one
      `tracker check` runs, through the door against every adapter present,
      then moves a filled workspace between every ordered pair and back. The
      contract's story is valid under `local` with no binary on the path.
      `measurements/measure/mutate_tracker.py` breaks one promised rule at a
      time; fourteen of fourteen are caught, after one test was sharpened by
      the mutation that first survived it.
- [x] A create through `local` takes 0.134 s at the median; through `beads`
      0.903 s against 0.893 s on 0.5.0, the binary alone 0.42 s, the law
      under one second on both. The runs are in `measurements/results/`.
- [x] The records: the tracker and its adapters as objects of the model, the
      boundary generalised, the interface's operations bound once per
      adapter in the IDL, and the change recorded as strengthening with its
      migration plan; the README says what a worker sees, which is nothing
      new unless they choose a tracker. Forty-two operations, a hundred and three
      types.

Not in 0.6.0: beads stays a dependency of the tap's formula, so that a
checkout on it changes nothing by upgrading. 0.7.0 makes it optional, drops
it from the formula, and names it only where it was chosen.

## 2026-11-04: typed from the IDL, formatted and linted

- [x] Every request, response and shared record of the IDL is a class in
      `dotdiw`: 93 `TypedDict`s generated by `poa/finish-idl.py` between
      markers of their own, beside the two doors, the required fields
      `Required`, the rest absent or `None` as the doors read them, every
      inline enum a `Literal`. The bodies take and answer those classes,
      and the shipped adapters answer the interface's, which mypy holds at
      check time. An adapter's answer is also held at run time, since a
      loaded one is not checked by anything else.
      `test_promise.py` regenerates the region and compares it, and holds
      every class to the IDL's fields and required keys.
- [x] Every function in `dotdiw` is annotated, 155 of them, and `mypy
      --strict` passes on the tool, `promise_bindings.py`, the Jira adapter
      and the generator; the tests are checked with the tool's types and not
      annotated. From 1709 findings to none, by typing rather than by
      silencing: no `type: ignore`, five casts, each saying why.
- [x] Three things the types found. Twenty-one bodies read `root` from a
      request the IDL did not require it on; the IDL now requires it there.
      `update-item` refuses a status of `closed` it could not, by its own
      type, be asked for; the request's enum now admits it. A shared failure
      constant was copied into responses of every type; `failed_as` builds
      one in the caller's own type instead, and `tracker_unknown`,
      `adapter_failed` and `beads_failed` answer in the caller's type too.
- [x] The tree is formatted and linted with ruff, line length 100, every
      finding fixed: 391 to none across 42 files, the generated regions kept
      out of the formatter. The Python floor is 3.11, written in
      `pyproject.toml` beside the tools' versions; `uv.lock` pins them and
      `.python-version` pins 3.12, the tap's interpreter. The `tomllib`
      fallback for older interpreters is gone with the floor.
- [x] `check-promise-artifacts.formula.toml` is version 4, with a lint step
      and a type step; `test_promise.py` holds `pyproject.toml`'s version to
      the version line. The four suites pass under 3.12 and 3.14; the mutations, retargeted at
      the formatted source, are each caught; the
      IDL's fourteen checks, the contract, its five replays, the sweep and
      the conformance harness's 426 pass.

## 2026-11-04: a move that finishes, answers held to their values

- [x] `tracker migrate` keeps a record of what is finished, not only what was
      made. The mapping is saved as each item is made, so a run that dies does
      not make that item twice. Needs already written and items with nothing
      left to write are recorded beside it, and the next run finishes the
      needs, statuses and closes of every item not yet finished, whichever run
      made it. A need, status or close the target refuses fails the move and
      names it, where before the answer was ignored and the move reported
      completed. A closed item the target will not close because its need is
      still open fails the same way. A finished move writes nothing on a
      second run.
- [x] The tracker door holds an adapter's answer to its type down to the
      values: a record's fields, each item of a list, the values of an enum,
      and a completed answer must hold the record its callers read. From a
      loaded adapter a wrong value is the same one line as any other failure,
      where before it passed the door and raised wherever it was first read.
      The classes generated from the IDL are what it checks against, through
      a `responseType` the generator adds to each row of the door's table.
- [x] Metrics go off before bd is first asked anything in a run, whichever
      adapter the checkout chose. The door does it the first time it reaches
      an adapter that offers `metrics-off`, so `tracker list`, `check`, `use`
      and `migrate` under local are covered, and the notice is still said
      once. A run that never reaches bd never runs it.
- [x] The local adapter takes the write lock before its first read in every
      write, with `BEGIN IMMEDIATE`, so that what a check saw still holds when
      its write commits, across processes. A store another writer holds past
      the five seconds it waits is a failed response in one line.
- [x] The checkout's choice is written after the store opens, so a switch that
      fails leaves the checkout on the tracker that works.
- [x] A formula's steps may need steps declared after them; declaration order
      is no part of a formula. A need naming no step is `step-not-found`, a
      cycle among the steps is `cycle`, a new reason on pour-steps and
      pour-procedure, and neither writes anything. All three adapters.
- [x] A description given to `create` is saved on the item, carried through
      `name-the-work` to `create-item`; under beads it already was, as typed.
- [x] `--json` under an adapter that answers in records prints JSON on
      `create`, `close`, `update`, `dep add` and `mol pour`, as it already did
      on `list`, `ready` and `show`. `list` and `ready` draw a tree to any depth,
      in the lines the tracker draws, and an item in a loop of parents is still
      printed.
- [x] The Jira adapter searches through `/rest/api/3/search/jql` and its
      `nextPageToken`, the legacy endpoint being marked as being removed in
      Atlassian's OpenAPI document; the stub answers the legacy one with 410.
      It assigns through `PUT /issue/{key}/assignee` with `accountId`, the
      form that document gives. A close with no transition to done, or an
      update with none to the status asked, is refused and leaves the issue as
      it was, and a close is read back before it is reported. Priority 0 stays
      0. An issue already in the status category asked for needs no transition.
- [x] The conformance scenario asks these of every adapter: priority 0 kept, a
      need on a later step, `step-not-found`, `cycle`, and a refused pour
      writing nothing. Fourteen more mutations, one per rule, are each caught;
      the table is in `measurements/results/mutation-tracker.txt`.
- [ ] The one-second law read on an idle machine. Alternating single runs under
      other load put this tree 77 ms behind 0.5.0 under beads, 1.011 s against
      0.934 s; a command that runs no tracker went from 56 ms to 101 ms, most of
      it compiling a longer script on every run. The runs are in
      `measurements/results/time-create.txt`.
- [ ] `show` does not print a description and `tracker migrate` does not carry
      one, since the item record has no such field.
