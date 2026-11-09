# ADR-0077: Support OpenAI-compatible endpoints

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.1 requires that the system support OpenAI-compatible endpoints: OpenRouter, OpenAI, Groq, vLLM, LM Studio, or any relay. The `OpenAIProvider` adapter in `albanna/providers/openai.py` was already designed to talk to any endpoint that speaks the OpenAI chat-completions API — the differences between these endpoints are only the base URL and the model id. However, the `provider_kind` Select field in `Albanna Settings` only listed `openai`, `ollama`, `anthropic`, and the `build_provider` function only mapped those three kinds. A System Manager could not select `openrouter`, `groq`, `vllm`, `lmstudio`, or `together` from the UI, even though the underlying adapter already supported them.

## Decision

**Add the new provider kinds to the Select options and map them to `OpenAIProvider`.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `provider_kind` is a Select field with eight options: `openai`, `ollama`, `anthropic`, `openrouter`, `groq`, `vllm`, `lmstudio`, `together`.

* `albanna/providers/base.py::build_provider` asserts that the kinds `openai`, `openrouter`, `groq`, `vllm`, `lmstudio`, `together` all return `OpenAIProvider`, and that `ollama` and `anthropic` return their respective native providers.

* `albanna/tests/test_providers.py` asserts that `build_provider` works for all eight kinds without raising `ValueError`.

## Alternatives considered

**Keep the Select options minimal, and document that `openai` kind works with any OpenAI-compatible endpoint.** Rejected: a System Manager selecting a provider from the UI expects the kind name they choose to be valid; hiding the capability behind the `openai` kind would cause confusion and underutilisation.

**Add new provider adapter classes for each kind.** Rejected: the `OpenAIProvider` adapter already handles all OpenAI-compatible endpoints; adding separate adapter classes would be duplication with no functional benefit.

## Consequences

* FR-10.1 is now held: System Managers can select any OpenAI-compatible endpoint from the provider kind dropdown, and the correct adapter is used.

* No new adapter code was needed; the existing `OpenAIProvider` already supports all these endpoints. The work was updating the Select options and the `build_provider` mapping.

## See also

* `albanna/providers/openai.py` — the `OpenAIProvider` which handles all OpenAI-compatible endpoints.
* `albanna/providers/base.py::build_provider` — the kind-to-adapter mapping.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped Select options.