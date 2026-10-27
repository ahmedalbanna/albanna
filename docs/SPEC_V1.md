# Spec: Albanna v1 — Trust & Discoverability

**Scope:** the three "do next" items from `docs/ROADMAP.md` §1, plus the
hero workflow they serve:
1. "Explain this error" button on Frappe error dialogs.
2. "Explain why" / sources line under answers.
3. Diff preview for `update_doc` in the approval card.

**Primary persona:** sales rep closing an order end-to-end via chat.
**Hero workflow:** entry (form button on Sales Order) → context → tool calls
(get_doc, update_doc, submit_doc) → approval gate (diff preview) → audit row → success.

---

## Problem Statement

Albanna already has governed autonomy (permission parity, approval gates, audit),
but three gaps limit trust and discoverability for a sales rep:

1. When a Frappe error dialog appears, the user has no way to ask "why did
   this fail?" in context — they must copy the traceback by hand.
2. An answer names the documents it read, but the reader has to trust that
   the assistant actually read them; there is no visible "sources" line.
3. The approval card shows *what* will change but not *from what to what*, so
   confirming an edit is a leap of faith.

## Solution

Three small, independent changes that each make an existing surface more
trustworthy, without new backend subsystems:

1. A global script (like `albanna-form-button.bundle.js`) that hooks Frappe error
   dialogs and adds an "Ask Albanna" button passing the error text as the
   first question.
2. A "Sources" line under each assistant answer listing the documents the
   tools actually read (already stored as `documents` on the message).
3. `update_doc` returns a before/after diff of the changed fields; the
   approval card renders it before the reader confirms.

## User Stories

1. As a sales rep, I want an "Ask Albanna" button on any Frappe error
   dialog, so that I can ask why it failed without copying the traceback.
2. As a sales rep, I want the error text and doctype pre-filled into the
   chat, so that I do not have to re-describe the problem.
3. As a sales rep, I want a "Sources" line under an answer, so that I can
   see which documents the assistant read.
4. As a sales rep, I want each source to be a link, so that I can open the
   document the assistant read.
5. As a sales rep, I want the sources to be exactly the documents the tools
   read, so that nothing is guessed.
6. As a sales rep, I want to see old → new values for each changed field
   before I confirm an edit, so that I can make an informed decision.
7. As a sales rep, I want the diff to show only the fields I asked to
   change, so that the card stays short.
8. As a sales rep, I want the diff to be readable on a phone, so that I can
   confirm in the field.
9. As a sales rep, I want a refused edit to show no diff, so that a failed
   write is not presented as a success.
10. As a sales rep, I want the sources line to be absent when no documents
    were read, so that the assistant does not claim sources it did not use.
11. As a sales rep, I want the error button to be absent when chat access
    is denied, so that it never offers a chat I cannot use.
12. As a sales rep, I want the diff to handle a field whose value is a
    child table, so that nested changes are visible.
13. As a sales rep, I want the sources to survive a page reload, so that a
    reopened thread still shows what was read.

## Implementation Decisions

- **Seam:** three independent seams, each at the highest possible level.
  - Error button: a global script (already the pattern for
    `albanna-form-button.bundle.js`), hooking Frappe's error dialog rendering.
  - Sources line: pure frontend, reading `message.documents` which is
    already populated from the stored tool calls. No new backend, no new
    data.
  - Diff preview: the `update_doc` adapter already returns the changed
    fields; the diff is computed in the adapter (before/after per field) and
    carried in the `confirm` event's `preview` (or a new `diff` field). The
    authority layer is unchanged; the diff is a *presentation* of the data
    the authority already authorised.
- **No new DocTypes, no schema changes, no new API endpoints.**
- **No new permissions.** The error button checks `window.albannaSideChat`
  existence (which implies chat access) before rendering.
- **Diff shape:** `{ fieldname: { before: any, after: any } }` for each
  changed field, computed from the document before and after `doc.save()`.
  Only fields present in the user's `data` argument are included.
- **Sources shape:** already `{ doctype, name }[]` per assistant message;
  rendered as links using the existing `openDocumentFrom`/document-link logic.
- **Mobile:** the diff renders as a two-column (old / new) list that
  stacks on narrow screens.

## Testing Decisions

- **Good tests** test external behaviour: the button appears on error
  dialogs when chat access holds; the sources line lists exactly the stored
  documents; the diff contains exactly the changed fields with old/new values.
- **Prior art:** `tests/test_tool_manifest.py` (manifest/adapter parity),
  `albanna/tests/test_integration.py` (tool path, update path), and the
  `context.test.mjs` / `markdown.test.mjs` node tests for frontend logic.
- **New tests:**
  - Domain: a pure function `diffFields(before, after, requested)` returns
    the right shape; a pure function `sourcesFor(message)` returns the
    stored documents.
  - Site: `update_doc` on a document returns a diff containing the changed
    field; a refused write returns no diff.
  - Node: the Sources line renders one link per document and none when
    empty.
- **Not tested:** visual layout, CSS, button placement (manual review).

## Out of Scope

- Undo last AI action (v2).
- Dry-run mode (v2).
- Bulk actions via chat (v2, needs diff preview + partial success first).
- Mobile voice input, file drop, image understanding (v3).
- Any change to the permission model or tool set.

## Further Notes

- The three items are independent and can ship in any order; item 3 (diff
  preview) is the largest and should be last so items 1 and 2 land first.
- The diff preview depends on `update_doc` returning before/after values,
  which is a small adapter change; the approval card already consumes the
  `confirm` event's `preview` field, so the diff can ride along there.
- No new translation strings beyond "Sources", "Changed", "from", "to",
  "Explain this error", and "Ask Albanna about this error".
