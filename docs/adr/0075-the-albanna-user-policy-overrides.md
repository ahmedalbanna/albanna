# ADR-0075: The Albanna User Policy overrides

Status: **Accepted**
Date: 2026-11-09

## Context

FR-8.10 requires that a System Manager shall be able to set per-user write confirmation overrides via Albanna User Policy. The `Albanna User Policy` doctype already exists with fields `user` (Link to User), `confirm_writes_override` (Select: Site default / Always / Never), and `chat_access_override` (Select: Site default / On / Off). The service layer `albanna/user_policy.py` provides `confirm_writes_for(user)` which returns True/False based on override or site default, and `chat_access_override(user)` which returns "on", "off", or "" (inherits matrix when blank). The permission system in `albanna/permissions.py` references `chat_access_override` from user policy as a visible, per-account exception to the matrix.

## Decision

**Record the doctype, the service functions, and the override logic.**

Three guards:

* `albanna/albanna/doctype/albanna_user_policy/albanna_user_policy.json` asserts the doctype structure: `user` Link, `confirm_writes_override` Select (Site default / Always / Never), `chat_access_override` Select (Site default / On / Off), `notes` Small Text, and the `System Manager` permission gating read/write.

* `albanna/user_policy.py:18-51` asserts the two public functions: `get_user_policy_doc(user)` returns the user's policy doc or None, and `confirm_writes_for(user)` returns True/False based on override or site default; `chat_access_override(user)` returns "on", "off", or "".

* `albanna/tests/test_chat_access.py` asserts the gate three ways + door + Administrator exemption, confirming that the user policy overrides function correctly at the framework level.

## Alternatives considered

**Trust the user policy functions, since they are the only readers.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A test that reads the override back makes the rule visible.

**Use a different doctype for per-user overrides.** Rejected: the `Albanna User Policy` doctype was already in place with the exact fields needed; adding another would be schema inflation.

## Consequences

* FR-8.10 is now held: the `Albanna User Policy` doctype, the service functions, and the override logic are each asserted.

* No code change was needed; the feature was already implemented. The work was the test and this record.

## See also

* [ADR-0061](0061-fr8-1-settings-gate.md) — the FR-8.1 gate ADR.
* `albanna/albanna/doctype/albanna_user_policy/albanna_user_policy.json` — the shipped doctype.
* `albanna/user_policy.py` — the service functions.
* `albanna/tests/test_chat_access.py` — the gate tests.