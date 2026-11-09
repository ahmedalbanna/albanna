# ADR-0088: Turn runs in a background worker and returns a stream ID

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.1 requires that a turn shall run in a background worker; the API shall return a stream ID immediately. The chat API in `albanna/api/chat.py` already implements this pattern: when a user sends a question, the endpoint generates a `stream_id = uuid.uuid4().hex`, writes a "running" marker to the cache with a TTL covering the job's full budget, enqueues a background job `albanna.services.chat_job.run_turn_job` with `job_id=f"albanna-turn-{stream_id}"`, and returns `{"status": "queued", "stream_id": stream_id, "event": "STREAM_EVENT"}`. The client can then poll the `status` endpoint with the stream ID to check the turn's progress and final result.

## Decision

**Record the stream ID pattern and the three code paths.**

Two guards:

* `albanna/api/chat.py:297` asserts that `stream_id = uuid.uuid4().hex` generates a unique identifier for each turn.

* `albanna/api/chat.py:352` asserts that the response returns `{"status": "queued", "stream_id": stream_id, "event": "STREAM_EVENT"}` — the stream ID is immediately available to the client.

* `albanna/services/chat_job.py` asserts that the background job `run_turn_job` processes the turn, writes results to the `Albanna Chat Log`, and updates the cache marker from `"running"` to the final status (`ok`, `error`, `truncated`, etc.).

## Alternatives considered

**Return the turn result synchronously.** Rejected: a model call can take seconds; blocking the API request would make the chat feel slow and could cause timeouts under load. The background worker pattern gives the API response immediately and frees the worker to handle other requests.

**Use a fixed stream ID per user/session.** Rejected: a fixed ID would conflict if a user opens multiple turns simultaneously; a fresh UUID per turn is required for correct polling and result association.

## Consequences

* FR-12.1 is now held: the stream ID generation, the queued response, and the background worker pattern are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/api/chat.py:297` — the stream ID generation.
* `albanna/api/chat.py:352` — the queued response.
* `albanna/services/chat_job.py` — the background worker.
* `albanna/api/chat.py:336` — the `status` endpoint that polls the stream ID.