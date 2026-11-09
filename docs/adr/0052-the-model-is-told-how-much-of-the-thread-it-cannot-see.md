# ADR-0052: The model is told how much of the thread it cannot see

Status: **Accepted**
Date: 2026-11-09

## Context

A long thread is worked on for days, and the model sees only the last
`history_limit` of it — fifty by default. It used to not know that.

So a question about a decision made forty messages ago was answered from
the window, and wrong in a way nobody could see. The roadmap named this
as *"a long thread remembers"* and marked it not started, effort M.

## Decision

**The count of what is behind the window is carried into the site block
of the prompt, as a number.**

A number, not a warning: the model can act on "there are 290 messages
behind what you can see" and cannot act on "this is a long thread".

**The prompt tells it what to do with the number** — say that a question
about something decided earlier is one it cannot answer from what it has,
and ask the reader to repeat the decision, rather than answering from the
window and being wrong silently.

That is the same rule the app already ships for refused reads: silence is
not the whole truth.

## Alternatives considered

**Raise `history_limit`.** Rejected: it costs tokens on every turn of
every thread, including the short ones, and it does not fix "silently" —
a bigger window still has an edge.

**Summarise the older messages.** Rejected for now: it is a second model
call per turn, and the summary is a lossy copy of the thing it
summarises. It is the right answer eventually and the wrong thing to
build before the honest version exists.

**Give the model a tool to reach further back.** Rejected for now: it is
a feature, and it needs a decision about what "further back" means —
a window? a search? a summary? This ADR does not preempt that.

**Say nothing and let the reader notice.** Rejected: that is the argument
for every unguarded silent loss, and the reader cannot notice a decision
the model never saw.

## Consequences

* A reader who asks about something decided early is told the model
  cannot see it, rather than given an answer built from the wrong part of
  the thread.
* The count is taken in one query and never goes below zero.
* A count that cannot be taken reads as nothing behind — the safe
  direction to be wrong in, because it tells the model the window is the
  thread.
* This is the honest half of the fix and not the whole of it. The other
  half — a way to reach further back — is a feature, and it is not built
  here. What is built is that the loss is stated rather than silent,
  which is the difference between an answer the reader can check and one
  they cannot.
* The test fails with the count removed.
* The general lesson is ADR-0040's from the other side: a bound nobody is
  told about is a bound that fails silently at the edge. The trim had a
  bound that never ran; this one runs on every turn and nobody knew.

## See also

* [ADR-0040](0040-a-guard-that-only-runs-past-a-threshold-fails-in-whatever-crossed-it.md)
  — the other bound in this app that was wrong at its edge.
* `albanna/core/prompt.py` — `PromptContext.history_behind`, and the
  instruction that says what to do with it.
* `albanna/services/chat_service.py` — `_messages_behind`, the count.
* `docs/ROADMAP.md` §2 item 9 — the record that named this as not
  started.
