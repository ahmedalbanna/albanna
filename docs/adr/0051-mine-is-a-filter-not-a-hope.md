# ADR-0051: "Mine" is a filter, not a hope

Status: **Accepted**
Date: 2026-11-09

## Context

The Issue list offered the suggestion "Show my open tickets", and the
assistant could not answer it. The reader was named in the system prompt
already, but nothing turned "mine" into a condition — so the model listed
every open ticket and called them the reader's.

A confident wrong answer is the worst kind, and the roadmap recorded this
as half-shipped: *"the suggestion is on the Issue list, but the assistant
has no way to know who 'my' is."*

The roadmap named two fixes and said both needed the owner's yes. One of
them — tell the model who the reader is — was already done. What was
missing was the second half: a filter the model could write.

## Decision

**`list_docs` resolves the fieldname `assigned_to` against the site's
assignments.**

It is not a column and not in any DocType's meta, because an assignment
is not a field: Frappe keeps it in `tabToDo`, keyed by (reference_type,
reference_name, allocated_to). A filter the model can write has to be a
fieldname, so this one is a fieldname the tool resolves rather than
passes on.

**The value is ignored.** Whatever the model wrote there, the question is
"which documents are mine", and the answer is the session's. A filter
that named somebody else would answer a question about a third party.

**An empty assignment list is not an error.** It is the honest answer to
"what is on my desk?" when nothing is. The condition becomes one that
matches nothing rather than being dropped, because dropping it would
list everything — which is the bug this exists to fix.

**A cancelled assignment is not a document on anybody's desk.**

## Alternatives considered

**Tell the model the reader's email and let it filter by `_assignee`.**
Rejected, and it would not have worked: `_assignee` is not a column on
this Frappe version. I checked — `frappe.get_all` with an `_assignee`
filter raises `Unknown column 'tabIssue._assignee'`, and it is not in the
meta either. The standard Frappe way is not available here.

**Change the suggestion to "Show open tickets".** Rejected: it is honest
and it loses the thing the agent actually wants. The first question on a
support seat is "what is on my desk?", and a suggestion that cannot
answer it is a suggestion that teaches the reader not to trust the
others.

**Add a join to `list_docs`.** Rejected: `frappe.get_list` does not
support joins on arbitrary tables, and building one would be a second
query engine inside the tool. Resolving the filter into a `name in (...)`
is the same answer with none of that.

**A magic value like `"me"`.** Rejected: a magic string is a magic
string, and the model would have to be told about it anyway. A fieldname
the schema documents is discoverable; a value is not.

## Consequences

* "Show my open tickets" is answerable, and the answer is the reader's
  own.
* The schema documents the fieldname, because a filter the model cannot
  discover is a filter it will not write.
* The prompt tells the model that "mine" means the user named in the site
  block, and never to answer "my" by listing everything and calling it
  theirs.
* Four tests, and all four fail with the resolution removed.
* The general lesson is ADR-0048's and ADR-0049's again: a "product
  decision" that turns out to be a mechanism nobody wired up is not a
  product decision. The roadmap said this needed the owner's yes; what it
  needed was somebody to check whether the system already answered the
  question.

## See also

* [ADR-0048](0048-the-escalate-button-follows-a-permission.md) and
  [ADR-0049](0049-the-search-matches-the-display-title.md) — the other two
  "product decisions" from the same pass that were not.
* `albanna/tools/erpnext.py` — `_resolve_assigned_to`, and `list_docs`,
  which calls it before the query is built.
* `docs/ROADMAP.md` §2 item 4 — the record that named this as
  half-shipped.
