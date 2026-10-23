# ADR-0008: Frappe decides who may chat and who may write

Status: **Accepted**
Date: 2026-10-21

## Context

The app used to keep its own permission layer on top of Frappe's:

* `Albanna Settings.chat_roles` — the roles that may use the chat.
* `Albanna Settings.widget_roles` — the roles that may see the widget.
* `Albanna Settings.allow_writes` — a site-wide switch for the write tools.
* `Albanna Settings.widget_enabled` — a duplicate of `enabled`.

None of these are things Frappe does not already do.  Frappe has a
permission matrix: every DocType carries rows that say which role may read,
write, create, delete it, and `if_owner` narrows a row to the document's
owner.  Keeping a second list of role names in the app's settings meant the
app's answer could disagree with the matrix, and it did: a role granted
read on `Albanna Conversation` in the matrix still could not chat until
somebody also typed its name into `chat_roles`, and a typo in that field
was silently ignored.

The user's statement of the principle: **we do not want to increase
complexity in the application or impose a restriction that makes the chat
and the artificial intelligence appear weak and unable to do what they
should.**  A chat that is weaker than the person in front of it, because
of a switch the operator forgot to flip, is exactly that.

## Decision

**The app keeps no permission switches.  Frappe's matrix decides.**

* **Chat access** is read permission on `Albanna Conversation`.  The app
  ships one role, `Albanna User`, with read, write, create and delete rows
  on that DocType, all `if_owner`, plus a `System Manager` row without
  `if_owner`.  `can_use_chat()` asks Frappe whether the session user holds
  read on it.  There is no list of role names.
* **Write-tool visibility** follows the caller's own rights: `create_doc`
  appears when the caller may create at least one DocType, and `update_doc`
  when they may change at least one.  There is no `allow_writes` switch.
* **The locked panel** names what is missing — the permission the account
  does not hold — rather than asking the operator to add a role to a
  setting.  The wording is the same shape the authority layer uses for a
  refused write: a fact about the organisation, with the roles that could.
* **`get_doc` checks read permission** with the document in hand, because
  `frappe.get_doc` applies no permission check at all.  This closes the
  hole where a Sales User read a Sales Invoice in full through the chat
  while `list_docs` refused it.

What is kept:

* `enabled` — the single site-wide kill switch for the chat.  It is not a
  permission; it is an operator's "the chat is off" decision, and it
  leaves the widget in its locked state so the reason is visible.

What is removed: `chat_roles`, `widget_roles`, `widget_enabled`,
`allow_writes`, `disabled_tools`.  The migration moves the old `chat_roles` values into the
new model by granting `Albanna User` to the users who held one of those
roles.

## Consequences

* **The operator grants the chat the way they grant anything else** —
  through the User form, by adding the `Albanna User` role.  No second
  screen, no field that can drift.
* **The chat is never weaker than the person in front of it.**  If a
  person can create a ToDo in the Desk, the assistant can create a ToDo
  for them, without anyone having to remember a switch.
* **`get_doc` no longer leaks row data** the caller may not read.
* **Existing sites migrate.**  A site that named `Desk User` in
  `chat_roles` keeps its Desk Users chatting; a site that named nothing
  keeps System Managers only, which the shipped rows already give them.
* **The locked message changed.**  It now names the missing permission
  rather than a setting to edit.  The Arabic catalogue carries the new
  wording.