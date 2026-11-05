# ADR-0035: A create validates the fieldnames it is given

Status: **Accepted**
Date: 2026-11-06

## Context

`_validate_fields` checks a fieldname against the DocType's meta and, when it
does not exist, answers with the closest matches:

> *"field 'custmer' (closest: 'customer')"*

Three paths called it: `list_docs`, `get_doc`, and `_field_refusal` — which the
**update** path goes through. `create_doc` went through `_create_refusal_for`,
which checked the protected fields and the attachments and never the fieldnames.

So a model that invented a fieldname on a create got one of two things. Either
Frappe ignored the field — it is not in the meta, so it is not written — and the
model believed it had set something. Or the insert failed with a database error
the model could not act on. The same mistake on an update got the correction.

The write path that needed the check most was the one without it. A create is
where the model is most likely to be guessing: it is composing a document from
nothing, and the fieldnames are the part it has least to go on.

## Decision

**A create validates its fieldnames, exactly as an update does, and no more.**

`_create_refusal_for` now calls `_validate_fields` after the protected-field
check — the same order `_field_refusal` uses, so a protected field is refused
before its existence is questioned.

**The validation covers the top-level keys only.** Child-table rows are not
checked: a model that invents a fieldname inside `items` is still silently
ignored. That is a real and common error, and it is deliberately left for a
separate decision rather than built quietly — recursing into child rows means
walking every table field's meta, deciding what a "row" is for each fieldtype,
and answering a correction the model can act on for a field it cannot see the
shape of. It is a bigger change than the top level, and it should be made on
purpose.

## Alternatives considered

**Leave it, because Frappe ignores an unknown field harmlessly.** Rejected:
harmless to the database is not harmless to the reader. The model reports a
field it set, the reader believes it, and nobody discovers otherwise. A silent
drop is the failure mode this app has been closing all along.

**Validate child-table rows too.** Deferred, not rejected. It is the right
eventual answer and the wrong thing to do silently in the same change as the top
level — the two have different shapes and different failure modes, and one test
file covering both would read as though they were one rule.

**Refuse the whole create on any unknown field.** Rejected: that is what this
does, and it is right — a create with a field the model invented is a create the
model did not understand. But the alternative reading, *drop the unknown field
and carry on*, was considered and rejected because it reproduces the silence
this ADR exists to end.

**Validate at the backend, generically from the schema.** Rejected: the schema
declares `additionalProperties: True` for `data`, deliberately, because a
document's fields are the DocType's business and not the manifest's. Only the
tool has the meta.

## Consequences

* An invented fieldname on a create is refused with the correction, before
  anything is written.
* The create and update paths now answer the same mistake the same way, which is
  the point: two write paths that disagree about a fieldname are two answers to
  one question.
* A model that invents a field inside a child table is still silently ignored.
  That gap is recorded in `docs/FR-4_WRITING.md` as blocked, with the reason,
  rather than being forgotten.
* The check runs before the insert, so a refused create costs one meta read and
  no database write.

## See also

* [ADR-0026](0026-the-manifests-schema-is-a-contract.md) — the sibling decision
  on the read side: a tool validates what its schema promises.
* `albanna/tools/erpnext.py` — `_create_refusal_for`, `_field_refusal`, and the
  one validator they now share.
