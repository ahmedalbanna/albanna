# ADR-0061: The settings gate is a System Manager, a Single, and carries the provider fields

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.1 requires that a System Manager be able to configure the model
provider: kind, base URL, model, API key, temperature, max tokens, and
timeout. The settings doctype (`Albanna Settings`) already satisfies
this — it is a Single, gated to System Manager (read and write), and
carries every field the requirement names, plus a fallback provider and
access/safety tabs.

The gap was the usual one for this review: a rule that is correct in
the code and unheld by anything, so a change to it would pass every
suite. The settings hold the provider's API key, so who may read them
is a security question and not a convenience one. A second permission
row — `All`, or `Desk User` — would hand the key to every account on
the site, and nothing would notice. A settings document that is not a
Single would give every user their own copy, and the provider the
assistant uses would depend on who opened the form. A field renamed or
removed would be discovered by an operator who opened the form and found
it empty.

## Decision

**Hold the gate, the shape, and the fields, each where it lives.**

Three guards:

* `tests/test_settings_access.py` (pure) asserts the shipped matrix
  names one door and no other — System Manager for both read and write
  — that the doctype is a Single, and that the provider fields FR-8.1
  names are present.
* `albanna/tests/test_settings.py` gains `TestSettingsAccess`, which
  asks the framework whether a System Manager may read and write and
  whether a plain user may not. The settings hold the provider's key,
  so read access is a security question and not a convenience one.

## Alternatives considered

**Trust the doctype JSON, since it is right today.** Rejected: that is
the state the review keeps finding. A permission row added by a future
edit, or a field renamed, would pass every existing test.

**Test only the pure matrix, since the framework's permission check is
its own concern.** Rejected: the framework's check is the thing that
actually gates the door, and a doctype whose JSON says one thing while
the framework computes another is a real failure mode. Both halves are
asked.

## Consequences

* FR-8.1 is met, and now held: the gate, the Single shape, and the
  provider fields are each asserted.
* The settings hold the provider's key, and a plain user may neither
  read nor write them — verified against the framework, not assumed.
* No code change was needed; the requirement was already satisfied.
  The work was the tests and this record.

## See also

* [ADR-0055](0055-a-requirement-that-is-met-is-not-a-requirement-that-is-held.md)
  — the pass this is an instance of.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` —
  the shipped matrix, the Single flag, and the provider fields.
* `tests/test_settings_access.py` — the pure guards.
* `albanna/tests/test_settings.py` — `TestSettingsAccess`.