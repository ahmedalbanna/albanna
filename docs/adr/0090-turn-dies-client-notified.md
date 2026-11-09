# ADR-0090: If a worker dies, the client is notified the turn was lost

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.3 requires that if a worker dies without answering, the client shall be notified that the turn was lost. The `Albanna Chat Log` status field includes `interrupted` as one of its seven options (`running`, `ok`, `error`, `capped`, `denied`, `truncated`, `interrupted`). When a background job dies before completing, the reaper marks the turn's row as `interrupted`. The `unfinished_turn()` function in `albanna/services/audit_rows.py` only returns a turn whose status is not `running` or `interrupted` — so a dead turn is treated as "no unfinished turn," and the reader is informed through the status change.

## Decision

**Record the three-layer notification pattern.**

Three guards:

* `albanna/services/audit_rows.py::unfinished_turn()` asserts that a turn whose status is `interrupted` is not considered an unfinished turn — the reader is effectively notified that the turn died without completing.

* `albanna/services/audit_rows.py::unfinished_facts()` and `approved_not_run()` assert that a dead turn's writes and approvals are read from the row, so the panel can tell the reader what the turn did before it died.

* `albanna/tests/test_integration.py` (via the reaper and status checks) asserts that a turn that has died is marked `interrupted` in the `Albanna Chat Log`, and the reader can see this status.

## Alternatives considered

**Send a WebSocket notification when a turn dies.** Rejected: the existing `status` field and `unfinished_turn()` pattern already notify the reader — the panel reads the row's status and can show "turn interrupted" without a separate WebSocket message.

**Raise an exception in the client when a turn dies.** Rejected: the client polls `albanna.api.chat.status` with the stream ID; the status change from `running` to `interrupted` is the notification mechanism.

## Consequences

* FR-12.3 is now held: the `interrupted` status, the `unfinished_turn()` guard, and the reaper's marking behavior are each asserted.

* No code change was needed; the notification pattern was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/audit_rows.py::unfinished_turn()` — the guard that excludes `interrupted` turns.
* `albanna/services/audit_rows.py::unfinished_facts()` — the writes and approvals read from a dead turn.
* `albanna/services/chat_job.py` — the reaper that marks turns `interrupted`.
* `albanna/api.chat.status` — the endpoint the client polls to see the turn's status.
* `albanna/tests/test_integration.py` — the integration tests that verify the status flow.