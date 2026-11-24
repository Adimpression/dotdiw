# Dotdiw proposal — Choices and outcome-dependent steps

A formula can declare one choice and make steps depend on the outcome recorded for that run.

## Formula fields

- `choice.options` lists the allowed outcomes.
- `choice.needs` lists the steps that must finish before the choice can be filled. Evaluate the formula’s `verify-using` after these prerequisites and before filling the choice.
- `choice.chooser` says what fills the choice. With `human`, a person selects the outcome. With `ai`, AI selects it using judgment. With `map`, the check result is looked up in a map of results to outcomes.
- `steps.when-choice` names the outcome that enables the step. The step’s ordinary `needs` still apply.

## Example

```toml
formula = "handle-renewal-reply"
verify-using = [
  'json+https://support.example.org/drafts/{{ prepare-reply.draft-revision }} | .renewal_payment == "confirmed"',
]

[choice]
options = ["send", "revise", "hold"]
needs = ["prepare-reply"]
chooser = "human"

[[steps]]
id = "prepare-reply"
title = "Prepare a reply about the customer's renewal"

[steps.claim]
statement = "Draft revision {{ draft-revision }} concerns a confirmed renewal payment."
"draft-revision:" = {}

[[steps]]
id = "send-reply"
title = "Send the approved draft"
when-choice = "send"

[[steps]]
id = "revise-reply"
title = "Revise the draft and return it for a fresh check and choice"
when-choice = "revise"

[[steps]]
id = "hold-reply"
title = "Keep the draft unsent and record why it was held"
when-choice = "hold"
```

## Run behavior

1. `prepare-reply` completes and supplies the draft revision. Dotdiw exposes that the choice prerequisites are met. The root `verify-using` is evaluated for that revision.
2. The support person sees the check result, then fills the choice by selecting `send`, `revise`, or `hold`. Dotdiw records the selected outcome for that draft.
3. While the choice is open, the three dependent steps wait. When it is filled, only the step matching the outcome becomes eligible.
4. Dotdiw tracks the choice and step completion separately. `send` enables `send-reply`. `send-reply` is marked complete when the approved draft has been sent. A revised draft requires a fresh check and choice.

## Map behavior

With `chooser = "map"`, use the check result as the lookup key. Each mapped outcome must be declared in `choice.options`. A matching key fills the choice with its mapped outcome. An unmapped result leaves the choice open.

| Check result | Choice outcome |
|---|---|
| `met` | `send` |
| `unmet` | `revise` |
| `unconfirmed` | `hold` |
| `no-current-result` | `hold` |

The map supplies an outcome. Dotdiw records it and uses it to determine which steps are eligible. The map’s format and implementation are outside the scope of this proposal.
