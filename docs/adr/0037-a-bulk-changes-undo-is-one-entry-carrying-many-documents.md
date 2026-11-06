# ADR-0037: A bulk change's undo is one entry carrying many documents

Status: **Accepted**
Date: 2026-11-06

## Context

The undo model is *one tool call → one undo entry → one document*.
`undo_entry` builds one dict per call, `_take_back` carries out one entry
against one `doctype` and `name`, and `spend` removes one entry from the
stored calls. Every tool fits that shape.

`bulk_update_doc` does not. It changes the same fields on up to two hundred
documents in one call.

The rule said it was undoable. `UNDO_BY_ACTION["update"]` listed
`bulk_update_doc`, and `test_a_bulk_change_may_be_undone_too` asserted it.
But that test constructed a **synthetic** entry — a single document with
hand-written `before` values — so it proved the rule and not the tool.

The tool never produced an entry. `bulk_update_doc`'s result carried
`{"doctype", "changed", "total", "failed"}` and no `before`, and
`undo_entry` needs `data["before"]` to build an update entry. So it returned
`None`; `_is_undoable_call` returned `False`; the live event carried no
`undoable`; the stored entry had no `undo`; and the transcript said not
undoable. **The button never appeared.**

`_bulk_change_one` computed `_actual_changes(document, data)` — which knows
exactly what the before-values were — and threw them away, keeping only a
count.

## Decision

**A bulk change's undo is one entry carrying a per-document list, under a
new action.**

```python
{"action": "update_many", "doctype": "Sales Invoice",
 "documents": [{"name": "SAL-1", "data": {"status": "Draft"}}, …]}
```

`UNDO_BY_ACTION` gains `"update_many": ("bulk_update_doc",)`, and
`_take_back` loops the list **in reverse**, stopping at the first failure
exactly as `undo_message` does for a sequence of calls.

One-entry-per-call is preserved. `spend` is unchanged. The data model every
other tool uses is untouched.

## Alternatives considered

**Make an entry a list, and change the data model.** Rejected: it would
touch `entry()`, `is_undoable()`, `spend()` and `_take_back()` for every
tool, to accommodate the one tool that needs many. The contained shape is a
new action; the alternative is a migration of the undo format.

**Store one call entry per document.** Rejected: it is one call. The stored
tool calls are a record of what the assistant *did*, and it did one thing.

**Drop the bulk undo.** Rejected: the capability is real and the roadmap
lists it. A bulk change is exactly the write a reader most wants to be able
to take back, because it is the one they are least able to check by eye.

**Revert by re-running the change with the old values as a second bulk
change.** Rejected: it would need the same per-document before-map, so it
costs the same to build and loses the reverse ordering and the
stop-at-first-failure behaviour the single-document undo already has.

## Consequences

* A bulk change is offered for undo, and the undo puts every document back.
* `_take_back` grew a fourth action, and it is the only one that loops. Its
  failure behaviour matches `undo_message`'s: stop, log, and report what was
  taken back.
* The stored entry is larger — one before-map per changed document — on a
  call that already changed up to two hundred. That is proportionate, and it
  is the same trade `update_doc` already makes by storing its `before`.
* The test that would have caught this now exists: it runs a real bulk
  change through the backend and follows it all the way through — the stored
  entry carries the undo, the transcript offers the button, and taking it
  back puts every document back. It fails without the fix.
* The general lesson is the one ADR-0035 recorded for a different tool: a
  rule that is tested with a hand-written entry is a rule that has not been
  tested. The synthetic entry was correct about the rule and silent about
  the tool.

## See also

* [ADR-0035](0035-a-create-validates-the-fieldnames-it-is-given.md) — the
  same failure shape on the write side: a check that exists for one path and
  not the one that needs it.
* `albanna/core/undo.py` — the rule, and the new action.
* `albanna/services/undo.py` — `_take_back`, and the loop that stops at the
  first failure.
* `albanna/tools/erpnext.py` — `_bulk_change_one`, which now keeps the
  before-values it always had.
