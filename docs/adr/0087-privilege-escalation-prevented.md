# ADR-0087: Privilege escalation through the chat interface is prevented

Status: **Accepted**
Date: 2026-11-09

## Context

FR-11.3 requires that the system not expose API keys in logs, error messages, or the UI (except to System Managers in settings). A related and equally important concern is that the system shall not allow privilege escalation through the chat interface. The tool manifest `TOOL_MANIFEST` in `albanna/core/tools.py` deliberately excludes dangerous tools such as `run_sql_query`, `find_tools`, and `run_flow` — the comment explicitly states that if `run_sql_query` is ever added to the chat interface, it must be System Manager only and must not be part of this set. The authority layer in `albanna/core/authority.py` enforces role-based access: `Principal.has_role(role)` returns `True` only when the role is in the principal's roles frozenset (or `is_system_manager` is `True`). The tool registry `albanna/services/toolset.py::tool_registry(user)` filters the available tools by the caller's creatable/writable/submittable/cancellable/amendable doctypes, using Frappe's permission engine. The `Authority.visible()` list and `authorize()` decision both use the principal's actual roles, so a `Sales User` only sees and may call the tools their role permits — a `System Manager` may bypass role checks, but that is an intentional, documented privilege, not the default.

## Decision

**Record the prevention pattern and the three-layer guard.**

Three guards:

* `albanna/core/tools.py::TOOL_MANIFEST` asserts that dangerous tools such as `run_sql_query`, `find_tools`, and `run_flow` are deliberately excluded from the manifest, preventing them from being called through the chat interface.

* `albanna/core/authority.py::Authority.visible()` asserts that the tool list shown to the model is the intersection of the tool manifest and the principal's reachable tools — computed from the principal's actual roles, not hardcoded or Administrator-default.

* `albanna/core/authority.py::authorize()` asserts that each tool call is decided against the principal's actual roles via `Principal.has_role(role)`, which requires the role to be in the principal's roles frozenset (system manager override is explicit and documented).

## Alternatives considered

**Add `run_sql_query` to the manifest with System Manager-only gating.** Rejected: the comment in `albanna/core/tools.py:225-229` explicitly states that `run_sql_query` bypasses Frappe's permission engine completely, including User Permissions and every row-level rule; adding it to the chat interface would be a privilege escalation risk, not a feature.

**Omit the authority layer and rely on Frappe's built-in permissions.** Rejected: Frappe's built-in permissions apply to document reads/writes through `frappe.get_doc` / `frappe.get_list`, but the chat interface sends arbitrary tool calls that Frappe's ORM does not see; the authority layer is the dedicated gate for tool calls.

## Consequences

* FR-11.5 is now held: the manifest exclusion, the authority-layer filtration, and the role-based authorization are each asserted — the system prevents privilege escalation through the chat interface.

* No code change was needed; the prevention was already implemented. The work was the ADR and this record.

## See also

* `albanna/core/tools.py::TOOL_MANIFEST` — the excluded tools.
* `albanna/core/authority.py::Authority.visible` — the reachability list.
* `albanna/core/authority.py::authorize` — the per-call decision.
* `albanna/services/toolset.py::tool_registry` — the tool-filtration registry.
* `albanna/core/tools.py:225-229` — the privilege-escalation comment.