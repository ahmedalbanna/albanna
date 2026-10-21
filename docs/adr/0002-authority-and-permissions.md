# ADR-0002: The authority layer, and who the write path runs as

Status: **Accepted**
Date: 2026-10-21

## Context

The tools this app started with had two safety properties that a caller got
from the server rather than from the tool:

1. **A role gate.**  The registration layer refused a tool the caller's
   Frappe roles did not permit, before the tool body ran.
2. **A write-permission default.**  The tool functions were decorated with
   `with_frappe`, and the write tools called
   `doc.insert(ignore_permissions=_bypass_permissions())`.
   `_bypass_permissions()` returns `True` by default, so **a write tool
   bypasses Frappe's permission engine** unless something says otherwise.

Both existed because the backend was the authority: it ran as a mapped user
(`mcp_per_call_user`) or as Administrator, and it had to decide what that
identity was allowed to do.

Calling such functions in-process removes the role gate entirely
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

**Layer two — the framework's own permissions.**  The tools are the app's
own now, and they call the framework's own functions: a read through
`frappe.get_list` / `frappe.get_doc`, a write through `doc.insert()`.  Both
apply the *session* user's roles, permissions and User Permissions, with no
bypass to switch off.

So there is no marker to set, no cache to clear, and no window in which a
tool could run as somebody else.  The adapter checks the acting user before
each call and refuses if the request has no user at all.

The rules that used to be the backend's are now the app's, and they are
written down rather than inherited:

* a write is an ordinary insert, so the caller's create permission
  applies, and a duplicate or an invalid document is a rollback and an
  error envelope, not a half-written row;
* a read is an ordinary list, so the caller's read permission and their
  User Permissions apply, and a document they may not read is a refusal
  rather than a row with the fields blanked out;
* a report is checked the way the desk checks it, before it runs.

## Consequences

* **A write runs under the caller's real permissions.**  A Sales User
  cannot create a Sales Invoice through the chat: the authority layer
  refuses it, and if that were bypassed, `doc.insert()` refuses it too.
  Both layers are tested against the real Frappe permission engine, with
  real roles.
* **Reads respect User Permissions and row-level rules**, because the
  session user is the acting user.
* **The authority layer is the app's main security surface**, and it is
  small, pure and independently testable.  That is a deliberate trade: a
  gate that is hard to test is a gate that fails open.
* **The permissions are stronger than they were.**  The old tools bypassed
  the engine by default and relied on the app to switch that off; these
  ones never bypass it, so a mistake in the authority layer can only *add*
  access that Frappe would have refused, never remove a check Frappe would
  have made.

## The trap worth recording

`frappe.has_permission` — the top-level function — does **not** accept
`print_logs`, while `frappe.permissions.has_permission` does.  Passing it
to the wrong one raises a `TypeError`, which a fail-closed checker catches
and turns into "denied" — so every write on the site is refused, and it
looks exactly like a permissions problem.

That is why the checker logs the exception as well as refusing.  A gate that
fails because of a renamed argument should be loud.
