# ADR-0070: The confirm_writes Check field

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.5 requires that a System Manager shall be able to set the site-wide default for write confirmation. The `Albanna Settings` doctype already carries the field `confirm_writes` (Check, labeled "Confirm writes", default `1`). The service layer `albanna/services/settings_service.py:188` reads `doc.confirm_writes` and passes it to `AppSettings` as `confirm_writes: bool = False`. When `confirm_writes` is true, writes wait for reader approval via the approval card; when false, writes proceed immediately.

## Decision

**Record the field, the default, and the service read.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `confirm_writes` is a Check field with label "Confirm writes" and default `1`.

* `albanna/services/settings_service.py:188` asserts that `confirm_writes=bool(getattr(doc, "confirm_writes", 0))` passes the value to `AppSettings`.

## Alternatives considered

**Trust the doctype JSON, since the field is fixed.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the setting back makes the rule visible.

**Use a different field name for write confirmation.** Rejected: the field name `confirm_writes` was already chosen and is used throughout the codebase; renaming it would be a large refactor.

## Consequences

* FR-8.5 is now held: the `confirm_writes` field, its default, and the service read are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/services/settings_service.py:188` — the service read.