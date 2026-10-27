# Product & UX Review — Albanna (side chat)

> **Historical snapshot.**  This review was written at `8dca8f5`, before the
> lifecycle tools, the trust layer and the support-agent re-cut.  It is kept
> as the record of what the review found and what it asked for — not as a
> description of the app today.  For the current state, read
> `docs/ROADMAP.md`, `README.md` and `CONTEXT.md`.
>
> Everything it raised has since shipped: the lifecycle tools, the diff
> preview, the approval residue ("the wait ran out — the change was not
> made"), the per-turn cost line, undo, dry-run mode, the bulk update,
> escalation, the sources line, image and voice input, and the "explain this
> error" button.

**Scope:** the Albanna Frappe app as it stands on `main` (46 commits, last `8dca8f5`), plus the in-progress lifecycle-tools work stashed at `stash@{0}`.
**Reviewed against:** the app's own `CONTEXT.md` / ADRs, the README's stated design language, and the Frappe Desk UI/UX considerations in `AGENTS.md`.

---

## 1. What the product actually is

Albanna is not "a chatbot on ERPNext." It is a **governed, in-process AI side panel for the Frappe Desk**: six tools (`list_docs`, `get_doc`, `get_doctype_meta`, `run_report`, `create_doc`, `update_doc`), one panel per page, one conversation per page per user, running under the caller's own permissions. The strongest product claims are:

- **Permission parity.** Tools run in-process inside the request that opened the chat, so the assistant can never see or do more than the person asking. This is the differentiator vs. an MCP-backed assistant and it is correctly treated as an invariant, not a feature.
- **Honesty about limits.** Truncated answers say so; refusals name the missing right; a turn that hits `max_tool_rounds` produces a diagnosis instead of silence. This is rare and valuable.
- **Recoverability.** A turn survives a reload; a question can be undone (question + answer together); a turn can be stopped; approval waits can expire with an explanation.
- **Arabic/RTL as first-class.** Widget sits on the reading end; not a translation pass at the end.

The product is mature for its age: 46 commits, a pure `core/` with unit tests, ADRs, an invariant list, and a translation-drift checker. The UX is already above most Frappe custom apps.

---

## 2. UX strengths (keep these)

1. **Launcher-as-gate, lazy UI bundle.** `albanna-side-chat.bundle.js` is ~4 KB and always loaded; the ~180 KB Vue bundle is fetched only when the panel opens. This is the right trade for a Desk that has many pages and many users.
2. **Docked panel, not a modal.** The panel is a column of the Desk; the transcript is a view, the conversation list is a drawer *inside* that column, not a second floating thing. Matches the stated philosophy.
3. **Progressive disclosure of tool calls.** Tool calls fold behind one activity line and open on demand. Good — tool noise is the #1 cause of chat fatigue.
4. **Empty state is contextual.** It names the page and document the assistant is looking at and offers questions about *that*. Strong first-run moment.
5. **Document names in answers are real links**, sourced from what the tools actually read — no hallucinated navigation.
6. **Tables copy as TSV/CSV** and export to Markdown — spreadsheet-friendly.
7. **Drag-to-widen panel** with remembered width; the Desk gives up space only when needed (tables).
8. **Approval rail is well thought through.** Per-user approval, savepoint rollback, countdown, expiry explained, survives reload, audited. This is the hardest UX in the app and it has been done carefully (see ADR-0007, invariant 49).
9. **Reduced-motion and mobile responsive** already shipped (63f4386).
10. **Accessibility basics present:** `aria-label`, `aria-expanded`, `aria-controls`, `aria-live` announcement, focus handling.

---

## 3. Gaps, risks, and ideas

### 3.1 Tool surface is about to grow — and the UX has not been designed for it

The stash (`stash@{0}`) adds `submit_doc`, `cancel_doc`, `amend_doc`, `delete_doc` — i.e. the assistant moves from "edit fields" to **lifecycle actions**. This is the biggest pending product change and it has three UX consequences that the current design does not yet address:

- **These are irreversible-ish and high-stakes.** `delete_doc` and `cancel_doc` are destructive. The approval rail exists, but the *language* of approval ("Waiting for your approval…") is generic. A delete approval should say what will be deleted and that it cannot be undone (or that it can be restored via `Deleted Document`). The commit message even notes `delete_doc` cannot restore identity — the UX must not imply it can.
- **Lifecycle tools need state-aware affordances.** `submit_doc` only makes sense on a draft; `amend_doc` only on a submitted doc. The assistant should surface *why* an action is unavailable as a fact about the document (the stash already writes this into `actionable`), but the panel has no visual distinction between "refused by permission" and "refused by state." Consider an icon/color or a small badge on the tool-call fold.
- **Tool-call fold labels.** The activity line maps tool names to verbs (`Creating`, `Editing`). The new verbs (`Submitting`, `Cancelling`, `Amending`, `Deleting`) are already in `WRITE_VERBS`. Check that the fold's "Tools used: X · Calls: Y" summary and the approval card render these without truncation, and that `Deleting` is visually marked (danger indicator) in the fold.

**Recommendation:** before merging the stash, add a UX spec for destructive approvals: distinct card color, explicit consequence text, and a "this cannot be undone" line where applicable. Add a test that the fold renders the new verbs.

### 3.2 The approval timeout is server-owned but the card must not lie

Commit `8dca8f5` ("the server owns the deadline it tells the reader about") and `41b009c` fixed a real bug: the card's countdown and the server's wait could disagree. Invariant 49 now says the server owns the deadline. **Idea:** make the expiry itself a first-class UX moment — when a wait runs out, the card should not just disappear; it should leave a one-line residue in the transcript ("The wait ran out — the change was not made.") so the reader understands *why* nothing happened. The untranslated string "The wait ran out — the change was not made." suggests this residue exists but is not yet translated. Make sure it is appended to the transcript, not only shown on the card.

### 3.3 i18n drift is a recurring tax

`scripts/check_translations.py` currently reports **10 missing** and **1 unused** Arabic strings (see §4). The stash itself introduces 27 more. The check exists and is good, but it is not wired into CI in a way that blocks merges (the pre-commit/CI configs should be checked). **Idea:** make the translation check a required CI gate, and add a "translation debt" line to the release checklist. Also consider extracting the strings into a small "copy deck" document so reviewers can review wording without reading code.

### 3.4 Discoverability of history and "New"

The README lists many features (pin conversations, search, export, regenerate, rating). These are power features, but there is no onboarding hint. A first-time user sees the empty state with suggestions, but never learns that conversations can be pinned, searched, or exported. **Idea:** a one-time "tip" in the empty state or a `?` help affordance listing shortcuts (keyboard shortcuts already exist per `cdbf05d`). Keep it dismissible and never show it again after dismissal (store in user prefs / localStorage).

### 3.5 Cost/usage visibility is operator-only

The monthly budget field and usage line exist (`1081e78`), and the audit row records cost. But the person *using* the chat has no sense of cost. For a governed-execution product, per-user cost attribution is both a trust feature and a billing primitive. **Idea:** show a small "this turn cost X" line under the answer (already have the data in the audit row / turn result), and a personal "my usage this month" in the drawer. This also supports future per-tenant billing.

### 3.6 Mobile/tablet is "responsive" but not "usable"

Commit 63f4386 added mobile responsive. But the design is desktop-first and the panel is a docked column; on a phone a docked column is essentially a full-screen takeover. **Idea:** define an explicit mobile mode: full-screen panel, bottom-sheet composer, larger tap targets (≥44px), and a "back to Desk" affordance. Test on a real tablet in a warehouse flow (the most likely mobile surface for ERPNext). Also: child-table answers (wide tables) need horizontal scroll with a sticky first column, or a "view as list" fallback.

### 3.7 Dark mode and theming

The app uses CSS variables (good). But custom CSS must be scoped and reviewed in both themes. **Idea:** add a dark-mode visual regression check (screenshot diff in CI) for the panel, the approval card, and the markdown table. The approval card's countdown and the "cut off" notice are the most likely to have contrast issues.

### 3.8 Error taxonomy in the panel

The panel distinguishes network vs. permission vs. validation errors in code (per the UX guide), but the user-facing copy should be reviewed. **Idea:** a small "what went wrong and what to do" pattern: each error category gets a consistent icon + one sentence + one action (retry / contact admin / fix the field). Avoid the generic "Something went wrong."

### 3.9 Search across conversations

Search exists (`3dc4878`). But conversations are per-page; search presumably scopes to the current page's thread or to all of the user's. **Idea:** make search global by default with a "this page only" filter, and show the page identity in each result so the user knows which context the answer belongs to. Also index conversation titles for fuzzy match.

### 3.10 Feedback loop is one-way

Rating buttons exist and are toggles with visible state (fixed in `42bfbbb`). But ratings go nowhere visible: no aggregate, no "most helpful answers," no signal to improve prompts. **Idea:** a small operator view in Albanna Settings showing rating distribution by model/user, and a "regenerate with feedback" loop (the regenerate feature exists). This turns ratings into a product-improvement input rather than a vanity metric.

### 3.11 The six-tool contract vs. the "governed execution" story

The README is explicit that `run_sql_query` is absent by design. That is correct and should be defended. But as the tool set grows (lifecycle tools now), the *manifest* becomes the product's security contract. **Idea:** publish the manifest (names + tiers + required permissions) in the docs and in a read-only "About Albanna" panel, so an admin can audit what the assistant is allowed to do without reading source. This is a trust feature for enterprise buyers.

### 3.12 Concurrency and "two users, one document"

The approval rail is per-user, but two users can approve writes to the same document concurrently. Frappe's optimistic concurrency will reject one. **Idea:** surface the conflict cleanly ("This document changed since you asked; review it and ask again") rather than a raw validation error. Also consider a short-lived lock on the document during a write turn.

### 3.13 Offline / poor-connection behavior

Frappe is not offline-first. The panel's status poll ramps up when idle and slows while the socket delivers (`096b64d`). **Idea:** an explicit "reconnecting…" indicator when the socket drops, and queue the composer's submit until reconnected (with a visible "waiting for connection" state) rather than a silent failure.

### 3.14 Empty-state suggestions should be data-aware

The empty state offers static suggestions ("Which Sales Orders are still open?"). **Idea:** make suggestions data-aware: if there are 0 open orders, don't suggest "open orders"; suggest "create a sales order" instead. Requires one cheap `count` call on panel open. High perceived intelligence for low cost.

### 3.15 "New" conversation semantics

The README says "New starts a real new thread" and "the panel follows the page." There is a subtle UX trap: a user who opens the panel, asks nothing, and clicks "New" creates an empty conversation. **Idea:** lazy-create: only persist a conversation when the first question is submitted; "New" just clears the in-memory draft and resets the thread pointer. This avoids orphan conversations and keeps the list clean.

### 3.16 Export and print

Export to Markdown exists. **Idea:** add "print this answer" / "save as PDF" using the browser's print, with a print stylesheet that strips the chrome. Also allow exporting a whole conversation (not just one turn) — useful for handover/audit.

### 3.17 Settings UX

`Albanna Settings` has 35 fields. That is a lot for a single form, even grouped. **Idea:** split into tabs (Provider, Access, Limits, Prompts, Audit) and add a "test provider" that already exists (good) plus a "dry run a turn" button that runs a sample question as the current user and shows the tool calls — this is the single best way for an admin to understand and trust the app.

### 3.18 Onboarding for non-admins

The widget is hidden from users without `Albanna User` (`35a0a40`). But a user who *does* have it and opens the panel for the first time sees suggestions only. **Idea:** a 3-step first-run tour (highlighted launcher → empty state → first answer) that can be replayed from settings. Especially valuable because the product's value is non-obvious ("ask in plain language").

---

## 4. Translation debt (concrete, today)

`scripts/check_translations.py` currently reports:

**Missing (10) — Arabic users see English for these:**
- `A request is required.`
- `Approval wait (seconds)`
- `How long a write waits for the reader's approval before it is given up on. The reader sees this count down on the approval card.`
- `That is not a decision.`
- `The approval could not be recorded.`
- `The approval wait is kept between {0} and {1} seconds; {2} was used.`
- `The wait ran out — the change was not made.`
- `Waiting {0}s`
- `You`
- `You moved to another page. The turn is still running — its answer will be in that page's conversation.`

**Unused (1):** `You moved to another page, so the turn was stopped.` (leftover from a rewording)

**Action:** translate the 10, delete the 1, and wire the check into CI so the stash's 27 new strings cannot land untranslated.

---

## 5. Suggested prioritization

| Priority | Item | Effort | Why |
|---|---|---|---|
| P0 | Translate the 10 missing strings; wire check into CI | S | Arabic is a first-class case; shipping English fallbacks breaks the promise |
| P0 | Destructive-approval UX spec before merging lifecycle tools | M | Highest-stakes new surface; approval copy is currently generic |
| P1 | Manifest published in docs + "About" panel | S | Trust/audit feature, cheap, high enterprise value |
| P1 | Lazy conversation creation ("New" clears, not creates) | S | Prevents orphan rows and list clutter |
| P1 | Data-aware empty-state suggestions | S | High perceived intelligence, one count call |
| P1 | Per-turn cost line + personal usage in drawer | M | Trust + billing primitive |
| P1 | Dry-run-a-turn button in settings | M | Best admin onboarding tool |
| P2 | Mobile full-screen mode + tablet test | M | Field usage is real for ERPNext |
| P2 | Dark-mode visual regression in CI | M | Prevents contrast regressions |
| P2 | Error taxonomy with consistent copy + actions | M | Reduces support burden |
| P2 | Feedback → operator dashboard | M | Closes the improvement loop |
| P2 | Global search with page identity in results | M | Power-user feature already half-built |
| P3 | Print/PDF of an answer or whole thread | S | Handover/audit |
| P3 | First-run tour | M | Onboarding |
| P3 | Concurrency conflict copy | S | Correctness edge case |

---

## 6. What I would not change

- The six-tool (soon ten-tool) contract and the deliberate absence of `run_sql_query`. Keep it.
- In-process execution and permission parity. This is the moat.
- The pure `core/` layer and its tests. Do not let Frappe leak in.
- The approval rail's savepoint discipline. Do not weaken it.
- The "truncated says so" honesty. It is the product's character.

---

## 7. Open questions for the owner

1. Is the lifecycle-tools stash (`submit_doc`/`cancel_doc`/`amend_doc`/`delete_doc`) intended for the next release, or is it experimental? It changes the product from "read + light write" to "full document lifecycle," which is a positioning shift worth deciding deliberately.
2. Should per-user cost be surfaced to end users, or only to operators? (Affects trust vs. noise.)
3. Is mobile/tablet a supported target, or is the Desk desktop-only by policy? The commit says "responsive" but there is no stated support matrix.
4. What is the release cadence / versioning? `__version__` and `patches.txt` exist but there is no CHANGELOG. Enterprise buyers will ask.
