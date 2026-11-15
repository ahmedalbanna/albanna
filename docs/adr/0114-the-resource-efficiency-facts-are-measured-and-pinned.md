# ADR-0114: The resource efficiency facts are measured and pinned

Date: 2026-11-15 · Status: accepted · The twelfth NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107), M- (ADR-0108),
C- (ADR-0109), I- (ADR-0110), D- (ADR-0111), O- (ADR-0112) and
DI-series (ADR-0113); answers the NFR-RE1–RE5 questions raised against
the app's footprint — memory, connections, cache span, the history
bound, and how turn status is asked for.

## What the reading found

Three of the five held outright.  One was exposed with a number, and
one was bounded but nobody's choice.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| RE1 | memory overhead ≤ 10% of the frappe baseline per worker | **exposed, fixed, measured** | measured in a fresh interpreter: frappe import baseline 42,100 kB; + every app module the turn path pulls 51,596 kB — **22.6%**, over the budget.  The entire 9.5 MB was `requests` and its tree (93 request modules, 43 chardet modules with their CJK codec tables, urllib3, idna — 8,336 kB for `requests` alone), dragged in by `albanna/providers/__init__.py`, which imported all three adapter modules eagerly.  Because `settings_service` imports `providers.base`, *every* worker paid for the adapters' HTTP stack at boot, whether it ever spoke to a provider or not — and `build_provider`'s own lazy scan (a pkgutil walk at call time) was being defeated by the package `__init__`.  Fixed with a PEP 562 lazy `__init__`: the base names re-export at import time, the concrete adapter classes resolve on first attribute use, `__all__` unchanged.  **After the fix: 1,592 kB — 3.8% of the baseline, and `requests` no longer loads at boot.**  The HTTP stack now loads with the first turn.  The residual is recorded below |
| RE2 | ≤ 5 database connections per worker | **holds** | the app opens no connections of its own — no pymysql, no connector, no engine, no `frappe.db.get_connection` anywhere; every read is the request-scoped `frappe.db` (one connection per worker per request, the framework's pool) and every cache touchpoint (19 of them) goes through the framework's pooled `frappe.cache()`.  The rate-limit counters are Redis keys with TTLs, not connections.  Module-level state is one bounded registry (`_KIND_REGISTRY`) and per-request `frappe.local` caches — nothing that grows with use |
| RE3 | parked answers expire after 1 hour, configurable | **partial, fixed** | the entries were never unbounded — every marker write carried `expires_in_sec = job_budget_seconds(settings) + 90` (600 s work + 120 s wait + 60 s slack + 90 s grace ≈ 14.5 min by default).  But the span was derived arithmetic, not an operator choice, and a longer wait budget silently lengthened it.  Now: a `turn_cache_ttl_seconds` Int setting, **default 3600**, floored at the turn's own clock plus the grace — a marker that dies under a live turn has `status` declare the turn lost while its worker is still working, so the floor is load-bearing, not cosmetic.  The lost-turn *deadline* (when a running turn is declared lost) stays on the turn's clock, which is a different number and must stay one |
| RE4 | history bounded by the configured limit, default 50 | **holds** | one field (`history_limit`, default 50), and both consumers read the setting: the turn's history read passes `settings.history_limit` into `load_messages`, whose SQL is bounded in the *database* (`limit %s`, with the tail-slice afterwards), and the prompt window reads the same setting.  A conversation with four hundred messages never sends four hundred |
| RE5 | turn status: socket.io + cache, no DB polling | **holds** | delivery is a `frappe.publish_realtime` event from the job; the browser polls `albanna.api.chat.status` only as the fallback, on a growing interval (1.5 s → 9 s; 6 s while the turn's heart beats).  The *running* path reads only the cache — the marker and the heartbeat, both with `expires=True` so no stale process-local mirror answers — and the approval card is mirrored into the marker, so even that asks no database while the turn runs.  The one DB read (`unfinished_facts`, the audit row's writes) happens once, at the terminal lost verdict — an answer, not a poll.  The reaper's five-minute DB sweep is the reaper, not a poll, and is documented as such |

## The decision worth keeping

**The HTTP stack is the turn's, and it loads with the turn.**  The
lazy `__init__` cut boot overhead from 22.6% to 3.8%, but a chat
worker that serves a turn still ends up carrying `requests` — some
8 MB — once the first provider call has been made.  Replacing
`requests` with the stdlib would drop the megabytes and cost the
keep-alive pooling `providers/http.py` exists to provide (a turn
speaks to the provider once per tool round; pooling is one TLS
handshake for the whole turn instead of one per round) — a bad trade,
and it was rejected.  The honest numbers:

*   against the *fresh frappe-import* baseline (42.1 MB), the turn
    working set is +9.5 MB ≈ 22.6% — the worst case, a worker that
    serves nothing but a turn;
*   against a *real* worker's baseline — the live gunicorn workers
    measure 73–101 MB with erpnext and the other apps loaded — the
    same megabytes are ~10–13%, and erpnext's own controllers load
    `requests` on their first request anyway (verified by import), so
    in a worker that serves the desk the app's marginal cost is its
    own modules only, the 3.8%.

The boot figure is the one the requirement's words measure ("Frappe's
baseline"), it is now inside the budget, and the turn-time figure is
recorded rather than hidden.

## What is pinned

`tests/test_resource_pins.py`, ten walkers plus one subprocess check;
three red-checked live (an eager adapter import re-added to the
package `__init__` → both the walker and the subprocess check FAILED;
the TTL floor removed → FAILED; a DB read added to the status running
path → FAILED; each reverted from a saved copy):

- RE1: the providers package imports nothing but `base` at module
  level, `__getattr__` resolves the concrete classes, and a fresh
  interpreter that imports frappe, `providers.base`,
  `settings_service` and `chat_service` ends with no `requests` in
  `sys.modules` — held behaviourally, not only by shape.
- RE2: no own database client anywhere in the package.
- RE3: the TTL is a setting (default "3600", in `field_order`), every
  marker write is named to the TTL function, the configured value
  never dips below `max(configured, budget+grace)`, and the
  lost-turn deadline is still the turn's clock.
- RE4: the 50 default, both consumers reading the setting, and the
  history query bounded in the database.
- RE5: the `status` function's body contains no database access, and
  the realtime publish plus the cache-backed poll endpoint are both
  present.
