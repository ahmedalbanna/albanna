# ADR-0060: A rule is tested where it is obeyed, not only where it is computed

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7.5, FR-7.6 and FR-7.7 are three statements about the authority
layer, and all three were implemented correctly. All three were tested
only where the rule is *computed*.

The authority layer's docstring states the rule — *"a tool the principal
may not reach is never mentioned to the model"* — and
`albanna/services/toolset.py` implements it. The unit tests assert
`visible_names()` excludes the tool. All of that is the rule computed.

The rule is *obeyed* in two separate places, by separate code: the tool
schemas that travel in the request body, and the tool list inside the
system prompt. Both are built from the same filtered list. Nothing asked
either of them.

The same shape appeared twice more. FR-7.6's pairing of write tool to
right was asserted for two of the seven write tools, and the six lists
that feed it were never asked which parameter they landed in. FR-7.7's
fail-closed rule was asserted for all six denials it names — but not for
the *unresolved* half of two of them, nor for a third branch the shipped
manifest cannot reach.

## Decision

**Ask the consumers, not only the computation.**

Three guards, each proved by reintroducing its defect:

* **FR-7.5** — a turn is run as a reader who holds no submit right
  anywhere on the site, and both the system prompt and the provider
  payload are asked whether they name `submit_doc`. Each consumer has
  its own test, because each has its own line of code. Pointing the
  prompt at the whole manifest failed one test; pointing the provider
  payload at it failed a different one.
* **FR-7.6** — all seven write tools are asserted in both directions,
  with the exactness proved too: holding one right must switch on the
  tools that right governs and nothing else. And the wiring is asked, by
  giving each of the six lists a name of its own, one at a time, and
  asking the tools which one they followed.
* **FR-7.7** — the unresolved branches are asked: a call bound to no
  site, a call with no actor, and a mutating tool that names no target
  DocType.

## Alternatives considered

**Trust the unit tests, since the consumers read the same list.**
Rejected: that is the state the review found. "Reads the same list" is
true today and is one edit away from being false, and the edit would
pass every existing test.

**Test only the provider payload, since that is what the model chooses
from.** Rejected: the prompt names the tools too, in words, and a model
that has read about a tool it cannot use spends a turn discovering
that — which is the waste the rule exists to prevent.

**Collapse the two consumers into one so there is only one place to
get wrong.** Rejected for now, and recorded rather than hidden: it is
the real fix, and it is a larger change than this pass. Two guards hold
the property in the meantime.

**Skip the unreachable branch, since the manifest cannot reach it.**
Rejected: that is backwards. A branch that has never run is a branch
that has never been proved to refuse, and the day somebody adds the tool
that reaches it is the day it starts mattering.

## Consequences

* Three requirements, and each defect reintroduced was caught by
  exactly the test that targets it.
* The reader used for FR-7.5's test holds no submit right anywhere on
  the site — verified against the role's actual rows rather than
  assumed. `Albanna User` grants rights on two DocTypes, neither
  submittable, and the `Desk User` role Frappe adds alongside it grants
  none either.
* One thing worth naming, because it looked like a bug and was not:
  `creatable_doctypes` reported seventeen DocTypes for a bare
  `Albanna User`. That is `Desk User`, which Frappe attaches
  automatically and which grants create on fifteen unrelated ones. Not
  a defect — but it is the kind of number that reads like one.
* One thing this pass got wrong on its own, caught by the suite: the
  test helper read `user or frappe.session.user`, which turned the empty
  string into the session user, so the case under test never reached the
  gate. The test passed for the wrong reason — the failure mode
  ADR-0055 is about, occurring inside the fix for it.
* The general lesson, and the one that generalises furthest: a rule
  that is computed in one place and obeyed in another is a rule that
  needs a test in both. The computation is the easy half to test, which
  is exactly why it is the half that gets tested.

## See also

* [ADR-0055](0055-a-requirement-that-is-met-is-not-a-requirement-that-is-held.md)
  — the pass this is the sharpest instance of.
* [ADR-0002](0002-authority-and-permissions.md) — the authority layer
  itself, and the fail-closed rule FR-7.7 names.
* `albanna/core/authority.py` — `visible()`, `authorize()`, and the
  docstring that states the rule.
* `albanna/services/toolset.py` — `tool_registry`, which computes the
  per-user set.
* `tests/test_tool_switches.py` and `tests/test_authority.py` — the
  computation, purely.
* `albanna/tests/test_integration.py` — the obedience.
