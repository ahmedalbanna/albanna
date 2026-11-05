# ADR-0019: Stop stops

Status: **Accepted**
Date: 2026-11-05

## Context

The send button becomes a Stop button while a turn runs.  Pressing it is
supposed to stop the turn — and the requirement it was written against
says so in as many words: *the UI shall stop waiting while the server
completes the work.*

`turn.mjs` implements that honestly and at length.  Stopping is a *client*
action: the worker keeps running, the answer is still parked in the cache,
the turn is not lost — it is merely no longer waited for.  The socket
subscription drops, the poll stops, the inflight address is kept so that
returning to the thread picks the turn up again mid-answer.

`stop()` in `SideChatApp.vue` did not always reach that code.

```js
function stop() {
	if (visibleApprovals.value.length) {
		for (const wait of visibleApprovals.value) {
			decideWrite(wait.streamId, "reject");
		}
		return;                          // no wait is aborted
	}
	…
	for (const wait of visibleWaits.value) {
		wait.controller.abort();
	}
}
```

When a write was waiting for the reader's approval, Stop rejected every
visible approval and returned without aborting anything.  The worker
received the rejection, told the model, and continued to its next round.
The turn kept running and the reader kept watching it.

So the button labelled "Stop" did not stop the turn in the one state where
the reader most wants to stop it: they have decided against the write, and
quite possibly against the whole turn.  It took a second press — now that
no approval was visible — to actually stop.

The comment showed this was a conscious choice: *"Stopping is a decision
as much as a click is, and it is the same decision: not to run it."*  That
reasoning is sound as far as it goes.  What it missed is that the button
says "stop the turn", and the choice it made was "reject the write" —
which is a third thing the reader did not ask for.

## Decision

**Stop rejects the pending approvals and stops the turn.  Both.**

The decision moved out of the component into `stop.mjs` as `stopPlan`, so
that it can be tested under plain node — the same rule ADR-0017 recorded,
applied to a decision rather than to geometry:

```js
rejectApprovals: hasApproval,   // a write waiting is not run
abortWaits: mayStop,            // and the turn stops, approval or not
```

`abortWaits` is true even when an approval was just rejected, because
rejecting only tells the model to carry on to its next round.  The worker
is blocked on the reader's decision; releasing it does not end the turn.

Rejecting before aborting is safe, and the order matters for a reason
worth stating: the rejection is its own request, while the abort only
stops the client's waiting.  `decideWrite` already clears both the live
card and the remembered one — `saveInflight({...saved, approval: null})` —
so a reload after the decision cannot resurrect a card that was already
answered.

`stop.test.mjs` covers all three branches, including the one that was the
defect: an approval pending rejects it **and** aborts.

## Alternatives considered

**Reject only, and let the turn continue.**  This was the behaviour, and
it is rejected because it is not what the button says.  A reader who
presses Stop and watches the turn carry on has been told something false
by a control.

**Abort only, and let the approval window expire.**  Rejected: the reader
gets no immediate answer about the write, and returning to the thread
later shows a card that says "waiting" about a worker that has already
given up.  `canDecide` guards against drawing an expired card, but the
honest answer is to decide now.

**Ask the reader which they meant.**  Rejected: a second question between
the reader and the thing they already pressed.  The app's own pattern is
that a control does the safe thing and says what it did.

**Make Stop refuse while an approval is pending.**  Rejected: it leaves
the reader with no way out of a turn they have decided against, short of
reloading the Desk.

## Consequences

* One press stops the turn, in every state it can be in.
* A write waiting for approval is still not run — that part of the old
  behaviour was right and is kept.
* The decision is tested, where before the tested halves (the transport,
  the state transition) were correct and the untested half was wrong.
* The reader who stops a turn mid-approval gets both effects at once, and
  the notice says the turn stopped.  There is no separate "the write was
  refused" sentence, because the card going *is* that sentence.
* `stop.mjs` is the second module extracted from `SideChatApp.vue` in this
  pass, after `submit.mjs`.  The component is smaller and the decisions in
  it are testable.

## See also

* [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md) — the
  rule that put this decision in a module rather than in the component.
* `albanna/public/js/side-chat/turn.mjs` — the transport, whose comment
  already described the semantics `stop()` was failing to reach.
* `albanna/public/js/side-chat/SideChatApp.vue` — `decideWrite`, which
  clears the card and the remembered approval.
