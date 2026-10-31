# Day 0

The day dotdiw goes on the machine. Once, by one person, the way git does.

`brew install dotdiw`. Brew pulls what dotdiw depends on and puts `dotdiw` on
PATH. No dotfile is touched and no project is involved.

What it has to achieve:

**Reachable by every caller.** A person in a terminal, a script, an agent
spawning a subprocess. All three resolve the same file.

**Installs what dotdiw depends on.** A prerequisite the newcomer installs
themselves is a per-project step in disguise. Day 0 either leaves a working
machine or it has not happened.

**Knows nothing about any project.** One installation serves every project on
the machine, reading whichever one it is run in.

**Leaves nothing to install later.** No per-project step and no missing
dependency, so there is nothing a newcomer can skip.
