# ADR-0067: The fallback provider configuration

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.2 requires that a System Manager shall be able to configure a fallback provider. The `Albanna Settings` doctype already carries the fields `fallback_enabled` (Check), `fallback_kind` (Select: openai/ollama/anthropic), `fallback_base_url` (Data), `fallback_model` (Data), and `fallback_api_key` (Password). The service layer `albanna/services/settings_service.py:152-168` reads these fields and builds a `ProviderConfig` for the fallback. The chat service `albanna/services/chat_service.py:533` passes `fallback=settings.fallback` to `LLMConfig`, and `LLMConfig.chain()` returns `[primary, fallback]` when the fallback is usable, or just `[primary]` when it is not.

## Decision

**Record the configuration points and the chain logic.**

Three guards:

* `albanna/services/settings_service.py:152-168` asserts that when `doc.fallback_enabled` is set, a fallback `ProviderConfig` is constructed from `fallback_kind`, `fallback_base_url`, `fallback_model`, and `fallback_api_key`, with `supports_vision` derived from `attachment_support`.

* `albanna/services/chat_service.py:533` asserts that `LLMConfig(primary=settings.provider, fallback=settings.fallback, retries=1)` is used, and the chain is written to the audit row.

* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` asserts the chain behavior: unusable primary + usable fallback → chain of one; both unusable → empty chain.

## Alternatives considered

**Trust the service layer, since it is the only writer.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the chain back makes the rule visible.

**Add a new field for fallback kind options.** Rejected: the `fallback_kind` Select field (`openai`, `ollama`, `anthropic`) was already present on the doctype; adding another would be schema inflation.

## Consequences

* FR-8.2 is now held: the fallback provider configuration and chain logic are asserted at the point where the chain is built, and the provider test confirms the chain behavior.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/services/settings_service.py:152-168` — the fallback builder.
* `albanna/services/chat_service.py:533` — the chain usage.
* `albanna/tests/test_providers.py::test_the_fallback_chain_only_includes_usable_providers` — the chain test.