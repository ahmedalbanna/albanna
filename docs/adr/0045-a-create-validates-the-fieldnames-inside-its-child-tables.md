# ADR-0045: A create validates the fieldnames inside its child tables

Status: **Accepted**
Date: 2026-11-08

## Context

ADR-0035 gave the create path the fieldname check the update path already
had: an invented fieldname at the top level is refused with the
close-match correction, instead of being silently dropped by the
framework.

It validated the top-level keys only. A model that invented a fieldname
inside `items` was still silently ignored.

That is the level a model is *more* likely to get wrong, not less. The
schema it was given names the parent's fields and says "items" without
saying what an item holds — so the child DocType's fieldnames are exactly
the ones it has never been shown.

And a table field is replaced whole, so the rows the model sends are the
rows the document will have. A fieldname that is not in the child
DocType's meta is dropped without a word: the model believes it set
something, the reader believes it, and nobody discovers otherwise until
somebody opens the form.

## Decision

**A create validates its child-table rows against the child DocType's own
meta, with the same close-match correction.**

The refusal names the child DocType as well as the field, because
*"field 'quntity' (closest: 'qty')"* on its own does not say *where* the
model put it — and the same wrong fieldname is plausible at the top level
too.

Only the rows' keys are checked, and only against the child DocType's
meta. The correction names the closest matches from that meta, which is
safe to show: the caller is creating the parent document, so they can
already see the parent's form, and the form shows the child table's
columns.

A child DocType that cannot be read is refused rather than guessed at:
the rows would be written against a meta nobody has seen.

## Alternatives considered

**Leave it, because the framework drops an unknown field harmlessly.**
Rejected: harmless to the database is not harmless to the reader. This is
the failure mode the app has been closing all along — a silent drop the
model reports as a success.

**Validate only the first row.** Rejected: a model that gets a fieldname
wrong gets it wrong in every row, but a model that gets it wrong in one
row is also possible, and checking one row would be a check that is right
most of the time.

**Refuse the whole create on any unknown key in any row.** This is what
it does. The alternative reading — drop the unknown key and carry on —
was rejected because it reproduces the silence this ADR exists to end.

**Recurse arbitrarily deep.** Rejected: a child table's rows can
themselves carry table fields, and the check stops at one level. That is
a real limit and it is recorded rather than hidden — the common case is
one level, and a model composing three-deep child rows has a bigger
problem than a fieldname.

## Consequences

* An invented fieldname inside a child table is refused with the
  correction, before anything is written.
* The create and update paths now answer the same mistake the same way at
  both levels.
* The test that would have caught the original gap fails with the check
  removed. A second test asserts a well-formed row still goes through,
  because a guard that refused every table field would make the tool
  useless for exactly the documents that have them.
* The check stops at one level of nesting. Recorded in
  `docs/FR-4_WRITING.md` as a known limit rather than as a gap that was
  missed.
* The general lesson is ADR-0035's, one level down: a check that exists
  for one path and not the one that needs it is a check that is true by
  inspection and false in use.

## See also

* [ADR-0035](0035-a-create-validates-the-fieldnames-it-is-given.md) — the
  top-level check this extends.
* `albanna/tools/erpnext.py` — `_child_table_refusal`, and
  `_create_refusal_for`, which calls it.
* `docs/FR-4_WRITING.md` — the requirements record, where the one-level
  limit is named.
