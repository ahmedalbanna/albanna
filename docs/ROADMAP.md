# Albanna — Product Roadmap

**Status:** current as of 2026-10-28.  This document was re-cut around the
primary persona — **the support agent** — and every item marked *shipped*
is in the code, not in a plan.

**Source:** the original 25 batches of product/UX ideas (chat, 2026-10-24),
filtered through Albanna's architecture and its stated design philosophy
(`CONTEXT.md`, `README.md`, `docs/PRODUCT_UX_REVIEW.md`).

**Principle:** Albanna's moat is *governed autonomy with permission parity* —
the assistant can never see or do more than the person asking, and it says so
when it cannot.  Every feature below is judged against that moat and against
the rule that a feature that is not used is clutter.

**The persona, decided:** a support agent working a ticket queue.  They open
an Issue (or a Communication, or a Customer), they need to know what the
customer wants, what has already been done, what is outstanding, and then
they need to act on the ticket and reply — without leaving the record.

---

## 0. What is already shipped (do not re-invent)

### The core

- Global floating widget (opt-in `floating` mode) + docked default
- Document-anchored entry point ("Ask Albanna" on every form)
- Auto-context from route (page identity `form|doctype|name`)
- Selection-based context (`currentSelection`)
- Role-aware context (permission parity, in-process)
- Inline tool cards (folded tool calls with open-on-demand)
- Approval gates (per-user, savepoint, countdown, expiry)
- Diff preview — the card shows the field, the value now, the value after
- Thread per document (page identity)
- Audit trail (`Albanna Chat Log`, no question/answer text)
- Multi-tenant safety (in-process, site-scoped)
- Permission mirroring (Frappe decides)
- Settings DocType (`Albanna Settings`)
- Tool visibility by right (create/write/submit/cancel/amend/delete)
- Usage dashboard (settings page sums month by model/user)
- Feature flags (enabled toggle, widget position)
- Form-aware suggestions (empty state)
- Source citations (document links from tool reads)
- "No access" states (refusals name the missing right)
- Retry with context (retry module)
- Mobile/tablet usable (full-screen sheet, tap targets, table scroll)
- First-run tour (dismissible, localStorage)
- RTL/Arabic first-class
- Keyboard shortcuts
- Empty-state suggestions
- Truncation honesty ("cut off" notice + `truncated` flag)
- Cost ledger (site currency, per-million pricing)
- Global search across conversations (server-side, by title)
- Lazy conversation creation
- Per-turn cost in audit
- Data-aware empty states (count → "Create a …")

### The trust and control layer

- **Bulk update** with an approval card that names every document it touches
- **Undo** for create / update / submit — and no undo button where the
  reversal is not the same operation in the opposite direction
- **Dry-run mode**: writes are proposed, nothing is committed
- **Proactive nudges** (count → "Create a …", "3 overdue")
- **Smart defaults** on a new document
- **Escalate to a human**: a Frappe Issue carrying the transcript
- **Destructive-action approval UX** (what is lost, stated plainly)
- **"Explain this error"** on Frappe error dialogs
- **Question removal** — the reader can erase what they asked

### The input and output layer

- **Voice input** (browser Web Speech API)
- **Image attachment** (paste / drop / choose; stored as a Frappe File under
  `Home/Albanna`; vision only for OpenAI-compatible providers; off by default)
- **File-name chip** for non-image attachments
- **Copy-as-Markdown** for an answer, with a clipboard fallback
- **Sources line** ("See more" for long lists)
- **Thumb rating** with SVG icons
- **Bubble, footer and tool-row alignment**; every emoji replaced by an SVG
- **Dark-mode pass** and an **Arabic/RTL pass**

---

## 1. The hero workflow (support agent, ticket triage)

One journey, designed end to end.  Everything else is v2.

> **A support agent triages a ticket and answers the customer, without
> leaving the ticket.**
>
> **Entry** — the agent opens an Issue, a Communication, a ToDo or a
> Customer, and presses "Ask Albanna" (or opens the launcher on the list
> view).  The panel is scoped to that page.
>
> **Context** — the page identity is the ticket; the assistant is told the
> DocType, the name and the fields the reader is looking at.
>
> **Tool calls** — `get_doc` on the Issue, `get_doc` on the Customer and
> the Contact, `list_docs` on Communication for the thread, `list_docs` on
> ToDo for what is already assigned, `get_doctype_meta` before writing to
> a field the model is not sure of.
>
> **The answer** — what the customer is asking for, what has already been
> done, what is outstanding, and the records each of those claims came
> from (the Sources line).
>
> **The action** — one write: `update_doc` on the Issue (status, priority,
> assignment), or `create_doc` of a Communication holding the drafted
> reply, or a ToDo for the follow-up.  The draft is *drafted* — nothing is
> sent to the customer without the agent sending it.
>
> **The gate** — the approval card carries the diff, and the write happens
> only if the agent approves it.
>
> **The record** — the audit row says who asked, which model, what it
> cost, and which documents were touched.

**Why this journey and not another.**  It is the one journey that
exercises everything the app already has: a document-anchored entry, page
context, reads across several DocTypes, one write, an approval with a
diff, an audit row and the audit trail the reader can trust.  It is also
the journey a support agent performs dozens of times a day, so it is the
one where "excellent" is worth more than "broad".

**What "excellent" means here, concretely:**

1. The answer leads with *what the customer wants*, not with a recital of
   fields.
2. The agent does not have to leave the ticket to find the customer, the
   thread or the outstanding work.
3. Nothing reaches the customer without the agent reading it first.
4. The write that happens is the write the agent expected, and the diff
   proved it before it ran.
5. Every claim in the answer is traceable to a document the tools read.

---

## 2. Next (v2) — support-shaped work, in order

Each item names the trigger that would make it worth doing.

| # | Item | Why it matters for this persona | Effort | Trigger |
|---|---|---|---|---|
| 1 | **Escalation that fits support** — today "Ask a human" creates an Issue; for an agent who is *already* in a ticket, a handover should be a ToDo assigned to a person, or a Communication, not a new ticket | confirmed live: escalating a ticket opened a *second* ticket while the first was still open | S | the first live agent complains that escalating made more work |
| 2 | **Ticket-shaped suggestions** — on an Issue the empty state should offer "What is the customer asking for?", "What have we already done?", "What is still open?" instead of the generic list | the generic suggestions are the first thing a new agent reads | S | immediately — it is a prompt + a context change |
| 3 | **The drafted reply, copyable** — a Communication the assistant writes should be readable in the panel and copyable, because sending is the agent's job | the draft exists; the agent has nowhere to read it | S | immediately |
| 4 | **"My open tickets"** — one click from the launcher to the agent's queue, filtered by assignee and status | an agent's first question is always "what is on my desk?" | S | with item 2 |
| 5 | **A ticket summary that fits the ticket** — the system prompt tells the model the shape of a triage answer (want / done / outstanding / next) | the model will summarise a ticket well only if it is told what a good triage summary is | S | immediately — a prompt change, not a feature |
| 6 | **Per-ticket conversation memory** — the thread is per page today; an agent moving between the Issue and the Customer gets two threads | the agent reads the same customer across records | M | an agent actually asks about a customer in two threads in one sitting |
| 7 | **The assistant says what it could not read** — when a tool is refused for a missing right, the answer says so, instead of leaving the reader to believe the silence was the whole truth | on a support seat the customer thread was invisible (no Communication read) and the answer paraphrased a date field instead of the customer's words | S | immediately — the refusals are already counted, they are only not said out loud |
| 8 | **An approval always ends in a sentence** — after the reader approves, the panel says what happened to the write: it ran, it was refused, or the turn died before it could run.  The audit row is written before the turn can die | found live: a turn that needed an approval hit the ten-minute wall, and the reader was left with the one question that matters — "did it happen?" — and no answer | S | immediately — this is a trust hole, not a feature |
| 9 | **A long thread remembers** — the model sees only the last `history_limit` messages of a thread (50 by default), so a ticket that has been worked on for days loses its earlier decisions, and it loses them silently | the thread belongs to the page, and a support ticket stays open for longer than fifty messages | M | an agent's thread passes the history limit and the answer forgets what was already decided |

---

## 3. Later (v3) — only with a named customer or a named vertical

- **Sending the reply** — Frappe Communication can send email, but it needs
  an Email Account, and an agent's reply to a customer is a commitment.
  Blocked on the operator, not on the app.
- **SLAs and ageing** — `run_report` can answer "how old is my oldest open
  ticket" once a report exists; a dashboard is a separate thing.
- **Helpdesk integration** — ERPNext Helpdesk is a separate app with its
  own models; a support agent using *that* is a different context.
- **File drop → analyse** (an attached PDF being read) — needs a document
  parsing pipeline.
- **Shared threads** — contradicts the `if_owner` privacy model; a named
  team wants it.
- **Saved prompts library** — admins ask for it repeatedly.
- **Quotas beyond `monthly_budget`** — per-user quotas, for a multi-tenant
  SaaS deployment.
- **Barcode / scan** — warehouse, not support.

---

## 4. Deliberately not doing (clutter, or it fights the design)

- **Floating widget as the default.** The docked panel exists so the record
  stays readable. Floating is opt-in for helpdesk deployments; making it
  default would undo the core value prop.
- **DocType sidebar panel as a separate UI.** Frappe's form sidebar has no
  stable API for custom widgets; embedding there is fragile. The form button
  achieves the same reachability without the fragility.
- **A dedicated "AI Workspace" page.** The panel is a column of the Desk,
  not a page, by design. A full-screen page would be a second home and
  split attention.
- **Command palette integration (Ctrl+K).** The launcher is already on every
  page. Adds a second entry point to maintain.
- **Tool palette / pinned chips.** The empty-state suggestions already serve
  this; a persistent chip bar is clutter.
- **Saved prompts library / team prompt library.** The empty-state
  suggestions cover the common case, and item 2 of §2 makes them *better*
  rather than adding a second place for them.
- **@mention AI in comments.** Complex integration with Frappe's comment
  thread; low frequency of use.
- **Shared threads.** Contradicts the `if_owner` privacy model.
- **Custom avatars/personas.** Cosmetic; no leverage.
- **Gamification (streaks, badges, leaderboards).** Not appropriate for an
  ERP tool.
- **Tool marketplace / no-code tool builder.** Albanna's tool set is fixed
  by design (eleven tools: manifest + adapter, tested for drift). A
  marketplace breaks the security contract.
- **Cross-app / ecosystem (Frappe-to-Frappe, Shopify bridge, email-to-chat,
  calendar).** Out of scope; these are integration projects, not chat
  features.
- **Personalization / adaptive UI.** Over-engineering; the role-based tool
  visibility already adapts.
- **Multi-modal beyond what shipped.** Voice and images are in. Charts,
  file-drop analysis and voice notes are not, and each is vertical-specific.
- **Enterprise governance (data residency toggle, red-team mode).**
  Compliance features for a SaaS that does not exist yet.
- **Developer extensibility (webhooks, sandbox mode).** Out of scope for an
  end-user chat.
- **Accessibility beyond what exists.** Already good (aria, keyboard, Esc,
  focus). Don't gold-plate.
- **Offline queue / low-bandwidth mode.** The mobile pass covers 90% of it.

---

## 5. Phases

### Shipped (v1 and the trust layer)

Widget, page context, eleven tools, approval gates with a diff, audit,
mobile, RTL, first-run tour, document entry point, cost ledger, global
search, bulk update, undo, dry-run, nudge, smart defaults, escalation,
voice, images, copy-as-markdown, sources, "explain this error".

And the moat audit (§9): every tool, the counts, the confirmation card,
the DocType catalogue, the page context, the approval binding and the chat
log were read against the permission question, and every hole was closed.

### Next (v2) — the eight items in §2, in that order

### Shipped in this pass (v0.2.1, support-shaped)

- Item 2 (ticket-shaped suggestions) — shipped.
- Item 3 (drafted reply copyable) — shipped as a fenced code block in the answer.
- Item 4 ("My open tickets") — shipped as an empty-state suggestion.
- Item 5 (triage-shaped summary) — shipped as a prompt instruction.
- Item 7 (say what could not be read) — shipped: deterministic note in
  `list_docs` for Communications, plus a prompt instruction.
- Item 8 (approval ends in a sentence + audit row before the turn can die)
  — shipped: a `running` audit row is written and committed at turn start
  and updated in place at the turn's end; writes are committed as they run;
  a turn that dies reads its row back and names what it wrote before it
  stopped; and an undo corrects the stored answer, so a thread no longer
  claims a change that was taken back.  The Sources line keeps the document
  the change was made to, so an answer that was undone still names what it
  did — and a reader who follows the link finds the document gone, which
  is the deliberate price (CONTEXT 73).

*Verified on production, 2026-10-29, after the migrate:* one turn answered
in Arabic; a turn that listed Communications said, in Arabic, that the
customer threads could not be read and why; a proposed ToDo waited at the
approval gate, was approved, was written, and its ledger row carried
`"write": true` with the per-round timings; the undo deleted the ToDo and
corrected the stored answer in the panel; and the dead-turn sentence named
a write in Arabic, from the audit row.

Two more things from the live run's findings, both small and both about the
truth rather than the features: the icon rule is now enforced by a test
(`tests/test_icons.py`) instead of by memory — the attachment label was the
last emoji in the app — and the per-round timings ride the existing ledger
column, so the operator can see where a slow turn spent its time without a
schema change on production.

Items 1 and 6 remain deferred per their triggers.

### Shipped in this pass (v0.2.2, trust and operations)

The product is at the point where the remaining work is not features.  §2's
items are shipped or deferred on their own triggers, so this pass went after
the two things that are *about* the app rather than *in* it: the truth of the
ledger when a turn dies, and the survival of the data the app writes.

- **The reaper's cadence** — the job that re-labels a dead turn's row ran
  once a day, against a cutoff of fifteen minutes, so the ledger said
  `running` about a turn that had finished by dying for up to a day.  It
  now runs every five minutes, and the gap between two runs is tied to the
  window it closes by a test.  §10 has the finding.
- **A scheduled, verified backup of the site databases** — the MCP
  control-plane backup says in its own header that the MariaDB site
  databases are not covered, and the only copy of production's data was a
  manual dump on the same disk as the database it protected.  There is now a
  daily, verified backup of `albanna.localhost` and `frappe.localhost`, and
  a runbook for restoring it.
- **`docs/DEPLOYMENT.md`** — the runbook for a deploy, written from what the
  0.2.1 deployment actually needed, so the next release is boring.

Two things remain open, and neither is the app's to decide: the model is
still picked per turn by `auto` (fourteen models in a hundred turns, a
twenty-fold spread in seconds per round — the operator's call), and the
customer email threads still cannot be read, because all four Email
Accounts have `enable_incoming = 0` and the site has no `User Email` row
for the support mailbox.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
backup (`20261029_042500`, the dump taken before the migrate) → build →
maintenance mode on → migrate (25 s) → maintenance mode off → every worker
set restarted (systemd web + three workers, supervisor two workers + the
scheduler).  Verified after it: the site answers `200`; the assets are
served by nginx with the same bundle hash as before (nothing in this
release touched the front end); the reaper's `Scheduled Job Type` is now
`Cron` with `*/5 * * * *`, the old `Daily` row is gone, and the job
**fired** at 04:32 — the first scheduler tick after its 04:30 slot — and
moved its next execution to 04:35; a live turn answered in 18 s over three
rounds, and its ledger row carries `status: ok` with the per-round
timings (`[7848, 5201, 4374]`); the worker log holds no traceback; the site
reports `albanna 0.2.2`; and the Error Log holds nothing new since the
deploy.

### Shipped in this pass (v0.2.3, who may use the chat)

The question behind this pass was an ordinary one: *who can turn this
on, and who can turn it off for one person?*  The answer was mostly
already there — the chat is a Frappe permission, and the operator grants
it the same way they grant everything else — but looking at it properly
turned up three things, one of them a defect a reader could hit.

- **The matrix is the rule** — read on `Albanna Conversation`, shipped
  as the `Albanna User` role.  Grant it to a team by putting the role on
  the team's role; take it from a person by taking the role away.  The
  widget and the endpoints read one function, so they cannot disagree.
- **A per-user override** (`Albanna User Policy` → *Chat access*:
  *Site default* / *On* / *Off*) — because the matrix is granted by
  *role*, and a role cannot say "everyone except this one".  A Frappe
  User Permission cannot fill the gap either: it applies at the row
  level, while this gate is a doctype-level check.
- **The dead "Ask Albanna" button** — every reader was given the button
  on every form, and for a reader who may not chat it opened nothing at
  all.  The launcher and the button were answering the same question
  separately; the answer now has one home, and the button waits for it.

Two things found on the way, recorded because they are the kind of thing
that looks done and is not:

- **Production has an inert role.**  `Albanna Chat User` was created by
  hand on 2026-10-22, before the app was installed, and it holds *no*
  permission rows at all — assigning it grants Desk access and nothing
  else.  Anyone who assigned it in the hope of opening the chat for a
  team opened nothing.  The live matrix on `Albanna Conversation` has two
  rows: `Albanna User` and `System Manager`.
- **Only the Administrator holds a chat role** on production, so the chat
  is System-Manager-only there today.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
backup (`20261029_064704`) → build → maintenance mode on → migrate (26 s)
→ maintenance mode off → every worker set restarted (systemd web + three
workers, supervisor two workers + the scheduler).  Verified after it: the
site answers `200`; the four bundles are served by nginx under their new
hashes; the site reports `albanna 0.2.3`; the new column is on the
policy table; the gate was proved on production by switching the
Administrator's own chat off — the widget disappeared and a turn was
refused with *"Your account's Albanna user policy switches it off"* —
and then by switching it back and running a live turn (`status: ok`, two
rounds, `list_docs` answered "12" customers); in the browser, the
Administrator's form carries the "Ask Albanna" button and it opens the
panel; the Error Log holds nothing new since the deploy; and the worker
and web logs hold no traceback.

### Shipped in this pass (v0.2.4, one door)

The question was the one the owner of the site asked: *only one role may
use the chat — not other roles such as System Manager.*  The chat was
already a Frappe permission, so the answer was a row in the matrix, and
the row that had to go was the `System Manager` one.

- **The shipped matrix names one role.**  `Albanna Conversation` carries
  `Albanna User` — read, write, create, delete, all `if_owner` — and
  nothing else.  A System Manager who wants the chat takes that role,
  through the User form, like anybody else; one who does not take it is
  refused, like anybody else.
- **The Administrator is inside, by Frappe's rule.**  `has_permission`
  returns `True` for the Administrator before it looks at a row, and
  `get_roles` gives that account every role on the site.  The app does
  not add a second rule to undo it; the per-user policy of v0.2.3 is the
  lever for one account, the Administrator included.
- **A System Manager is not exempt from the transcript either.**  The
  direct-SQL paths have always said "the owner and nobody else" (decision
  13); the permission hooks said the opposite for the list view, and the
  two halves of the app disagreed.  The hooks now agree.  An operator
  still reads `Albanna Chat Log`, which is the audit trail.
- **The inert role is gone.**  `Albanna Chat User` — created by hand on
  production, holding no permission rows, granting nothing but Desk
  access — is deleted.  Assigning it had opened nothing.
- **The stale comments are fixed.**  `hooks.py` claimed the DocType
  grants `All` read/write; it has never done so, and the live matrix had
  two rows and no `All`.  A comment that says the opposite of the code
  is worse than no comment.

Two facts about the matrix, measured rather than assumed, and worth
knowing before editing it in the Desk:

- **A Desk edit survives a migrate only until the next release that
  touches the DocType's JSON.**  The migrate does not rewrite a DocType
  whose file has not changed, so the edited rows stay; the next change
  to `albanna_conversation.json` writes the rows from the file again and
  the edit is undone.  The shipped matrix is the matrix that holds, and
  `tests/test_access_matrix.py` reads that file and holds it to one role.
- **Custom DocPerm rows cannot open this gate.**  The doctype-level
  check reads the DocType's own rows, so a custom permission on
  `Albanna Conversation` is not a way in.  It is not harmless either:
  where the framework reads the *valid* permissions — the client-side
  permission map the Desk builds, the list of DocTypes a user may read —
  a Custom DocPerm row **replaces** the DocType's own rows, so adding
  one makes the Desk believe the `Albanna User` role has no rights on the
  DocType, while the gate still lets its holders in.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
backup (`20261029_080235`) → build → maintenance mode on → migrate (24 s)
→ maintenance mode off → every worker set restarted (systemd web + three
workers, supervisor two workers + the scheduler).  The inert role was
deleted through the API — disabled first, which is what clears the
`Has Role` rows a Role delete would otherwise refuse, then deleted — and
the API answers `404` for it now.  Verified after it: the site answers
`200`; the site reports `albanna 0.2.4`; the live matrix on
`Albanna Conversation` names one role, `Albanna User`, with
read/write/create/delete and `if_owner`; the bundles are served under
their hashes (no front end changed in this release); **the gate was
proved on production** with a probe account that held `System Manager`
and nothing else — the widget came back `visible: false`, and a turn was
refused with the sentence that names the one role — and the probe was
deleted afterwards; the Administrator, who holds `Albanna User`, still
gets the widget (eleven tools) and a live turn (`status: ok`, two rounds,
`list_docs` → "12" customers); in the browser the form carries the "Ask
Albanna" button, the panel opens, and a question asked in it answers
*"There are 12 customers."* with its sources; the ledger's rows are `ok`
and carry their per-round timings; the Error Log holds one row since the
deploy — Frappe's own *"Session Stopped"* for the request that was in
flight when maintenance mode went on — and nothing else; the worker error
log is empty and the journal holds no traceback.

### Shipped in this pass (v0.2.5, the confirmed change that never ran)

§8's third finding was the last open hole in the trust layer: the panel
could name the documents a dead turn **changed**, and could not name the
change a reader **confirmed** that never ran.

The reason was where the answer lived.  The approval gate keeps the
pending write and the reader's answer in a cache record with a two-minute
life — the right place for a *wait*, and the wrong place for a *fact*.
The wait ends when the worker dies, which is exactly when the reader
needs the answer most.

- **The approval is recorded before the reader is asked.**  It goes into
  the turn's `Albanna Chat Log` row and is committed there.  The row
  outlives the turn; the cache record does not.
- **The reader's answer is recorded in the row too.**  The endpoint that
  takes the decision writes it there, so a worker that dies between the
  answer and the write still leaves a row that knows the reader said yes.
- **The write records itself in the same transaction as the change it
  made.**  The row cannot say a change was confirmed and never ran while
  the database says it is there.  This also closed a second hole: the
  row's calls used to be written only when the turn *ended*, so a worker
  killed half-way through left a row that named nothing — a turn that
  wrote a document and then died was a change nobody was told about.
- **One writer per fact, and the row is merged under a lock.**  The
  endpoint owns the decision (it is what refuses a second answer) and the
  worker owns the write.  Without the lock, the worker can read the row,
  the endpoint can write the answer, and the worker can write its own
  version over the top — losing the reader's answer silently.
- **The panel names it.**  A change the reader confirmed and that never
  ran is named as exactly that: *"The change you confirmed did not run:
  Customer CUST-0001."*  A change that ran is not named as one that did
  not, and a change the reader turned down is not named at all — they
  know they turned it down.
- **No DDL.**  The approvals ride the existing `tools` Long Text, beside
  the calls and the per-round timings.

What the record does **not** hold is the values the model wanted to write.
The ledger is read by operators, and a value the reader alone may see has
no business there; the document's identity is enough to answer *did my
change happen?*.

One narrow thing this does not cover: if the **endpoint's** write to the
row fails — a database error, not a race — the reader's answer is in the
cache only, and the row does not learn it.  The failure is logged rather
than raised, because the decision is already in the cache and the worker
is already acting on it; refusing the reader's answer over a failed
ledger write would be worse than the ledger missing it.  The hole that
leaves is the narrowest one of all: a turn that died between the
approval and the write, *and* whose endpoint write failed.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
backup (`20261029_110858`) → build → maintenance mode on → migrate (29 s)
→ maintenance mode off → every worker set restarted (systemd web + three
workers, supervisor two workers + the scheduler).  Verified after it: the
site answers `200`; the site reports `albanna 0.2.5`; the bundles are
served under their hashes (no front end changed in this release); **the
recording was proved on production** with a turn that proposed a
`create_doc` — while the turn was waiting for the reader, its row already
held `{"approvals": [{"request_id": …, "tool": "create_doc", "doctype":
"Customer", "name": ""}]}`, which is the approval recorded *before* the
reader is asked; the decision endpoint was then called with `reject`, and
the row carried `"decision": "reject"` a moment later, which is the
reader's answer written by a separate request from the worker; the turn
finished `ok` in three rounds and its final payload still held the calls,
the per-round timings **and** the approval, so the turn's own write did
not drop what it had recorded on the way; and nothing was created — there
is no Customer named "Verify 0.2.5", because the write was refused.  In
the browser the panel opens and a question asked in it answers *"There are
12 customers in total."* with its sources and its links; the Error Log
holds no row since the deploy; the worker error log is empty and the
journal holds no traceback.

What was **not** proved on production is the panel's sentence for a dead
turn, because that needs a worker killed between an approval and its
write — which is what the site suite proves, in the dead-turn tests of
`albanna/tests/test_integration.py`, and which is not worth staging on a
live site to demonstrate.

### Shipped in this pass (v0.2.6, the review of 0.2.5)

v0.2.5 was reviewed before it was called finished, and the review was
worth more than the release had been.  The claim did not change — a
confirmed change that never ran is named — but three edges of it were
not as tight as the decision said they were.

- **The turn's own last write could drop the reader's answer.**  The row
  is written once more when the turn ends, and that write reads the row
  to keep the approvals.  Read without a lock, the payload can be stale
  by the time it is written back — and an answer that arrived in between
  goes with it.  The row is now locked before it is read, and the lock
  is held until the write is committed.  Every writer locks now, not
  only the two that merge.
- **A row that could not be written was left saying the change never
  ran.**  The write and the row's record of it share a transaction, so
  they usually agree; when the row could not be written, the change
  still stood (the change is what the reader asked for, and the ledger's
  trouble is not a reason to undo it) and the row did not know.  The row
  is now told again, in a transaction of its own — because a row that
  says "confirmed" and never ran sends the reader off to make the same
  change twice.
- **A merge into a row that is not there reported success**, and the
  same call could be recorded twice in a row that grows as the turn
  runs.  Both are now what they say they are: the merge says when there
  was no row to write into, and a call is identified by what it did.
- **The document named in an approval record is named only when the
  reader may read it** — for every tool, not only for the update one.
- **The reader's answer carries a timestamp**, so the ledger says when
  it was given.

And the claim is now proved the way it is claimed: a test runs a real
turn, answers it through the **real endpoint**, lets the write not run,
and reads the **panel's own answer** — it names the change the reader
confirmed and says that it did not run.  Nothing in that test is a
hand-written row; the synthetic rows are still there for the edges, but
the middle is the app.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
backup (`20261029_121723`) → build → maintenance mode on → migrate (33 s)
→ maintenance mode off → every worker set restarted (systemd web + three
workers, supervisor two workers + the scheduler).  Verified after it: the
site answers `200`; the site reports `albanna 0.2.6`; the recording was
proved on the live site again — a turn that proposed a `create_doc` held
its approval in the row before the reader was asked, the decision
endpoint wrote the answer *and its timestamp* into the row
(`"decision": "reject", "decided_at": "2026-10-29 12:21:05"`), the
turn's own final payload still held the approval — which is the write
that the lock now covers — and nothing was created.  In the browser the
panel opens and a question asked in it answers with its sources and its
links; the Error Log holds no row since the deploy; the worker error log
is empty.

### In this pass (unreleased — the gates, and the drafts that were reviewed)

Nothing here changes what the app does.  Two things happened: the
repository's own gates were repaired, and the feature drafts an agent
had opened against it were reviewed and closed (the verdict is §11, and
the design decision behind it is CONTEXT 80).

**The gates had been red on every commit since 0.2.1** — an unpinned
linter, a pre-commit configuration that listed the same hook twice, and
a server job that installed Frappe v15 against an app written for v16.
Each reason was found by running the job and reading its log, and each
is fixed: the tools are pinned, the duplicate hook is gone, the
formatter is part of the CI job, the complexity bar is explicit, and
the server job installs the framework the app is written against.

**And then the job ran, and found what only a job can find.**  A green
CI is not a gate that was made green by not running: the server job
builds a site, gives it the data the suite reads, and runs the suite.
Three more defects came out of that, all of them invisible to the bench:

* **the site suite only passed in one order.**  A test that acts as
  somebody left the session as that person, and the framework does not
  put it back — so the next test started as somebody it did not choose,
  and a test that creates a user failed with "Could not find User: …",
  naming a user it had never heard of.  Every test class now stands on
  one base that puts the session back (CONTEXT 81);
* **a fresh site has no company for ERPNext's demo setup to clone**,
  and no price list for a Sales Invoice to name — so the site the job
  tests is made by this app's own script, from ERPNext's own setup
  operations (CONTEXT 82);
* **the backup's systemd unit was checked in a way only this host
  could pass** — the test compared an absolute path with the
  repository's own.  It now checks the thing that matters, and a new
  test holds the unit systemd runs to the committed one.

The outcome, measured: **the whole workflow is green** as of
2026-10-29 — pre-commit, the linters and the seventeen front-end
suites, and the server job: 203 domain tests and 174 site tests, with
the three site tests that need a submitted Sales Invoice skipping
themselves and saying so.  What the CI says is *the app works against
the released v16 line*; what the bench says is *the app works against
what is deployed*, and that is the site suite run against the deployed
fork, before a deploy (CONTEXT 81).

**And three defects the bench could not see, found while repairing the
gates:**

* `conversation_service.py` used `Any` in an annotation without
  importing it — harmless at runtime, and a `NameError` waiting for
  the day it was not;
* the package said its licence twice — the SPDX expression and the
  deprecated classifier — and a modern flit refused to build it;
* the CI's domain suite had never been runnable where it was, because
  five of its modules import the framework.

*Deployed on production, 2026-10-29, following `docs/DEPLOYMENT.md`:*
the scheduled backup was fresh (`last_ok` 2026-10-29 03:47) → build
(the bundles came out byte-identical, which is what a change of
whitespace should do) → **no migrate**: the migrate syncs the schema,
the scheduler's job types and the fixtures, and none of those changed,
so there was no lock to take and no window to ask for → every worker
set restarted (systemd web + three workers, supervisor two workers and
the scheduler).  Verified after it: the site answers `200`; the assets
answer `200` under their hashed name; a live turn answered "12" for
*How many Customers are there?* — two rounds, 10.8 s, model
`sensenova-6.8-flash-lite`, one `list_docs` call that found the twelve
customers and named them; the ledger row `11i036me5b` says `ok`, one
tool call, 10 802 ms; the Error Log holds no row since the deploy.

After that deploy the rest of this pass changed no runtime code — the
tests, the CI's own site script, this document — so it needed no second
one: no build, no migrate, no worker restart.  The bench still runs the
suite the same way it did, and now the CI runs it too.

### Later (v3) — §3, only with a named customer

---

## 6. Decision rule for new ideas

Before adding any feature, answer three questions:

1. **Does it make the hero workflow better?** If no, skip.
2. **Does it duplicate something that exists?** If yes, skip.
3. **Can it be done in under a week without new backend subsystems?** If no,
   defer.

If an idea fails any of these, it goes to the backlog and stays there until
a named customer asks for it.  This is how Albanna stays sharp instead of
becoming a feature list.

---

## 7. The persona question, answered

**Primary persona: the support agent.**  Decided 2026-10-27.

The earlier draft of this document assumed a sales rep closing an order.
That assumption is retired.  The support journey in §1 is the one that is
designed, tested and judged; the v2 list in §2 is derived from it, not from
a feature catalogue.

What changed because of the decision:

* the hero journey is ticket triage, not order closing;
* the empty-state suggestions, the answer's shape and the escalation
  semantics all become support-shaped (§2 items 1, 2 and 5);
* the "later" list is re-weighted towards the things a support agent hits
  — replies, SLAs, Helpdesk — and away from the things a warehouse
  operator hits — scan, stock counts.

If the primary persona turns out to be somebody else — an accountant
doing a month-end close, say — the hero journey is re-cut the same way,
and the v2 list is re-derived from it.

---

## 8. The live run — what it found (2026-10-27)

The support journey was run end to end on a production site, in Arabic,
as a support agent with the Support Team and Sales User roles.  It found
seven things that no unit test had found, because a unit test cannot see a
page.

| What | Why it matters | What was done |
|---|---|---|
| "Ask Albanna" and "Explain this error" never loaded — the global includes carried no `.bundle.`, so Frappe served them from the site root and they 404ed on every page of every site | two of the app's entry points did not exist in any browser | fixed; a test asserts the rule |
| Undo deleted the document the turn had only read — the transcript recorded a document's name from any tool envelope, so a *read* was stored as a *creation* | the trust layer's undo was a data-loss bug | fixed at both ends: the tool decides its own undo, and the server refuses a stored "delete" that came from a read |
| The undo button stayed after the undo — the undo was never *spent*, so the turn was still offered, and a turn that could never be undone could be offered too | a button that says "you can take this back" about a change that has already been taken back | fixed: the rules live in one place, the undo is spent when it is carried out, and the panel follows the server's verdict |
| A failed turn showed the reader a raw Python exception (`JobTimeoutException: …`) | a reader is not a stack-trace reader | now a translated sentence; the detail stays in the log |
| The sources of an answer were invisible in the dark theme — the accent did double duty, as the fill of the reader's bubble and as the ink of a link | in the light theme the two are the same colour, so only the dark theme could show it | the links have their own ink; a test asserts it |
| A search that matched nothing took the search box with it, and told the reader they had no conversations | a search that finds nothing has to say so, and stay editable | fixed |
| On a phone the sheet was 32px short of the screen | the composer sat above the strip where the home indicator is | fixed |

Three findings are *product* findings, not bugs:

1. **The assistant cannot see what the customer actually wrote.**  The
   hero journey is triage, and triage starts with the customer's own
   words.  On this site the email thread on the ticket is invisible to
   the tools — and the answer reported that "a first response was logged
   on 2026-10-27", which it inferred from a date field rather than from
   the message.

   *The mechanism, checked rather than assumed:* it is **not** a missing
   permission.  `Communication` is readable by the `All` role, so the
   support role already has read on it, and granting it again would change
   nothing.  What hides the thread is Frappe's own permission query
   condition, which scopes a `Communication` listing to the reader's own
   `User Email` accounts — and this site has no `User Email` row for the
   support mailbox, so every non-administrator sees no email threads at
   all.

   So the fix is site setup, not an app permission: a `User Email` row for
   the support mailbox makes Frappe's own query return the thread.  The
   app cannot do that for the operator, so it does the next best thing —
   it says what it could not read, in the tool's own answer (v2 item 7,
   shipped).  The app does not grant permissions — Frappe decides — but it
   must not let the silence pass for the whole truth.
2. **The model is slow enough to be the experience.**  A turn on this
   deployment takes five to ten minutes; one hit the ten-minute wall and
   came back as an error.  No new feature matters as much as the answer
   arriving.  On a slow provider the reader has to see that something is
   happening, and the site needs a faster model or a streaming answer.
3. **After an approval, the reader is not told whether the change
   happened.**  The turn that needed an approval hit the ten-minute wall:
   the panel said the turn did not finish, the approved write never
   landed, and no audit row was written either.  So the reader was left
   with the one question that matters — "did it happen?" — and no answer
   at all.  This is the sharp end of finding 2: a turn slow enough to
   die takes the answer *and* the write with it.  The approval gate has
   to end in a sentence about the write — "approved, and it ran" or
   "approved, and it did not run" — even when the turn dies around it,
   and the audit row has to be written before the turn can die.

   **Shipped in v0.2.1.**  The audit row is written and committed at the
   turn's start and updated in place at its end, so a turn that dies
   leaves its row behind; a write is committed as it runs, so a write in
   the row is a write that happened; and a dead turn is read out of that
   row — the panel names the documents it changed before it stopped.
   Nothing is named unless the row is certainly the reader's own turn: a
   reader sent after the wrong turn's writes is worse off than one told
   nothing.

   **Shipped in v0.2.5.**  The approval and the reader's answer now live in
   the turn's audit row — in the database, not in the cache record the
   worker polls — and the write records itself in the same transaction as
   the change it made.  So the row can say both things: that a change was
   confirmed, and whether it ran.  The panel reads that and names the
   confirmed change that never ran, by document, instead of saying only
   that the turn did not finish.  See §5 and decision 79.

A fourth thing was found but is not yet a defect: after an undo, the
answer still reads "Priority changed from Medium to High" — the answer
is a record of what the assistant said, and the panel says "the turn has
been undone" underneath it.  The honest end state is an answer that says
it was undone; that is a change to the transcript, and it is worth doing
when the transcript is reworked rather than now.

   **Shipped in v0.2.1.**  The correction goes into the stored answer
   itself, as its own paragraph in the reader's language — so it reaches
   the reader who reopens the thread tomorrow, and the model that is
   given the transcript on the next turn.  The panel's notice was never
   enough: a notice goes, the thread stays.

The escalation finding is already in the list: "Ask a human" on a ticket
creates a *second* ticket (v2 item 1), confirmed live.

---

## 9. The moat audit — what it found (2026-10-28)

The moat is *governed autonomy with permission parity*: the assistant can
never see or do more than the person asking.  That is a claim about a seam,
and a claim about a seam is only worth what the tests on both sides of it
are worth.  So the whole app was read against one question — **can the
assistant reach past the person it is answering?** — and every hole found
was closed, with a test that names it.

| What | Why it matters | What was done |
|---|---|---|
| A creation could arrive **submitted** — `docstatus` in the data — so a document was permanent without the submit permission and without the hooks a submission runs | the assistant could write history the reader could not | the framework's own fields are refused, on creation and on change |
| A **bulk** change reached past the permission engine to find its targets and skipped the field checks a single change gets, so `owner` and `docstatus` were writable there and nowhere else | two paths to the same write, one of them unguarded | the bulk path enumerates its targets through the permission engine and makes the same checks |
| A **read** handed the model every field, including the ones hidden from the person at a higher permission level — and left the hidden field in the payload with its default value | a field that is not there is a false statement about the document | a hidden field is removed from the payload entirely, and the read is refused for a document the caller may not read |
| A **lifecycle action** could act on — and report the state of — a document the person may not read, because a write permission is not a read permission | the answer leaked the existence and the state of a document the Desk would not show | every lifecycle action reads first, and refuses as a read would |
| A **private file** belonging to somebody else could be copied into a document and published with it | private bytes leaving the private folder | the file is adopted only if the caller may read it |
| The **number** in the empty state was the size of the table | a number offered before a question is asked is still a leak | the count is the list view's count: the caller's rows |
| The **confirmation card** named documents the reader may not read, showed the values the model wanted to change, carried a diff of a document the reader may not read, and counted the whole table in a bulk change | the card is the one place a write is described *before* it runs | the card says only what the reader may read |
| The **approval** was a string in a cache key: it was not bound to a write, a second decision overwrote the first, and a document that changed while the reader was deciding was changed anyway | "you approve, and it happens" — of *what*? | the pending write is recorded before the reader is asked; a decision naming no write is refused, a second decision is refused, and the document's timestamp is checked again before the write runs |
| The **DocType catalogue** was the whole site's, the **company** was the first row of the table, the **page context** named whatever document the browser asked it to | the model was told the site's structure, and a browser could name a row the reader may not see | the catalogue is the caller's, the company is the caller's, and the page context drops a name the reader may not read |
| The **conversation services** trusted the endpoint to have checked ownership, and the chat log could hold the site's own API key | a caller that forgot the check would delete somebody else's history; a provider's refusal often quotes the key it refused | the ownership check is in the service as well, and the log is written with the keys taken out of it |

One deliberate difference from Frappe's own API: a field the caller may not
read is **removed** from the payload, not returned with its default.  Frappe
leaves `ignore_pricing_rule: 0` on a Sales Order, and `0` is a statement
about a document that is not true.  The assistant is held to a stricter
standard than the Desk on this one point, on purpose.

## 10. The operations pass — what it found (2026-10-29)

The 0.2.1 release made the app say what happened.  This pass asked a
narrower question about those claims: **are they still true a minute later,
a day later, and after a deploy?**

| What | Why it matters | What was done |
|---|---|---|
| The job that re-labels a dead turn's row ran **once a day**, against a cutoff of **fifteen minutes** — so the ledger said `running` about a turn that had finished by dying for up to a day | the ledger's whole job is to say what happened; a stale `running` says the opposite | the reaper runs every five minutes, and the gap between two runs is tied to the window it closes by a test (`tests/test_scheduler.py`) |
| The MCP control-plane backup covers PostgreSQL, Redis and the secrets, and says so — **the MariaDB site databases were not covered at all**; the only copy of production's data was a manual dump on the same disk as the database it protected | a backup on the same disk protects against a mistake, not against the disk | a daily, verified backup of `albanna.localhost` and `frappe.localhost`, with the runbook next to the artifacts |
| Frappe deletes a site's own backups after **24 hours** by default, which would have deleted the safety net taken before a migration a day later | the dump taken before *that* migration is not the same thing as yesterday's scheduled dump | `keep_backups_for_hours` is 336 (a fortnight) on both covered sites |
| The deployment knowledge was in one operator's head — which units to restart, that `bench restart` does nothing here, that the migrate locks the site | the next deploy is inevitable, and the discovery work is not something to repeat | `docs/DEPLOYMENT.md`, written from what the 0.2.1 deployment needed |
| **The repository's own gates were red on every commit** — the CI installed `ruff` without a version and judged the code against rules this app never agreed to, the pre-commit configuration listed the same hook twice (so pre-commit refused to run at all), and the server job installed Frappe v15 while the app targets v16 | a gate that is red is not a gate; the local suites were the only ones that had been running, so "CI is green" was a claim nobody had checked | the tools are pinned (ruff 0.16.1, pytest, `frappe-bench`, Node 24), the duplicate hook is gone, the formatter is part of the CI job, the complexity bar is explicit, and the server job installs the tag `v16.0.0` — **and runs**: as of 2026-10-29 the whole workflow is green (pre-commit, the linters and the seventeen front-end suites, 203 domain tests and 174 site tests) |

Two of these were found by *running* the thing rather than reading it: the
backup script's first run against both live sites caught a missing
`--with-files` and the `zcat dump | grep -q` trap — under `set -o pipefail`
that pipeline reports a **missing** pattern when the pattern is there,
because grep exits early and the producer dies of SIGPIPE.  Both are fixed,
and the second is now a test that refuses that shape anywhere in the script.

What this pass did **not** do, on purpose:

* It did not copy the artifacts off this host.  They are still on the same
  disk as the databases they protect, and both the runbook and the host's
  `AGENTS.md` say so in those words.
* It did not back up `test.localhost`.  It is a disposable clone that the
  test suite overwrites; backing it up would fill the disk to protect
  nothing.
* It did not choose the model.  The evidence is in §8's finding 2 — and the
  ledger's own timings now say it precisely.  Measured on production's
  ledger (164 turns, 2026-10-21 → 2026-10-29, `model = auto`):

  | Model | Turns | Answered | Median turn | Slowest turn |
  |---|---:|---:|---:|---:|
  | `minimax-m3.1-flash-free` | 51 | 49 | 30 s | 335 s |
  | `longcat-2.5-preview-free` | 24 | 19 | 81 s | 156 s |
  | `stepfun-ai/step-5-preview` | 18 | 11 | 83 s | 473 s |
  | *(no model answered)* | 14 | 0 | — | — |
  | `Gemma-4-31B-IT` | 9 | 9 | 18 s | 63 s |
  | `sensenova-6.8-flash-lite` | 8 | 8 | 17 s | 262 s |
  | `Qwen3.8-Flash-Next` | 8 | 8 | 199 s | 487 s |
  | `step-5-preview` (the fallback) | 7 | 7 | 75 s | 356 s |
  | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 7 | 7 | 199 s | 390 s |
  | `MiMo-V2.6-Flash` | 4 | 3 | 404 s | 599 s |
  | `nvidia/nemotron-3.5-lightning-30b-a3b` | 4 | 2 | 62 s | 133 s |

  The per-round timings — the model's own latency, without the reader's
  thinking time in it — say the same thing more sharply.  Only nine rows
  carry them (the feature is new), all from 2026-10-29:
  `sensenova-6.8-flash-lite` ran 12 rounds at a median of **5.5 s**
  (slowest 13.6 s), `minimaxai/minimax-m3.1-flash` ran 6 at a median of
  13 s (slowest 42 s), and `DeepSeek-V4-Flash` ran 3 at 6–10 s.

  So the spread is not a matter of taste: the reasoning-heavy models take
  two to seven minutes for a turn, which is the "the model is the
  experience" finding of §8 again, and `auto` picks them often enough to
  matter.  **The shortlist is `sensenova-6.8-flash-lite` first** (the
  fastest and the most consistent on the only per-round evidence there
  is) and `minimax-m3.1-flash-free` second (the most-used model, 49 of 51
  turns answered, and free).  The choice belongs to the operator; setting
  `model` in `Albanna Settings` is the whole of it.

  One thing to change with it: `max_tokens` is **1200** on production,
  while the DocType ships 8192.  Eight turns came back *truncated*, six of
  them on `stepfun-ai/step-5-preview` — a model that spends its budget
  thinking.  The setting was lowered at some point and nothing says why.
* It did not make the CI test the framework production runs.  Production
  runs Albanna's own fork of Frappe — `16.0.0-dev`, on Python 3.12 — and
  that fork is not public, so the CI installs upstream Frappe `v16.0.0` on
  Python 3.14 instead.  The gate therefore tests the released line, not
  the deployed one.  It is the closest public thing to the deployed one,
  and it is not the same thing: the site suite run against the deployed
  fork is the gate that speaks for what is deployed.  (The job is green;
  what it cannot cover is the fork, and no amount of green changes
  that.)

## 11. The drafts that were reviewed (2026-10-29)

An agent opened a pull request against this repository with a set of
feature drafts — PR #1, *"feat: compact session + MCP client + missing
feature drafts"* — and a second branch carrying a four-week plan built
on it.  Nothing in either was wired into the chat loop, so nothing
shipped by accident; the question was what to do with the ideas.

**The verdict, item by item.**

| What was proposed | What was decided | Why |
|---|---|---|
| An MCP client: a registry of external servers, a tool search, a dispatch | **Rejected** | §4 already says the tool set is fixed by design, and an external tool cannot have permission parity, an approval card, an undo, or a ledger row (CONTEXT 80) |
| The approval gate generalised to external tool calls | **Rejected** | it only means anything with the line above it; the ERPNext-side equivalent was closed in 0.2.5 and 0.2.6 |
| Compact context: summarise the older turns, keep the recent ones | **Kept as a candidate — §2 item 9** | the model sees only the last `history_limit` messages (50 by default), so a long thread forgets without saying so; it waits for its trigger, like items 1 and 6 |
| Uploading documents other than images and PDFs, and extracting their text | **Deferred to v3** | §3 already lists "File drop → analyse" as v3 work that needs a named customer |
| Inline actions: edit a message, branch a thread, regenerate any answer | **Deferred** | not support-shaped; §6's first question is whether it makes the hero journey better, and branching fights the one-thread-per-page decision |
| More providers: Gemini, Azure OpenAI, Bedrock | **Deferred** | §10's finding is *which* model, not which provider; the latency is a pinning decision, not an adapter |
| Real per-model pricing in the ledger | **Already shipped** | `price_per_million` and `core/cost.py` have been there since v1; the gap is that the setting is zero on production, which is the operator's job and not a feature |

**What the audit in the draft got wrong.**  It claimed PDF text
extraction was in place: a PDF can be attached, but nothing reads it —
§3 says so.  It listed per-model pricing as missing when the ledger
has had it since v1.  It called the escalation to a human partial,
when the road to a handover that fits support is short (item 1).

**What was wrong with the draft itself.**  It was built on a base from
before 0.2.5, so "the tests still pass" was an assumption; it carried
no tests at all; one of its files sat at the root of the repository,
outside the package, where it would never have been imported or
installed; its registry was a module-level global, which each worker
would have held separately; its tool calls had no permission check, no
approval, no ledger row and no secret redaction, so wiring it up would
have broken the promise the panel makes; its MCP transport was a bare
JSON-RPC POST with no session negotiation, so it would not have spoken
to a real server; and it carried an install script for a
reverse-engineering toolchain, which is the agent's business and not
the product's.

**What became of the branches.**  PR #1 was closed, unmerged, with this
verdict on it.  The branch with the four-week plan was deleted; its one
surviving idea is §2 item 9.  The stale local branch was deleted: it
was the per-user policy as it stood before 0.2.3 and 0.2.4 reworked
it, and nothing in it was left to keep.
