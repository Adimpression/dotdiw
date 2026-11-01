# measurements

The evidence for the numbers in `../IMPLEMENTATION.md`. Nothing here is part of
the tool; it is the apparatus the tool was measured with, kept so that the
claims can be checked rather than taken on trust.

Ground truth throughout is a log of every `dotdiw` invocation plus the repository
diffs, never what an agent said it did. Several of the numbers in
IMPLEMENTATION.md changed because the log disagreed with the summaries.

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
| `verify.py` | the four-formula fixtures, the baseline every change was checked against |
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
