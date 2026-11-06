# ADR-0039: The submit undo discloses rather than disappears

Status: **Accepted**
Date: 2026-11-06

## Context

FR-5.4 says the undo button shall appear only where the reversal is the same
operation in the opposite direction. `core/undo.py`'s docstring states the
same standard in its own words:

> *"A cancel is not an undo, an amend is not an undo, and a delete cannot be
> taken back by anything this app offers — so the reader is not offered a
> button that cannot be honest."*

`create_doc` → delete and `update_doc` → revert both satisfy it: the document
returns to not existing, and the fields return to the values they held.

`submit_doc` → cancel does not. Submitting moves a document
`draft → submitted`. Cancelling moves it `submitted → cancelled`. The
opposite of submitting would be `submitted → draft`, which Frappe does not
offer. So the reversal is neither the same operation nor the opposite
direction — it is a forward move to a third state, and the document does not
return to where it was.

The app decided this deliberately and documented it, and the capability is
genuinely useful. What was missing was the disclosure. `undoTurn` used the
server's answer only for its length:

```js
const undone = (result && result.undone) || [];
if (undone.length) {
	state.notice = "undone";        // "The turn was undone."
}
```

`_take_back` returned `{"action": "cancelled", "doctype": "Sales Invoice",
"name": "ACC-SINV-00042"}` — the server knew exactly what it had done — and
the client discarded it. A reader who undid a submission was told *"The turn
was undone."* and left to believe the document was a draft again. It was
cancelled, and getting it back needed an amendment.

## Decision

**Keep the button, and say what the undo did.**

`undoTurn` now reads the action from the server's response and picks the
notice that names it — *"The submission was cancelled."*, *"The change was
reverted."*, *"The document was deleted."* — falling back to the generic
notice only when the action is absent or unrecognised.

The information was already there. The change is to stop throwing it away.

## Alternatives considered

**Drop the submit undo.** Rejected: it would satisfy FR-5.4 exactly as
written, and it would remove a capability the roadmap lists as shipped and a
reader genuinely wants. A reader who submitted the wrong invoice wants to
un-submit it; cancelling is the closest thing the site offers, and refusing
to offer it leaves them with nothing.

**Keep the vague notice.** This was the behaviour. Rejected: it is the one
case where vagueness misleads rather than merely under-informs. A reader who
is told "undone" about a cancellation will look for a draft and find a
cancelled document, and will not know which of the two the assistant did.

**Name the document in the notice.** Rejected for now: the server returns it,
so it is available, but a notice that names a document is a notice that has
to be translated with a value in it, and the app's rule is that numbers go
into the string after the translation rather than through it. The action
alone is enough to stop the reader being misled; the document is one click
away in the transcript.

**Reframe the button as "Cancel this submission" rather than "Undo".**
Rejected: it would make the button's label depend on which tool made the
write, and the panel already has one undo button per answer. The disclosure
belongs in the result, not in a label that changes meaning.

## Consequences

* A reader who undoes a submission is told the document is cancelled, not
  that the turn was undone.
* The notice keys gained `deleted`, `reverted` and `cancelled`, and the
  existing `deleted` — which had meant *the conversation was deleted* — was
  renamed to `conversation-deleted`. That collision was forced by this
  change and is the reason the rename exists; a key, its sentence, its test
  entry and its catalogue entry are one thing, and the test that asserts
  every key has a sentence is what caught the removal of the dead
  `truncated` key in the same pass.
* FR-5.4's clause is met by disclosure rather than by absence. That is
  recorded in `docs/FR-5_APPROVAL.md` as a deliberate reading, with the
  stricter alternative named rather than taken.
* The general principle: when a reversal is not the opposite operation, the
  honest options are to not offer it or to say what it did. Silence is not a
  third option.

## See also

* [ADR-0036](0036-no-tool-is-handed-sql.md) — the previous pass's decision
  about a rule that was true and unenforced; this is the same shape on the
  product side.
* `albanna/core/undo.py` — the rule, and the docstring that states the
  standard this decision is measured against.
* `albanna/services/undo.py` — `_take_back`, which already returned the
  action the client was discarding.
* `albanna/public/js/side-chat/notices.mjs` — the three new sentences and
  the rename.
