# FR-3 — Reading

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the five functional requirements FR-3.1 … FR-3.5, which
describe the act of reading — listing documents, reading one document,
describing a DocType's fields, running a report, and the permission
parity that has to hold across all four.  The write side is covered by
FR-2's asking and by the moat audit in `docs/ROADMAP.md` §9.

---

## FR-3.1 — Listing documents

**Requirement.** The assistant can find documents of one DocType, with
filters, sorting and pagination, and the result is the caller's own view
of the data: the filters and the sort are checked before they reach the
database, and a malformed request is corrected rather than passed through.

**Status.** Shipped, with the gaps below closed in this pass.

**Evidence.**
- `albanna/tools/erpnext.py:350` — `list_docs`, the implementation.
- `albanna/tools/erpnext.py:392-398` — `limit` is clamped to
  `MAX_LIMIT` (500) and `offset` to a non-negative integer.
- `albanna/tools/erpnext.py:190` — `_validate_filters`, added this
  pass: a filter must be a three-element `[fieldname, operator, value]`
  triple, the operator must be one of the documented set, and the value
  must be a plain string.  A list or an object as a value — the shape
  the model reaches for when it wants `in` or `between` — is refused.
- `albanna/tools/erpnext.py:270` — `_validate_order_by`, added this
  pass: the sort is checked against the DocType's fields, with the same
  close-match correction `_validate_fields` gives an invented fieldname.
- `albanna/core/tools.py:240-310` — the manifest's schema, which
  documents the filter shape and the operator set the validator enforces.

**Gaps found.**
- **G1 (fixed this pass).** `_normalise_filters` passed every malformed
  shape through: a list value, an object value, a two-element triple, a
  four-element triple.  The schema promised rejection; nothing rejected.
  Fixed by `_validate_filters`, which refuses each shape with an envelope
  naming the rule.
- **G2 (fixed this pass).** `order_by` was the one parameter with no
  app-level check — Frappe's blacklist only.  Fixed by
  `_validate_order_by`.
- **G3 (tested this pass).** Filters, sorting, limit and offset had no
  test through the tool.  Covered in `albanna/tests/test_integration.py`
  (`TestListDocsFilters`) and in `tests/test_list_docs_validation.py`.

**Accepted trade-offs.** Enforcing the operator set exactly as documented
refuses an operator Frappe would have accepted.  That is the right trade
— the schema is the contract shown to the model — but it is a narrowing,
and it is recorded here as a decision awaiting confirmation (see
§Blocked).

---

## FR-3.2 — Reading one document

**Requirement.** The assistant can read one document by its DocType and
name, with an optional list of fields, and a field the caller may not
read is never returned — not even as a default value, and not even when
the caller names it.

**Status.** Shipped, with the gaps below closed in this pass.

**Evidence.**
- `albanna/tools/erpnext.py:587` — `get_doc`, the implementation.
- `albanna/tools/erpnext.py:572` — `_hidden_fields`, the fields at a
  higher permission level.
- `albanna/tools/erpnext.py:748-785` — the read is loaded, then checked
  with `may_read`, then the hidden fields are removed before any field is
  chosen, so naming a hidden field explicitly does not bring it back.
- `albanna/tools/erpnext.py:626-633` — the whole-document path pops the
  hidden fields rather than leaving them with their default value.
- `albanna/tools/erpnext.py:618-633` — the `fields` path now adds a hint
  when a requested field was withheld.

**Gaps found.**
- **G1 (fixed this pass).** The `fields` path dropped a hidden field in
  silence: the model could not tell "empty" from "hidden", and so could
  report a flag as off when it was merely unreadable.  Fixed by a hint
  in the envelope: *"one of the fields you asked for is not readable by
  this account and was not returned."*  The field is not named — not even
  by being absent from a list — because the model must not know which one.
- **G2 (tested this pass).** `get_doc`'s own read refusal — load, check,
  refuse, before any field is chosen or `as_dict()` is called — had no
  test.  Covered in `albanna/tests/test_integration.py`
  (`TestGetDocRead`).

---

## FR-3.3 — Describing a DocType

**Requirement.** The assistant can ask what fields a DocType has — their
names, types, labels, whether they are mandatory, and their options — so
that it uses real fieldnames rather than plausible guesses.  The
description is the DocType's own, and a DocType the caller may not read
is not theirs to describe.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/tools/erpnext.py:802` — `get_doctype_meta`, the
  implementation.
- `albanna/tools/erpnext.py:823-845` — the gate added this pass: the
  DocType must be in `readable_doctypes(user)`, the same helper
  `list_doctypes` uses at `albanna/tools/erpnext.py:2129-2131`.  It
  fails closed on an exception.
- `albanna/tools/erpnext.py:847-875` — the full field list, the `fields`
  projection, and the `unknown_fields` hints.

**Gaps found.**
- **G1 (fixed this pass).** `get_doctype_meta` called `frappe.get_meta`
  and checked nothing.  The authority layer returns `Decision.allow()`
  outright for a non-mutating spec (`albanna/core/authority.py:247-250`),
  so per-DocType permission was the tool's own job, and it did not do
  it.  This is the same hole `list_doctypes` was already closed for:
  its docstring says the Desk hides the DocTypes a reader may not read,
  and `tests/test_parity.py:809-834` holds the catalogue to exactly that,
  naming Salary Slip, Salary Component and Employee Checkin.
  `get_doctype_meta` was the front door to the same knowledge —
  fieldnames, labels, and the `options` of a Select field, which is the
  list of permitted values — and it was unlocked.
- **G3 (tested this pass).** The full field list, the `fields`
  projection, the `unknown_fields` hints, and the new refusal are covered
  in `albanna/tests/test_integration.py` (`TestGetDoctypeMetaBehaviour`).

**Accepted trade-offs.** The refusal is consistent rather than
obstructive: the prompt tells the model to call `get_doctype_meta`
before writing to a field, and a model that cannot read a DocType cannot
write to it either.

---

## FR-3.4 — Running a report

**Requirement.** The assistant can run an ERPNext report and return its
rows, with pagination, and a report the caller may not run is refused
before it runs.  A report that needs a filter the caller did not supply
says which one.

**Status.** Shipped, with the gaps below closed in this pass.

**Evidence.**
- `albanna/tools/erpnext.py:683` — `run_report`, the implementation.
- `albanna/tools/erpnext.py:993` — `_report_refusal`: the report's own
  role restriction, the report permission on the DocType it is about, and
  the disabled flag.  A role check that raises is a refusal.
- `albanna/tools/erpnext.py:959` — `_missing_mandatory_filters`, added
  this pass: a mandatory filter with no default that the caller did not
  supply is reported back with its key.
- `albanna/tools/erpnext.py:1097` — `_report_shape`, which reads the
  four result shapes ERPNext's reports return.
- `albanna/tools/erpnext.py:930-935` — the pagination envelope
  (`truncated`, `next_offset`).

**Gaps found.**
- **G2 (fixed this pass).** The schema promised twice that a missing
  mandatory filter would be reported back with the key to add; nothing
  looked at the report's mandatory filters.  Fixed by
  `_missing_mandatory_filters`, which reads `report_doc.filters` (a Table
  of Report Filter, each row carrying `fieldname`, `label`, `mandatory`
  and `default`) and refuses with the keys to add.  A mandatory filter
  that carries a default is not missing — the report fills it.
- **G1 (tested this pass).** The three refusal checks, the bounds
  envelopes, the pagination, and the four result shapes are covered in
  `albanna/tests/test_integration.py` (`TestRunReportBehaviour`) and in
  `tests/test_report_shape.py`.

---

## FR-3.5 — Permission parity of the read operations

**Requirement.** The assistant may never read what the person asking may
not.  Every read path is gated, and a new read path added next year is
gated the day it is registered.

**Status.** Shipped, with the guard added this pass.

**Evidence.**  The read path against how its permissions are applied:

| Read path | Where the permission is applied | Helper |
|---|---|---|
| `list_docs` | `frappe.get_list`, which applies the caller's roles and User Permissions | the framework's own |
| `get_doc` | `may_read(document)` after loading, before any field is chosen | `albanna/permissions.py:285` |
| `get_doctype_meta` | `readable_doctypes(user)` before describing | `albanna/permissions.py:217` (added this pass) |
| `run_report` | `_report_refusal`: the report's own role check, the report permission on its DocType, and the disabled flag | `albanna/tools/erpnext.py:993` |
| `list_doctypes` | `readable_doctypes(user)` | `albanna/permissions.py:217` |
| `ask_question` | nothing: it touches no document | — |

**Gaps found.**
- **G1 (fixed this pass, shared with FR-3.3).** `get_doctype_meta` had
  no permission check.  Fixed once, for both requirements.
- **G2 (added this pass).** No guard enumerated the read tools and
  asserted each was gated.  Added in
  `albanna/tests/test_read_guard.py`: it walks the read tools by name
  from `TOOL_MANIFEST` rather than a hand-written list, so a read tool
  added next year is covered the day it is registered, and it failed on
  `get_doctype_meta` before Stage 1 fixed it — which is the evidence
  that it works.

---

## Blocked

- **FR-3.1's operator-set narrowing.**  Enforcing the operator set
  exactly as documented refuses an operator Frappe would have accepted.
  Implemented as specified; the owner may want the validator to allow
  anything Frappe allows and reject only the shape.  Recorded as a
  decision awaiting confirmation.

## Deliberate exclusions

None in this pass.

## Accepted trade-offs

- `get_doctype_meta` refuses a DocType the caller may not read, which is
  consistent with the prompt's instruction to call it before writing: a
  model that cannot read a DocType cannot write to it either.
- The withheld-field hint does not name the field, and does not count
  them, so the model learns that something was withheld without learning
  what.

---

## Pointer

`docs/ROADMAP.md` §9 records the moat audit that found the read-side
holes this pass closes; §10 records the operations pass.  This document
is the reading-specific record.