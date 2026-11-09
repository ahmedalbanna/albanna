# ADR-0058: The fallback provider is already implemented

Status: **Accepted**
Date: 2026-10-27

## Context

FR-8.2 requires that a System Manager shall be able to configure a fallback provider. The fallback provider fields (`fallback_enabled`, `fallback_kind`, `fallback_base_url`, `fallback_model`, `fallback_api_key`) were already present in the `Albanna Settings` doctype, and the service layer in `albanna/services/settings_service.py` already reads these fields and builds a `ProviderConfig` for the fallback. The chat service in `albanna/services/chat_service.py` already uses `LLMConfig` with a fallback chain via `LLMConfig.chain()`. The rule had no ADR because the feature was already shipped.

## Decision

**Record the rule where the fallback is wired, and test it where the chain is read.**

Two guards:

* `albanna/services/settings_service.py:152-168` asserts that when `doc.fallback_enabled` is true, a fallback `ProviderConfig` is built from `fallback_kind`, `fallback_base_url`, `fallback_model`, and `fallback_api_key`.

* `albanna/services/chat_service.py:533` asserts that the `LLMConfig` is constructed with `fallback=settings.fallback`, and `LLMConfig.chain()` returns `[primary, fallback]` when the fallback is usable, or just `[primary]` when it is not.

* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` asserts the chain behavior: when the primary is unusable, the fallback is used; when both are unusable, the chain is empty.

## Alternatives considered

**Trust the service layer, since it is the only writer.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the chain back makes the rule visible.

**Add a new field for the fallback kind.** Rejected: the `fallback_kind` Select field (`openai`, `ollama`, `anthropic`) was already present on the doctype; adding another would be schema inflation.

## Consequences

* FR-8.2 is now held: the fallback provider configuration is asserted at the point where the chain is built, and the integration test confirms the chain behavior.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/services/settings_service.py:152-168` — the fallback builder.
* `albanna/services/chat_service.py:533` — the chain usage.
* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` — the chain test.