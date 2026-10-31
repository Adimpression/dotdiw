# Workflow discovery: what a project needs and declares

"A project" means a repository whose work is done by people and AI coding
agents together. Nothing here names a tool. Anything built answers to this.

## What a project needs

A project holds named procedures — cut a release, migrate a schema, onboard a
contributor. Each is a short DAG of steps. Four things have to work.

**Workflow management.** Instantiate a procedure, track the state of each step,
honour the dependencies so work happens in a sensible order.

**Workflow declaration.** Write the procedure down: its description, its steps,
which step depends on which.

**Workflow sharing.** The project's procedures are available to everyone
working in the project.

**Workflow discovery.** When someone starts a piece of work, the procedure that
applies surfaces to them. They are not searching for it. They do not know it
exists.

The first three are met by tools a project already has — an issue tracker that
honours dependencies, and version control. Discovery is the one nothing
provides.

## What a project declares

Two conventions. They are not habits anyone holds — the project states them,
and they bind whoever shows up, human or agent, including everyone who was not
there when they were written.

**Work starts at one declared moment.** The project names the single act that
begins a piece of work, and every task and subtask begins with it. That
declaration is the mechanism, not a note about one: it is what gives discovery
a hook that always fires. Where work may begin some other way, nothing
surfaces — the discipline was skipped, not the mechanism broken.

**Procedures are described to be found.** A description is the only thing
standing between what someone calls their work and the procedure that fits it.
It names the situation and when to use it, in the words people use for the
work, not a restatement of the procedure's own name.

## What anything built has to satisfy

Discovery fires at the declared moment, and reaches a person at a terminal and
an agent spawning a subprocess by the same path.

A procedure the project holds is reachable from the words someone would
actually use to name the work. A procedure nobody can reach is not held.

A procedure is available to everyone in the project by being part of the
project, not by anyone's local setup.

Procedures ship in natural places among the project's own files, and get
edited in place.

Nothing is installed or configured per project, and nothing is left for a
newcomer to install later.

The conventions are checkable, not advisory: a project can tell whether it is
holding them, without asking anyone.

Hundreds of procedures in one project, with no per-procedure registration.

## What follows

A project that declares both gets discovery that always fires over a set it can
state. A project that declares neither cannot recover the loss by any
mechanism — which is why the declarations are the design rather than an
addendum to it.
