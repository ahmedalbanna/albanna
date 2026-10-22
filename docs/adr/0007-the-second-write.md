# ADR-0007: The second write — changing a document

Status: **Accepted**
Date: 2026-10-22

## Context

The first release could make a document and could not change one.  A person
who asked the assistant to create a customer with a wrong phone number, and
then asked it to fix the phone number, was told — correctly, and
pointlessly — that no tool could do that.

The gap was noticed by the people who use it, which is the best way a gap is
noticed.  A tool set that can only *make* things and never *change* them
leaves the person who mistyped a field with no way to fix it through the
one interface that made the mistake.

There is a second reason, which is about the assistant's standing.  An
assistant that can only do half of what a person can do is an assistant
that has to apologise for the other half, and the apology is worse than the
refusal: it says the *tool* is weak, when the truth is that the
*organisation's* rules decide who may change what.  Those are very
different sentences, and only one of them is true.

## Decision

**A second write tool, `update_doc`, authorised against a different
right.**

| | `create_doc` | `update_doc` |
|---|---|---|
| target | a document that does not exist | a document that does |
| Frappe permission | `create` | `write` |
| target named by | `doctype` | `doctype` and `name` |

The right is the manifest's, not the authority layer's guess: `ToolSpec`
carries `write_permission`, and the authority layer asks the permission
checker the question that field names.  A role model that grants one does
not necessarily grant the other, and a refusal that named the wrong one
would be a refusal with a wrong reason in it.

### What it refuses, and why each refusal is a fact

* **A submitted document.**  The framework would let a server-side save
  rewrite one — the guard is in the form, not in `db_update` — so the
  guard is in the tool.  The refusal names the way a person does it:
  cancelling and amending, which this tool does not do.
* **A read-only field.**  The form will not let a person change one.  If
  the chat could, the assistant would be the only actor on the site who
  could set a field nobody else can.
* **The framework's own fields.**  `owner`, `docstatus`, `name` and the
  rest.  A document whose owner had been rewritten by a chat would be a
  document nobody could reason about afterwards — and `name` is worse than
  wrong, because `Document.update()` assigns it *first*: a data object
  that carried one would rename the document rather than change it.
* **A field that does not exist**, and **a document that does not exist**,
  each reported as itself.  "Not found" and "not permitted" are different
  answers, and only one of them is true most of the time.

### What it does about a table field

A table field is replaced whole, and the result says so — how many lines
were there, how many there are now, and, if lines went missing, that they
are gone.  A replacement is not a change of one field, and a report that
did not say so would be a lie.

### What it does when nothing changes

Nothing.  Writing the value a document already has would touch its
modified timestamp, run every hook on it, and tell the reader that
something was done when nothing was.  The result says that instead.

## Consequences

* **A write can fail without taking the turn's other writes with it.**
  This is the property the tool exposed.  A rollback is transaction-wide
  unless it is given a savepoint, and a transaction-wide rollback in the
  middle of a turn undoes everything the turn has done so far — including
  a document the assistant has already told the reader it created.  Every
  write now takes a savepoint first, and a failure rolls back to it and
  no further.  The bug this fixes was in `create_doc` too; it was simply
  rarer there.
* **The refusal says "edit" when the call was an edit.**  The wording is
  in the authority layer and it is worth being pedantic about: "creating a
  Customer is done by these roles" is the wrong sentence when the
  assistant was asked to *change* one.
* **The assistant knows what it may change before it starts.**  The prompt
  carries the account's writable DocTypes, for the same reason it carries
  the creatable ones: a person who says "change the phone number on this
  customer" should not be answered with a refusal, and should not have to
  be told what they already know.
* **The write surface is two tools, and both are things a person asks
  for.**  Not a third, not a general "edit anything" operation.  A delete
  is a different decision, and it does not have one yet.
