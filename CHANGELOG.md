# Changelog

All notable changes to Albanna are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the app uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.4] — 2026-10-29

The one-door release.  The question it answers came from the owner of
the site: *only one role may use the chat — not other roles such as
System Manager.*  The chat was already a Frappe permission, so the answer
was a row in the matrix, and the row that had to go was the
`System Manager` one.

### Changed

- **The shipped matrix names one role.**  `Albanna Conversation` carries
  `Albanna User` — read, write, create, delete, all `if_owner` — and
  nothing else.  A System Manager who wants the chat takes that role,
  through the User form, like anybody else; one who does not take it is
  refused, like anybody else.  The Administrator is inside, by Frappe's
  own rule: `has_permission` returns `True` for that account before it
  reads a row, and `get_roles` gives it every role on the site.  The
  app does not add a second rule to undo that; the per-user policy of
  v0.2.3 is the lever for one account, the Administrator included.
- **A System Manager is not exempt from the transcript either.**  The
  direct-SQL paths have always said "the owner and nobody else"
  (decision 13), and the permission hooks said the opposite for the list
  view — so the two halves of the app disagreed about who may read
  somebody else's conversation.  The hooks now agree.  An operator still
  reads `Albanna Chat Log`, which is the audit trail and not the
  transcript.

### Fixed

- **`hooks.py` described a grant the DocType never had.**  It claimed
  that `Albanna Conversation` grants `All` read/write, and that the
  grant is what makes the gate reachable for a non-manager user.  It has
  never done so: the live matrix had two rows and no `All`, and a
  comment that says the opposite of the code is worse than no comment.
- **The v0.1 patch's docstring described the shipped rows as they were
  then.**  It now says the site is left with the shipped matrix, which
  is the gate.

### Added

- **`tests/test_access_matrix.py`** — holds the shipped matrix to one
  role, and reads the DocType's JSON rather than the database: the
  database holds what the last migrate put there, the file holds what
  the next migrate will put there.  A Desk edit of the live rows
  survives a migrate only until the next release that touches the JSON.

### Removed

- **The inert `Albanna Chat User` role is deleted from production.**  It
  was created by hand on 2026-10-22, before the app was installed, and
  it holds no permission rows at all — assigning it granted Desk access
  and nothing else.  The app never shipped it, so no patch recreates it.

## [0.2.3] — 2026-10-29

The access release.  The question it answers is an ordinary one — *who
can turn this on, and who can turn it off for one person?* — and most of
the answer was already there: the chat is a Frappe permission, granted
the same way everything else on the site is granted.  Looking at it
properly turned up one real defect and one gap that only the matrix
could not fill.

### Fixed

- **The "Ask Albanna" button on a form now respects the gate.**  Every
  reader was given the button on every form, whether or not they could
  use it.  For a reader who may not chat it was dead: the launcher had
  not mounted, so there was no panel behind it, and clicking it did
  nothing at all.  The launcher and the button were answering the same
  question separately — the launcher asked the server and decided, the
  button assumed.  The answer now has one home (`side-chat/access.mjs`),
  and the button waits for it: it is added when the widget exists for
  this reader and not before, and it is added even when the answer lands
  after the form has been drawn.  A test holds the rule, and it fails
  against the old button.
- **The launcher's header no longer describes a locked panel it never
  rendered.**  `options()` reports the widget as not visible for a
  reader who may not chat, and the launcher returns before rendering —
  so the "locked state" the comment promised could not appear.  The
  comment now says what the code does.

### Added

- **A per-user switch for the chat.**  `Albanna User Policy` grows a
  *Chat access override*: *Site default* (inherit the permission
  matrix), *On* (allow this account whatever the matrix says) or *Off*
  (refuse it whatever the matrix says).  It exists because the matrix is
  granted by *role*, and a role cannot say "everyone except this one" —
  and a Frappe User Permission cannot fill the gap, because it applies
  at the row level while this gate is a doctype-level check.  It is an
  exception to the matrix, not a second matrix: one account, one visible
  row, kept by the same people who own the matrix, and read in the same
  place the matrix is read — so the widget and the endpoints cannot
  disagree about who may chat.  A reader switched off by policy is told
  *that*, rather than being pointed at roles that would not have helped.

### Changed

- The chat's access is now a question with one answer in the app: the
  permission matrix decides, a policy row may except one account, and
  the widget's options and every endpoint ask the same function.

## [0.2.2] — 2026-10-29

The operations release.  Nothing here changes what the assistant can do;
everything here makes the app's *claims* hold up when something goes wrong
around it — a turn that dies, a disk that fills, a deploy at the wrong
moment.

### Fixed

- **The ledger no longer says `running` about a turn that died.**  The
  scheduled job that re-labels a dead turn's row ran once a day, while the
  row it re-labels stops being true a quarter of an hour after the turn
  died — so the ledger spent up to a day claiming a turn was still
  working.  The reaper now runs every five minutes, and the gap between two
  runs is tied to the cutoff it closes by a test
  (`tests/test_scheduler.py`), so the two cannot drift apart again.  The
  failure was quiet: the job ran, the job succeeded, and the numbers were
  right throughout, because the ledger counts only the turns that
  finished.

### Added

- **A scheduled, verified backup of the site databases.**  The MCP
  control-plane backup covers PostgreSQL, Redis and the secrets, and says
  plainly that the MariaDB site databases are not included — so the only
  copy of production's data was a manual dump on the same disk as the
  database it protected.  `scripts/site_backup.sh` now dumps
  `albanna.localhost` and `frappe.localhost` daily (`albanna-site-backup.timer`,
  03:47) and **verifies each dump before declaring the run good**: the gzip
  stream is intact, mysqldump's completion footer is there, the site's own
  tables are in it, and it holds no fewer tables than the last good dump.
  A failed check exits non-zero and leaves `last_ok` alone — with no mail
  on this host, a stale `last_ok` is the alert.  `test.localhost` is
  deliberately not backed up: it is a disposable clone.
- **`docs/BACKUP.md`** — what the backup covers, how to tell whether it is
  working, and how to restore, including what a restore costs and what it
  does not bring back.  The script copies it next to the artifacts, so the
  runbook is where the data is.
- **`docs/DEPLOYMENT.md`** — the runbook for putting a change on the
  production site: the order (backup, build, migrate, restart every worker
  set, verify), the two worker sets and why both must be restarted, the
  metadata lock that hangs the site during a migrate, the job-type sync a
  change to `scheduler_events` needs, the language trap, and the three
  commands that look like health checks and are not.

### Changed

- Both covered sites keep `keep_backups_for_hours` at 336 (a fortnight)
  instead of Frappe's 24 hours, so the dump taken before a migration is
  not deleted a day later by the next backup.
- The host's `AGENTS.md` no longer says the site databases have no
  scheduled backup.

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
