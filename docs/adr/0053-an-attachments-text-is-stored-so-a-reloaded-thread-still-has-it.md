# ADR-0053: An attachment's text is stored, so a reloaded thread still has it

Status: **Accepted**
Date: 2026-11-09

## Context

ADR-0050 gave a PDF's text to the model in the turn that attached it, and
recorded the gap it left: the history is rebuilt from stored URLs alone,
so a reader who reloaded the thread and asked a follow-up about the
document was answered about a file nobody had read since.

That was honest and useless. The reader asks "what was the total?" and the
model has to say it cannot tell.

## Decision

**The text is stored on the message row, parallel to the URLs, and
replayed when the history is loaded.**

A `Long Text` column on `tabAlbanna Message`, written by the same path
that writes the URLs and read by the same path that reads them. The
column arrives with the schema sync, so there is nothing to move and the
patch is a guard rather than a migration.

**A row written before the column existed carries no text, and the note
says nothing about readability.** That is the correct answer for a row
nobody looked at, and it is the reason `None` and an empty entry mean
different things in `attachment_note`.

## Alternatives considered

**Re-extract from the stored File on every history load.** Rejected: it
is I/O and a `pypdf` parse per attachment per turn, and a thread with
five documents would pay it on every turn for ever. The column pays once.

**Store it in the existing `attachment_urls` JSON.** Rejected: that field
means "the addresses", and a text living in a field named for addresses
is a lie about the schema — the exact thing ADR-0041 spent a migrate
removing.

**Store a shorter version.** Rejected: the history would then be a lossy
copy of what the turn saw, and the model would be told a different
document from the one the reader attached. The bound is the turn's own,
so the history is exactly what the turn had.

**Leave it.** Rejected: it is the difference between a thread that
remembers what it was shown and one that remembers only that something
was shown.

## Consequences

* A reader who reloads a thread and asks a follow-up about an attached
  document is answered about it.
* The column is one more on `tabAlbanna Message`, and the migrate is the
  same procedure as ADR-0041's and ADR-0042's.
* The test fails with the replay removed.
* The general lesson is ADR-0052's from the other side: a fact that
  exists in one turn and not the next is a fact the reader does not have.
  The turn had the text; the thread did not.

## See also

* [ADR-0050](0050-a-pdfs-text-reaches-the-model-and-its-bytes-do-not.md)
  — the turn-side half, and the gap this closes.
* [ADR-0041](0041-the-attachment-fields-are-named-for-what-they-hold.md)
  and [ADR-0042](0042-the-truncation-flag-is-stored-not-inferred.md) — the
  other two columns on this table, and the same migrate procedure.
* `albanna/services/conversation_service.py` — `append_messages`, which
  writes it, and `load_messages`, which replays it.
