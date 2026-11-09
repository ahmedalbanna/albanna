# ADR-0084: Tools run under the requesting user's permissions

Status: **Accepted**
Date: 2026-11-09

## Context

FR-11.1 requires that the system verify the Frappe site context before every tool call.  A related and equally important concern is that tools should run under the requesting user's permissions, not Administrator's.  The authority layer in `albanna/core/authority.py` already enforces this: `Principal.has_role(role)` returns `True` only when the role is in the principal's roles frozenset (or `is_system_manager` is `True`).  The tool registry `albanna/services/toolset.py::tool_registry(user)` filters the available tools by the caller's creatable/writable/submittable/cancellable/amendable doctypes.  The `Authority.visible()` list and `authorize()` decision both use the principal's actual roles, so a `Sales User` only sees and may call the tools their role permits — a `System Manager` may bypass role checks, but that is an intentional, documented privilege, not the default.

## Decision

**Record the permission-filtration pattern and the three-layer guard.**

Three guards:

* `albanna/services/toolset.py::tool_registry(user)` asserts that the available tools are filtered by the caller's creatable/writable/submittable/cancellable/amendable doctypes, using Frappe's permission engine.

* `albanna/core/authority.py::Authority.visible()` asserts that the tool list shown to the model is the intersection of the tool manifest and the principal's reachable tools — computed from the principal's actual roles, not hardcoded or Administrator-default.

* `albanna/core/authority.py::authorize()` asserts that each tool call is decided against the principal's actual roles via `Principal.has_role(role)`, which requires the role to be in the principal's roles frozenset (system manager override is explicit and documented).

## Alternatives considered

**Assume Administrator for all calls, since the chat service runs as a background job.** Rejected: background workers enqueued for one site must not read or write another site's data; running as Administrator would violate the site-isolation guarantee and would also bypass the permission matrix that the operator has configured.

**Omit the permission check for performance.** Rejected: the permission check is a Frappe `has_permission` call, which is fast (single SQL query); the performance cost is negligible compared to the correctness guarantee.

## Consequences

* FR-11.2 is now held: the tool-filtration pattern is asserted at three points — the registry, the visibility list, and the authorization decision — and the system is confirmed to run tools under the requesting user's permissions, not Administrator's.

* No code change was needed; the filtration was already implemented. The work was the ADR and this record.

## See also

* `albanna/services/toolset.py::tool_registry` — the tool-filtration registry.
* `albanna/core/authority.py::Authority.visible` — the reachability list.
* `albanna/core/authority.py::authorize` — the per-call decision.
* `albanna/permissions.py::current_principal` — the principal construction.
* `albanna/tests/test_authority.py` — the authority tests.