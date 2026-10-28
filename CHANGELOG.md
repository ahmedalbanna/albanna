# Changelog

All notable changes to Albanna are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] — 2026-10-28

The truth release.  Everything here is about one thing the app did not do:
say what actually happened.  A turn that died, a change that was taken
back, a thread the assistant could not read — each of them was a place
where the app was silent, and silence about a write is the worst answer
there is.

### Added

- **A dead turn names what it wrote.**  The audit row is the truth about a
  turn and it outlives the turn, so when a turn dies the panel reads the
  row and names the documents it changed before it stopped: *"Before it
  stopped, it changed Sales Invoice SIN-0001."*  Nothing is named unless
  the row is certainly the reader's own unfinished turn — a reader sent
  after the wrong turn's writes is worse off than one told nothing.
- **The audit row is written before the turn can die.**  A turn writes an
  `Albanna Chat Log` row with status `running`, commits it, and updates it
  in place at the turn's end.  A turn that dies leaves its row behind, a
  scheduled task re-labels stale rows as `interrupted`, and the ledger
  counts only the turns that finished.  No new column: the per-round
  timings ride the existing `tools` field, so production needs no DDL.
- **The app says what it could not read.**  `list_docs` on Communication
  states, in the tool's own answer, that Frappe scopes the listing to the
  reader's own `User Email` accounts — a note derived from the site rather
  than hoped for from the model.
- **Ticket-shaped suggestions.**  On an Issue the empty state offers the
  triage questions — what the customer wants, what has been done, what is
  still outstanding — and "Show my open tickets".
- **The drafted reply, copyable.**  A Communication the assistant writes is
  handed back in a fenced code block, so it can be copied out of the
  answer.
- **The triage-shaped prompt.**  The model is told the shape of a good
  triage answer — want / done / outstanding / next — and is asked to read
  in batches rather than one document at a time.

### Changed

- The attachment label carries a drawn paperclip instead of an emoji, and
  the rule is now a test (`tests/test_icons.py`) rather than a habit: an
  emoji does not take the text colour, cannot be sized, and renders
  differently on every operating system.
- The Arabic catalogue carries every new string, and the translation
  checker stays green.

### Fixed

- An undo that had been carried out left the stored answer claiming the
  change — the panel said "the turn has been undone" and the thread said
  otherwise.  The correction is now in the answer itself, in the reader's
  language, so it reaches the reader who reopens the thread tomorrow and
  the model that is given the transcript on the next turn.

## [0.2.0] — 2026-10-28

The trust layer's release.  The moat — *the assistant can never see or do
more than the person asking* — was audited end to end against that one
question, and every hole found was closed.  Nothing here adds a feature;
everything here makes a claim the app already made true.

### Added

- **The moat test suite** (`albanna/tests/test_parity.py`).  Twelve tests
  that ask one question — *can the assistant reach past the person it is
  answering?* — and each names the hole it covers, because a test without a
  name is a test nobody reads when it fails.
- **One answer to "may this account read this document"**
  (`albanna.permissions.may_read`).  The tools and the confirmation card
  read it, so they cannot disagree about it.

### Fixed — the moat audit

- A creation could arrive **submitted**, because `docstatus` could be sent
  as data.  A document was permanent without the submit permission and
  without the hooks a submission runs.
- A **bulk** change reached past the permission engine to find its targets
  and skipped the field checks a single change gets, so `owner` and
  `docstatus` were writable there and nowhere else.
- A **read** handed the model every field of the document, including the
  ones hidden from the person at a higher permission level.
- A **lifecycle action** — submit, cancel, amend, delete — could act on,
  and report the state of, a document the person may not read.  A write
  permission is not a read permission.
- A **change** could be made to a document the caller may not read, for
  the same reason.
- A **private file** belonging to somebody else could be copied into a
  document and published with it, which takes the bytes out of the private
  folder.
- The **number** in the empty state was the size of the table — every row,
  including the ones the reader may not see.
- The **confirmation card** named documents the reader may not read, showed
  the values the model wanted to change, carried a diff of a document the
  reader may not read, and counted the whole table in a bulk change.
- The **approval** was a string in a cache key: it was not bound to a
  write, a second decision overwrote the first, and a document that changed
  while the reader was deciding was changed anyway.
- The **DocType catalogue** was the whole site's, so the model could tell
  the reader the site has Salary Slips when the reader may not read one.
- The **company** the model was told about was the first row of the table,
  not the caller's company.
- The **page context** named whatever document the browser asked it to.
- The **conversation services** trusted the endpoint to have checked
  ownership, and the conversation document was deleted with `force=True`.
- The **chat log** could hold the site's own API key, because a provider's
  refusal often quotes the key it refused.

### Fixed — the live run (2026-10-27)

- The global includes carried no `.bundle.`, so "Ask Albanna" and "Explain
  this error" 404ed on every page of every site.
- Undo deleted the document the turn had only read.
- The undo button stayed after the undo, offering to take back a change
  that had already been taken back.
- A failed turn showed the reader a raw Python exception.
- The sources of an answer were invisible in the dark theme.
- A search that matched nothing took the search box with it.
- On a phone, the sheet was 32px short of the screen.

### Changed

- **A hidden field is removed, not defaulted.**  A field the caller may not
  read is taken out of the payload entirely.  Frappe leaves
  `ignore_pricing_rule: 0` on a Sales Order, and `0` is a statement about a
  document that is not true.  The app is stricter than the Desk on this one
  point, on purpose.
- **An approval is a decision about a write.**  The pending write is
  recorded before the reader is asked, under the reader's own namespace, and
  the decision is recorded against it: a decision naming no pending write
  is refused, a second decision is refused, another account's decision is
  not found, and a document that has moved is not changed.

### Documentation

- `ROADMAP.md` §9 records the audit — one row per hole.
- `CONTEXT.md` entries 62 to 68 record the decisions behind it.
- `SECURITY.md` no longer claims that `frappe.get_doc` applies the
  framework's permissions.  It does not, and that false belief is what the
  read hole was built on.

## [0.1.0]

The first release: the widget, the eleven tools, the approval gate with a
diff, the audit trail, undo, dry-run, the cost ledger, images and voice,
Arabic and RTL, and the support-agent cut of the roadmap.
