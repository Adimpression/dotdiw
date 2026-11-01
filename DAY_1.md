# Day 1

The first day someone works in a project. Day 0 already happened, so `dotdiw`
is on the machine. Three situations.

**An existing project that has dotdiw.** They type `dotdiw`, which teaches them
the four things and the two conventions. From then on work starts with
`dotdiw create "<title>"`, and the formula that applies to their title
surfaces. Nothing to install. The tracker lives under your home, keyed to
your checkout, so a fresh clone runs `dotdiw init` once first; `create` says
so if it was not done, and init commits nothing.

**An existing project without dotdiw.** Someone runs `dotdiw init` once. It
keys the checkout, makes the tracker under their home, writes the declaration
into the project's instruction files and names them as yours to commit. The
repository gains those two files and nothing else. From then on everyone else
arrives into the situation above.

**A new project.** The same `dotdiw init`, run before there is anything to
discover. The project accumulates formulas as work that deserves one shows up.
