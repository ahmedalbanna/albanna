# ADR-0028: The permission check comes before the hint

Status: **Accepted**
Date: 2026-11-05

## Context

`run_report` gained a check for missing mandatory filters: read the
report's own filter rows, and refuse with the keys to add before the report
runs. It was written to sit *before* the permission refusal.

So a reader who may not run a report was told which filters it requires,
and then told they could not run it.

The mandatory filters are the report's own shape. The shape of a thing the
reader cannot reach is the same knowledge the DocType catalogue withholds —
which is the hole [ADR-0027](0027-a-read-tool-is-gated-by-the-doctype-it-names.md)
closed in the same pass, for `get_doctype_meta`. It was reintroduced two
files later, by the fix that was meant to be helping.

The two blocks look interchangeable. One returns an error envelope naming
filters; the other returns an error envelope naming a permission. Nothing
in their shapes says which must come first, and nothing in the tests said so
either — the read guard asserts *a* refusal, and both are refusals, so it
passed.

## Decision

**When one check leaks and another refuses, the refusal goes first.**

`_report_refusal` runs before `_missing_mandatory_filters`. A reader who may
not run a report is told that, and nothing else. A reader who may run it
gets the missing-filter hint, because for them it is actionable rather than
a disclosure.

The order is commented, because the reason is not visible in the code. Two
adjacent blocks that both `return error(...)` are exactly the kind of thing
a later contributor reorders for a cheaper check to run first.

## Alternatives considered

**Run the filter check first because it is cheaper.** Rejected: it is
cheaper and it leaks. Cost is not the tiebreaker when one ordering discloses
and the other does not.

**Run both and report the permission one.** Rejected: it computes the leak
in order to discard it, and it is more code for the same outcome.

**Merge them into one refusal naming both facts.** Rejected: they are two
different facts about two different things — one about the account, one
about the report — and a sentence that says both tells the reader who may
not run the report something about the report.

**Leave it, because the leak is small.** Rejected: it is small and it is the
same class the app has now refused twice. A small leak in a consistent
direction is how a direction stops being a rule.

## Consequences

* A refused report says only that it was refused.
* A permitted report still gets its missing-filter hint — the ordering must
  not cost the reader who can run it, and there is a test for exactly that.
* Two tests pin the order: one fails with the old ordering, and the other
  fails if the permission check is allowed to swallow the hint.
* The general rule is now written down: a check that discloses runs after a
  check that refuses. It applied to `get_doctype_meta`'s field definitions,
  to the DocType catalogue, and to the page context's document name, and it
  applied here the day the code was written.

## See also

* [ADR-0027](0027-a-read-tool-is-gated-by-the-doctype-it-names.md) — the hole
  this ordering reintroduced, in the same pass.
* [ADR-0020](0020-a-refused-read-leaves-no-link.md) — the same principle
  applied to a document link rather than a report's shape.
* `albanna/tools/erpnext.py` — `run_report`, where the two blocks sit and
  the comment says why their order is not arbitrary.
