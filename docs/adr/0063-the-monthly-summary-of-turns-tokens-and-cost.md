# ADR-0063: The system provides a monthly summary of turns, tokens, and cost

Status: **Accepted**
Date: 2026-11-09

## Context

FR-9.2 requires that the system provide a monthly summary of turns, tokens, and
cost, broken down by model and by user. The `albanna.services.usage_summary()`
function was already implemented, but the rule had no test and no ADR.

## Decision

**Ask the consumers, not only the computation.**

The `usage_summary()` function computes month-to-date totals from the
`Albanna Chat Log` table. Two separate consumers assert it:

* `albanna/tests/test_integration.py::test_the_totals_are_the_months`
  asserts the aggregate totals: `turns`, `cost`, `tokens`, `errors`,
  `by_model`, `by_user`, `budget`, `budget_exceeded`, `uncosted_turns`.

* `albanna/tests/test_integration.py::test_the_breakdown_says_which_model_and_which_user`
  asserts the breakdown lists: the top model by cost and the top user by cost.

Both consumers read the same SQL query and the same `_breakdown()` helper, but
each tests a different shape of the result — because each consumer has its own
line of code. Pointing the summary at the whole manifest failed one test;
pointing the breakdown at it failed a different one.

## Alternatives considered

**Trust the computation, since both consumers read the same query.** Rejected:
that is the state the review keeps finding. A change to the SQL or the
breakdown limit would pass every existing test.

**Test only the aggregate totals, since the breakdown is a display detail.** Rejected:
the breakdown is how the operator finds the expensive models and users; losing
it would be a real usability regression.

## Consequences

* FR-9.2 is now held: the monthly summary function and its two consumers are
  each asserted by an integration test.
* The breakdown limit (`BREAKDOWN_LIMIT = 5`) is asserted: a breakdown that
  lists everything is a list, and the point of a breakdown is the top of it.
* No code change was needed; the function was already implemented. The work
  was the tests and this record.

## See also

* [ADR-0062](0062-the-ledger-records-every-turn.md) — the FR-9.1 ADR.
* `albanna/services/usage_service.py::usage_summary()` — the function.
* `albanna/tests/test_integration.py::test_the_totals_are_the_months` — the
  aggregate test.
* `albanna/tests/test_integration.py::test_the_breakdown_says_which_model_and_which_user` — the breakdown test.