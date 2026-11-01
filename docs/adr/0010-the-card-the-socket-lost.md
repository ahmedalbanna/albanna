# ADR-0010: The card the socket lost

Status: **Accepted**
Date: 2026-10-30

## Context

The approval card — *shall this change happen?* — is published over
socket.io, once, at the moment the worker asks.  It is the only way a
write on the rail can be approved.  And the socket is not a guarantee:
a reload, a sleeping laptop, a mobile network handing over, or the
reader's own browser cache going away takes the event with it.  The
worker, meanwhile, is holding its slot asleep inside the wait.

The reported failure had that exact shape, twice over:

* The reader pressed Approve on a card and was told the worker had died
  while it sat waiting for the press — the clock ([ADR-0009](0009-the-turns-clock-covers-the-wait.md)).
* The reader saw **no card at all** — a working turn, no way to answer
  it, and the worker's wait running out on a decision that was never
  offered.

The polling fallback existed for the *answer*, and said nothing about
the wait: `status` answered `running`, which told the reader nothing
they could act on.

Two further faults turned "the card is lost" into "the turn never
finished", both of them in `frappe.cache`:

1. **The process-local mirror.**  `frappe.cache().get_value` answers
   from `frappe.local.cache` — the process's own copy — before it touches
   Redis, and any read without `expires=True` fills that copy.  The
   job's first read filled it with the `running` marker; the job's last
   event read the stale copy, concluded the turn still running, cleared
   the card, and wrote `running` **over the answer the job had parked a
   moment earlier**.
2. **The user namespace.**  Keys written with `user=` live under
   `<db>|user:<user>:` — the prefix `clear_user_cache(user)` empties
   outright, on a login, a logout, a User save, a role change, or the
   **Cache Cleared** button the reader pressed while watching the stuck
   turn.  Marker and pending record both lived there; each death was a
   different lie (the turn "did not finish"; the confirmed change "did
   not run"), and both were told about a turn that had actually
   completed and written its documents.

## Decision

**The card is parked, in the site's namespace, and the poll may carry
it.**

* The `confirm` event is mirrored into the turn's marker as it is
  asked; any later event clears it (the decision was taken, the turn
  moved on).  `status` answers `awaiting_approval` with the card, and
  the client feeds it to the same handler the socket's event uses —
  once per request id, so a slow poll cadence cannot redraw the card
  and restart its clock.
* The card carries the server's own `at` — the moment the wait opened,
  in epoch milliseconds.  A card drawn late counts down the time that
  remains; it does not hand the reader a fresh window the worker no
  longer holds.
* The turn's state (marker, pending record) lives in the **site's**
  namespace: `<db>|albanna:turn:…`.  The stream id and the pending id
  are 128-bit random hexes; the markers are no more reachable than the
  browser that owns them, and they survive the framework's housekeeping.
* *Who may answer* is a **field in the pending record**, not a prefix
  of its key.  The binding survives a cache clear, and one reader still
  cannot approve another reader's write — that isolation no longer
  depends on a namespace the framework empties at inconvenient moments.

### Why mirror into the marker rather than a second endpoint

The poll already reads one key and already handles "running" versus
"finished".  Adding a second source of truth for the card is a second
thing to get out of sync, at exactly the moment the reader is
concentrating on a decision.  The marker *is* the turn's state; the
card is state of the turn.

### Why not keep the user namespace and patch around the wipe

Because the wipe is not one path, it is a class of them — every event
that invalidates a user's cache, present and future.  A key that must
outlive the turn cannot live in a namespace the framework empties for
housekeeping reasons of its own.  Moving the key is the fix; the
identity field keeps what the namespace was accidentally providing.

## Consequences

* A reader whose socket drops — or whose browser cache goes away —
  still sees the card and can still answer it.  The wait no longer
  depends on one event arriving once.
* A finished turn is never written over by its own stale copy: the
  mirror is dropped and the cache is read fresh, and the last event of
  a successful job leaves the parked answer in place.
* `frappe.sessions.clear` — the reader's own **Cache Cleared** press —
  no longer destroys a turn in flight.  (It was the observed trigger:
  the reader, watching a stuck turn, pressed it.)
* `tests/test_turn_clocks.py` holds all three properties: the card
  survives the socket, the stale copy, and the framework's wipe.

## See also

* [ADR-0009](0009-the-turns-clock-covers-the-wait.md) — how long the
  wait may take.
* [ADR-0006](0006-stopping-a-turn.md) — the same shape on the client:
  a turn is delivered, or the user is told it was lost.
