# ADR-0074: The dry_run Check field

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.9 requires that a System Manager shall be able to enable dry-run mode, where writes are proposed but not committed. The `Albanna Settings` doctype already carries the field `dry_run` (Check, labeled "Dry Run", default `0`). The service layer `albanna/services/settings_service.py:188` reads `doc.dry_run` and passes it to `AppSettings` as `dry_run: bool = False`. When `dry_run` is true, write tools run their validation and report what they would do, but nothing is saved. Useful for testing prompts and training.

## Decision

**Record the field, the default, and the service read.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `dry_run` is a Check field with label "Dry Run" and default `0`.

* `albanna/services/settings_service.py:188` asserts that `dry_run=bool(getattr(doc, "dry_run", 0))` passes the value to `AppSettings`.

* `albanna/services/chat_service.py:1095` asserts that `if settings.dry_run and spec.mutating and result.ok:` gates the save of a write.

## Alternatives considered

**Trust the doctype JSON, since the field is fixed.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the setting back makes the rule visible.

**Use a different field name for dry-run mode.** Rejected: the field name `dry_run` was already chosen and is used throughout the codebase; renaming it would be a large refactor.

## Consequences

* FR-8.9 is now held: the `dry_run` field, its default, and the service read are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/services/settings_service.py:188` — the service read.
* `albanna/services/chat_service.py:1095` — the dry-run gate.