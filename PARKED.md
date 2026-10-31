# Parked

Requirements captured to revisit. Not part of the current design.

## Formula capture from repetition — 2026-10-30

**The requirement.** A user works with an AI across many tasks in a day, prompting
as they go. After `dotdiw learn` the AI can write formulas. We want the
probability of dotdiw being used regularly to rise — whenever either of them
wants to create a task or do something. And when the agent or the human feels
the work is repetitive, that should naturally trigger creating a formula, at the
right path and with the discovery conventions satisfied, so future work does not
forget it.

**Is it achievable, and is it learn text or implementation?** Implementation.
Learn text cannot carry it: noticing repetition is a judgment made later, from
memory, while doing something else — the same class of thing we rejected when we
tied the convention to a moment that always fires instead of a habit someone
holds. An agent reads `learn` once per session, and repetition only becomes
visible several tasks later, by which point that text is out of context.

**The mechanism.** Repetition is already recorded. Every task went through
`dotdiw create`, so the titles are in beads. When discovery returns nothing above
the floor, that is a miss; mark it. When several misses score high against each
other, that is a repeated procedure with no formula, scored by the same ranker.

**What already ships.** `bd mol distill <epic-id> [name]` turns an existing epic
into a formula, and takes `--output <dir>` — the lever for placing it next to the
code. Its defaults are the old `.beads/formulas/` locations, so dotdiw must always
pass `--output`.

**The good part.** The cluster supplies the example titles. They are real
phrasings people actually used, so the retrieval self-test passes by construction
and the formula is tuned to how this team titles work.

**Open.**

- Distill needs an epic with children. It covers "this piece of work had good
  structure", not "these five loose tasks look alike" — dotdiw writes that one.
- The title-against-title threshold is unmeasured. Title-against-description was
  0.048 to 0.312; same-register comparison probably scores higher. Measure it
  against trial1's data.
- The suggestion arrives at the start of the next task, one task late, because
  that is the only moment that always fires.
- Nagging is the real risk. Fire too eagerly and people stop reading dotdiw's
  output, which costs discovery too.
