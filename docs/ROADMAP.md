# Albanna — Refined Product Roadmap

**Source:** the 25 batches of product/UX ideas (chat, 2026-10-24), filtered through
Albanna's existing architecture and its stated design philosophy
(`CONTEXT.md`, `README.md`, `docs/PRODUCT_UX_REVIEW.md`).

**Principle:** Albanna's moat is *governed autonomy with permission parity* — the
assistant can never see or do more than the person asking, and it says so when
it cannot. Every feature below is judged against that moat and against the
rule that a feature that is not used is clutter.

---

## 0. What is already shipped (do not re-invent)

These ideas from the list are **done** and must not be re-proposed:

- Global floating widget (opt-in `floating` mode) + docked default
- Document-anchored entry point (form button → opens scoped panel)
- Auto-context from route (page identity `form|doctype|name`)
- Selection-based context (`currentSelection`)
- Role-aware context (permission parity, in-process)
- Inline tool cards (folded tool calls with open-on-demand)
- Approval gates (per-user, savepoint, countdown, expiry)
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
- Global search across conversations (server-side)
- Lazy conversation creation
- Per-turn cost in audit
- Data-aware empty states (count → "Create a …")

---

## 1. The three that matter most (do next)

These are the only ideas from the list that are **both** high-impact and
low-complexity, and that do not fight the existing design:

### A. "Explain this error" button on Frappe error dialogs
- **Idea #2, bullet 4.**
- **Why:** a user staring at a Frappe traceback has a concrete, high-intent
  question ("why did this fail?"). The chat already has the context machinery;
  the dialog just needs a button that opens the panel with the traceback + doctype
  pre-filled.
- **Effort:** S. **Impact:** 5.
- **Implementation:** a small global script (like `albanna-form-button.js`) that
  hooks `frappe.msgprint`/error dialog rendering and adds an "Ask Albanna" button
  passing the error text as the first question.

### B. "Explain why" on an answer (reasoning + records read)
- **Idea #13, bullet 3.**
- **Why:** trust. The tool calls are already folded behind a summary line; adding
  "which documents I read to answer this" makes the answer auditable without
  exposing raw JSON.
- **Effort:** S (the tool calls already carry `documents`). **Impact:** 4.
- **Implementation:** show the document list that is *already stored* on the
  assistant message as a small "Sources" line under the answer.

### C. Diff preview for edits
- **Idea #13, bullet 1.**
- **Why:** the approval card already shows a preview of *what* will change.
  Showing old → new for the changed fields turns "Confirm" into an informed
  decision. This is the single biggest trust upgrade for write actions.
- **Effort:** M (compute diff in `update_doc` adapter, return it in the confirm
  event). **Impact:** 5.

---

## 2. Maybe (enterprise / v2, do only if asked)

| Idea | Why maybe | Trigger to do it |
|---|---|---|
| Dry-run mode (#3) | Approval gate already prevents commit; a separate toggle is a second opinion. | Enterprise buyers ask for "preview" explicitly. |
| Undo last AI action (#13) | Reversibility is good, but only `delete_doc` is truly irreversible and it is already gated. | A user actually loses data to an AI action. |
| Quota & budget controls (#19) | `monthly_budget` field exists; per-user quotas add complexity. | Multi-tenant SaaS deployment. |
| Saved prompts library (#4) | Admin-curated templates are nice; the empty-state suggestions already cover the common case. | Admins ask for it repeatedly. |
| Approval workflows for AI actions (#19) | The approval rail *is* an approval workflow. Routing through Frappe's approval engine duplicates it. | Compliance requires Frappe-level audit of the approval itself. |
| Shared threads (#9) | Conversations are private by design (`if_owner`). Sharing is a different product. | A named customer asks for it. |
| File drop → analyze (#18) | High value but needs a document-parsing pipeline. | A vertical (e.g. accounting) needs invoice import. |
| Image understanding (#18) | Same as above. | Quality-inspection vertical. |
| Voice input (#7, #10) | Warehouse users want it; but it is a whole subsystem. | Field-deployment customer. |
| Handoff to human (#4, #9) | Useful, but Frappe Issue/Communication creation is straightforward to add later. | Support-agent persona is primary. |
| Bulk actions via chat (#7) | High value but high risk; needs diff preview + partial-success handling first. | After diff preview ships. |
| Natural-language filters (#7) | The list context already carries filters; translating NL → filters is a model prompt change, not a feature. | Low effort, do as a prompt tweak, not a feature. |
| Proactive nudges (#16) | Delightful but requires background jobs and risks annoyance. | After core is stable and trusted. |
| Smart defaults on new doc (#16) | Nice; the empty state already suggests "create". | Low effort, do opportunistically. |
| Contextual empty states (#16) | Already shipped. | — |

---

## 3. Don't (clutter, or fights the design)

These are explicitly **not** recommended. Each one either duplicates something that exists, adds surface area without leverage, or fights Albanna's stated philosophy.

- **Floating widget as the default.** The docked panel exists so the record stays readable. Floating is an opt-in for helpdesk deployments; making it default would undo the core value prop. (Shipped as opt-in.)
- **DocType sidebar panel as a separate UI.** Frappe's form sidebar has no stable API for custom widgets; embedding there is fragile. The form button (shipped) achieves the same reachability without the fragility.
- **Dedicated "AI Workspace" page.** The panel is a column of the Desk, not a page, by design. A full-screen page would be a second home and split attention.
- **Command palette integration (Ctrl+K).** Nice but the launcher is already on every page. Adds a second entry point to maintain.
- **Tool palette / pinned chips.** The empty-state suggestions already serve this; a persistent chip bar is clutter.
- **Saved prompts library / team prompt library.** Admin-curated templates are a feature nobody maintains. The empty-state suggestions + examples module are the right size.
- **@mention AI in comments.** Complex integration with Frappe's comment thread; low frequency of use.
- **Shared threads.** Contradicts `if_owner` privacy model.
- **Custom avatars/personas.** Cosmetic; no leverage.
- **Gamification (streaks, badges, leaderboards).** Not appropriate for an ERP tool; reads as patronising.
- **"Wow" moments / easter eggs.** Delight is earned by reliability, not animations.
- **Tool marketplace / no-code tool builder.** Albanna's tool set is fixed by design (six → ten tools, manifest + adapter, tested for drift). A marketplace breaks the security contract.
- **Cross-app / ecosystem (Frappe-to-Frappe, Shopify bridge, email-to-chat, calendar).** Out of scope; these are integration projects, not chat features.
- **Personalization/adaptive UI (role-based home, learning from usage, saved layouts).** Over-engineering; the role-based tool visibility already adapts.
- **Multi-modal (charts, file drop, image, voice notes).** High effort, vertical-specific. Defer until a named customer needs it.
- **Enterprise governance (data residency toggle, red-team mode).** Compliance features for a SaaS that does not exist yet.
- **Developer extensibility (webhooks, sandbox mode).** Out of scope for an end-user chat.
- **Accessibility beyond what exists.** Already good (aria, keyboard, Esc, focus). Don't gold-plate.
- **Offline queue / low-bandwidth mode / voice-to-action.** Real needs for field users, but the mobile pass (shipped) covers 90% of it. Defer the rest.

---

## 4. The one "hero workflow" (recommended focus)

Pick **one** and design the full journey; everything else is v2:

> **A sales rep closes an order end-to-end via chat.**
>
> Entry (form button on Sales Order) → context (SO name, status, customer,
> items) → tool calls (get_doc, update_doc for delivery date, submit_doc) →
> approval gate (diff preview) → audit row → success.

This single journey exercises: document-anchored entry, page context, read +
write tools, approval, diff preview, audit, and the mobile path. If that
journey is excellent, the app is competitive. If it is mediocre, no amount of
feature breadth fixes it.

---

## 5. Phased roadmap

### MVP (shipped)
Floating/docked widget, page context, six→ten tools, approval gates, audit,
mobile, RTL, first-run tour, document entry point, cost ledger, global search.

### v1 (next 3)
1. **"Explain this error" button** on Frappe error dialogs.
2. **"Explain why" / sources line** under answers.
3. **Diff preview** for `update_doc` in the approval card.

### v2 (if demand)
- Bulk actions via chat (needs diff preview + partial success first).
- Smart defaults on new doc ("copy from last order for this customer").
- Proactive nudges ("3 invoices overdue — draft reminders?").
- Undo last AI action.
- Dry-run mode (if enterprise asks).
- Handoff to human (Issue/Communication with transcript).

### v3 (vertical / enterprise, only with a named customer)
- Voice input, barcode/scan → chat, file drop, image understanding.
- Quota & budget controls, data residency, red-team mode.
- Shared threads, saved prompts, team prompt library.

---

## 6. Decision rule for new ideas

Before adding any feature, answer three questions:

1. **Does it make the hero workflow better?** If no, skip.
2. **Does it duplicate something that exists?** If yes, skip.
3. **Can it be done in under a week without new backend subsystems?** If no, defer.

If an idea fails any of these, it goes to the backlog and stays there until a
named customer asks for it. This is how Albanna stays sharp instead of becoming
a feature list.

---

## 7. The one question that still needs your answer

**Primary persona and top-3 workflows.** Everything above assumes "sales rep
closing orders" as the hero. If the real primary user is an accountant (month-end
close), a support agent (ticket triage), or a warehouse operator (stock checks),
the hero workflow and the v1/v2 ordering change. Tell me the persona and I will
re-rank.
