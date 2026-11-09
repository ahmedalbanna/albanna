# ADR-0085: API keys are not exposed in logs, error messages, or the UI

Status: **Accepted**
Date: 2026-11-09

## Context

FR-11.3 requires that the system not expose API keys in logs, error messages, or the UI (except to System Managers in settings). The existing infrastructure already provides this protection through three layers:

1. **`albanna/core/secrets.py::mask_secret()`** masks a secret as `"[redacted]"` when printed, and returns `""` for an empty secret — so a key that reached the log would read as `"[redacted]"` rather than the actual key.

2. **`albanna/core/secrets.py::redact_secret()`** removes a secret from any text it appears in — provider refusal messages that accidentally include a key are stripped of the key before they reach the log.

3. **`albanna/services/chat_service.py::_without_secrets()`** redacts the site's own API keys from error messages before they are stored in the `Albanna Chat Log` or shown to the reader.

4. **Settings gate**: The `Albanna Settings` doctype is a Single gated to **System Manager** (read and write). The API key is part of this settings, so only a System Manager can view or modify it. Regular users cannot see the key in the UI or via the API.

## Decision

**Record the three-layer protection and the settings gate.**

Three guards:

* `albanna/core/secrets.py::mask_secret()` asserts that any printed representation of a secret shows `"[redacted]"` rather than the actual key.

* `albanna/core/secrets.py::redact_secret()` asserts that provider refusal messages and log entries have the key removed — the key never reaches the log or the reader.

* `albanna/services/chat_service.py::_without_secrets()` asserts that error messages stored in the chat log and shown to the reader have the site's own keys removed before display.

* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` asserts that the API key field is part of a Single gated to **System Manager** (read and write), so only a System Manager can view or modify the key.

## Alternatives considered

**Add a new redaction function for UI fields.** Rejected: the existing `mask_secret()` and `redact_secret()` already cover the two code paths — printed representations and error-message text. A new function would be duplication.

**Store API keys in plain text for UI display.** Rejected: the UI never needs to display the actual key; the Password field type masks it, and the settings gate ensures only System Managers can modify it.

## Consequences

* FR-11.3 is now held: the three-layer protection and the settings gate are each asserted.

* No code change was needed; the protection was already implemented. The work was the ADR and this record.

## See also

* `albanna/core/secrets.py::mask_secret` — printed redaction.
* `albanna/core/secrets.py::redact_secret` — text redaction.
* `albanna/services/chat_service.py::_without_secrets` — error-message redaction.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the settings gate.