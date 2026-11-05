# ADR-0027: A read tool is gated by the DocType it names

Status: **Accepted**
Date: 2026-11-05

## Context

`docs/TOOLS.md` has a table of the read tools, and a column headed
*Authorised against*. For `get_doctype_meta` it says:

> Frappe's `read` permission on that DocType.

The implementation called `frappe.get_meta(doctype)` and checked nothing.

The authority layer did not fill the gap, and the reason matters. For a
non-mutating spec it returns `Decision.allow()` outright
(`core/authority.py:247-250`). Per-DocType permission is deliberately the
*tool's* job, because the authority layer decides about tools and the tool
knows its target. `list_docs` does that job through `frappe.get_list`, and
`get_doc` through `may_read(document)`. `get_doctype_meta` did not do it.

So the one read tool that describes a DocType's shape was the one read tool
that would describe any DocType at all.

The app had already decided this question elsewhere, and had tested it.
`list_doctypes` — the catalogue behind the answer to "that DocType does not
exist" — filters by `readable_doctypes(user)`, and its docstring says why:

> *"The Desk's own search hides the DocTypes a reader may not read, and a
> model that knew the site had a 'Salary Slip' could tell the reader
> something the reader could not find out for themselves."*

`tests/test_parity.py:829-834` holds the catalogue to exactly that, naming
Salary Slip, Salary Component and Employee Checkin. `get_doctype_meta` was
the front door to the same knowledge — fieldnames, labels, and `options`,
which on a Select field is the list of permitted values — and it was
unlocked. A reader with no payroll role could ask the assistant what a
Salary Slip is made of.

## Decision

**A read tool that names a DocType is gated on the caller's read permission
for that DocType, and refuses naming the roles that hold it.**

`get_doctype_meta` now reads `readable_doctypes(str(frappe.session.user or
""))` — the same helper `list_doctypes` already uses, on a code path that
already runs — and refuses when the DocType is not in it. The refusal is
the shape `_read_refusal` established: it names the roles that *can* read
the DocType, because *"'you may not read this' is a wall and 'a Sales
Invoice is read by an Accounts User' is a fact about the organisation the
reader can act on."* When no role on the site holds the right, it says that
instead — a fact about the site rather than about the account.

It fails closed. An exception reading the readable set is an empty set, and
an empty set refuses: a permission engine that cannot answer has not said
yes.

## Alternatives considered

**Metadata is harmless — fieldnames are not data.** Rejected. `options` on a
Select field is the list of permitted values, and the app has already
decided, and tested, that a reader may not learn a DocType exists. The
catalogue hiding Salary Slip while `get_doctype_meta` describes it is not a
policy; it is an inconsistency.

**Gate it in the authority layer instead.** Rejected: the authority layer
would have to parse the tool's arguments to learn the target, which is the
tool's job and would put a per-tool concern in a per-tool-agnostic place.
The layer's `Decision.allow()` for reads is correct; the gate belongs where
the target is known.

**Check `frappe.has_permission(doctype, "read")` directly.** Considered.
`readable_doctypes` was chosen because `list_doctypes` already calls it on
the same path — the near-miss answer to "that DocType does not exist" runs
it — so the cost is already being paid and there is one source of truth for
what a caller may read.

**Refuse silently, without naming the roles.** Rejected: it is the wall the
app already decided against, and the roles are public knowledge — they are
on the DocType's own permission rows, which the reader can see in the Desk
if they hold the right to.

## Consequences

* The front door to a hidden DocType's shape is closed, and the catalogue
  and the describer now agree.
* The refusal names the roles that can read it, in the same sentence shape
  `get_doc` uses, so a reader who meets both refusals meets one rule.
* `readable_doctypes` is now called on a path that runs whenever the model
  asks about a DocType. It is the same call `list_doctypes` makes, so this
  is a second caller rather than a new cost — but it is worth knowing before
  a third is added.
* A model that cannot read a DocType cannot write to it either, so the
  refusal is consistent rather than obstructive: the prompt tells the model
  to call `get_doctype_meta` before writing to a field, and a model refused
  here would have been refused at the write too.
* The gap was invisible for as long as it was because nothing enumerated
  the read tools. [ADR-0030](0030-the-read-guard-walks-the-manifest.md) is
  what closes that, and it failed on this tool the day it was written —
  which is the evidence that it was needed.

## See also

* [ADR-0002](0002-authority-and-permissions.md) — the authority layer, and
  why it decides about tools rather than targets.
* [ADR-0008](0008-frappe-decides-permissions.md) — Frappe decides, which is
  the rule this applies rather than duplicates.
* [ADR-0030](0030-the-read-guard-walks-the-manifest.md) — the guard that
  would have caught this, and did.
* `docs/TOOLS.md` — the table whose promise was not kept, now true.
