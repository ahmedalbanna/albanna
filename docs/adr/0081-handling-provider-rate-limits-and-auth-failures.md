# ADR-0081: Provider rate limits and auth failures are handled gracefully

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.5 requires that the system handle provider rate limits and auth failures gracefully, surfacing clear errors to the user. The error taxonomy in `albanna/core/errors.py` defines `ProviderBudgetExceeded` (rate/cost limits), `ProviderRejected` (auth/key issues), and `ProviderError` (general provider failures). The `reader_message()` function maps these exceptions to reader-friendly sentences. The chat service in `albanna/services/chat_service.py` catches `ProviderBudgetExceeded` and `ProviderError` during provider calls and records the failure in the audit log. Fourteen integration tests in `albanna/tests/test_budget.py`, `albanna/tests/test_errors.py`, and `albanna/tests/test_providers.py` assert the behavior.

## Decision

**Record the error taxonomy, the reader-facing messages, and the service-level handling.**

Three guards:

* `albanna/core/errors.py` asserts the error taxonomy: `ProviderBudgetExceeded`, `ProviderRejected`, `ProviderError`, and the subclass chain (`ProviderTimeout`, `ProviderUnreachable`, `ProviderRejected`, `ProviderBudgetExceeded`).

* `albanna/core/errors.py::reader_message` asserts that each exception class maps to a clear, operator-facing sentence — `ProviderBudgetExceeded` names the affordable token number, `ProviderRejected` names API key/model access, and `AllProvidersFailed` says no model answered.

* `albanna/services/chat_service.py:815` and `:834` assert that `ProviderBudgetExceeded` and `ProviderError` are caught during provider calls, failures are recorded in the audit row's `error_class` and `error_message`, and the reader is shown a friendly message via `TurnOutcome.error`.

## Alternatives considered

**Skip the ADR, since the error taxonomy is already fixed.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the error back makes the rule visible.

**Add new exception classes for each specific failure mode.** Rejected: the existing taxonomy already covers rate limits (`ProviderBudgetExceeded`), auth failures (`ProviderRejected`), and general provider failures (`ProviderError`); adding more would fragment the hierarchy without benefit.

## Consequences

* FR-10.5 is now held: the error taxonomy, reader messages, and service-level handling are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/core/errors.py` — the error taxonomy and `reader_message`.
* `albanna/services/chat_service.py:815,834` — the service-level error handling.
* `albanna/tests/test_budget.py`, `albanna/tests/test_errors.py`, `albanna/tests/test_providers.py` — the integration and provider tests.