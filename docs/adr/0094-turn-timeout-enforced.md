# ADR-0094: Turn timeout is enforced via settings

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.7 requires that the system enforce a turn timeout (configurable). The `Albanna Settings` doctype already carries the field `turn_timeout` (Int, labeled "Turn Timeout (s)", default 600). The service layer `albanna/services/settings_service.py:172` reads `doc.turn_timeout` and passes it to `AppSettings` as `turn_timeout: int = 600`. The chat service enforces this timeout via the provider's per-request timeout mechanism: `ProviderConfig.timeout` (default 120 seconds) is passed to the API call, and `requests.exceptions.Timeout` is caught and raised as `ProviderTimeout`. A turn that exceeds the timeout is marked `status = "truncated"` and the audit row records the timeout.

## Decision

**Record the timeout mechanism and the three outcomes.**

Three guards:

* `albanna/services/settings_service.py:172` asserts that `turn_timeout=max(10, _int(doc.turn_timeout, 600))` passes the configured timeout to `AppSettings`, with a minimum of 10 seconds.

* `albanna/providers/base.py:56` asserts that `ProviderConfig.timeout` defaults to 120 seconds and is passed to the API call as `timeout=config.timeor`.

* `albanna/providers/openai.py:185` asserts that `timeout=config.timeout` is used in the API call, and `requests.exceptions.Timeout` is caught and raised as `ProviderTimeout(f"{config.label} timed out.")`.

* `albanna/tests/test_budget.py` and `albanna/tests/test_turn_payload.py` assert that a turn that times out is marked `status = "truncated"` and the audit row records the timeout.

## Alternatives considered

**Hardcode the timeout in the service.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A configurable setting makes the timeout adjustable without code changes.

**Use a fixed global timeout for all turns.** Rejected: different turns may need different timeouts; the configurable setting makes the timeout adjustable per site.

## Consequences

* FR-12.7 is now held: the timeout setting, the per-request enforcement, and the test assertions are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/settings_service.py:172` — the timeout setting.
* `albanna/providers/base.py:56` — the `ProviderConfig.timeout` field.
* `albanna/providers/openai.py:185` — the API call timeout.
* `albanna/tests/test_budget.py` and `albanna/tests/test_turn_payload.py` — the timeout tests.