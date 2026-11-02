# ADR-0012: Several questions at once, and more than one answer to a question

Status: **Accepted**
Date: 2026-11-02

## Context

The reader's own words settled the shape of a question that a single
choice could not carry: sometimes the assistant needs *which* customer
and *which* items, and sometimes the answer is not one thing but several
— the three items that go on one invoice.  And sometimes one question
is not enough: the assistant runs out of road twice in the same breath,
and asking twice in two turns makes the reader answer twice.

opencode's own question tool already does both: a call carries a list of
questions, each of them single or multi, and the person answers them in
one dialog — moving back and forth, changing a choice, and sending them
all when they are sure.

## Decision

**A turn may ask several questions at once, and a question may take
several answers.**

* **Several at once.**  The model may call `ask_question` more than once
  in the same round.  Those calls share the turn they were asked in, and
  the browser renders them as one set: one question on screen at a time,
  with back and next, and a single submit that sends them all.  The
  turn still ends when the first of them is asked — the assistant may
  only speak afterwards — but the set is complete before the reader is
  asked to decide.
* **More than one answer.**  A question carries a `multiple` flag.  When
  it is set, the reader may choose several of the offered answers; when
  it is not, only one.  The model sets the flag, because the model
  knows whether the task needs one customer or several items.
* **One message carries the set.**  The reader's submit records each
  answer against its own row and sends one message with every answer in
  the order the questions were asked.  The assistant reads the whole
  answer in one turn.
* **The invariants hold.**  Only the reader may answer, the first
  answer is the answer, and an answer the reader was never offered is
  refused — now per value, so a multi-select question refuses a value
  that was never on its list even when the others were.  A single-select
  question that receives several answers is refused rather than
  half-kept, because choosing two on a single choice is a contradiction,
  not an answer.

## Consequences

* `Albanna Question` gains a `multiple` field.  A question that does not
  carry it reads as single, so questions written before this change keep
  their meaning.
* `Albanna Question` rows that share a turn form one set in the browser.
* `answer_question` accepts a single `value` or a list of `values`.
* The widget gains a small wizard per set: progress, back and next,
  checkboxes or single choice depending on the flag, a text box for an
  answer the assistant did not offer, and a submit that is disabled
  until every question has an answer.

## See also

* [ADR-0011](0011-the-question-is-asked-in-the-chat.md) — the question
  is asked in the chat, and the reader answers it in the chat.
