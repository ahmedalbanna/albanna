# ADR-0023: A fact about an answer belongs to the answer

Status: **Accepted**
Date: 2026-11-05

## Context

An answer cut off at the token ceiling is not wrong — it is unfinished, and
the reader is told so, because an answer that looks complete and is not is
worse than one that says it was cut.  The detection is thorough: one rule
in `providers/base.py` reads whatever word the provider used, all three
provider kinds apply it in both the streaming and the assembled paths, the
flag travels through the payload, and the ledger records it as a status.

The reader was told through `state.notice` — one slot for the whole panel.

`beginTurn` clears it.  So asking a follow-up erased the previous answer's
truncation indication while that answer was still visible in the transcript
above.  Any other notice overwrote it too: a failed copy, a deleted
conversation, a moved page.  And it rendered at the foot of the panel
rather than beside the answer it described.

So the reader asked, got a cut-off answer, saw *"The answer was cut off
before it was finished."*, asked a follow-up — and the truncated answer
above now looked complete.  The information was available; it was put in a
place that could not hold it.

## Decision

**A fact about an answer is carried on the answer.**

`makeMessage` grew a `truncated` field, `applyTurnResult` sets it, and the
message's footer renders it beside the answer — so it survives the next
question, any other notice, and a reader who scrolls back up the
transcript.  The announcement line still fires once, for a screen-reader
user who is not looking at the footer.

The other notices stay where they are.  `dry_run` and `image_dropped` are
facts about the *turn* rather than about one answer, and the panel's single
slot is the right home for them.  The distinction is not the kind of fact
but its scope: a fact that outlives the turn belongs to the thing it is
about.

Persistence is deliberately not part of this decision.  `tabAlbanna Message`
has no column for the flag, so a conversation reopened tomorrow still shows
the truncated answer with nothing saying so.  Adding the column is a
migrate — backup, build, maintenance mode, migrate, every worker set
restarted — and that is a deploy decision rather than a code change.  The
live view is fixed now; the stored view waits for a decision.

## Alternatives considered

**Keep the notice and clear it less eagerly.**  Rejected: it would mean
`beginTurn` no longer clears the notice, and then a stale "stopped" or
"copy-failed" would sit under a new question.  The notice slot is correct
for what it holds; the truncation flag was simply in the wrong place.

**Put the flag in the message's `summary` line.**  Rejected: the summary is
the tool calls' line, and a reader looking for what the assistant did would
find a statement about what it failed to finish.  Two different facts in
one field is how a field stops being read.

**Mark the answer's text itself — an ellipsis, or a trailing note in the
**bubble**.**  Rejected for now: it would mean post-processing the model's
markdown, and a note inside the answer is a note the model did not write.
The footer is outside the answer and unambiguous.

**Persist it by riding an existing Long Text column.**  Rejected: the
precedent for that (ADR-0007's approvals riding the ledger's `tools`
column) is the *ledger*, which operators read.  A truncation flag buried in
the transcript's tool-calls JSON is a flag the reader cannot rely on, and
the whole point of this change is that the reader can.

**Add the column now.**  Rejected as sequencing rather than as direction:
the live defect is the one a reader hits today, and it costs nothing to
fix.  The migrate should be taken deliberately, with the deploy window it
needs.

## Consequences

* A truncated answer carries its own mark, and the mark survives the next
  question, a scroll back up the transcript, and any other notice.
* The panel's notice slot keeps what it is good at — transient facts about
  the turn — and loses a fact it could not hold.
* The stored conversation still does not say an answer was truncated.  That
  gap is recorded in `docs/FR-2_ASKING.md` as blocked on a migrate, rather
  than being quietly forgotten.
* `makeMessage` grew a field whose only reader is the footer, which is the
  same shape as `cost` and `hasTable` — a fact about one answer, carried on
  it.

## See also

* `docs/ROADMAP.md` §0.2.5 — the precedent for riding an existing column
  rather than taking a migrate, and the reason it applied to the *ledger*
  and not to the transcript: the ledger is read by operators, the
  transcript is trusted by readers.
* `albanna/public/js/side-chat/state.mjs` — `beginTurn`, whose clearing of
  the notice slot is correct for everything except this.
* `tests/test_truncation.py` — the detection rule, which was never the
  problem.
