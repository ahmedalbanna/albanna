"""Move the app's chat-role list into Frappe's permission matrix.

The app used to keep its own list of roles that may chat, in
``Albanna Settings.chat_roles``.  That list is now gone: the chat is
granted by a permission row on ``Albanna Conversation``, held by the
``Albanna User`` role.

So the roles that used to be named are granted the role instead.  A
site that named ``Desk User`` keeps its Desk Users chatting; a site that
named nothing is left with the shipped matrix, which is the gate.
"""

import frappe


def execute() -> None:
    # The field is dropped by this migration, so read it while it is
    # still there.  A Single stores its values in tabSingles, so the
    # "column" is a row there rather than a table column.
    try:
        raw = frappe.db.get_single_value("Albanna Settings", "chat_roles")
    except Exception:
        raw = None
        _ensure_role()
        return

    _ensure_role()

    if not raw:
        return

    names = _split_names(raw)
    if not names:
        return

    _grant_role_to_candidates(names)


def _split_names(raw) -> list[str]:
    names = []
    for part in str(raw).replace(",", "\n").split("\n"):
        part = part.strip()
        if part and part not in names:
            names.append(part)
    return names


def _grant_role_to_candidates(names: list[str]) -> None:
    candidates = _candidates_for(names)
    for email in candidates:
        _grant_role(email)
    frappe.db.commit()


def _candidates_for(names: list[str]) -> set[str]:
    candidates: set[str] = set()
    for role in names:
        if role in ("System Manager", "All"):
            continue
        try:
            rows = frappe.db.sql(
                "select distinct parent from `tabHas Role` where role = %s and parenttype = %s",
                (role, "User"),
                as_dict=True,
            )
        except Exception:
            rows = []
        for row in rows:
            candidates.add(row["parent"])
    return candidates


def _grant_role(email: str) -> None:
    try:
        user = frappe.get_doc("User", email)
        if "Albanna User" not in [r.role for r in (user.get("roles") or [])]:
            user.add_roles("Albanna User")
            user.save(ignore_permissions=True)
    except Exception:
        frappe.log_error(
            title="Albanna: could not grant Albanna User",
            message=str(email),
        )


def _ensure_role() -> None:
    if frappe.db.exists("Role", "Albanna User"):
        return

    role = frappe.new_doc("Role")
    role.role_name = "Albanna User"
    role.desk_access = 1
    role.flags.ignore_permissions = True
    role.insert(ignore_if_duplicate=True)
    frappe.db.commit()
