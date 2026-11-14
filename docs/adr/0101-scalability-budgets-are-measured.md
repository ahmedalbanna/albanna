# ADR-0101: The chat's scalability budgets are measured

Date: 2026-11-14 · Status: accepted · Supersedes the NFR-S1–S6 questions
raised against the chat without a measurement behind them.

## The requirement, and what "measured" means here

Six scalability budgets were named for the chat:

- **S1** — at least 50 concurrent chat sessions per site, without degradation.
- **S2** — at least 100 turns per minute per site, across all users.
- **S3** — the background worker queue handles at least 20 concurrent turn
  jobs without queue buildup.
- **S4** — the ledger and audit trail handle at least 1 million records per
  site without query degradation.
- **S5** — no vertical scaling (more RAM/CPU) needed for sites up to 100
  active users.
- **S6** — Redis holds session state and parked answers; the database is not
  polled for turn status.

In this app the audit trail and the ledger are one table: the
`Albanna Chat Log` row carries the turn's tool calls and approvals payload
(`albanna/services/audit_rows.py`), so S4 is one table measured.

Every number below was measured on `test.localhost` on this host, the same
site the acceptance harness runs against.  Where the harness differs from
production the difference is named, because a measurement whose
unrepresentativeness is hidden is worse than no measurement.

## S6 — the poll never reads the ledger (and costs one query, not five)

The turn-status read was already cache-only by design: the running marker and
the parked answer live under `TURN_CACHE_KEY` in the cache Redis
(`albanna/api/chat.py`), and the ledger is read only on the *lost turn* path,
once, when the turn is declared gone — that read is the point of the ledger.
What the measurement added is the cost of a poll:

- **Before:** a poll of a running turn executed **5 SQL statements and took
  60–130 ms** in-process.  One was the auth gate's policy read; four built the
  whole settings document — the controller import, the singles read, and the
  provider API key *decrypted* — to reach the two integers the marker's
  deadline is made of (`_turn_deadline` → `get_settings`).  The settings are
  memoised per request, but a poll is its own request, so the memo never
  carried over and every poll of every session decrypted the key again.
- **After** (`get_budgets` reads the two fields from the cached document):
  a steady-state poll is **1 SQL statement** (the auth gate's own) and
  **~3 ms** in-process.  The document cache warms on the first poll in a
  worker process (3 reads) and is invalidated when the settings are saved.

The database is not polled for turn status; the one statement a poll issues
is the access gate, which is not the turn.

## S3 — one worker serialised every concurrent turn

The chat worker runs RQ's standard `Worker`: **one job at a time per worker
process**.  Supervisor was running it with `numprocs=1`, so every concurrent
turn queued behind the turn in hand.  Measured with twenty sleeper jobs
(2 s each) enqueued on the `chat` queue of `test.localhost`:

- **Before:** `max_active=1`, all twenty jobs executed strictly serially,
  wall time 45.9 s against a 40 s serial bound.
- **After** (`numprocs=4` in `/etc/supervisor/conf.d/frappe-bench.conf`):
  `max_active=4`, wall time 10.5 s — twenty concurrent turn jobs are four
  waves instead of twenty, no job lost, no timeout.

The worker's idle cost is small (~9 MB per parent process; each job is a
fork), so the fix is horizontal scaling — more processes, not a bigger
machine — which is what S5 asks for.

## S2 — 100 turns/min is worker arithmetic

Sustained turns/min = **worker count × (60 ÷ median turn latency)**.  The
ledger's own `duration_ms` gives the latency distribution of real turns
(14 completed turns on `test.localhost`, provider MiniMax via the configured
endpoint): min 115 ms, p50 ≈ 3.2 s, p90 ≈ 95 s, max ≈ 153 s.  Simple one-round
turns cluster under 700 ms; tool-heavy turns run tens of seconds.

At the four workers S3 installed: ≈ **76 turns/min at the median turn**,
a few per minute if traffic is dominated by tool-heavy turns.  The enqueue
side is not the bottleneck: ~2–4 ms per turn enqueued in-process, parallel
across gunicorn workers (S3 measured 20 enqueues in 36–82 ms).

Scaling is linear in `numprocs` (measured 1→4 = 4.4× throughput on identical
jobs), so clearing 100 turns/min at the measured median needs ≈ 6 chat
workers; at the *tail* latency no realistic worker count carries 100
tool-heavy turns per minute.  The site's own rate limit
(`Albanna Settings.turns_per_minute`, default 6/min/user) means 100
turns/min across a site needs ≥ 17 users asking in every minute — the
budget is an aggregate ceiling, not one user's.

## S1 — fifty concurrent sessions

Method: a temporary gunicorn on this bench (`frappe.app:application`,
cwd = `sites/`, `-w 4`, every request pinned to `test.localhost` with the
`X-Frappe-Site-Name` header) — the same WSGI app production serves with,
nine workers to the harness's four, so the harness is the *conservative*
configuration.  A first attempt with `bench serve` was discarded: the dev
server serialised logins to 34 s each, which measures werkzeug, not the app.
Sessions drive the HTTP layer a real session drives: login, desk page load,
status polls.

- **Burst** — 50 sessions started at once, each: login + 5×(page load +
  poll).  **350/350 requests succeeded, 0 failures**: login p50 4.1 s /
  p95 7.8 s (fifty bcrypt checks at once on four workers), page p50 1.3 s /
  p95 8.9 s, poll p50 1.1 s / p95 2.2 s.
- **Steady state** — 50 established sessions polling, 500 status polls over
  14 s: **0 failures**, poll p50 **205 ms**, p95 1.8 s, max 3.5 s.  The
  steady-state number is the S6 fix at work: each poll is one gate query
  plus a Redis read.

The realtime path is measured separately (ADR-0100: emit 0.8–5.3 ms,
publish→browser 1.5–7.1 ms).  Not covered here: socket.io connection storms,
which need a dedicated socket harness.

## S4 — a million ledger rows

Method: 1,000,000 synthetic `Albanna Chat Log` rows on `test.localhost`
(batched inserts, 52 s to seed), `creation` spread over twelve months so the
month-bounded reads see a realistic slice (~85 k rows/month).  The host's
MariaDB runs a 128 MB buffer pool, so a table this size is disk-bound — the
numbers below are honest for this host and conservative for a tuned one.

- **Before (18 rows → 1M rows, no index beyond name/creation/conversation):**
  the app's hot ledger read — the unfinished-turn read every ask and every
  refresh fallback makes (`unfinished_turn`, filters by user, status, and a
  30-day window) — went from 1.7 ms to **10.1 s per ask**.  At a million rows
  the ledger made every question wait ten seconds.
- **The `user` index alone is not enough:** a user *with* a million rows
  still scanned all of them for a running turn (10.7 s).  The composite
  **`(user, status, creation)`** reads the same query in **0.9 ms** — the
  index answers user, status, and window, and the order-by is served inside
  the user's own slice.
- **The usage dialog was the second finding:** it read every row of the
  month into Python (22.7 s at a million rows in one month, 6.8 s at the
  realistic 85 k slice).  It now aggregates **in SQL**
  (`usage_summary` groups by provider, model, user, status — 11 grouped rows
  instead of 85 k rows), returning the same shape; its cost tracks the
  month's aggregation volume, not the ledger's total size.

Shipped: the composite index joins `add_lookup_indexes` (the patch is
idempotent; `bench migrate` adds it to every site), and the usage dialog
reads groups, not rows.  The per-thread totals query was already served by
the `conversation` index (4 ms at a million rows, measured — the NFR-P1
work's index holding).  `count(*)` over the whole table remains a scan
(~1.5 s here); nothing per-request reads it.

## S5 — no vertical scaling for 100 active users

Synthesis of the measurements, not a new harness:

- The two scaling levers this batch moved are **process counts, not machine
  size**: four chat workers instead of one (S3), gunicorn's existing nine
  web workers (production).  An idle chat worker parent is ~9 MB; the cost
  is peak memory while turns run, in forked children that die with the job.
- The host runs this bench's full stack — gunicorn `-w 9`, the database,
  Redis, socket.io, the MCP stacks — in **7.8 GB with ~1.7–2.4 GB free**.
  Fifty concurrent sessions passed on *four* web workers; production runs
  nine.  A site with 100 active users adds worker pressure linearly and is
  absorbed by `numprocs`, not by a bigger host.
- The remaining hard ceilings are the *provider's* turn latency (S2's tail)
  and MariaDB's buffer pool, which is an explicit tuning decision on this
  host (128 MB today).  Neither is met by more RAM on this box alone; both
  are named here so the next scaling decision starts from arithmetic, not
  guesswork.

## What would falsify this ADR

- A ledger read that grows with table size despite the composite index —
  the `EXPLAIN` in the S4 harness run must show the index in use.
- A poll that issues more than the gate's one query — the poll probe
  (query counter around `albanna.api.chat.status`) is the check.
- Chat-worker concurrency lower than `numprocs` under load — the sleeper
  harness reads it off the queue directly.
