# ADR-0078: Support Ollama

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.2 requires that the system support Ollama. The `Ollama` provider kind is already present in the `Albanna Settings` `provider_kind` Select field with the option `ollama`. The `build_provider` function in `albanna/providers/base.py` already maps `ollama` to `OllamaProvider`, and `OllamaProvider` in `albanna/providers/ollama.py` implements the adapter for the Ollama API. The system already supports Ollama out of the box, but the rule had no ADR.

## Decision

**Record the existing support where the provider kind and adapter are defined.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `provider_kind` includes the option `ollama`.

* `albanna/providers/base.py::build_provider` asserts that `kind == OLLAMA` returns `OllamaProvider`.

* `albanna/providers/ollama.py` implements the Ollama adapter with `complete` and `stream` methods, and `test_the_ollama_tool_arguments_are_an_object` and `test_the_ollama_tool_results_share_one_user_turn` in `tests/test_providers.py` assert correct tool argument and result shapes.

## Alternatives considered

**Remove Ollama from the Select options.** Rejected: Ollama is a widely used provider, and removing it would eliminate a supported capability without benefit.

**Add a new Ollama-specific field separate from provider_kind.** Rejected: the existing `provider_kind` Select with `ollama` is the correct place; adding a separate field would be schema inflation.

## Consequences

* FR-10.2 is now held: Ollama support is asserted at the provider kind and build_provider level, and the provider tests confirm it.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/providers/ollama.py` — the Ollama adapter.
* `albanna/providers/base.py::build_provider` — the kind-to-adapter mapping.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped Select options.
* `tests/test_providers.py::test_the_ollama_tool_arguments_are_an_object` and `test_the_ollama_tool_results_share_one_user_turn` — the Ollama provider tests.