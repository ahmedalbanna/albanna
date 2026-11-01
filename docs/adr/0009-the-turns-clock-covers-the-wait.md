# ADR-0009: The turn's clock covers the wait

Status: **Accepted**
Date: 2026-10-30

## Context

A turn has two phases with two clocks, and one of them was missing.

The labour — model rounds and tool calls — has a budget:
`turn_timeout`, in minutes, on the settings document.  The *wait* —
a write that needs the reader's approval, where the worker sits asleep
inside `await_decision` until the reader answers — has a budget too:
`confirm_timeout`.  Both are the operator's to set, both are real time
spent by the turn.

The background job, however, was given `turn_timeout` alone.  RQ kills
a job by the enqueue timeout, and the wait is spent from the same
budget as the labour.  A heavy turn (ten rounds, fifty-two tool calls,
318 seconds) reached its approval card with under two minutes of its
budget left — and a reader who spent a normal sixty seconds thinking
before pressing Approve got the job killed under them:
`JobTimeoutException`, raised inside `await_decision`.  The reader was
told the worker "did not complete the turn" while it sat waiting for
exactly the click they were about to make.

The same wrong number was also the reaper's window, and the marker's
TTL, and the ledger's "unfinished turn" cutoff — each derived from
`turn_timeout` alone.  Raising `turn_timeout` to cover the wait would
have fixed the crash and quietly broken the others: the marker would
outlive the job's clock by a factor, and the reaper would call live
turns dead.

## Decision

**One number, derived once: the job's budget is the labour plus the
wait plus the queue's slack.**

`albanna.services.settings_service.job_budget_seconds(settings)` is
that number:

```
job budget = turn_timeout + confirm_timeout + TURN_SLACK_SECONDS
```

`turn_timeout` keeps its meaning — the budget of the turn's *labour* —
and no longer pretends to be the whole turn.  Everything that needs to
outlive the *whole* turn reads the sum through that one function:

| Reader | What it was | What it is now |
|---|---|---|
| the enqueue's `timeout` | `turn_timeout` | the sum — the job is never killed inside the wait |
| the marker's TTL | `turn_timeout + grace` | the sum + grace |
| `_turn_deadline()` (when a turn is lost) | `turn_timeout + grace` | the sum + grace |
| `audit_rows.unfinished_facts`' cutoff | `turn_timeout + slack` | the sum + slack |
| the reaper's cutoff | a fixed 15 minutes | the sum + the same 15-minute margin |

The margin is not part of the turn; it is the time the truth takes to
be noticed.

### Why not just raise `turn_timeout`

Because it already means something.  It is the labour's budget, and the
tests and the reaper's reason both read it as such.  Folding the wait
into it would make one number two things, and the reaper's cutoff —
the ledger's promise about what it calls dead — would silently grow
with a setting whose purpose is unrelated.  A sum named once is a
number that cannot be right in one place and wrong in another.

### Why the slack is the queue's

Two things happen around the work that are not the work: the job is
picked up by a worker, and the finished answer is parked for the
polling fallback.  Both are fast, and both must not be able to turn a
completed turn into a lost one.  Sixty seconds.

## Consequences

* The queue no longer kills a worker that is waiting for the reader.
  The reader's thinking time is a budget of its own, and it is
  allocated explicitly.
* All five clocks derive from one function, so a change to either
  setting is a change to all of them at once — the contradiction that
  produced both the crash and the reaper's mislabels is gone.
* The reaper's margin stays fifteen minutes, and
  `tests/test_scheduler.py`'s cadence tie still holds trivially: the
  window is now much longer than the cron gap.
* A reader who takes a long time is still asked *something*: after
  `confirm_timeout`, the worker proceeds and the model is told the
  write was not approved.  The budget buys the reader time; it does not
  make time infinite.

## See also

* [ADR-0010](0010-the-card-the-socket-lost.md) — the other half of the
  wait: the card must reach a reader whose socket did not.
* [ADR-0006](0006-stopping-a-turn.md) — the client can stop waiting;
  this is the server's side of how long waiting may take.
