# measurements

What was measured about dotdiw, and the apparatus it was measured with. Nothing
here is part of the tool; it is kept so that the claims can be checked rather
than taken on trust.

Ground truth throughout is a log of every `dotdiw` invocation plus the repository
diffs, never what an agent said it did. Several of the numbers below changed
because the log disagreed with the summaries.

## Layout

    fixtures/domains3.py     eleven domains: their files, formulas and the job
                             each run was given
    harness/                 builds the matrix, writes the prompts, scores the
                             runs from the log and from git
    measure/                 the retrieval sweeps, each one answering a single
                             question and reporting the whole trade rather than
                             a chosen point
    results/                 the invocation logs, the scores, the run maps
    workflows/               the two orchestration scripts that ran the agents

## What each measurement answers

| | |
|---|---|
| `verify.py` | the four-formula fixtures, the baseline every change was checked against until 2026-11-01, when dotdiw dropped the functions it calls; the fixtures are not in the repository |
| `rank_between.py` | from 1.0.0: whether a version surfaces what the version before it surfaced -- every title `verify.py` was written against and every committed example, ranked under an earlier version read from git and under the tree, over this repository and a checkout of the README's example formula, with each version's self-test; the run is in `results/rank-between.txt` |
| `cover_sweep.py` | how low the silence threshold can go before a formula stops retrieving its own examples |
| `words_sweep.py` | whether requiring two shared words beats raising the threshold (it does not) |
| `echo_sweep.py` | whether a repeated procedure can be noticed by matching one title against earlier titles (it cannot) |
| `pool.py` | collects every real formula written across the trials into one project |
| `scale.py` | recall and silence as formula count rises from three to fifty-six |
| `outlier.py` | whether judging a match against its competitors rather than a constant recovers silence (it does not) |
| `clean_scale.py` | both sweeps again, after eleven negatives turned out to have become positives |
| `embed_build.py`, `embed_scale.py` | the same curves with a local embedding model |
| `embed_max.py`, `max_scale.py` | the same, scoring each formula by its closest part rather than one mean-pooled string |
| `occasion.py` | whether capture ever had an occasion to fire: twenty-two of thirty titles were already covered |
| `harness/witness.py` | from 0.3.0: scores a round from the runs' own witness logs through the contract in `../contracts`, so "discovery fired" is what the contract calls `valid` or `caveated` and not a judgement made by hand; earlier rounds have no logs and are not re-scored |
| `time_create.py` | from 0.5.0: the create path's wall time, ten runs of `dotdiw create` against ten of bare `bd create` in the same tracker, so that the difference is dotdiw's own part; the law is one second. From 0.6.0 it times `create` under the shipped default adapter or the one `--tracker` names, and the bare tracker only under beads |
| `mutate_tracker.py` | from 0.6.0: whether the tests that hold the tracker door bite, and from 1.0.0 those that hold an item's kind and the means to prove a run -- a hundred and ninety-two mutations, each breaking one promised rule in a copy of the working tree, each with the test that must fail on it and pass on the copy unbroken, or the mutation is counted missed; the table is in `results/mutation-tracker.txt`. The mutations name source lines as they stand, so a reformatting of `dotdiw` retargets them. The copy of the tree, and every store a test makes in it, is kept on a RAM disk made for the run where the machine offers one, as the suites that run bd keep theirs |

## The runs

Three states in `runmap3.tsv` — a project not started, started without any of
this, started with it — across eleven domains, thirty-three runs. One agent per
repository on a small model, told the domain job and nothing about the tooling,
with the state absent from every path and one repository per parent directory so
that nothing could be inferred by looking around.

`runmap4.tsv` is a fourth state added afterwards: the same adopted projects given
work none of their formulas covers. The first three states could not test
whether anyone writes a formula, because every job they were given was already
covered by one.

`invocations-round3-uncovered-pass1/2/3.log` are three passes over the same
eleven fixtures with the same prompts and fresh agents, measuring one wording
change each time. Each is one sample of eleven from a stochastic model, so the
trend across them is worth more than any single figure.

## Discovery

- Retrieve with SQLite's FTS5, which the interpreter already ships: bm25()
  ranking and a porter stemmer. Nothing hand-rolled and nothing installed.
  A word is now worth what it is distinctive, not one point like every
  other word, and "failing" reaches "fail".
- `dotdiw create "<title>"` runs the create, then ranks the project's
  formulas against the title and prints the top three.
- Find formulas with `git ls-files '*.formula.toml'`. Anywhere in the tree,
  next to whatever they are about. The directory does not matter.
- Fold the path into the matchable text.
  `services/billing/release.formula.toml` matches on "billing" and
  "release" without the description repeating them.
- `bd cook` takes the path, so nothing is copied or linked into `.beads/`.
- Index the project's own tracked text beside the formulas -- up to 300
  files, 100KB each -- and never return it. It is there so bm25 can see
  which words are everyday ones here. Against four documents of prose
  "version" was distinctive enough to pull the release formula up for a Go
  toolchain bump; against twenty-two it is not.
- Show a formula when it accounts for at least 0.15 of what is distinctive
  about the title, measured as the share of the title's word weights the
  formula holds. bm25's scale depends on how much text a project has, so no
  absolute threshold means the same thing in two projects. A fixed floor
  silences every match in a project with one formula and one README, where
  bm25's idf is zero by construction. Ordering is bm25's.
- Stop list is function words only. Nothing with meaning belongs on it:
  "down" is the outage formula's best word.
- Leave-one-out self-test: take the example out of the index before
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

- Declare where work starts, in the files agents read. Zero of five began
  with `create`. They opened with `--help`, `prime` or `list`, then
  enumerated `formula list`. Discovery fires on `create` and fired for none
  of them: with three formulas, browsing substitutes, and at the hundreds
  this is for, browsing finds nothing. The cause was that nothing ever wrote
  the convention down -- `init` renamed bd inside AGENTS.md and CLAUDE.md
  and left them stating bd's conventions and nothing about where work
  begins. `init` now writes the declaration into both, between markers so it
  survives bd rewriting those files, and `check` fails without it.
- Answer `formula list` about the project. bd answers it about its own two
  search paths, so in a project whose formulas sit next to what they are
  about it says "No formulas found" -- true of `.beads/formulas`, false of a
  repo holding three formulas `check` calls discoverable. It was the first
  thing every agent reached for, sixteen calls across the five, and all five
  believed it and moved the formulas into `.beads/formulas/`, writing the
  breach of natural placement permanently into the repo. One committed it:
  "dotdiw only looks for formulas under .beads/formulas, so the two formulas
  at the repo root were invisible to it."
- Pour from where the formula lives. `mol pour <id>` cooks by path first
  when bd does not know the id, so a formula never has to be moved or
  linked. `cook <id>` resolves to the file too. The chain was already
  sound -- `create` surfaces it, `cook --persist` registers it, `mol pour`
  gives tracked steps -- so the relocations were caused by signposting, not
  by a missing capability.
- Print the durable handoff. `create` prints `mol pour <id>`. `cook --persist
  && mol wisp create` would leave a wisp, which is ephemeral and never synced
  via git.
- Check the conventions where someone actually looks. No agent ran `check`
  or `learn`. They ran bd's `doctor` and `lint`, so those two now carry the
  convention check as well.
- Nudge at the point capture happens. Nobody in any of the fifteen wrote a
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

- Make writing one cost a command. `formula new "<what it is for>"` writes
  the file: the id, a description seeded with the title and marked TODO,
  the examples, and placeholder steps. Writing the TOML was the cost of
  declaring a procedure, and prose cost nothing.
  `check` rejects a file that still says TODO, so a scaffold counts as
  started and not as done.
- Take the steps from the work itself. `formula new "..." --from <id>`
  reads an issue's children and the `blocks` edges between them and writes
  them out as steps in the order they were done. It records the procedure
  as it was carried out.
- Notice the undeclared procedure, structurally. Pouring a formula leaves
  a molecule behind; a parent that is not a molecule, with three or more
  children and at least one dependency among them, is that same shape built
  by hand. The procedure exists, in the tracker, where nothing can match it
  against a title or pour it again. `create`, `check`, `doctor` and `lint`
  all name it and print the `--from` line that converts it, and the notice
  stops once a formula reaches that title. The check reads the DAG, so it
  cannot misfire.
- Say it in the declaration. The convention block in AGENTS.md and
  CLAUDE.md now names `formula new` and says to reach for it the moment you
  notice you are repeating yourself. Every fix that moved behaviour in the
  second round was one that landed in those two files; the one runtime
  nudge converted none of the three times it fired.
- Point `remember` at the command. It prints the `formula new` line with the
  title already in it.

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

- Let the project's own declaration satisfy bd's git policy. All nine of
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

## The create path

The one law with a number: `dotdiw create` under one second, since it runs
before every piece of work. `measure/time_create.py` times ten creates through
dotdiw and ten through the bare tracker in the same adopted repository under
an isolated home, on an idle machine; `results/time-create.txt` holds the
runs. On 2026-11-01, once the tracker's state had moved under the home, a create
cost what it had cost in the tree: 0.40 s for bd's part. On 2026-11-02, back to
back on one machine: 0.4.1 median 0.922 s with
the tracker alone at 0.448 s, so dotdiw's own part 0.474 s; the one door
(0.5.0) 0.893 s with the tracker at 0.452 s, its own part 0.441 s. The door
costs nothing the harness can see, and the index built once per process gives
a little back. A sample taken while anything else runs is load: one read
1.042 s with two test suites running and was discarded.

On 2026-11-04, under load and so not a reading of the law, alternating single
runs put what became 0.6.0 77 ms behind 0.5.0 under beads. A command that runs
no tracker went from 56 ms on 0.5.0 to 101 ms, about half of it compiling a
longer script, which has no cached bytecode, on every run.

On 2026-11-05, under load and so not a reading of the law, alternating single
runs read 0.869 s on 0.5.0, 0.934 s on 0.6.0 and 0.933 s on 0.7.0 under beads at
the median, and about 0.2 s under local. Under heavier load they read 1.028 s,
1.083 s and 1.081 s. 0.7.0 costs nothing against 0.6.0.

## Caveats, and two things removed

The scripts were written against a scratchpad directory and carry its absolute
path as a default. Set `DOTDIW_SIM_ROOT` to run them anywhere else. The default
is left in place so that what is committed is what produced the results.

`invocations-round1.log` has seventeen lines removed. A logging shim installed
for the first round captured the author's own `dotdiw` calls as well as the
simulations'; those are not simulation data. Later rounds used a shim that logs
only from inside the matrix, and captured none.

Rounds one to four were built with the init of their day, which let bd commit
its own files into each fixture repository; the agents saw bd's agent files
with bd renamed, plus dotdiw's declaration. From 0.4.0 init puts the tracker
under the home and writes no agent files, so a new round is built with that
init -- the harness's `HOME` is the sim root's, and each run's log is at
`$HOME/.dotdiw/<key>/witness.jsonl`, the key read from the run directory's
`.git/config` -- and is the measurement of whether agents do as well without
bd's files. The earlier rounds are not rebuilt or re-scored; their numbers
keep that provenance.

The generated repositories are not here — about 85MB of them, rebuilt by
`harness/build3.py` and `harness/build4.py`. Neither is the embedding model, nor
the vectors it produced.
