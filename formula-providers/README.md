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
    "info": {"name": "acme-api", "version": "0.1.0"},
    "operations": {
        "describe": describe,
        "list": list_formulas,
        "show": show,
    },
}
```

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
- `show` takes `id` as well, and answers `{"text": ..., "format": "toml"}`, or
  `"json"`: the formula as the provider keeps it. For an id it does not hold,
  it answers `{}`. dotdiw reads the text, sets its `formula` key to the
  suffixed id however it is spelled, and writes it out again with every other
  value as given, taking it only when it reads back as exactly that.

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
`show` only when a formula is shown or poured, and writes the text, its
`formula` key set to the suffixed id, under the checkout's workspace,
`~/.dotdiw/<key>/formula-providers/`, in a file named for a digest of the
provider's name, the id and the text. A file is written once and never
changed, so a pour reads its steps and its means to prove from the very copy
the tracker cooks. From there it pours as a formula in the checkout does. Nothing about a provider reaches the tracker beyond the formula poured.
Caching across runs, where the store needs it, is the provider's own.

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
