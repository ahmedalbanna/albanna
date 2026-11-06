# FR-5 — Approval and undo

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the five functional requirements FR-5.1 … FR-5.5, which describe
the two moments where a write stops being the assistant's decision: the
card that asks the reader before it runs, and the button that takes it
back afterwards.

---

## FR-5.1 — The card shows the document, the field, the current value and the proposed value

**Requirement.** Before a write runs, the reader is shown what it will
change: the document, the field, the value it holds now and the value it
will hold afterwards.

**Status.** Shipped for a single update.  Shipped for a bulk change after
this pass.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — the card: the action
  verb, a live countdown read from the server's own deadline, the preview,
  a destructive consequence where one applies, the diff, and
  Cancel/Confirm.
- `albanna/services/approval.py` — `write_diff`, which builds the
  before/after map for `update_doc`, and `write_preview`, which builds the
  human-readable sentence for every write.
- `albanna/core/diff.py` — `diff_fields`, which reports only the requested
  fields that actually changed, so the diff is *a report of the change the
  reader asked for, and nothing else*.
- `albanna/services/approval.py` — `_preview_bulk`, which now carries the
  distribution of current values for each field being changed (added this
  pass), drawn from the same permission-filtered query the count and the
  sample names come from.

**Gaps found.**
- **G1 (fixed this pass).** The bulk card showed the proposed value and
  not the current one: *"Change 42 Sales Invoice document(s): status =
  Paid"*.  The reader approved a change **from** a state they were not
  shown, and across forty-two documents that state is not one value.  The
  card now says *"status is currently Draft 12, To Bill 30"*, which is the
  difference between a decision and a request for trust.  The distribution
  is the reader's own, so the card still never tells a reader what they
  cannot see.
- **G2 (tested this pass).** `write_diff` appeared in the suite once, in
  the negative case — that it returns `None` for a document the reader may
  not read.  `diff_fields` was tested directly and thoroughly, but the
  wrapper that loads the document and builds the before-map was not, and
  that wrapper is the whole of this requirement.  Covered in
  `albanna/tests/test_parity.py`.

**Blocked.** Nothing.

---

## FR-5.2 — The reader can approve or reject from the card

**Requirement.** The card offers both answers, and the one the reader
gives is the one that happens.

**Status.** Shipped.  One defect found and fixed this pass.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — the card's Cancel and
  Confirm, both disabled while `!canDecide(...)`.
- `albanna/api/chat.py` — `confirm_write`: chat access, a request id, and
  a decision of `approve` or `reject`, because *a write that is neither
  approved nor declined is not a thing that can be acted on*.
- `albanna/services/approval.py` — `record_decision`: a decision naming no
  pending write is refused, the first decision is the decision, and the
  answer is bound to the reader it was asked of — *an endpoint that took
  any account's word for any pending write would let one reader approve
  another reader's change — and the worker runs it*.
- `albanna/services/approval.py` — `canDecide` and `remainingSeconds`: the
  client's window is the server's own deadline, sent with the event,
  because *a countdown that runs on the browser's clock against a
  different constant tells the reader they have time they do not have*.
- Tested: an approved write runs, a declined one does not, a decision
  naming no write is refused, a second decision is refused, another
  account's decision is refused, a timeout is recorded, and the approval
  is recorded in the row before the reader is asked.

**Gaps found.**
- **G1 (fixed this pass).** The *"The wait ran out — the change was not
  made."* message was the **diff's else-branch**.  It fired whenever there
  was no diff — which is every write except a field-changing update,
  because `write_diff` returns `None` for the rest by design.  So the
  cards for `create_doc`, `bulk_update_doc`, `submit_doc`, `cancel_doc`,
  `amend_doc` and `delete_doc` all told the reader the change had not
  happened while the header still counted down and the Confirm button was
  still enabled.  The message is now gated on the window having actually
  expired.

**Blocked.** Nothing.  The defect was in template wiring, and the app has
no component-test harness, so it is verifiable by reading and by opening a
card in a browser rather than by a unit test.  The condition it should
have used (`canDecide`) is tested; what was wrong is that the template
used a different one.

---

## FR-5.3 — A reversible write offers an undo button in the answer

**Requirement.** After a create, an update or a submit, the answer carries
a button that takes the write back.

**Status.** Shipped for create, update and submit.  Shipped for a bulk
change after this pass.

**Evidence.**
- `albanna/core/undo.py` — `UNDO_BY_ACTION`, the rule in one place, read
  by both the endpoint that undoes and the transcript that offers, because
  *a rule that lives in two places is a rule that will be true in one of
  them*.
- `albanna/services/chat_service.py` — `undo_entry`, the one builder, so
  the transcript and the live panel cannot disagree about whether a turn
  can be taken back.
- `albanna/services/conversation_service.py` — the transcript carries
  `undoable` per tool, computed by the same rule the live event uses.
- `albanna/services/undo.py` — `_take_back`, which carries out one entry,
  and now `update_many` in reverse, stopping at the first failure exactly
  as `undo_message` does for a sequence of calls.
- Tested: a creation undone by deleting, a change by writing the old
  values back, a submission by cancelling, a read never offered, the
  button disappearing once the undo is spent, and the endpoint's
  transcript agreeing.

**Gaps found.**
- **G1 (fixed this pass).** A bulk change was declared undoable and never
  offered.  `UNDO_BY_ACTION` listed `bulk_update_doc`, and a test asserted
  it was undoable — but that test built a **synthetic** entry, so it
  proved the rule and not the tool.  `bulk_update_doc`'s result carried no
  `before`, `undo_entry` built nothing, and the button never appeared.
  `_bulk_change_one` knew exactly what the before-values were and threw
  them away, keeping only a count.  Fixed by carrying them through to a
  new `update_many` action, and by the test that runs a real bulk change
  through the backend and follows it all the way through — the stored
  entry carries the undo, the transcript offers the button, and taking it
  back puts every document back.

**Blocked.** Nothing.

---

## FR-5.4 — The undo button appears only where the reversal is the opposite operation

**Requirement.** A button that cannot honestly take a change back is not
offered.

**Status.** Shipped for create and update.  Submit is met by disclosure
rather than by absence — see below.

**Evidence.**
- `albanna/core/undo.py` — the rule, and the docstring that states the
  standard in this requirement's own terms: *"A cancel is not an undo, an
  amend is not an undo, and a delete cannot be taken back by anything this
  app offers — so the reader is not offered a button that cannot be
  honest."*
- `albanna/core/undo.py` — `is_undoable` checks the **tool name** against
  the action's allowed tools, so a forged, stale or mis-written entry
  cannot make a tool undoable that is not.
- Tested: a delete may not be undone by anything, a cancel may not be
  undone by anything, and a read may not be undone by deleting what it
  read.

**Gaps found.**
- **G1 (disclosed this pass).** `submit_doc`'s undo cancels rather than
  reverses.  Submitting moves a document `draft → submitted`; cancelling
  moves it `submitted → cancelled`; the opposite of submitting
  (`submitted → draft`) is not something Frappe offers.  So the reversal
  is neither the same operation nor the opposite direction — it is a
  forward move to a third state, and the document does not return to where
  it was.  The app decided this deliberately and documented it, and the
  capability is genuinely useful.  What was missing was the disclosure:
  the reader was told *"The turn was undone."* and left to believe the
  document was a draft again.  The undo now says what it did — *"The
  submission was cancelled."* — using the action the server already
  returned and the client was discarding.

**Blocked.** The stricter reading of this requirement.  If the owner wants
it satisfied exactly as written, the alternative is to drop the submit
undo and remove `UNDO_BY_ACTION`'s `cancel` entry.  That loses a
capability the roadmap lists as shipped.  This pass discloses instead, and
records the alternative rather than taking it.

---

## FR-5.5 — Cancel, amend and delete do not offer undo

**Requirement.** The three lifecycle actions that cannot be taken back
offer no button.

**Status.** Shipped.  Amend was untested; covered this pass.

**Evidence.**
- `albanna/core/undo.py` — `UNDO_BY_ACTION` maps no action to
  `cancel_doc`, `amend_doc` or `delete_doc`.
- `albanna/core/undo.py` — `is_undoable` checks the tool name, so even a
  stored entry claiming `{"action": "update", …}` on a `cancel_doc` call
  is refused.
- `albanna/services/chat_service.py` — `undo_entry` returns `None` for all
  three, for three independent reasons: `_created_name` answers only for
  `create_doc` (*"the tool decides, not the envelope"*), none of them
  carries `before`, and none is `submit_doc`.
- Tested: a delete may not be undone, a cancel may not be undone, and —
  added this pass — an amend may not be undone, at both the rule layer and
  the transcript layer the button actually reads.

**Gaps found.**
- **G1 (tested this pass).** `amend_doc` was the one of the three whose
  exclusion was asserted only by reading the code.  The docstring named
  it, the rule excluded it, and `undo_entry` returned `None` for it — and
  no test said so.  It is the interesting case of the three, because its
  reversal *looks* available: an amendment cancels the original and
  creates a new draft, so "delete the new draft and un-cancel the
  original" is imaginable, and Frappe does not offer un-cancelling.
- **G2 (tested this pass).** The transcript-level tests covered a read and
  an update.  Nothing asserted that the transcript — the thing the button
  reads — says not-undoable for cancel, amend or delete.

**Blocked.** Nothing.

---

## Found on the way, and not part of any requirement

**The conversation trim had never worked.** `trim_conversation`'s DELETE
put a `LIMIT` inside an `IN` subquery, which MariaDB refuses outright —
*"This version of MariaDB doesn't yet support 'LIMIT & IN/ALL/ANY/SOME
subquery'"*.  So the trim only ever failed once a conversation outgrew its
400-message bound, which is exactly when it is needed.  It surfaced as an
error in whatever turn happened to push a thread past the bound, which
made it look like a bug in that turn rather than in the trim.  Four tests
were red from it on `test.localhost` by the time it was found, and the
number grows with the accumulated data.  The two forms delete the same
rows; the fix is `DELETE … ORDER BY … LIMIT`.

It is recorded here rather than in a requirement because it belongs to
none of them, and because the way it presented — as a failure in an
unrelated test — is the thing worth remembering.
