# ADR-0002: The authority layer, and who the write path runs as

Status: **Accepted**
Date: 2026-10-21

## Context

The `erpnext_mcp` tools have two safety properties that a caller used to
get from the server rather than from the tool:

1. **A role gate.**  The registration layer refused a tool the caller's
   Frappe roles did not permit, before the tool body ran.
2. **A write-permission default.**  The tool functions are decorated with
   `with_frappe`, and the write tools call
   `doc.insert(ignore_permissions=_bypass_permissions())`.
   `_bypass_permissions()` returns `True` by default, so **a write tool
   bypasses Frappe's permission engine** unless something says otherwise.

Both existed because the backend was the authority: it ran as a mapped user
(`mcp_per_call_user`) or as Administrator, and it had to decide what that
identity was allowed to do.

Calling the functions in-process removes the role gate entirely
([ADR-0001](0001-in-process-tools.md)) and leaves the permission bypass
switched **on**.  Taken naively, that turns a side chat into an
Administrator.

## Decision

**Two layers, both fail-closed.**

**Layer one — `core/authority.py`.**  Albanna owns the reachability and
authorisation decision.

* *Reachability* is static: is the tool switched on, does the principal
  hold the roles it requires.  It is computed once per turn and decides
  which tools the model is **told about**.  A tool the user may not reach
  is never mentioned to the model.
* *Authorisation* is dynamic: for a write tool, the target DocType comes
  from the arguments, so whether the user may create *that* document is
  checked at call time.

Every path that is not an explicit yes is a no: an unknown tool name, a
switched-off tool, a missing role, a write call with no target DocType, a
permission checker that raises.

**Layer two — the per-call-user marker.**  The adapter sets

```python
frappe.local.mcp_per_call_user = <the requesting user>
```

before every tool call, and clears it afterwards.  This is the backend's own
mechanism for "run this call as this user", and it does two things:

* `with_frappe` re-applies the user and drops the cached role permissions,
  so the call sees that user's roles and not a stale cache;
* `_bypass_permissions()` sees an active per-call user and returns
  `False`, so the write tools stop bypassing Frappe's permission engine.

The marker is deliberately absent from the backend's authentication-marker
list (`utils/frappe_auth.py`), so setting it does not make the call look
authenticated and does not disturb the site-authorisation check.

## Consequences

* **A write runs under the caller's real permissions.**  A Sales User
  cannot create a Sales Invoice through the chat: the authority layer
  refuses it, and if that were bypassed, `doc.insert(ignore_permissions=False)`
  refuses it too.  Both layers are tested against the real Frappe
  permission engine, with real roles.
* **Reads respect User Permissions and row-level rules**, because the
  session user is the acting user.
* **The authority layer is the app's main security surface**, and it is
  small, pure and independently testable.  That is a deliberate trade: a
  gate that is hard to test is a gate that fails open.
* **The marker must be set on every call, including in a worker.**  A
  worker thread's `frappe.local` is fresh, so the session user is not
  automatically in effect there.  The adapter sets the marker on every
  call regardless of context, so there is one code path, not two.

## The trap worth recording

`frappe.has_permission` — the top-level function — does **not** accept
`print_logs`, while `frappe.permissions.has_permission` does.  Passing it
to the wrong one raises a `TypeError`, which a fail-closed checker catches
and turns into "denied" — so every write on the site is refused, and it
looks exactly like a permissions problem.

That is why the checker logs the exception as well as refusing.  A gate that
fails because of a renamed argument should be loud.
