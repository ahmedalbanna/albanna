# ADR-0083: Verify the Frappe site context before every tool call

Status: **Accepted**
Date: 2026-11-09

## Context

FR-11.1 requires that the system verify the Frappe site context before every tool call. The `albanna/site_context.py` module provides `current_site()`, which reads the site from `frappe.local.site` and raises `RuntimeError` if no site is bound to the request. The chat service in `albanna/services/chat_service.py:430` calls `current_site()` at the start of every turn, before the tool registry is consulted or any tool is executed. This ensures that a background job enqueued for one site cannot silently read or write data belonging to another site.

## Decision

**Record the site verification point and the RuntimeError guard.**

Two guards:

* `albanna/site_context.py::current_site()` asserts that a site is always bound to the request; if not, it raises `RuntimeError` with a message directing the enqueuer to explicitify the site.

* `albanna/services/chat_service.py:430` asserts that `current_site()` is called at the start of every turn, before `self._tool_registry(principal.user)` or any tool execution. The `RuntimeError` from `current_site()` propagates upward, preventing the turn from starting with an unbound site.

## Alternatives considered

**Skip the guard, since Frappe web requests always have a site.** Rejected: background workers and enqueued jobs do not always have `frappe.local.site` initialised; without the guard, a job enqueued for one site could silently read/write another site's data.

**Use a fallback to `currentsite.txt`.** Rejected: the entire purpose of `site_context.py` is to prevent exactly this class of bug: a silent read/write across sites. A fallback would reintroduce the bug.

## Consequences

* FR-11.1 is now held: the site verification point and the RuntimeError guard are each asserted.

* No code change was needed; the verification was already implemented in `site_context.py` and called from `chat_service.py`. The work was the ADR and this record.

## See also

* `albanna/site_context.py::current_site()` — the site verification function.
* `albanna/services/chat_service.py:430` — the call site before every turn.
* `albanna/hooks.py` — enqueue jobs with an explicit site.