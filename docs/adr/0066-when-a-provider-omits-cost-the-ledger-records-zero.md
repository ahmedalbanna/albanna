# ADR-0066: When a provider omits cost, the ledger records zero

Status: **Accepted**
Date: 2026-11-09

## Context

FR-9.6 requires that if a provider does not report cost, the ledger shall record
zero (not omit the field). The `Albanna Chat Log.cost` field is Currency, and
`Albanna Chat Log.provider_cost` is Float. Both are always present on every
row. The `cost_of_turn()` function in `albanna/core/cost.py` returns `0.0`
when `price_per_million <= 0`, and the `_log()` method always writes both
fields.

The rule had no ADR.

## Decision

**Record the rule where the cost is computed, and test it where the row is read.**

Two guards:

* `albanna/core/cost.py::cost_of_turn()` asserts that it returns `0.0` when
  `price_per_million <= 0` or when there are no tokens. This is the single
  point where the site's cost is computed from the provider's tokens and the
  operator's price.

* `albanna/services/chat_service.py:1555` asserts that `doc.provider_cost =
  usage.cost` always writes the field, even when `usage.cost` is `0.0`.

* `albanna/tests/test_integration.py` asserts that the ledger row always has
  a `cost` value — never omitted — even when the provider reported no price.

## Alternatives considered

**Trust that the fields are always present, since the doctype defines them.** Rejected:
the review's pattern has consistently found rules that are correct in the code
and unheld by any test. A test that reads the row back makes the rule
visible.

**Omit the cost field when it is zero.** Rejected: FR-9.6 explicitly requires
that the field be present with value zero, not omitted.

## Consequences

* FR-9.6 is now held: the cost fields are always present, and zero is the
  value when the provider omits cost.

* No code change was needed; the rule was already implemented. The work was
  the tests and this record.

## See also

* [ADR-0062](0062-the-ledger-records-every-turn.md) — the FR-9.1 ADR.
* `albanna/core/cost.py::cost_of_turn()` — the cost computation.
* `albanna/services/chat_service.py:1555` — the writer.
* `albanna/tests/test_integration.py` — the ledger test.