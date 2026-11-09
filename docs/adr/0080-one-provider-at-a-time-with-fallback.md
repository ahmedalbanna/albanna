# ADR-0080: The system uses one provider at a time, with an optional fallback

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.4 requires that the system use one provider at a time, with an optional fallback. The `LLMConfig` data class in `albanna/providers/base.py` models a primary provider and an optional fallback. The `LLMConfig.chain()` method returns a list of one or two `ProviderConfig` objects: `[primary, fallback]` when the fallback is usable, or `[primary]` when it is not, or `[]` when both are unusable. The chat service in `albanna/services/chat_service.py` iterates over `config.chain()` to try each provider in order, stopping when a provider returns a successful answer. This pattern ensures that the system always uses one provider at a time, with an optional fallback as a secondary attempt.

## Decision

**Record the chain logic and the three outcomes.**

Three guards:

* `albanna/providers/base.py::LLMConfig.chain()` asserts the three possible chain lengths:
  - Two providers when both primary and fallback are usable.
  - One provider when the primary is unusable but the fallback is usable, or when only the primary is provided.
  - Zero providers when both primary and fallback are unusable.

* `albanna/services/chat_service.py:793` asserts that the loop `for provider_config in config.chain()` tries each provider in order and stops when a successful answer is obtained.

* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` asserts the chain behavior: unusable primary + usable fallback → chain of one; both unusable → empty chain.

## Alternatives considered

**Model the chain as a fixed two-element tuple.** Rejected: the chain must be variable-length because the fallback may or may not be usable; a fixed tuple would require a sentinel value to indicate "no fallback", which is less clear than a list that can have length 0, 1, or 2.

**Always attempt both providers, even if the first succeeds.** Rejected: this would waste tokens and latency; the whole point of the fallback is to attempt it only when the first provider fails.

## Consequences

* FR-10.4 is now held: the chain logic, the three outcomes, and the service-level iteration are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/providers/base.py::LLMConfig.chain()` — the chain logic.
* `albanna/services/chat_service.py:793` — the service-level iteration.
* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` — the chain test.
* `albanna/services/chat_service.py:774` — the `config` object used in `_run`.