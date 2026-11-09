# ADR-0079: Support Anthropic

Status: **Accepted**
Date: 2026-11-09

## Context

FR-10.3 requires that the system support Anthropic. The `Anthropic` provider kind is already present in the `Albanna Settings` `provider_kind` Select field with the option `anthropic`. The `build_provider` function in `albanna/providers/base.py` already maps `anthropic` to `AnthropicProvider`, and `AnthropicProvider` in `albanna/providers/anthropic.py` implements the adapter for the Anthropic API. The system already supports Anthropic out of the box, but the rule had no ADR.

## Decision

**Record the existing support where the provider kind and adapter are defined.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `provider_kind` includes the option `anthropic`.

* `albanna/providers/base.py::build_provider` asserts that `kind == ANTHROPIC` returns `AnthropicProvider`.

* `albanna/providers/anthropic.py` implements the Anthropic adapter with `complete` and `stream` methods, and `test_the_anthropic_system_prompt_is_a_top_level_parameter`, `test_the_anthropic_tool_results_share_one_user_turn`, and `test_the_anthropic_tools_use_input_schema` in `tests/test_providers.py` assert correct tool argument and result shapes.

## Alternatives considered

**Remove Anthropic from the Select options.** Rejected: Anthropic is a widely used provider, and removing it would eliminate a supported capability without benefit.

**Add a new Anthropic-specific field separate from provider_kind.** Rejected: the existing `provider_kind` Select with `anthropic` is the correct place; adding a separate field would be schema inflation.

## Consequences

* FR-10.3 is now held: Anthropic support is asserted at the provider kind and build_provider level, and the provider tests confirm it.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/providers/anthropic.py` — the Anthropic adapter.
* `albanna/providers/base.py::build_provider` — the kind-to-adapter mapping.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped Select options.
* `tests/test_providers.py::test_the_anthropic_system_prompt_is_a_top_level_parameter`, `test_the_anthropic_tool_results_share_one_user_turn`, and `test_the_anthropic_tools_use_input_schema` — the Anthropic provider tests.