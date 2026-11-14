# ADR-0104: The thread's earlier words are reachable, not merely counted

Status: **Accepted**
Date: 2026-11-14
Completes ROADMAP §2 item 9; the honest half shipped as ADR-0052.

## Context

A long thread is worked on for days, and the model sees only the last
`history_limit` of it — fifty by default.  ADR-0052 shipped the honest
half: the prompt carries the count of what is behind the window, and the
model is told to say when a question about something decided earlier is
one it cannot answer from what it has, and ask the reader to repeat the
decision.

That half made the gap *visible*.  It did not close it: a reader with a
four-hundred-message thread was still asked to repeat decisions they
had already made, because the only machine that could see message
twelve was the database.

## Decision

**One backend tool — `read_thread_history` — reads the current thread's
own earlier messages.**

* **Reach, not a dump.**  Arguments: `query` (optional text match, the
  drawer's own search semantics — `%`, `_` and the escape character are
  ordinary characters in what a reader typed) and `page` (0-based).
  Twenty messages a call, each labelled with its absolute position in
  the thread ("message 214 of 340"), content truncated to a fixed
  ceiling per message.  The tool's answer is bounded twice: per message
  here, and the whole envelope by the manifest's
  `max_result_chars`, which already announces its own truncation.
* **Browse is behind the window; search is the whole thread.**  With no
  query, page 0 is the twenty messages immediately behind the window's
  edge — the words most likely to matter — and each page steps further
  back, chronological inside the page.  With a query, the match runs
  over the whole thread, chronological from the first message: a search
  that reaches only behind the window would hide matches the reader can
  see, and the model needs to find where a decision was made, not only
  how near the edge it sits.
* **The thread is the server's fact, not the model's.**  The tool
  declares `context` (the port's `ToolContext`, exactly as the question
  tool does): the conversation comes from the turn being run, is never
  in the schema, and the model cannot name another thread.  There is no
  doctype parameter, no thread parameter, nothing to get wrong; a call
  outside a conversation is refused with the reason.
* **Only what the reader can already see.**  The tool returns the
  user/assistant rows of the thread — the transcript copy the panel
  already draws — and no tool-call payloads, which the stored history
  never replays either (`as_plain_history` strips them for the same
  reason).  No new permission question is invented: the turn the tool
  runs in already belongs to the caller, and the words it returns are
  the caller's own thread.
* **The prompt instruction changes with the tool.**  The behind-count
  stays (ADR-0052's number), but "ask the reader to repeat the
  decision" becomes "look it up with `read_thread_history` first; ask
  the reader only when the tool cannot find it".  The honest sentence
  remains the fallback, not the primary.

## Alternatives considered

**Return the whole thread on one call.**  Rejected: the tool would
re-send what the window already carries and blow a tool round's token
budget on threads the budget is for.  Paging is what makes reach cheap.

**A summarise-the-older-turns service instead of raw reach.**  Rejected
for now: a summary is a second opinion about what mattered, and a wrong
one is silent.  Raw reach is checkable — the model quotes the words and
the reader recognises them.  A summary can come later, on top.

**Model-supplied thread id.**  Rejected: the id would be a claim the
model could get wrong, and a wrong id is a read of somebody else's
thread.  The server supplies the conversation; the model supplies only
what it is looking for.

## Consequences

* "What did we decide about X in March?" is answerable from the thread
  instead of a guess or a repeat request.
* The behind-count stays honest: the model is told how much sits behind
  the window *and* given the way to reach it.
* The cost of a reach is one indexed query on the message table's
  parent column, paged; the ceiling bounds the answer.
* Tests fail with any part of the contract dropped: the context
  refusals, the paging arithmetic, the absolute positions, the search's
  escaping, the window's edge as page 0.

## See also

* [ADR-0052](0052-the-model-is-told-how-much-of-the-thread-it-cannot-see.md)
  — the count that made the window honest; this gives it hands.
* `albanna/tools/history.py` — the handler.
* `albanna/core/tools.py` — the spec, in the manifest beside the others.
