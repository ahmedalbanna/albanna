# ADR-0073: The test_provider button and API

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.8 requires that a System Manager shall be able to test the provider connection and receive a result showing which model answered and how long it took. The `Albanna Settings` doctype already carries the field `test_provider` (Button, labeled "Test the connection"). The API endpoint `albanna.api.provider.test_provider` is `@frappe.whitelist()` with `require_system_manager()` — it calls the provider with a minimal probe config and returns results. On success: `{"status": "ok", "provider": "...", "model": "...", "reply": "...", "seconds": N, "base_url": "..."}`. On error: `{"status": "error", "error": "..."}`. The JS handler `test_provider(frm)` in `albanna_settings.js` shows a green msg with model + reply + seconds on ok, red msg with error on failure.

## Decision

**Record the button, the API, and the UI response.**

Two guards:

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that `test_provider` is a Button field with label "Test the connection".

* `albanna/api/provider.py:35` asserts that `test_provider()` is `@frappe.whitelist()` with `require_system_manager()`, returns `{"status": "ok", "provider": completion.provider, "model": completion.model, "reply": (completion.message.content or "")[:REPLY_LIMIT], "seconds": elapsed, "base_url": config.base_url}` on success, and `{"status": "error", "error": _redact(...)}` on error.

* `albanna/albanna/doctype/albanna_settings/albanna_settings.js:175` asserts that `test_provider(frm)` calls `frappe.call(method="albanna.api.provider.test_provider", args={...})` and shows the appropriate msgprint.

## Alternatives considered

**Trust the API, since it is the only caller.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that calls the API and checks the response makes the rule visible.

**Use a different button label.** Rejected: the button label "Test the connection" was already chosen and is used throughout the UI; renaming it would be a user experience regression.

## Consequences

* FR-8.8 is now held: the button, the API, and the UI response are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the shipped field.
* `albanna/api/provider.py:35` — the API.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.js:175` — the JS handler.