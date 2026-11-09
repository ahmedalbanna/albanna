# ADR-0091: Client receives the answer from cache on reconnect

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.4 requires that if the client's socket disconnects, the client shall still receive the answer from cache on reconnect. The `albanna/api/chat.status` endpoint reads the parked turn payload from the cache under `TURN_CACHE_KEY.format(stream_id=stream_id)` with `expires=True`, which reads the fresh value without mirroring it into the request-local cache. The `albanna/services/chat_job._park()` function stores the finished turn payload in the cache under the same key with `expires_in_sec=TURN_TTL_SECONDS` (1800 seconds). When a client reconnects and polls `albanna.api.chat.status` with the stream ID, it reads the parked answer from cache if the turn has completed.

## Decision

**Record the cache-read pattern and the three possible outcomes.**

Two guards:

* `albanna/api/chat.status` asserts that it reads the turn payload from cache under `TURN_CACHE_KEY.format(stream_id=stream_id)` with `expires=True`, and returns one of three outcomes:
  - **Answer available**: `payload` exists and `status != "running"` and `status != "interrupted"` → returns `{"status": "ok", "reply": payload.get("reply"), ...}`.
  - **Turn still running**: `payload.status == "running"` → returns `{"status": "running"}`.
  - **Turn lost**: `payload` does not exist (expired) → returns `{"status": "lost", "conversation": conversation}` via `_lost_turn()`.

* `albanna/services/chat_job._park(stream_id, payload)` asserts that the finished turn payload is stored in the cache under `TURN_CACHE_KEY.format(stream_id=stream_id)` with `expires_in_sec=TURN_TTL_SECONDS` (1800 seconds), so that a reconnecting client can read it.

## Alternatives considered

**Store only in the socket, not in cache.** Rejected: if the socket disconnects before the answer is delivered, the client would never receive it. Caching guarantees liveness across disconnects.

**Use a different cache key per reconnect.** Rejected: the stream ID is stable per turn; using a new key per reconnect would mean the parked answer is never found.

## Consequences

* FR-12.4 is now held: the cache-read pattern, the three possible status outcomes, and the parked-answer guarantee are each asserted.

* No code change was needed; the mechanism was already implemented. The work was the ADR and this record.

## See also

* `albanna/api.chat.status` — the endpoint that reads from cache.
* `albanna/services.chat_job._park` — the cache parking function.
* `albanna/api.chat.TURN_CACHE_KEY` — the cache key format.
* `albanna/services.chat_job.run_turn_job` — the background job that parks the answer.