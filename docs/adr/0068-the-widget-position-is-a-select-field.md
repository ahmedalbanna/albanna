# ADR-0068: The widget position is a Select field

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.3 requires that a System Manager shall be able to set the widget position. The `Albanna Settings` doctype already carries the field `widget_position` (Select) with options `bottom-right`, `bottom-left`, `floating` and default `bottom-right`. The service layer `albanna/services/settings_service.py:161` reads `doc.widget_position` and passes it to `AppSettings`. The chat UI uses the value to position the widget on the page.

## Decision

**Record the field, the default, and the service read.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `widget_position` is a Select field with the three options and the documented default.

* `albanna/services/settings_service.py:161` asserts that `widget_position=str(doc.widget_position or "bottom-right").strip() or "bottom-right"` is passed to `AppSettings`.

## Alternatives considered

**Trust the doctype JSON, since the field is fixed.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the setting back makes the rule visible.

**Use a different widget position field name.** Rejected: the field name `widget_position` was already chosen and is used throughout the codebase; renaming it would be a large refactor.

## Consequences

* FR-8.3 is now held: the widget position field, its options, and the service read are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/services/settings_service.py:161` — the service read.