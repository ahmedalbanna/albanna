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

The parked answer *is* the reconnect path.  **Measured** with a turn run
over HTTP alone — no socket.io subscription ever opened — on
`test.localhost`: the answer arrived through `status` polling alone in
**5.9 s**, status `ok`, no re-submission.  The poll is the delivery
guarantee and the socket the fast path (ADR-0101 S6 measured the poll's
cost); a reconnecting client resubscribes and, until events arrive,
polls, and the parked marker hands back the finished answer (or the
running state) with nothing enqueued again — `ask_stream` is called once
per question.

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

## R4 — the fallback is the chain, and the chain was walked

`LLMConfig.chain()` (albanna/providers/base.py) returns
`[primary, fallback]` filtered to usable configs, and `_complete`
(albanna/services/chat_service.py) walks it in order, retrying transient
failures once per provider and collecting each failure's sentence into
`AllProvidersFailed` — the reader's error names every provider tried.

**Measured** with a local mock provider speaking the OpenAI protocol's
server-sent events as the fallback, the primary pointed at a loopback
port nothing listens on (`albanna/tests/test_fallback.py`, site suite):

- the dead primary is tried, retried once (its failure is transient),
  the fallback is then tried and answers: the turn completes against
  the fallback in **2.0 s** wall, including the 2 s backoff between the
  primary's attempts, and the completion's provider and model are the
  fallback's — the reader's answer is not marked with the failure;
- both providers dead, the error carries **both** labels, so the
  operator reading the ledger sees the whole chain's verdict;
- a working primary is answered by the primary, and the mock counts
  **one** request: the fallback is not contacted for company.

**Pinned by** those three cases in the site suite.

## R5 — a turn that fails mid-execution leaves the thread whole

The mechanism is the append discipline: the question and answer rows are
written *together*, at the end, only after a completion is in hand — so a
turn that dies mid-execution cannot leave a half-written answer behind
it, and the failed turn's question is not inserted half-done either.
What the turn does leave is its ledger row, started before the turn
could die and updated in place: the row records the tool calls that ran
before the failure, the failure class, and the provider's own detail —
while the reader's sentence stays words (`tests/test_errors.py`).

**Measured** with a mock that answers round one with a tool call (the
tool runs), then fails round two with a transient HTTP 500 the chain
retries once and gives up on (`albanna/tests/test_partial_turn.py`, site
suite):

- the thread's transcript is **exactly** what it was before the turn —
  the earlier pairs intact, nothing of the failed turn appended;
- the ledger row says `status=error`, `tool_calls=1` (the call that ran
  before the failure), and carries the provider's detail
  ("collapsed in round two") that the reader's panel never showed.

**Pinned by** that case in the site suite.

## R8 — the row says ok only after the answer exists

The write order is the atomicity claim, and it is worth stating exactly,
because the order is deliberate and split across three writes:

1. the turn's completion is in hand (the stream ended, the answer text
   exists);
2. `_log` updates the row to `ok` and commits — its own commit, on
   purpose: the audit row must survive even if what follows does not;
3. the job parks the answer in the cache (`_park`), emits `done`, and
   commits the job's own transaction.

So a turn recorded `ok` always had an answer in hand when the row was
written.  The residual window is between steps 2 and 3 — a process
killed after the row's commit but before the cache write leaves the row
`ok` and the marker running; the marker expires at the turn's budget,
the poll says lost, and `_lost_turn`'s ledger read finds no unfinished
row to name writes from.  That window is a single cache write wide and
takes a crash inside it; the normal path delivers the answer over the
socket or the poll within the same second.  The reverse hole — an answer
parked with no row — cannot happen: the row is written first, and a row
that stays `running` is what the reaper and `_lost_turn` exist for.

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
- A row saying `ok` with no completion in hand, or a thread carrying a
  half-written answer: the append-at-the-end discipline was broken.
