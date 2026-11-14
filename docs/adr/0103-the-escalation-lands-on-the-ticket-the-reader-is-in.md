# ADR-0103: The escalation lands on the ticket the reader is already in

Status: **Accepted**
Date: 2026-11-14
Supersedes the ToDo/Communication half of ROADMAP §2 item 1; extends
ADR-0048's permission rule to the new shape.

## Context

"Ask a human" creates a Frappe Issue.  For a reader standing in a ticket
that is the wrong handover: escalating a thread anchored on an Issue's
page opened a *second* ticket while the first was still open — confirmed
live, and the reason the item exists.  The thread knows where it was
born: the panel's page identity is `form|<doctype>|<name>`
(`context.mjs`), and the conversation stores it, so a thread born on
`form|Issue|ISS-0001` knows its ticket without being told.

## Decision

**A thread anchored on an open Issue hands over as a ToDo on that
Issue, not as a second ticket.**

`escalate_conversation` reads the conversation's page anchor.  When the
anchor is a form page of doctype `Issue`, the Issue still exists and is
not closed, and the caller may write there, the handover is a **ToDo**
with `reference_type=Issue` and `reference_name=<the issue>`, carrying
the same transcript block the Issue path builds — subject, the
questions, the answers, and the lines saying what the assistant read and
changed, refusals marked.

**The assignee** is the Issue's existing assignee when there is one —
read from the open ToDo rows the assignment system already writes, not
from a second source.  When nobody is assigned, the ToDo is created
unallocated and the endpoint's reply says so (`allocated_to: ""`); the
way forward is the ticket's own assignment UI, which the person who
asked can see.  No person-picker is built into the panel: the chat is
not a form, and a handover addressed to "somebody" is honest about
being unaddressed.

**Every other shape takes the existing path.**  A thread on a list
page, a report, a customer, or an Issue that is closed gets a new Issue
exactly as before — there is no ticket to attach to, and inventing a
destination would be the same wrong handover in a different direction.

**Permission, extended from ADR-0048.**  The ToDo path's gate is the
framework's own assignment rule, read from the code rather than invented:
``frappe.desk.form.assign_to.add`` — the Desk's assign panel — gates on
the **reference document's** permission and inserts the ToDo bypassing
ToDo's own, because ToDo's controller hook
(`frappe/desk/doctype/todo/todo.py::has_permission`) admits only the
roles explicitly granted on ToDo, and with the default ToDo permissions
that is System Manager alone.  A handover onto a ticket *is* an
assignment, so this endpoint applies the same gate: the caller must be
able to **read** *that Issue document*, and the refusal names the
permission.  A reader who cannot open the ticket is not handed a second
ticket as a side effect of being refused.  The button's rule
(`options().can_escalate`) grows to `can_create("Issue") or
can_create("ToDo")`: a support agent who cannot raise tickets but can
add ToDos still gets the button, and the endpoint enforces whichever
path the shape takes.

**Why not a Communication.**  A Communication goes *out* — to the
customer, on the ticket's timeline.  An escalation is an *internal*
handover: the work moves to a person, and the record of that is a ToDo
on the ticket, visible in the ticket's own assignment list.  The
direction is the decision.

## Alternatives considered

**ToDo allocated to the caller.**  Rejected: the caller is the agent
asking for help; assigning the follow-up to themselves is a second job
on their own desk, which is what the complaint was about.

**ToDo allocated to a configurable "support" user.**  Rejected for now:
a setting that names a person ages badly (leavers, shared mailboxes),
and the Issue's own assignee is the organisation's answer, already
maintained.  A site that wants escalation routed to a specific person
has assignment rules — Frappe's, not this app's.

**Communication on the ticket.**  Rejected — see above; wrong
direction.

**New Issue, linked.**  Rejected: the confirmed problem.  A second open
ticket for one customer's words is the work the reader was trying to
avoid.

## Consequences

* Escalating from a ticket no longer opens a ticket.
* The person picking the handover up finds it on the ticket, with the
  transcript and the assistant's actions — the same content the Issue
  path delivers.
* An unassigned handover is honest about being unassigned.
* A closed ticket still escalates out, because there is nothing open to
  attach to; the new-Issue path is unchanged there.
* The handover ToDo is created the framework's way
  (`ignore_permissions` on the ToDo itself, the gate on the ticket) —
  recorded as created by the caller, and the ticket's `_assign` and
  assignment comment are maintained by ToDo's own hooks.
* The endpoint's reply names what it created and where; the panel's
  "Escalated to support." notice stays true for both shapes.
* Tests fail with any half of the shape removed: the ToDo path, the
  read-the-ticket gate, the closed-Issue fallback, the unallocated
  case.

## See also

* [ADR-0048](0048-the-escalate-button-follows-a-permission.md) — the
  button follows a permission; extended here, not replaced.
* `albanna/api/conversations.py` — `escalate_conversation`, and the
  anchor reader.
* `docs/ROADMAP.md` §2 item 1 — the record that named this.
