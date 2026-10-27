# Albanna — Product Roadmap

**Status:** current as of 2026-10-27.  This document was re-cut around the
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
| 1 | **Escalation that fits support** — today "Ask a human" creates an Issue; for an agent who is *already* in a ticket, a handover should be a ToDo assigned to a person, or a Communication, not a new ticket | today the button opens a second ticket while the first is still open | S | the first live agent complains that escalating made more work |
| 2 | **Ticket-shaped suggestions** — on an Issue the empty state should offer "What is the customer asking for?", "What have we already done?", "What is still open?" instead of the generic list | the generic suggestions are the first thing a new agent reads | S | immediately — it is a prompt + a context change |
| 3 | **The drafted reply, copyable** — a Communication the assistant writes should be readable in the panel and copyable, because sending is the agent's job | the draft exists; the agent has nowhere to read it | S | immediately |
| 4 | **"My open tickets"** — one click from the launcher to the agent's queue, filtered by assignee and status | an agent's first question is always "what is on my desk?" | S | with item 2 |
| 5 | **A ticket summary that fits the ticket** — the system prompt tells the model the shape of a triage answer (want / done / outstanding / next) | the model will summarise a ticket well only if it is told what a good triage summary is | S | immediately — a prompt change, not a feature |
| 6 | **Per-ticket conversation memory** — the thread is per page today; an agent moving between the Issue and the Customer gets two threads | the agent reads the same customer across records | M | an agent actually asks about a customer in two threads in one sitting |

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

### Next (v2) — the six items in §2, in that order

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
