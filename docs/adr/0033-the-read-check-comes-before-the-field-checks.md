# ADR-0033: The read check comes before the field checks

Status: **Accepted**
Date: 2026-11-06

## Context

`_load_for_update` validates a change before it loads the document. Its
docstring said why, and the reasons were good:

> *"The refusals that do not need the document come first: a field that does
> not exist, a field the framework owns, a field the form would not let a
> person change. They are cheaper, and they are the ones a model most often
> gets wrong."*

Both true. The field checks need only the DocType's meta; the read check needs
the document. And a model gets fieldnames wrong far more often than it gets
documents wrong, so answering the field question first saves the reader a
round trip.

What the docstring did not say was the consequence. A reader who may not read a
row learned its DocType's **fieldnames** before being refused the read. An
invented fieldname comes back with a correction — *"field 'custmer' (closest:
'customer')"* — and a correction is also a disclosure.

The existing test that proved the read refusal beat the *submitted* refusal used
valid data, so it never reached the field check and could not have caught this.

## Decision

**The document is loaded and the read is checked before the field checks.**

```python
document = frappe.get_doc(doctype, name)  # first
if not may_read(document):
    return _read_refusal(doctype, name)  # then the read
refusal = _field_refusal(meta, doctype, data, name)  # then the fields
```

The docstring now says the order is not the cheap one, and why. The document is
loaded either way — the field checks run after it, not instead of it — so the
cost of moving the read check first is one `get_doc` that was already going to
happen.

**This is a real trade-off, not a pure improvement, and it is recorded as one.**
The cheap checks now run after an expensive one. The disclosure argument wins,
but a reader who meets both refusals in one turn now waits for a document load
to be told their fieldname was wrong.

## Alternatives considered

**Keep the cheap order and accept the leak.** Rejected, but narrowly. The leak
is small: the authority layer refuses a caller with no write permission on the
DocType before `_load_for_update` runs at all, so the reader must hold write on
the DocType to reach this code — and a writer sees the form, which shows the
fieldnames. What decided it was not the size of the leak but the inconsistency:
the app had just closed the same hole for `get_doctype_meta` (ADR-0027), where
any reader could describe any DocType. Leaving this one open would mean the rule
was "a reader may not learn a DocType's fields, unless they hold write on it",
which is not a rule anybody chose.

**Check the read only when the field checks pass.** Rejected: it is the same
order with extra steps, and it leaks in exactly the same cases.

**Load the document lazily, only for the read check.** Rejected: the document is
needed for the change itself, so there is no saving to have.

**Refuse the field correction for an unreadable document but keep the cheap
order.** Rejected: that is the current behaviour with a special case bolted on,
and the special case would have to know the document was unreadable — which
means loading it, which is the reorder.

## Consequences

* A reader who may not read a row is told that, and nothing else — not the
  fieldnames, not the corrections.
* The field checks still run, and still correct, for a reader who may read the
  row. The model's most common mistake is still answered first *for them*.
* The cost is one document load before the cheap checks, on every update. It is
  a load that happened anyway.
* The docstring records the trade-off, so the next person who "optimises" the
  order back finds the reason it is not the cheap one.
* The test that pins it uses invalid data against an unreadable document — the
  combination the existing test avoided.

## See also

* [ADR-0027](0027-a-read-tool-is-gated-by-the-doctype-it-names.md) — the same
  hole, closed for `get_doctype_meta`, which is what made this one look like an
  inconsistency rather than a trade-off.
* [ADR-0028](0028-the-permission-check-comes-before-the-hint.md) — the ordering
  principle, stated for a report's filters and applied here to a field
  correction.
* `albanna/tools/erpnext.py` — `_load_for_update`, and the docstring that now
  says why the order is not the cheap one.
