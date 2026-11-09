# ADR-0082: Retry with a lower max_tokens when the provider rejects a request as too expensive

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.6 requires that the system retry with a lower `max_tokens` if the provider rejects a request as too expensive. The `OpenAIProvider` in `albanna/providers/openai.py` parses the provider's refusal detail to extract the affordable token number via `_affordable_tokens()`. The chat service in `albanna/services/chat_service.py:815-829` catches `ProviderBudgetExceeded`, and if `affordable_tokens` is set and `affordable < max_tokens`, it reduces `max_tokens` to `affordable` and retries the request. This avoids wasting tokens and gives the provider a chance to answer with a shorter ceiling.

## Decision

**Record the retry logic and the three-way guard.**

Three guards:

* `albanna/providers/openai.py:65-77` asserts `_affordable_tokens()` extracts the affordable token number from the provider's refusal detail using a regex.

* `albanna/providers/openai.py:343-344` asserts that when `ProviderBudgetExceeded` is raised, `affordable_tokens` is set from the parsed detail.

* `albanna/services/chat_service.py:816-824` asserts that when `ProviderBudgetExceeded` is caught, `affordable = exc.affordable_tokens or 0`, and if `affordable` is set and `affordable < max_tokens`, `max_tokens` is replaced with `affordable` and the request is retried. If `affordable >= max_tokens` or `affordable` is not set, the failure is recorded and the loop breaks.

## Alternatives considered

**Do not retry, and instead show the user an error immediately.** Rejected: wasting the user's tokens by showing an error when a cheaper retry would succeed is poorer UX; the retry gives the provider a chance with a reduced ceiling.

**Retry with the same `max_tokens` indefinitely.** Rejected: this would loop forever if the provider consistently refuses the ceiling; a bounded retry with a reduced ceiling is the correct pattern.

## Consequences

* FR-10.6 is now held: the retry-with-lower-`max_tokens` logic, the parsing of the provider's refusal, and the three-way guard (retry, record failure, keep original ceiling) are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/providers/openai.py:65-77` — the `_affordable_tokens()` parser.
* `albanna/providers/openai.py:343-344` — the `ProviderBudgetExceeded` handler.
* `albanna/services/chat_service.py:816-824` — the retry logic.
* `albanna/core/errors.py:94` — the refusal documentation.
* `albanna/tests/test_budget.py` — the budget tests.