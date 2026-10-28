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
  and updated in place at the turn's end; writes are committed as they run.

Items 1 and 6 remain deferred per their triggers.

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
   words.  On this site the support role may read an Issue but not a
   Communication, so the email thread on the ticket is invisible to the
   tools — and the answer reported that "a first response was logged on
   2026-10-27", which it inferred from a date field rather than from
   the message.  A support deployment has to grant the assistant role
   read access to Communication, and the assistant has to say when it
   could not read something (v2 item 7).  The app does not grant
   permissions — Frappe decides — but it must not let the silence pass
   for the whole truth.
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

A fourth thing was found but is not yet a defect: after an undo, the
answer still reads "Priority changed from Medium to High" — the answer
is a record of what the assistant said, and the panel says "the turn has
been undone" underneath it.  The honest end state is an answer that says
it was undone; that is a change to the transcript, and it is worth doing
when the transcript is reworked rather than now.

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
