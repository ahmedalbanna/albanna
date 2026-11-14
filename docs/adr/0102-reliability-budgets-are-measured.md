# ADR-0102: The chat's reliability budgets are measured

Date: 2026-11-14 · Status: accepted · Companion to ADR-0100 (performance)
and ADR-0101 (scalability); answers the NFR-R1–R8 questions raised against
the chat without a measurement behind them.

## The requirement, and what "measured" means here

Eight reliability budgets were named for the chat:

- **R1** — a worker dying mid-turn is announced to the client within 10 s.
- **R2** — a dropped socket costs nothing: the answer is recovered from the
  cache on reconnect, without re-submitting.
- **R3** — an unreachable provider returns a clear error within the
  configured timeout, never hangs.
- **R4** — a configured fallback is attempted before an error is returned.
- **R5** — a turn that fails mid-execution does not lose conversation data.
- **R6** — provider rate limits (HTTP 429) surface a clear message.
- **R7** — provider auth failures (HTTP 401/403) surface a clear message
  directing the admin to the settings.
- **R8** — ledger writes are atomic: a turn is never recorded successful
  when its answer was not delivered.

Where the evidence is a pinned test rather than a stopwatch, the test is
named; where it is a live failure, the measurement is the time.  All live
measurement ran on `test.localhost` on this host.

## R1 — the dead worker is announced in 3 s (budget: 10 s)

**Before.**  Nothing announced a worker's death.  The client's poll called
a turn lost only when the marker outlived the *whole job budget* plus a
90 s grace (`STALE_GRACE_SECONDS`, `albanna/api/chat.py`), and the job
budget is the work plus the reader's wait (`job_budget_seconds`) — a
half-hour ceiling for a turn that died in its first second.  The reaper
(`albanna/tasks.py`, cron `*/5`) closes the *ledger row*, not the reader's
wait, and runs minutes, not seconds.

**The fix.**  The turn's job beats a Redis key (`albanna:turn:hb:<stream>`,
TTL 3 s) every second while it lives, and `status()` declares a *flagged*
running turn with a gone beat lost.  The flag is written by the job, after
its first beat and before the turn starts — a turn still in the queue
carries no flag and is judged by the old age rule, so a queued turn cannot
be declared lost for not having started, and a marker parked by a worker
that predates the heartbeat (a turn in flight across a deploy) is not
declared lost the moment it is seen either.  The flag order is the race
closure: a flagged marker always has a beat underneath it.

The beat thread needed one care the obvious implementation gets wrong:
`frappe.conf` is an unbound proxy inside a bare thread, so `set_value`
raises `RuntimeError: object is not bound` on its first tick.  The
prefixed key and the pickled value are built in the job's main thread;
the thread speaks raw redis through the client's own connection pool
(`albanna/services/chat_job.py::_start_heartbeat`).  The first live run
caught exactly this — the beat expired 3 s in, a poll at 4.3 s mislabelled
a turn that finished `Job OK` in the same second, and the worker log
showed the exception class without a site to raise it in.

**Measured.**  The turn's own process — RQ forks a child per job, so the
supervisor's worker pid is *not* the runner; the first kill attempt hit
the parent and the turn ran on correctly, which is itself the detection
design working — was SIGKILLed mid-turn on `test.localhost`:

- the poll that says lost landed **3.0 s** after the kill (harness polls
  at 300 ms; the beat's TTL plus the one-second interval bound the server
  side at ≤ 4 s);
- the panel's own cadence adds at most one poll gap: the while-alive gap
  is **6 s** (`STATUS_POLL_MS_WHILE_ALIVE`, was 12 s — a twelve-second
  wait could spend the whole budget on its own), and the quiet-socket
  ramp re-checks within 1.5 s.  Worst case ≈ 9 s, inside the 10 s
  promise.

The killed worker's supervisor slot respawned in 13 s; the ledger row of
a killed turn stays `running` until the reaper marks it `interrupted`
(≤ 5 min + the 15-minute margin), which is the ledger's job, not the
reader's.

**Pinned by** `albanna/tests/test_turn_clocks.py::TestTheHeartbeat` —
gone beat → lost; live beat → running; unflagged marker → age rule; the
job beats before it flags.  The client cadence is pinned by
`albanna/public/js/side-chat/turn.test.mjs`.

## R2 — the socket never carries the only copy

The parked answer *is* the reconnect path.  A turn run over HTTP alone —
no socket.io subscription ever opened — delivered its answer through
`status` polling alone; the poll is the delivery guarantee and the socket
the fast path (`docs/adr/0101` S6 measured the poll's cost).  A
reconnecting client resubscribes and, until events arrive, polls; the
parked marker hands back the finished answer (or the running state) with
no re-submission — `ask_stream` is called once per question, and nothing
in the reconnect path enqueues again.

**Pinned by** the same marker tests as R1 (the poll answers from the
cache), plus the turn-await cases in `turn-await.test.mjs` (the card that
arrives through the poll, once, and is not re-forwarded per poll).

## R3, R6, R7 — provider failures say what happened, in words

The provider layer maps every HTTP status into typed errors whose reader
sentences are pinned:

- **R3** — a provider that does not answer becomes `ProviderTimeout`
  inside the turn's own deadline; the timeout is the configured
  `turn_timeout` (default 600 s), and the panel's deadline is the same
  number, told to both sides (see `tests/test_clocks.py` and
  `albanna/tests/test_turn_clocks.py`).  The pinned sentence:
  "The model did not answer in time. Try again, or ask a narrower
  question." — internals never shown (`tests/test_errors.py`).
- **R6** — 429 lands in `TRANSIENT_STATUSES` (the retry-then-chain
  policy) and its sentence tells the reader to try again
  (`tests/test_providers.py::test_a_rate_limit_is_transient_and_a_refused_key_is_not`).
- **R7** — 401/403 are *not* transient; the reader is told the key was
  refused and the admin where to look
  (`tests/test_errors.py::test_a_refused_key_...`,
  `test_an_operators_error_is_not_the_readers_words`), and the app's
  internals never reach the panel.

## R4 — the fallback is the chain, not a wish

`LLMConfig.chain()` (albanna/providers/base.py) returns
`[primary, fallback]` filtered to usable configs, and `_complete`
(albanna/services/chat_service.py) walks it in order, retrying transient
failures once per provider and collecting each failure's sentence into
`AllProvidersFailed` — the reader's error names every provider tried.
**Harness pending:** a local mock provider speaking the OpenAI protocol
as fallback with the primary pointed at a dead port (Stage R-c of the
plan).  The chain's order and the failure aggregation are pinned by the
unit tests around `_complete` (`tests/test_stream_restart.py` exercises
the same walk); the live cross-provider measurement is what remains.

## R5 — a failed turn leaves the thread's words alone

The turn writes its answer only at the end: `_park` replaces the marker
once, and the message rows are written by `ChatService.run` after the
completion is in hand.  A turn that dies mid-execution — worker killed,
provider error, timeout — leaves the thread's earlier question/answer
pairs untouched (deletion happens only for a regenerate, and only inside
the job, before the turn runs, committed first so the model never rereads
replaced words).  The ledger row records what happened: started as
`running` before the turn can die, updated in place — a ghost row is
truth, not a leak (ADR-0101 S4 covers the row's reads).  The mid-failure
harness (force a tool failure between two rounds, verify the thread) is
Stage R-c of the plan.

## R8 — the answer is parked before the row says ok

The write order is the atomicity claim: within the job's single
transaction, the turn parks its answer in the cache (`_park`), emits
`done`, commits — and only then does the endpoint's next request read the
parked answer.  The ledger row's final `ok` is written inside the same
transaction that parks (`ChatService.run` → `_log` → the job's
`frappe.db.commit()`); a crash between park and commit leaves the row
`running` and the reaper will not call it successful.  A turn recorded
`ok` therefore always had an answer to park.  The reverse — an answer
parked with no row — is the lost-turn row's business, and `_lost_turn`
names the writes the row recorded (R1's reader sentence).

The one deliberate exception, documented in the code, is a tool's own
write: approved writes commit mid-turn so they survive a later turn
failure, and the row's payload records them — which is exactly what
`_lost_turn` reports to the reader.

## What would falsify this ADR

- A kill measurement over 10 s: the beat TTL/interval drifted, or the
  panel's while-alive gap was raised past 6 s without re-doing this
  arithmetic.
- A turn declared lost while its worker lived: the flag/beat race was
  reopened, or a proxy between the app and Redis is expiring keys early.
- A poll returning `running` for a turn whose runner is dead longer than
  4 s server-side: the `expires=True` read of the beat was dropped, and
  a process-local mirror is answering.
- A 429/401 sentence quoting an exception class or a status code: the
  reader-message map was bypassed.
- A row saying `ok` with no parked answer: the park/commit order was
  inverted.
