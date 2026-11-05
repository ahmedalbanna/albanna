# ADR-0022: The launcher holds a question until the app is listening

Status: **Accepted**
Date: 2026-11-05

## Context

A Frappe error dialog offers "Ask Albanna about this error", which opens
the panel with the error text and the doctype pre-filled as the first
question.  The button is only offered when the reader may chat — it waits
for the launcher's published answer rather than rendering for everybody and
opening nothing for some.

The launcher's `ask` opened the panel and dispatched the question:

```js
ask: (question) => {
	setOpen(true);                       // begins an ASYNC fetch of the ~180KB Vue bundle
	window.setTimeout(() => {
		panel.dispatchEvent(new CustomEvent("albanna:ask", { detail: …, bubbles: true }));
	}, 0);                               // fires in the next macrotask
},
```

The Vue app registers its listener in `onMounted`.  So on a cold panel the
event was dispatched long before the script was fetched, parsed, executed
and Vue had mounted.  The event bubbled to `document` with nobody
listening, and the panel opened **empty**.

Every subsequent click worked, because the bundle was loaded and the
listener existed.

That is the hardest kind of defect to catch: the feature works when you
test it, because testing it means clicking it twice.  And it fails on the
*first* click — the one a reader makes when they have just hit an error and
most want the help.

## Decision

**The launcher holds a question asked before the app has mounted, and
flushes it once the app is listening.**

The launcher is the only party that knows when the app is ready, so it is
the one that decides when the question can be delivered:

* `ask` stores the question in `pendingAsk` and flushes immediately if the
  app is already mounted — the common case, where the panel has been opened
  before.
* `loadBundle`'s `script.onload` calls `mount()`, which sets `mounted`, and
  then flushes.  The already-loaded path flushes too, because a second
  `ask` on a warm panel must not wait for a mount that has already
  happened.
* `flushPendingAsk` dispatches on a `setTimeout(0)`, so the event is
  delivered after the current task whatever path reached it.

The queue's ownership is deliberately in the launcher and not in the Vue
app.  The alternative — the app asking the launcher for a pending question
on mount — works, but it puts the decision about *when a question may be
delivered* in the party that does not know the answer.

## Alternatives considered

**Have the Vue app read a pending question on mount.**  Rejected: it works,
and it is the wrong shape.  The app would have to ask, the launcher would
have to expose a getter, and the timing decision would live in the party
with the least information.  The launcher already has the hook — `mount()`
runs from `script.onload` — so the queue belongs there.

**Dispatch the event later, with a longer timeout.**  Rejected: it is a
race replaced by a guess.  A slow connection, a cold cache or a busy main
thread would still lose the question, and there would be no test that could
tell the difference between a long enough timeout and a lucky one.

**Make `ask` wait for the bundle before opening the panel.**  Rejected: the
reader would click and see nothing happen for as long as the fetch takes.
Opening first and filling in after is the right order; only the delivery
was wrong.

**Have the error button write the question into the composer directly.**
Rejected: the button is a separate bundle with no access to the Vue app's
state, and reaching into it would couple two entry points that are
deliberately independent.  The `albanna:ask` event is the seam, and it was
the seam that was being used too early.

**Queue in `sessionStorage` so a reload keeps the question.**  Rejected: a
question the reader asked and then reloaded is a question they can see in
the dialog they came from.  The queue only needs to outlive a bundle fetch.

## Consequences

* The first "Ask Albanna about this error" click after a page load now
  delivers the pre-filled question, which is the click that matters.
* Subsequent clicks are unchanged in behaviour and slightly cheaper — they
  flush immediately rather than waiting a macrotask.
* The launcher grew three lines of state (`mounted`, `pendingAsk`,
  `flushPendingAsk`) and one call site in each of the two load paths.
* The form button is unaffected: it calls `open()`, which carries no
  question, so it never had the race.
* The general lesson is recorded here rather than in a comment, because it
  applies to any future entry point that asks the panel to do something
  before the panel exists: the launcher is the gate, and it is also the
  queue.

## See also

* [ADR-0014](0014-a-reader-who-may-not-chat-gets-no-widget.md) — the gate
  the error button waits for, and why a button that opens nothing is worse
  than no button.
* [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md) — why
  the launcher is a browser bundle, and what that costs.
* `albanna/public/js/albanna-error-button.bundle.js` — the entry point that
  found the race, and the three facts about Frappe's dialogs that decided
  how it is written.
