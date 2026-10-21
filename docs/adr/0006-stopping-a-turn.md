# ADR-0006: Stopping a turn is a client-side act

Status: **Accepted**
Date: 2026-10-21

## Context

A turn is not a request that returns an answer.  The endpoint returns a
stream id immediately, the work happens in a background worker, and the
answer arrives over socket.io — with a poll as the guarantee that a
client whose socket died still gets it.

That makes a turn *wait*.  A turn can take a long time: the model may be
slow, the queue may be busy, and a worker may be restarted mid-turn.
None of that is a bug, and none of it is the reader's fault, but all of
it is time the reader is spending watching a panel that will not change.

The panel had no way out.  While a turn ran, the send button was
disabled and read "Working…", and the only way to stop waiting was to
reload the page — which threw away the question, the partial answer and
the conversation's position in one gesture.

## Decision

**The panel can stop *waiting*.  It cannot stop the *work*.**

The Stop button aborts the client: the socket subscription is dropped,
the poll stops, and the turn resolves as stopped.  The worker keeps
running.  The answer it produces is still parked in the cache and still
written to the conversation, so the reader who comes back to the
conversation finds the answer there.

### Why not cancel the worker

A server-side cancel would have to reach into the worker to interrupt a
model call that is already in flight.  That is a cancellation channel
between the browser and the queue — a new endpoint, a new signal in the
job, a new way for the two to disagree about whether the turn is
happening — for a benefit that is small: the reader has already decided
they do not want the answer.

And the cost is not only complexity.  A cancelled turn is a turn whose
conversation is *half* written: the question is in it, and the answer is
not, and the next question in that conversation starts from a question
that was never answered.  A stopped-but-completed turn has the same
question in it and the answer arrives later.  The second is a better
state to leave the conversation in, and it costs nothing.

### Why the client is the only thing that has to change

The worker, the queue and the cache already have everything they need.
The answer's delivery is already guaranteed by the cache, and the
conversation is already written by the worker.  Nothing on the server
needs to know that the reader stopped looking.

## Consequences

* The Stop button is always available while a turn runs, and the panel is
  the reader's again the moment it is pressed.  A turn that cannot be
  ended is the one thing in a chat that must never be a dead end.
* The panel says the turn was stopped.  It does not pretend the work
  stopped, because it did not.
* The transport takes an `AbortSignal` and resolves `{status:
  "aborted"}`.  The abort listener is registered *after* the poll timers
  are made, because a signal aborted while the request was in flight
  would otherwise settle the turn before there was a timer to clear —
  and the poll would then be scheduled after the turn was over, by
  nobody's hand and for nobody's benefit.
* The server keeps its promise: a turn whose worker dies without
  answering is reported as lost, not polled for ever.  Stopping is not
  that case, and the two are not confused.

## See also

* [ADR-0005](0005-five-tools.md) — the tool set a turn may use, and the
  rounds it may take.
* [CONTEXT.md](../CONTEXT.md) — invariant 9, "A turn is delivered, or the
  user is told it was lost".
