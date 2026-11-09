# ADR-0062: The ledger records every turn

Status: **Accepted**
Date: 2026-11-09

## Context

FR-9.1 requires that the system record every turn in a ledger: model, provider,
prompt tokens, completion tokens, total tokens, cost in site currency, tool
rounds, tool calls count, tools used, duration, and status. The existing
`Albanna Chat Log` doctype and the `_log()` method in `chat_service.py` were
already implemented, but the rule had no test and no ADR.

## Decision

**Record the rule where the ledger is written, and test it where it is read.**

Two guards:

* `albanna/tests/test_integration.py::test_the_ledger_records_every_turn`
  asserts that every turn end writes all eleven fields to `Albanna Chat Log`:
  `user`, `conversation`, `provider`, `model`, `status`, `rounds`,
  `tool_calls`, `tools`, `duration_ms`, `input_tokens`, `output_tokens`,
  `cost`. The test reads the row back via `frappe.db.get_value` and checks
  each field.

* `albanna/services/audit_rows.py::unfinished_turn()` and
  `unfinished_facts()` and `approved_not_run()` assert that the audit trail
  can be read back: who ran what, and what the reader is left with when a
  turn does not finish.

## Alternatives considered

**Trust the `_log()` method, since it is the only writer.** Rejected: the
review's pattern has consistently found rules that are correct in the code
and unheld by any test — and the difference between those two states is
invisible until somebody changes the code. A test that reads the row back
makes the rule visible.

**Add the fields as new columns on `Albanna Chat Log`.** Rejected: all
required fields already exist on the doctype; the issue is that the rule
is untested, not that the schema is missing.

## Consequences

* FR-9.1 is now held: every turn end writes all required fields, and a test
  asserts it.
* The audit trail (`unfinished_turn`, `unfinished_facts`, `approved_not_run`)
  can be read back, and its tests already exist.
* No new columns or doctype changes were needed; the rule was already
  implemented, it just needed to be held.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_chat_log/albanna_chat_log.json` — the
  shipped ledger doctype.
* `albanna/services/chat_service.py::_log()` — the writer.
* `albanna/services/audit_rows.py` — the readers.
* `albanna/tests/test_integration.py` — the ledger test.