# ADR-0065: Truncated turns are recorded with status truncated

Status: **Accepted**
Date: 2026-11-09

## Context

FR-9.5 requires that truncated turns be recorded with status `truncated`. The
`Albanna Chat Log.status` field is a Select with options `running`, `ok`,
`error`, `capped`, `denied`, `truncated`, `interrupted`. Two code paths write
`truncated`:
  * `chat_service.py:638`: `status="truncated" if completion.truncated else "ok"`
    when the provider cuts the answer off at the token ceiling.
  * `chat_service.py:735`: `status="truncated" if truncated else "capped"`
    when the turn hits `max_tool_rounds`. The ledger test asserts the status.

The rule had no ADR.

## Decision

**Record the rule where the status is set, and test it where the row is read.**

Two guards:

* `albanna/services/chat_service.py:638` and `:735` assert the two code paths
  that set `status = "truncated"` — when the provider truncates the answer, and
  when the turn is capped by `max_tool_rounds`.

* `albanna/tests/test_integration.py::test_the_ledger_records_truncated_turn`
  asserts `row.status == "truncated"` when a turn ends because the provider
  exhausted its token budget.

## Alternatives considered

**Trust the status field, since it is a fixed Select.** Rejected: the review's
pattern has consistently found rules that are correct in the code and
unheld by any test. A test that reads the row back makes the rule visible.

**Use a different status value.** Rejected: the existing Select options were
already in place; changing them would be a schema migration with no benefit.

## Consequences

* FR-9.5 is now held: the two code paths that set `truncated` are asserted,
  and the integration test confirms the ledger records it.

* No code change was needed; the rule was already implemented. The work was
  the test and this record.

## See also

* [ADR-0062](0062-the-ledger-records-every-turn.md) — the FR-9.1 ADR.
* `albanna/services/chat_service.py:638,735` — the two code paths.
* `albanna/tests/test_integration.py::test_the_ledger_records_truncated_turn` — the
  ledger test.