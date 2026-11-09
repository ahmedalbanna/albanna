# ADR-0089: Progress published over socket.io and finished answer parked in cache

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.2 requires that progress shall be published over socket.io; the finished answer shall be parked in cache. The background job `albanna.services.chat_job.run_turn_job` implements this pattern in two ways:

1. **Progress publishing**: During the turn, the `emit` callback (built by `_realtime_emit`) publishes events over socket.io via `frappe.publish_realtime(STREAM_EVENT, {"stream_id": stream_id, **event}, user=user)`. This keeps the client UI updated with progress (e.g., "thinking", "tool call in progress").

2. **Answer parking**: When the turn completes, `_park(stream_id, payload)` stores the final payload in the cache under `TURN_CACHE_KEY.format(stream_id=stream_id)` with a TTL of `TURN_TTL_SECONDS` (1800 seconds). The client can fall back to polling `albanna.api.chat.status` with the stream ID to retrieve the parked answer if the socket connection drops.

Two guarantees make this reliable:

* **The final answer is parked in the cache as well as published.** If a socket drops mid-turn, the answer is not lost — `albanna.api.chat.status` reads the parked copy.

* **The realtime publish is best-effort.** A socket failure must never abort the turn, because the answer is already computed and stored. The marker is parked in the site's cache namespace, never the reader's, so a login/logout/role change cannot delete it mid-turn.

## Decision

**Record the progress-and-park pattern and the two guarantees.**

Two guards:

* `albanna/services/chat_job.py:6-13` asserts that the final answer is parked in the cache as well as published, and that the marker is in the site's cache namespace (never the reader's).

* `albanna/services/chat_job.py:_park(stream_id, payload)` asserts that the finished turn is stored in the cache under `TURN_CACHE_KEY.format(stream_id=stream_id)` with `expires_in_sec=TURN_TTL_SECONDS` (1800 seconds), and that `albanna.api.chat.status` reads the parked copy.

## Alternatives considered

**Store only in the socket, not in cache.** Rejected: if the socket connection drops, the reader would sit on a spinner forever with no way to recover the answer. Caching guarantees liveness.

**Publish progress over a dedicated WebSocket namespace only.** Rejected: the existing `STREAM_EVENT` over `frappe.publish_realtime` is the established pattern; changing it would require client updates and is not a bug fix.

## Consequences

* FR-12.2 is now held: the progress-via-socket.io and answer-via-cache pattern is asserted, and the two guarantees are documented.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/chat_job.py:6-13` — the progress-and-park description.
* `albanna/services/chat_job.py:_park` — the cache parking function.
* `albanna/services/chat_job.py:_realtime_emit` — the socket.io progress publishing.
* `albanna/api.chat.status` — the polling fallback that reads the parked copy.
* `albanna/api.chat.STEAM_EVENT` — the event name.