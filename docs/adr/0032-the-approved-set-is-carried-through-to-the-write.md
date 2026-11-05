# ADR-0032: The approved set is carried through to the write

Status: **Accepted**
Date: 2026-11-06

## Context

A single update is protected against staleness. `write_target` records the
document and its `modified` stamp when the reader is asked, and
`still_unchanged` compares them once they have answered: a document that has
moved in the meantime is not the one they were asked about, and the change
would land on top of somebody else's edit.

A bulk change had no such protection, and it needed one more.

`_preview_bulk` queries `frappe.get_list` to build the card — the count and the
first five names. The reader approves. Then `bulk_update_doc` queries
`frappe.get_list` **again** to find the documents to change. Two queries, and
the second is the one that acts.

`write_target` returned `{}` for anything that was not `update_doc`, so
`still_unchanged` had nothing to compare and returned `True` — the check that
protects a single write simply did not exist for a bulk one. A document that
started matching the filter between the card and the write was changed without
ever having been counted, and the reader had approved a number that was true a
minute ago.

## Decision

**The approved set is carried through to the write, and the write refuses when
the set has moved.**

`write_target` now returns `{"doctype": …, "names": [...]}` for a bulk change —
the documents the card counted. `_ask_for_approval` copies them onto the call's
arguments as `_approved_names`, and `bulk_update_doc` compares its own query
against them through `_bulk_approved_set_refusal`. A document that appeared or
disappeared refuses the whole change:

> *"The set of Sales Invoice documents changed since approval (appeared: …);
> nothing was changed."*

`still_unchanged` returns `True` for a bulk target, and that is deliberate
rather than an oversight: the comparison needs the filters, which live in the
tool, and a set comparison in `still_unchanged` would be a second
implementation of a rule the tool already has to run. The function says
"unchanged" so the write proceeds and reports the difference in its own words.

`_approved_names` is not in the manifest's schema and `additionalProperties` is
`False`, so the model cannot supply it. It is the app's own channel, filled in
by the approval path.

## Alternatives considered

**Do the comparison in `still_unchanged`.** Rejected: it would need the filters
re-parsed there, which is the tool's job, and it would be the second place that
knows how a bulk target set is built. One implementation, in the place that has
the inputs.

**Let the write run and report the difference afterwards.** Rejected: the reader
approved a set, and changing a document outside it on their behalf is exactly
what the approval was for. A report after the fact tells them something
happened they did not approve.

**Re-query at approval time and freeze the names.** Rejected: that is what this
does. The alternative reading — freeze the *filter* rather than the names — was
rejected because a filter is not what the reader saw; they saw a count and a
list.

**Record only the count.** Rejected: a count cannot be compared. Two documents
swapping in and out leaves the count unchanged and the set different.

## Consequences

* A bulk change touches exactly the set the reader counted, or it does not run.
* The refusal names what moved — appeared and disappeared — so the reader can
  act on it rather than being told "something changed".
* `write_target` grew a third shape alongside the document stamp and the empty
  result, and `still_unchanged` grew a branch that deliberately does nothing.
  Both are commented, because a function with a branch that returns `True`
  unconditionally looks like a bug to the next reader.
* The cost is one extra `frappe.get_list` per approved bulk change — the card's
  preview, the target's names, and the tool's own query. Three queries for one
  change is not free, and it is the price of the reader's approval meaning
  something.
* The general lesson is the one ADR-0028 recorded for a different tool: when a
  check leaks and a check refuses, the refusal goes first. Here the leak was
  not information but *action* — changing a row the reader never counted.

## See also

* [ADR-0031](0031-a-bulk-change-is-gated-whatever-the-operators-setting.md) —
  the gate this protects the meaning of.
* [ADR-0028](0028-the-permission-check-comes-before-the-hint.md) — the ordering
  principle, applied to a report's filters.
* `albanna/services/approval.py` — `write_target`, `still_unchanged`, and
  `_preview_bulk`.
* `albanna/tools/erpnext.py` — `_bulk_approved_set_refusal`.
