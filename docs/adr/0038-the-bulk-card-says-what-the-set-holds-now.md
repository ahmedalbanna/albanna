# ADR-0038: The bulk card says what the set holds now

Status: **Accepted**
Date: 2026-11-06

## Context

The approval card for a bulk change said:

> *"Change 42 Sales Invoice document(s): status = Paid (showing SAL-1,
> SAL-2, …)"*

The proposed value, and nothing about the current one. The reader approved a
change **from** a state they were not shown.

The reason is understandable and was stated nowhere: across forty-two
documents the current values may all differ, so there is no single "current
value" to put on the card. But the consequence is that the reader cannot
picture the change. They may be moving twelve drafts and thirty billed
invoices, or forty-two documents that are already paid — and those are very
different requests, approved with the same click.

FR-5.1 asks for the current value. This is the one clause the bulk card
omitted, on the one write where the reader is least able to check by eye.

## Decision

**The bulk card carries the distribution of current values for each field
being changed.**

> *"Change 42 Sales Invoice document(s): status = Paid (status is currently
> Draft 12, To Bill 30) (showing SAL-1, SAL-2, …)"*

Counted **in Python** rather than by a grouped query: the set is already
bounded by the change's own limit, and a `group_by` over a field the model
named is one more thing that can fail on a site whose reports are somebody
else's. An empty value is named (`unset 4`) rather than dropped, because a
missing bucket is a count that does not add up.

The distribution is drawn from the same permission-filtered `get_list` the
count and the sample names come from, so the card still never tells a reader
what they cannot see — the property `_preview_bulk`'s docstring already
claimed and a test already held.

## Alternatives considered

**Say the current values vary.** Rejected: it is honest and it tells the
reader nothing they could not have guessed. A card that says "the values
vary" has replaced a missing fact with a restatement of the problem.

**Show nothing.** This was the behaviour. Rejected: it is the case where the
reader most needs the information, because a bulk change is the one write
they cannot verify by looking.

**Show a sample of current values.** Rejected: a sample implies the rest are
the same, which is exactly the assumption that is false. The distribution
says what is true without implying uniformity.

**Group in SQL.** Rejected: `frappe.get_list` with `group_by` and an
aggregate field works, and it is one round trip instead of one per field.
But it puts a query shape the model's fieldname flows into, on a path that
already runs arbitrary site reports, and the set is bounded by the change's
own limit — so the Python count is not a shortcut, it is the smaller risk.

**Show the distribution for every field in the data, not just the six the
card names.** Rejected: the card names at most six fields, and a change of
one field should cost one query.

## Consequences

* A reader approving a bulk change sees what they are changing from, which
  is the difference between a decision and a request for trust.
* The cost is one bounded query per changed field, over the same filtered set
  the card already queries. A change of one field costs one.
* The permission property is unchanged and still tested: the distribution is
  the reader's own.
* The card is longer. It was already the longest sentence in the panel, and
  the length is the information.
* The general principle is the one ADR-0032 recorded for the approved set:
  when a reader approves something, the thing they are shown has to be the
  thing that runs. Here it is the *state* rather than the *set*, but the
  shape of the hole is the same.

## See also

* [ADR-0032](0032-the-approved-set-is-carried-through-to-the-write.md) — the
  same principle applied to which documents run, rather than what state they
  hold.
* [ADR-0031](0031-a-bulk-change-is-gated-whatever-the-operators-setting.md) —
  the gate this card sits behind.
* `albanna/services/approval.py` — `_preview_bulk`, `_current_values` and
  `_distribution`.
