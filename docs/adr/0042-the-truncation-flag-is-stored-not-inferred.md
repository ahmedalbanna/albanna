# ADR-0042: The truncation flag is stored, not inferred

Status: **Accepted**
Date: 2026-11-08

## Context

When a provider cuts an answer off at the token ceiling, the reader is
told. The live view set the flag from the turn's own result and the
footer rendered it beside the answer it described.

Then the reader reloaded the thread, or came back to it tomorrow, and the
indication was gone. It lived only in the browser: `tabAlbanna Message`
had seven fields and none of them was the flag, and `load_transcript`
reads the table.

An unfinished answer and a short one look identical, and only one of them
is a warning. A reader who reloads and finds the marker gone has been
told something different from what they were told.

The turn-level fact was already persisted — `tabAlbanna Chat Log.status`
is a Select carrying `truncated` among its values, and the chat service
writes it. But that row is one per turn and names no message, so the
transcript could not join it to the answer.

## Decision

**The flag is stored on the message row and read back by the
transcript.**

A `truncated` Check field on `Albanna Message`, written by both paths
that store an answer — the ordinary one and the step-budget one, because
both can be cut off — and carried by `load_transcript` into the shape the
widget draws.

**Stored rather than inferred from the answer's length.** A short answer
is not an unfinished one. Marking every brief reply as truncated would
make the indication noise, and a reader learns to ignore a warning that
is usually wrong.

## Alternatives considered

**Join the Chat Log.** Rejected: it is one row per turn and carries no
message name, so the join does not exist. Adding one would mean writing
the message's name onto the audit row, which is a second denormalisation
to avoid one column.

**Store it in the existing `tool_calls` JSON.** Rejected: that field
means "the tool calls", and a flag living in a field named for something
else is a lie about the schema — the exact thing ADR-0041 just spent a
migrate removing.

**Leave it live-view-only.** Rejected: it is the case where the reader
most needs the information, because a reloaded thread is where they
cannot tell an unfinished answer from a finished one.

**Infer it from the answer's length.** Rejected: see above. It would be
right most of the time, which is the dangerous kind of wrong.

## Consequences

* A reader who reloads the thread sees the same indication the live view
  showed.
* The migrate that adds the column is the same one that renames the
  attachment fields (ADR-0041) — both touch `tabAlbanna Message`, so one
  maintenance window rather than two.
* The new test fails with the write removed, which is the evidence the
  column is load-bearing rather than decorative.
* The general lesson is ADR-0040's again, from the other side: a fact
  that exists in one layer and not the layer the reader reads is a fact
  the reader does not have. The ledger had it; the transcript did not.

## See also

* [ADR-0040](0040-a-guard-that-only-runs-past-a-threshold-fails-in-whatever-crossed-it.md)
  — the same shape: the check existed where nobody read it.
* [ADR-0041](0041-the-attachment-fields-are-named-for-what-they-hold.md) —
  the other change in the same migrate.
* `albanna/services/conversation_service.py` — `append_messages`, which
  writes it, and `load_transcript`, which reads it back.
