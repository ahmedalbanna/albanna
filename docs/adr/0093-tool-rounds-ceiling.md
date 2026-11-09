# ADR-0093: Tool rounds ceiling is enforced via settings

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.6 requires that the system enforce a maximum number of tool rounds per turn, configurable via the site settings. The `Albanna Settings` doctype already carries the field `max_tool_rounds` (Int, default 25). The service layer `albanna/services/chat_service.py:537` iterates `for round_no in range(settings.max_tool_rounds)`, hard-ceilinging the number of tool rounds a turn may spend. The `Authority` class in `albanna/core/authority.py` and the `LLMConfig` data class also reference this setting to determine when a turn has spent its round budget.

## Decision

**Record the ceiling mechanism and the three outcomes.**

Three guards:

* `albanna/services/chat_service.py:537` asserts that the `for round_no in range(settings.max_tool_rounds)` loop hard-ceils the number of tool rounds a turn may spend.

* `albanna/core/authority.py::LLMConfig` asserts that the `max_tool_rounds` setting is referenced when determining whether a turn has spent its round budget.

* `albanna/tests/test_budget.py` and `albanna/tests/test_turn_payload.py` assert that a turn that exceeds `max_tool_rounds` is marked `truncated` and the audit row records `status = "truncated"`.

## Alternatives considered

**Use a fixed ceiling hardcoded in the service.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A configurable setting makes the ceiling adjustable without code changes.

**Use a per-user ceiling.** Rejected: the round budget is a property of the turn, not the user; a per-user ceiling would not prevent a single user from exhausting the budget across multiple turns, and the current per-turn ceiling is the correct model.

## Consequences

* FR-12.6 is now held: the round-rounds ceiling, the settings field, and the service-level enforcement are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/chat_service.py:537` — the round ceiling loop.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/core/authority.py::LLMConfig` — the round budget reference.
* `albanna/tests/test_budget.py` and `albanna/tests/test_turn_payload.py` — the round ceiling tests.