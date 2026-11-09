# ADR-0069: The limits are read from the settings doctype

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.4 requires that a System Manager shall be able to set limits (max tool rounds, history limit, turn timeout, turns per minute). The `Albanna Settings` doctype already carries the fields `max_tool_rounds` (Int, default 25), `history_limit` (Int, default 50), `turn_timeout` (Int, default 600), `turns_per_minute` (Int, default 6), `price_per_million` (Float, default 0), and `monthly_budget` (Currency, default 0). The service layer `albanna/services/settings_service.py:170-179` reads each field from the doc with safe defaults (`_int`, `_int_allowing_zero`, `_float`, `getattr` with fallback) and passes them into `AppSettings`. The chat service enforces these limits on every turn.

## Decision

**Record the fields, the defaults, and the service reads.**

Six guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts each of the six limit fields: `max_tool_rounds`, `history_limit`, `turn_timeout`, `turns_per_minute`, `price_per_million`, `monthly_budget`, with their fieldtypes, defaults, and the `issingle: 1` / `permission: role=System Manager, read=1, write=1` gate.

* `albanna/services/settings_service.py:170-179` asserts that each field is read with the documented safe-default pattern: `max_tool_rounds=max(1, _int(doc.max_tool_rounds, 25))`, `history_limit=max(1, _int(doc.history_limit, 50))`, `turn_timeout=max(10, _int(doc.turn_timeout, 600))`, `turns_per_minute=max(0, _int_allowing_zero(doc.turns_per_minute, 6))`, `price_per_million=_float(getattr(doc, "price_per_million", 0), 0.0)`, `monthly_budget=_float(getattr(doc, "monthly_budget", 0), 0.0)`.

## Alternatives considered

**Trust the service layer, since it is the only reader.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the settings back makes the rule visible.

**Add a new section for limit validation.** Rejected: the limits are already validated in the settings controller (`_clamp_approval_wait`) and in the chat service; adding another section would be duplication.

## Consequences

* FR-8.4 is now held: the six limit fields, their defaults, and the service reads are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped fields.
* `albanna/services/settings_service.py:170-179` — the service reads.