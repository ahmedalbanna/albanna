# ADR-0072: The extra_options field

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.7 requires that a System Manager shall be able to set custom provider options as JSON. The `Albanna Settings` doctype already carries the field `extra_options` (Small Text) — free text, no options, no hardcoded default (operator writes raw JSON). The service layer `albanna/services/settings_service.py:147` reads `doc.extra_options` and passes it through `parse_options()` into `AppSettings` as `extra_options: dict[str, Any] = field(default_factory=dict)`. The `parse_options()` function in `albanna/core/options.py:33` converts the raw string to a `dict[str, Any]`, returning `{}` on empty/invalid JSON. The settings controller refuses saves with invalid JSON at the source (`_enforce_valid_options`).

## Decision

**Record the field, the parse logic, and the validation.**

Three guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `extra_options` is a Small Text field with no options and no default (free text, JSON dict).

* `albanna/services/settings_service.py:147` asserts that `extra_options=parse_options(getattr(doc, "extra_options", ""))` passes the parsed options to `AppSettings`.

* `albanna/core/options.py:33` asserts that `parse_options()` returns a `dict[str, Any]` from valid JSON, and `{}` on empty/invalid input.

## Alternatives considered

**Trust the parse function, since it is the only decoder.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the options back makes the rule visible.

**Add JSON validation in the UI layer.** Rejected: the validation already exists in the settings controller (`_enforce_valid_options`); adding another layer would be duplication.

## Consequences

* FR-8.7 is now held: the `extra_options` field, the `parse_options` logic, and the JSON validation are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/services/settings_service.py:147` — the service read.
* `albanna/core/options.py:33` — the parse function.