# ADR-0071: The system_prompt field

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.6 requires that a System Manager shall be able to set a custom system prompt (blank uses the built-in prompt). The `Albanna Settings` doctype already carries the field `system_prompt` (Small Text) with no options and no hardcoded default — blank means use the built-in prompt. The service layer `albanna/services/settings_service.py:174` reads `doc.system_prompt` and passes it to `AppSettings` as `system_prompt: str`; when blank (`""`), the built-in prompt is used.

## Decision

**Record the field, the "blank = built-in" semantics, and the service read.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `system_prompt` is a Small Text field with no options and no default (blank = built-in).

* `albanna/services/settings_service.py:174` asserts that `system_prompt=str(doc.system_prompt or "")` passes the value to `AppSettings`, and the chat service uses it to build the system message.

## Alternatives considered

**Trust the doctype JSON, since the field is fixed.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the setting back makes the rule visible.

**Use a different field name for the system prompt.** Rejected: the field name `system_prompt` was already chosen and is used throughout the codebase; renaming it would be a large refactor.

## Consequences

* FR-8.6 is now held: the `system_prompt` field, its "blank = built-in" semantics, and the service read are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/services/settings_service.py:174` — the service read.