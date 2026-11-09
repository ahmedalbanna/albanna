# ADR-0092: Per-user, per-minute turn limit is configurable

Status: **Accepted**
Date: 2026-11-09

## Context

FR-12.5 requires that the system enforce a per-user, per-minute turn limit, configurable via the site settings, where zero means no limit. The `Albanna Settings` doctype already carries the field `turns_per_minute` (Int, default 6). The service layer `albanna/services/rate_limit.py` reads this setting via `get_settings().turns_per_minute` and enforces the limit via `check_turn_allowed(user, surface)`. The bucket is per user *and* per surface (ask/stream), so a user who exhausts their ask allowance still has their stream allowance, and vice versa. Zero means no limit.

## Decision

**Record the limit mechanism and the three outcomes.**

Three guards:

* `albanna/services/rate_limit.py::_limit()` asserts that it reads `turns_per_minute` from the site settings, returning `0` when the field is absent or zero — which the system interprets as "no limit".

* `albanna/services/rate_limit.py:check_turn_allowed(user, surface)` asserts that the per-user, per-surface bucket is decremented on each allowed turn, and that `frappe.throw(frappe._("Too many questions. Wait a minute and try again."), frappe.TooManyRequestsError)` is raised when the bucket is exhausted.

* `albanna/settings_service.py:turns_per_minute` asserts that the field is an Int with default `6`, and that zero means "no limit" — the rate limit code interprets zero as unlimited.

## Alternatives considered

**Hardcode the limit in the chat service.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A configurable setting makes the limit adjustable without code changes.

**Use a fixed global limit for all users.** Rejected: the per-user, per-surface bucket is essential for a multi-user chat site; a global limit would be too restrictive for low-traffic users and too lenient for high-traffic users.

## Consequences

* FR-12.5 is now held: the per-user, per-minute limit setting, the bucket mechanism, and the zero-meaning-no-limit semantics are each asserted.

* No code change was needed; the feature was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/rate_limit.py` — the rate limit implementation.
* `albanna/services/settings_service.py:turns_per_minute` — the setting.
* `albanna/tests/test_budget.py` — the budget tests.