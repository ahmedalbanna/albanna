# ADR-0100: The streaming panel's budgets are measured, not assumed

Status: **Accepted**
Date: 2026-11-12

## Context

The panel's non-functional requirements (NFR-P2 through P9) name budgets
— a token in the browser within 3 s of the provider receiving the
request, a render within 100 ms of receipt, reads within 2 s, writes
within 3 s, the conversation list within 1 s at 500 threads, search
within 1 s at 10,000, no measurable Desk page-load degradation, and a
50 MB heap ceiling at 100 messages. A budget that is never measured is
a hope, and a hope fails on the one day it is needed.

Every number below was measured on test.localhost on 2026-11-12, after
ADR-0099's change was in. The harnesses live in `/tmp/opencode/`
(`nfr_p2.mjs` … `nfr_p9.mjs`, plus `nfr_p9_seed.py`); they are
measurement scripts in the same shape as `scripts/ui_smoke.mjs` — a
throwaway `bench serve`, a headless chromium, and probes that read the
same paths the app runs.

## The numbers

| Budget | Measured | Verdict |
|---|---|---|
| P2: provider-yields → browser has the token (app overhead only) | worker emit (mirror + publish) 0.8–5.3 ms per token; publish → browser receipt 1.5–7.1 ms (first delivery 183 ms) | sum ≤ ~12 ms, against 3 s |
| P3: socket receipt → DOM carries the token | min 7.9 / p50 46.8 / p95 89.3 / max 89.3 ms over 20 tokens | under 100 ms |
| P4: read tool ≤ 2 s (up to 100 docs) | cold first call 352 ms; warm `list_docs` 1.1–15.3 ms; warm `get_doc` full shape 33–43 ms | far under |
| P5: single-document write ≤ 3 s | create cold 410 ms, warm 27–39 ms; update 31–126 ms; delete 366–648 ms; submit 446 ms; cancel 1457 ms | worst case 1.5 s |
| P6: conversation list ≤ 1 s at 500 | cold 69 ms; warm 17–72 ms (page 1, page 4, limit 500) | far under |
| P7: search ≤ 1 s at 10,000 | cold 200 ms; warm 42–113 ms (common, unique, prefix, no-match, Arabic terms) | far under |
| P8: no measurable Desk page-load cost | interleaved A/B, 6 runs each: load median 2230 vs 2175 ms, DCL 1677 vs 1568 ms — deltas within run-to-run noise (±300 ms); long-task sum 1334 vs 1236 ms over the first 5 s | nothing attributable to the panel |
| P9: ≤ 50 MB heap at 100 messages | `usedJSHeapSize` delta vs a booted-but-closed panel: 3 MB total; vs the mounted empty panel: 0 MB; ~800 DOM nodes for the 100 messages | 6 % of budget |

## What the measurements changed

* P4 and P7 both read the conversation tables without an index the
  query needed: the drawer's totals (`tabAlbanna Chat Log` by
  conversation) scanned the whole table, and the title search filtered
  a user's rows by eye. `add_lookup_indexes` now carries a `title`
  index on `Albanna Conversation` and a `conversation` index on
  `Albanna Chat Log`, and the EXPLAIN plans show the totals query
  moving from a full scan to an index range read.
* Nothing else needed changing: every other budget is met with room to
  spare.

## Method notes, the parts that bite

* A harness page served from `127.0.0.1:<port>` never connects to
  realtime — the socketio auth maps a loopback Host to the bench's
  `default_site` (frappe.localhost) and rejects the namespace. The page
  must be served from `http://test.localhost:<port>`; chromium resolves
  `*.localhost` to loopback, and the origin hostname then matches the
  namespace.
* `bench serve` does not set `DEV_SERVER`, so `frappe.realtime` targets
  the serving origin instead of the socketio port. The harness passes
  `DEV_SERVER=1` to the spawned server.
* A subscription must be armed in an *awaited* `page.evaluate` before
  `execFileSync` starts the probe: a synchronous child process blocks
  the node loop, and an evaluate that was dispatched but not awaited
  never reaches the browser until the probe is done — every token is
  then already published, and the measurement reads an empty list.
* The ask must go through the panel's own composer for P3: the app
  renders only the tokens of the stream it initiated, so a raw fetch to
  `ask_stream` stamps tokens no render ever pairs with.

## Alternatives considered

**Record the budgets without numbers.** Rejected: the point of the
exercise was to find out, and one of the ten requirements was in fact
unmet (P10's indexes).

**Keep the harnesses in the repository.** Deferred: they hardcode the
bench's chrome path and a node_modules location; as committed code they
would be broken-on-arrival. The method notes above are what survives;
the scripts are a copyable shape, in the same style as
`scripts/ui_smoke.mjs`.

## See also

* ADR-0099 — the ask payload change P1's evidence came from.
* `albanna/patches/v0_1/add_lookup_indexes.py` — the indexes P4/P7
  exposed as missing.
