# ADR-0044: Every table in an answer can be copied

Status: **Accepted**
Date: 2026-11-08

## Context

An answer with two tables offered one button that took the *first* —
whichever the model happened to write first — so the second was
unreachable.

`tableRows` stopped at the first non-table line, which is correct when
you only ever want the first table and wrong the moment you want the
second. The test asserted the behaviour with the comment "Only the first
table is taken", which is a statement with no reason: it recorded what
the code did rather than justifying it.

The requirement says *"A table in an answer may be copied out as data"* —
singular, and the shipped behaviour picked one arbitrarily.

## Decision

**The renderer numbers the tables and puts a copy and a download button
beside each one.**

A reader with two tables has two of each and cannot press the wrong one.
The buttons name their own table by index, and the handler re-reads the
markdown to find it — carrying the rows in the DOM instead would mean a
data attribute holding a table's worth of TSV, which is a table's worth
of escaping problems for no gain.

**The buttons are inside `v-html`, so Vue does not compile them.** One
listener on the transcript catches them all, including the ones in
answers that arrive later — a listener attached per button would miss
those. The transcript already had a click handler for document links, so
the table case joins it rather than adding a second listener to the same
element.

**The confirmation is the panel's notice**, for the same reason: a ref
bound to text inside `v-html` never reaches the DOM.

**The button labels are translated** through the same local `__` that
`submit.mjs` uses — Frappe's global translator when there is one, the
identity under node. The renderer is the one place in the panel that
builds markup the reader reads, and a module that hardcoded English would
be a module that ships English to an Arabic reader.

## Alternatives considered

**One button that copies every table, separated by blank lines.**
Rejected: the reader gets two tables in one clipboard with no boundary
marker, which is ambiguous data — worse than no copy.

**Keep first-table-only and say so in the label.** Rejected: it is honest
and it leaves the reader unable to reach the second table at all, which
is the actual complaint.

**A dropdown listing the tables.** Rejected: it is more machinery than
the problem needs, and a dropdown hides the affordance until it is
opened.

**Put the buttons in the answer's footer, one pair per table.** Rejected
on UX: the reader would have to count tables to know which button is
which. It was also the cheaper option, and it was rejected for that
reason rather than despite it.

**Carry the TSV in a `data-` attribute.** Rejected: see above. A table's
worth of TSV in an attribute is a table's worth of escaping.

## Consequences

* Every table in an answer is reachable, by a button beside it.
* `tableRows` grew an index parameter and lost its early `break`; the
  early break was the second bug the index exposed.
* The old footer buttons are gone, and with them the `hasTable` flag and
  the `copiedTableId` ref that existed only to serve them.
* The renderer now emits markup with translatable text, which is new for
  a module that was pure data-in/data-out. The local `__` keeps it
  testable under node.
* The general lesson: a test that asserts a behaviour with a comment
  that states it rather than explains it is a test that recorded a bug.
  "Only the first table is taken" was true, and it was true because
  nobody had asked for the second.

## See also

* `albanna/public/js/side-chat/markdown.js` — `tableRows`, `renderTable`,
  and the local `__`.
* `albanna/public/js/side-chat/SideChatApp.vue` — `onTranscriptClick`,
  which catches the buttons, and `copyTable`/`downloadTable`.
* [ADR-0036](0036-no-tool-is-handed-sql.md) — the other decision about a
  property that was true and unenforced.
