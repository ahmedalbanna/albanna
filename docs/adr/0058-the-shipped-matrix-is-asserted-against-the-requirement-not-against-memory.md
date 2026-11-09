# ADR-0058: The shipped matrix is asserted against the requirement, not against memory

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7.3: the `Albanna User` role shall grant read, write, create and
delete on `Albanna Conversation`, all scoped to owner.

The shipped row is exactly that — one row, all four rights,
`if_owner=1`, permlevel 0 — and production's live `tabDocPerm` matches
it flag for flag. Only half of it was asserted.
`test_the_chat_row_is_scoped_to_the_owner` held the `if_owner` half.
Nothing held the other half: a row that quietly lost its `delete` would
still be `if_owner`, would still pass every test in that file, and a
reader who could no longer take back their own thread would have no way
to say so.

Nothing asserted there was exactly one row either. Frappe applies
*every* matching permission row, so a second row for the same role is a
second shape — and the wider of the two governs. A row added later "for
a special case" is how a gate that was one door becomes two.

## Decision

**Assert the four rights against a named list, and assert there is one
row.**

`CHAT_RIGHTS` names the four, and the test reads the row against it
rather than against a memory of the row. The row count is asserted as
one, with the reason spelled out: Frappe applies every matching row, so
two rows are two shapes.

## Alternatives considered

**Assert the whole row, flag by flag.** Rejected: it would fail on the
next legitimate addition — a right the requirement does not name — and
a test that fails for a reason nobody intended is a test somebody
deletes.

**Assert only the four rights and not the row count.** Rejected: the
count is the half that catches the "special case" row, which is the
failure that actually widens the gate.

**Read the live database instead of the JSON.** Rejected, and the
existing file already says why: the database holds what the last
migrate put there, the file holds what the next one will. A gate that
only holds until the next release is not a gate.

## Consequences

* Both halves fail with the defect reintroduced — a dropped right, and
  a second row.
* The doctype's docstring claimed the matrix granted read and write to
  *two* roles, "`System Manager` outright, and `Albanna User` for the
  rows the account owns". The `System Manager` row was removed on
  2026-10-29 when the matrix was narrowed to one door (ADR-0008). The
  comment described a matrix that had not existed for eleven days, and
  it is the kind of sentence that sends the next reader hunting for a
  row that is not there. Corrected.
* The row still grants five rights beyond the four the requirement
  names — `share`, `print`, `email`, `report`, `export`. They are
  Frappe's default permission row, never trimmed, and no ADR mentions
  them. `share` is the one that matters: it lets a reader hand their
  conversation to another user, crossing the owner-only boundary the
  rest of the app enforces. Recorded in the FR-7 record as needing the
  owner's decision rather than changed here.
* The general lesson is ADR-0055's first variant again: the held half
  was right there, and the unheld half was the one that would have
  changed quietly.

## See also

* [ADR-0008](0008-frappe-decides-permissions.md) — the matrix was
  narrowed to one role on 2026-10-29, which is what made the docstring
  stale.
* [ADR-0014](0014-a-reader-who-may-not-chat-gets-no-widget.md) — the
  owner-scoping this row is half of.
* `tests/test_access_matrix.py` — the shipped matrix, and the two
  halves of its shape.
