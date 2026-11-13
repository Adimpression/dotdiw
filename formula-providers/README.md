# formula-providers

The formula management providers that are not inside dotdiw. The `directory`
provider inside dotdiw is the reference: `directory_describe`, `directory_list`
and `directory_show` are its three operations, over a directory of formula
files outside any checkout. A provider of your own is written the same way, and
this file says how to write it and how to ship it.

## What a provider is

One Python file, `<module>.py`, exposing one table, `PROVIDER`. The module's
name uses lowercase letters, digits and hyphens, and starts with a letter or a
digit. Before the module runs, `dotdiw_version` is set on it. The module
imports nothing from dotdiw, and dotdiw reads nothing from it but the table.

```python
PROVIDER = {
    "info": {"name": "acme-api", "version": "0.1.0", "interface": 2},
    "operations": {
        "describe": describe,
        "list": list_formulas,
        "show": show,
    },
}
```

`info` says which formula provider interface the module was written for: 2,
from dotdiw 3.0.0, when `show` came to answer a formula as data. A module whose
info names another, or none, is refused in one line.

Each operation is a callable taking one dict and returning one. Every request
carries `location`, the store the provider was registered with: a directory, a
URL, or nothing. An operation raises when its store is not there, and never
answers an empty list for a store that is gone.

- `describe` answers `{"answers": [...]}`: which of `list`, `show` and
  `create` the provider answers. dotdiw 2.0 requires `list` and `show`, and
  registers no provider that does not declare both. It may also answer
  `"location"`: the store as the provider means it, which is what gets
  registered. The directory provider answers its directory's absolute path, so
  that it names one store from every directory dotdiw runs in.
- `list` answers `{"formulas": [{"id": ..., "description": ..., "examples":
  [...]}, ...]}`: every formula the provider holds. Each id is letters, digits,
  dots, hyphens and underscores, starts with a letter or a digit, and is listed
  once; each description is text; each list of examples is text. The whole
  answer is held to that shape before any of it is taken.
- `show` takes `id` as well, and answers the formula as data, however the
  provider keeps it: `{"formula": {"description": ..., "verifyUsing": [...],
  "steps": [{"id": ..., "title": ..., "needs": [...], "claim": {"statement":
  ..., "slots": [...]}}, ...]}}`. For an id it does not hold, it answers `{}`.
  dotdiw holds the answer to that shape -- a description that is text, each
  means to prove one line in a form `check` reads, each step an id and a
  title, once, with needs that name step ids, and a step's claim a statement
  with its slots' labels in lowercase kebab-case, each once, every `{{ label }}`
  placeholder naming one -- and refuses one outside it. Only `verifyUsing`, a
  step's `needs` and its `claim` may be left out; nothing given is replaced by
  a default. A provider with title and description fields alone may keep what
  it left out in its descriptions instead: the means under a `Verify using:`
  heading that ends the formula's description, one `- ` line each, and in a
  step's description its id on a `Step ID:` line, its needs on a `Needs:`
  line, comma separated, and its claim under a `Claim:` heading -- the
  statement, then a line for each slot, its label and a colon. dotdiw reads
  them into the same model as a file's. `dotdiw formula show` prints a
  provider's formula in the form a file takes, so what it prints pours with
  its claims.

## How dotdiw holds a provider

**Found, the home first.** `~/.dotdiw/formula-providers/<module>.py`, looked
in first; then `share/dotdiw/formula-providers/<module>.py` beside the `bin/`
dotdiw runs from, where a `dotdiw-formula-provider-<module>` package installs
it, or the same above `Cellar/` inside a Homebrew keg.

**Registered under a name.** `dotdiw formula provider register <name> <module>
[--at <location>]` loads the module, asks it to describe itself, and records
the name, the module and the location it answered under your home, in
`~/.dotdiw/formula-providers.json`, one change at a time. The name is letters
and digits, and no two names differ in case alone. It is the suffix: a formula
the provider lists as `mol-cut-release` is `mol-cut-release-<name>` everywhere
dotdiw shows or takes an id. Every registered provider serves every checkout.

**Listed once in a run, shown when wanted.** dotdiw reads each provider's
list once per process, and matches and lists its formulas from it. It asks
`show` only when a formula is shown or poured, and keeps the answer in memory:
nothing is written for it. A pour hands the tracker the steps `show` answered,
as it does those of a formula in the checkout, and `formula show` prints the
formula in the form a `.formula.json` file takes. Nothing about a provider
reaches the tracker beyond the formula poured. Caching across runs, where the
store needs it, is the provider's own.

**Left out when it fails.** A provider that raises, or answers outside its
shape, is left out of that run whole, with one line naming it, and the
formulas in the checkout answer as before.

**Removed.** `dotdiw formula provider remove <name>` takes the registration
away. From then on, an id with its suffix is refused, and never handed to the
tracker, which may still hold a copy of a formula it poured.

## Shipping it

A package named `dotdiw-formula-provider-<module>` installs `<module>.py` into
`share/dotdiw/formula-providers/`. Installing it makes the provider eligible;
registering it under a name is each person's own step, with
`dotdiw formula provider register`.
