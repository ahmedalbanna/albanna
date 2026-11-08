# FR-4 — Writing

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the ten functional requirements FR-4.1 … FR-4.10, which
describe the act of writing — creating a document, changing one, changing
many at once, the lifecycle actions (submit, cancel, amend, delete), the
permission parity that has to hold across all of them, the honesty of the
messages a write produces, and the surface the tools expose.

---

## FR-4.1 — Creating a document

**Requirement.** The assistant can create a document of a DocType the
caller may create, with field values the caller chose, and the framework's
own fields are not the assistant's to set.  A field that does not exist
is corrected rather than passed through, and a file the caller may not
read is not attached to the new document.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/tools/erpnext.py:1129` — `create_doc`, the implementation.
- `albanna/tools/erpnext.py:1188` — `_create_refusal_for`: the DocType
  must be named, the data must be an object, the data must not name a
  DocType of its own, and the framework's fields are refused.
- `albanna/tools/erpnext.py:1188-1243` — the fieldnames are now validated
  through `_validate_fields` (added this pass), after the protected-field
  check and before the attachment check, so an invented fieldname comes
  back with the close-match correction.
- `albanna/tools/erpnext.py:156` — `_validate_fields`, the correction.
- `albanna/tools/erpnext.py:1481` — `_attachment_refusal`, the file check.
- `albanna/tools/erpnext.py:1172` — `_submit_created`, the `submit=True`
  path with its own savepoint.

**Gaps found.**
- **G1 (fixed this pass).** `create_doc` went through
  `_create_refusal_for`, which checked the protected fields and the
  attachments but never the fieldnames.  An invented fieldname on a
  create got silence (Frappe ignores a field not in the meta) or an
  opaque database error, where the same mistake on an update got the
  close-match correction.  Fixed by validating the top-level keys through
  `_validate_fields`.
- **G2 (tested this pass).** The `submit=True` path and the file cleanup
  on a refused save had no coverage.  Covered in
  `albanna/tests/test_integration.py` (`TestRemainingPaths`).

**Blocked.** Nothing at the top level: Stage 1 validates the fieldnames
the create is given, exactly as the update path does.  What remains is
one level down — a fieldname invented inside a child-table row was still
silently dropped, because a table field is replaced whole and the
framework ignores a key the child DocType's meta does not have.  That is
now checked too, against the child DocType's own meta, with the same
close-match correction.  See ADR-0045.

**Known limit, recorded rather than hidden:** the check stops at one
level of nesting.  A child table's rows can themselves carry table
fields, and those are not validated.  The common case is one level, and a
model composing three-deep child rows has a bigger problem than a
fieldname — but the limit is real and it is named here rather than left
for somebody to discover.

---

## FR-4.2 — Changing a document

**Requirement.** The assistant can change the fields of a document the
caller may read and write, giving only the fields that should change.
A submitted document cannot be edited in place.  A field that does not
exist is corrected, a read-only field is refused, and a User Permission
that limits which rows may be changed is honoured.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/tools/erpnext.py:1254` — `update_doc`, the implementation.
- `albanna/tools/erpnext.py:1349` — `_field_refusal`: existence, then
  protected fields, then read-only fields.
- `albanna/tools/erpnext.py:1383` — `_load_for_update`: the document is
  loaded and the read is checked before the field checks (changed this
  pass), so a reader who may not read a row is not told its fieldnames.
- `albanna/tools/erpnext.py:1643` — `_update_refusal`, including the
  User Permission message.
- `albanna/tools/erpnext.py:1665` — `_submit_update`, the `submit=True`
  path.
- `albanna/tools/erpnext.py:1735` — `_table_lengths`, the child-table
  replacement count.

**Gaps found.**
- **G1 (fixed this pass).** `_load_for_update` ran `_field_refusal`
  before `may_read`, so a reader who may not read a row learned its
  DocType's fieldnames — an invented fieldname came back with
  "closest: 'customer'" — before being refused the read.  Fixed by
  loading the document and checking `may_read` first.  The document is
  loaded either way, so the cost is nil; the cheap checks now run after
  an expensive one, and that trade-off is recorded in the docstring.
- **G2 (tested this pass).** The `submit=True` path, the child-table
  replacement message, and the row-level (User Permission) refusal had
  no coverage.  Covered in `albanna/tests/test_integration.py`
  (`TestRemainingPaths`).

---

## FR-4.3 — Changing many documents at once

**Requirement.** The assistant can change the same fields on many
documents of one DocType at once, described by a condition.  The change
is proposed first and waits for the reader's approval before it runs.
A submitted document is never changed this way.

**Status.** Shipped after this pass, with a behaviour change flagged below.

**Evidence.**
- `albanna/tools/erpnext.py:2019` — `bulk_update_doc`, the implementation.
- `albanna/core/tools.py` — the `BULK_UPDATE_DOC` manifest entry, whose
  description promises the approval.
- `albanna/services/chat_service.py:961-964` — `gated` is now true for
  `bulk_update_doc` unconditionally (changed this pass).
- `albanna/services/approval.py:196` — `_preview_bulk`, the card's count
  and sample names.
- `albanna/services/approval.py:421` — `write_target`, which now carries
  the approved set for a bulk change.
- `albanna/services/approval.py:472` — `still_unchanged`.

**Gaps found.**
- **G1 (fixed this pass — behaviour change).** `gated` was
  `spec.mutating and confirm_writes_for(principal.user)`, and
  `confirm_writes_for` reads a site setting whose default is `False`
  (`albanna/user_policy.py:44-46`).  With the shipped configuration a
  bulk change of up to 200 documents ran immediately, with no card at
  all, even though the schema promises one for this tool specifically.
  `create_doc` and `update_doc` make no such promise.  Fixed by making
  `bulk_update_doc` always gated, regardless of the site setting.  The
  `confirm_writes` site default is left untouched, so every other write
  keeps the operator's setting.  **A reader will notice that a bulk
  change now always shows an approval card, even on sites where single
  writes do not.**
- **G2 (fixed this pass).** The count on the card and the set that runs
  were two separate queries: `_preview_bulk` queried `frappe.get_list`
  to build the card, then `bulk_update_doc` queried it again to find the
  documents to change, and `write_target` returned `{}` for anything that
  was not `update_doc`, so the `still_unchanged` check did not apply.
  A document that started matching the filter between the card and the
  write was changed without ever having been counted.  Fixed by carrying
  the approved set through `write_target` and having `bulk_update_doc`
  compare its own query against it, reporting any document that appeared
  or disappeared.  The comparison is done in `bulk_update_doc` itself
  rather than in `still_unchanged`, because that is where the filters
  live and where the difference can be named.
- **G3 (tested this pass).** `_preview_bulk` had no coverage — not the
  count, the sample names, the permission filtering, nor the zero-match
  case, including the claim that a card names only the documents the
  reader may see.  Covered in `albanna/tests/test_integration.py`
  (`TestPreviewBulk`).

**Blocked.** Flipping the `confirm_writes` site default to `True` would
change every write on the site and is not this requirement's to make.

---

## FR-4.4 — The lifecycle actions

**Requirement.** The assistant can submit a draft, cancel a submitted
document, amend a submitted document (cancel and create a new draft), and
delete a draft or cancelled document.  Each runs the document's own rules,
and a document in the wrong state is refused.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/tools/erpnext.py:1779` — `submit_doc`.
- `albanna/tools/erpnext.py:1837` — `cancel_doc`.
- `albanna/tools/erpnext.py:1895` — `amend_doc`, with the savepoint
  covering both halves.
- `albanna/tools/erpnext.py:1962` — `delete_doc`.
- `albanna/tools/erpnext.py:453` — `_load_for_action`, the shared loader
  that checks the read before the write.

**Gaps found.**
- **G1 (fixed this pass).** `submit_doc` distinguished three failures
  (`PermissionError`, `ValidationError`, generic `Exception`); `cancel_doc`,
  `amend_doc` and `delete_doc` distinguished only two, so a lifecycle
  action refused by a validation (an `on_cancel` hook, a linked document,
  an `on_trash` guard) was reported as "Failed to …" rather than
  "Validation failed for …".  The `ValidationError` branch was added to
  all three, with the message `submit_doc` already uses.
- **G2 (tested this pass).** None of the four had behavioural tests
  beyond the read refusal.  Covered in `albanna/tests/test_lifecycle.py`:
  the happy paths, the wrong-state refusals, the permission refusals, the
  read refusal (parameterised once over the four tools), and the savepoint
  property that a failed amend leaves the original submitted.

---

## FR-4.5 — Permission parity of the write operations

**Requirement.** The assistant may never write what the person asking may
not.  Every write path is gated, and a new write path added next year is
gated the day it is registered.

**Status.** Shipped after this pass.

**Evidence.**  The write path against how its permissions are applied:

| Write path | Where the permission is applied | Helper |
|---|---|---|
| `create_doc` | the authority layer's `creatable_doctypes`, then Frappe's create permission on `insert()` | `albanna/permissions.py` (`creatable_doctypes`) |
| `update_doc` | the authority layer's `writable_doctypes`, then Frappe's write permission on `save()`, plus `may_read` on the row | `albanna/permissions.py` (`writable_doctypes`, `may_read`) |
| `bulk_update_doc` | `get_list` (read) for the targets, `may_read` per document, then Frappe's write permission on `save()` | `albanna/permissions.py` (`may_read`) |
| `submit_doc` | the authority layer's `submittable_doctypes`, then Frappe's submit permission on `submit()` | `albanna/permissions.py` (`submittable_doctypes`) |
| `cancel_doc` | the authority layer's `cancellable_doctypes`, then Frappe's cancel permission on `cancel()` | `albanna/permissions.py` (`cancellable_doctypes`) |
| `amend_doc` | the authority layer's `amendable_doctypes`, then Frappe's cancel and create permissions | `albanna/permissions.py` (`amendable_doctypes`) |
| `delete_doc` | the authority layer's `deletable_doctypes`, then Frappe's delete permission on `delete_doc()` | `albanna/permissions.py` (`deletable_doctypes`) |

- `albanna/tests/test_write_guard.py` — the guard, added this pass: it
  walks the write tools by name from `TOOL_MANIFEST` rather than a
  hand-written list, and requires a denied case for each, built by a
  factory rather than static arguments, because a lifecycle tool needs a
  document in a particular state.

**Gaps found.**
- **G1 (added this pass).** `tests/test_authority.py` exercised
  `_authorize_write` throughout, but every write-tool case in it was
  `create_doc`.  The mechanism is generic so the mechanism was tested,
  but no test showed `submit_doc` refused for a user without the submit
  permission, or `delete_doc` for one without delete.  Fixed by the guard.

---

## FR-4.6 — The `submit` parameter

**Requirement.** `create_doc` and `update_doc` both take a `submit`
parameter; a caller who may create but may not submit gets a document
created and a message saying it could not be submitted.

**Status.** Shipped, tested this pass.

**Evidence.**
- `albanna/tools/erpnext.py:1129` — `create_doc(..., submit=False)`.
- `albanna/tools/erpnext.py:1254` — `update_doc(..., submit=False)`.
- `albanna/tools/erpnext.py:1172` — `_submit_created`, its own savepoint.
- `albanna/tools/erpnext.py:1665` — `_submit_update`.

**Gaps found.**
- **G1 (tested this pass).** Neither path had a test, including the
  may-create-but-not-submit case.  Covered in
  `albanna/tests/test_integration.py` (`TestRemainingPaths`).

---

## FR-4.7 — Child-table replacement honesty

**Requirement.** A table field is replaced whole.  When a replacement
leaves fewer lines than before, the message says how many went, because
that sentence is the only thing that says two rows were deleted.

**Status.** Shipped, tested this pass.

**Evidence.**
- `albanna/tools/erpnext.py:1735` — `_table_lengths`.
- `albanna/tools/erpnext.py:1749` — `_update_message`, the sentence:
  "Replaced the 5 line(s) of 'items' with 3 — the 2 line(s) that were
  not in the new list are gone".

**Gaps found.**
- **G1 (tested this pass).** `_table_lengths` and the sentence it feeds
  had no coverage.  Covered in `albanna/tests/test_integration.py`
  (`TestRemainingPaths`), asserting on the message rather than the state.

---

## FR-4.8 — The order of the checks

**Requirement.** The field checks run before the read check on the update
path, so that a model's most common mistakes are corrected cheaply —
but a reader who may not read a row must not learn its fieldnames from
the correction.

**Status.** Shipped after this pass, with the trade-off recorded.

**Evidence.**
- `albanna/tools/erpnext.py:1383` — `_load_for_update`, now loading the
  document and checking `may_read` before `_field_refusal`.

**Gaps found.**
- **G1 (fixed this pass).** The previous order ran `_field_refusal`
  first, and its docstring said why: the checks are cheaper and are the
  ones a model most often gets wrong.  Both true.  What it did not say
  is the consequence: a reader who may not read a row learns its
  DocType's fieldnames, because an invented fieldname comes back with
  "closest: 'customer'".  Fixed by loading the document and checking
  `may_read` first.  The document is loaded either way, so the cost is
  nil.  This is a real trade-off, not a pure improvement — the cheap
  checks now run after an expensive one — and it is made deliberately.

---

## FR-4.9 — The write path and its permissions

**Requirement.** The write path is recorded against how its permissions
are applied, so that a future contributor checks it before adding a
write tool, and so that the write guard is meaningful rather than
decorative.

**Status.** Shipped (this document).

**Evidence.**  See the table in FR-4.5.

---

## FR-4.10 — No SQL on the tool surface

**Requirement.** No tool accepts SQL.  The one path that runs SQL (Query
Reports) is administrator-authored, Frappe-guarded and parameterised.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/core/tools.py` — the comment beside `TOOL_MANIFEST` recording
  the rule.
- `albanna/tests/test_tool_manifest.py` — the guard that walks the
  manifest and asserts no tool declares a SQL-shaped parameter (`sql`,
  `query`, `statement`).
- `albanna/permissions.py:207` — `_doctypes_for_permission`, where
  `ptype` is interpolated into SQL as a column name; an allowlist now
  guards it (changed this pass), naming the seven literals that may
  reach it.

**Gaps found.**
- **G1 (added this pass).** Nothing held the tool surface to "no SQL".
  Fixed by the test and the comment.
- **G2 (fixed this pass).** `ptype` was interpolated into SQL as a
  column name with nothing enforcing that only the three (in fact seven)
  literals reached it.  Fixed by an allowlist in
  `_doctypes_for_permission`.

---

## Blocked

- **FR-4.1's child-table field validation.** Stage 1 validates the
  top-level keys only.  Recursing into child-table rows is a real and
  common model error, but it is a bigger change and should be a
  deliberate one.
- **FR-4.3's `confirm_writes` default.** Stage 2.1 gates
  `bulk_update_doc` specifically.  Flipping the site default to `True`
  would change every write on the site and is not this requirement's to
  make.

## Deliberate exclusions

None in this pass.

## Accepted trade-offs

- `get_doctype_meta` refuses a DocType the caller may not read (see
  FR-3.3); the same consistency holds for writes.
- The withheld-field hint does not name the field (see FR-3.2).
- FR-4.8 moves the cheap checks after an expensive one, deliberately.

---

## Pointer

`docs/ROADMAP.md` §9 records the moat audit that found the write-side
holes this pass closes.  This document is the writing-specific record.
