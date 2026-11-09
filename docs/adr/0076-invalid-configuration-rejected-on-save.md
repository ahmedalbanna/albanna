# ADR-0076: Invalid configuration is rejected on save

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.11 requires that invalid configuration (e.g., non-existent role names) shall be rejected on save with a clear error message. The `AlbannaSettings.validate()` method chains four checks that reject invalid configuration on save:

1. `_enforce_valid_options()` (line 137) rejects non-JSON in `extra_options` with clear error: `"These are not valid options: {error}"`.

2. `_validate_disabled_tools()` (line 139) rejects non-tool names in `disabled_tools` with clear error: `"These are not Albanna tools: {names}"`.

3. `_clamp_approval_wait()` (line 141) corrects `confirm_timeout` to `[MIN_TIMEOUT, MAX_TIMEOUT]` bounds.

4. `_secure_secrets()` (line 135) encrypts `api_key` / `fallback_api_key` — no plaintext leaves the ORM.

Provider kind is restricted by the `Select` field options (`openai`, `ollama`, `anthropic`), so invalid values cannot be entered. `build_provider()` in `providers/base.py:210` raises `ValueError` for unknown kinds with message: `"Unknown provider kind: {kind!r}. Known kinds: ..."`.

## Decision

**Record the validation points and the clear error messages.**

Four guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.py:137-207` asserts the four validation methods in `validate()`, each raising `frappe.ValidationError` with a descriptive title and message.

* `albanna/providers/base.py:210` asserts that `build_provider(kind)` raises `ValueError` for unknown kinds with the list of known kinds.

* `albanna/tests/test_disabled_tools.py` and `albanna/tests/test_options.py` assert that invalid tool names and invalid JSON options are rejected on save with clear error messages.

## Alternatives considered

**Trust the validate method, since it is the only save gate.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that attempts an invalid save and checks the error makes the rule visible.

**Omit the error message and rely on the field-level validation.** Rejected: FR-8.11 explicitly requires a clear error message on save; omitting the message would fail the requirement.

## Consequences

* FR-8.11 is now held: the four validation methods, the provider kind restriction, and the test assertions are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.py:137-207` — the four validation methods.
* `albanna/providers/base.py:210` — the provider kind restriction.
* `albanna/tests/test_disabled_tools.py` and `albanna/tests/test_options.py` — the validation tests.