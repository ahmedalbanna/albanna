"""Who is asking, and what may they do.

This is the Frappe half of the authority story.  :mod:`albanna.core.authority`
decides whether a principal may reach a tool; this module decides three
things that come *before* that:

  * who the principal is (the session user, their roles),
  * whether they may use the chat at all,
  * whether they may create or read a given DocType.

The permission checker lives here rather than in ``core/`` because it calls
Frappe, and ``core/`` may not.
"""

from __future__ import annotations

import logging

import frappe
from frappe import _

from albanna.core.authority import Principal

logger = logging.getLogger(__name__)

#: Frappe's guest user.  A guest has no roles, no identity and no history.
GUEST_USER = "Guest"


def is_system_manager() -> bool:
    """True when the session user is a System Manager."""
    try:
        return "System Manager" in frappe.get_roles()
    except Exception:
        return False


def chat_roles() -> set[str]:
    """The roles allowed to use the chat.

    Read from the settings, which is where the operator sets them.  An empty
    set means "System Managers only" — the default that a freshly installed
    app should have, because a side chat that can create documents should
    not be open to every account on the site by accident.
    """
    from albanna.services.settings_service import get_settings

    return set(get_settings().chat_roles)


def can_use_chat() -> bool:
    """True when the session user may start a conversation."""
    user = frappe.session.user
    if not user or user == GUEST_USER:
        return False

    if is_system_manager():
        return True

    allowed = chat_roles()
    if not allowed:
        return False

    try:
        roles = set(frappe.get_roles())
    except Exception:
        return False

    return bool(allowed & roles)


def require_chat_access() -> None:
    """Refuse the call when the session user may not use the chat.

    Every endpoint that carries a user's own data calls this first.  It is
    the same rule the connector used and for the same reason: a gate that
    some endpoints remember and others forget is a gate that fails open.
    """
    if not can_use_chat():
        frappe.throw(
            _("You do not have access to the chat. Ask an administrator to add your role."),
            frappe.PermissionError,
        )


def creatable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may create.

    The answer the assistant needs *before* it starts, so it does not spend
    a dozen calls discovering it.  A request to create a Sales Invoice,
    made by an account that has no Accounts role, is not going to work — and
    the assistant can know that in the first round if it is told.

    One query over the permission table, and it takes milliseconds.
    """
    try:
        roles = tuple(set(frappe.get_roles(user)) - {"Guest", "All"})
    except Exception:
        return []
    if not roles:
        return []

    try:
        names = frappe.db.sql_list(
            "select distinct parent from tabDocPerm "
            "where role in %s and `create` = 1 and permlevel = 0",
            (roles,),
        )
    except Exception:
        logger.exception("Could not read the creatable DocTypes for %s", user)
        return []

    return sorted({str(name) for name in names if name})


def current_principal() -> Principal:
    """The person this request is for."""
    user = frappe.session.user
    try:
        roles = frozenset(frappe.get_roles())
    except Exception:
        roles = frozenset()
    return Principal(user=user, roles=roles, is_system_manager=is_system_manager())


class FrappePermissionChecker:
    """Answers document-level permission questions through Frappe.

    Both methods fail closed: an exception inside Frappe's permission engine
    is a "no", not a "yes".  The authority layer treats a refusal as the
    answer and does not need to distinguish "denied" from "could not tell".

    The failure is *logged* as well as refused.  A checker that raises
    because of a programming error — a renamed argument, a changed API —
    would otherwise deny every write on the site and look exactly like a
    permissions problem, which is the hardest kind of bug to see.
    """

    def can_create(self, doctype: str) -> bool:
        return self._has_permission(doctype, "create")

    def can_read(self, doctype: str) -> bool:
        return self._has_permission(doctype, "read")

    def roles_for(self, doctype: str, ptype: str) -> list[str]:
        """The roles that hold *ptype* on *doctype*.

        Read from the DocType's own permission rows, so the answer is the
        organisation's own and not a copy of it.  Only the rows that apply at
        the top level count: a permission recorded at a deeper level
        (``permlevel``) is not the same right, and offering it as the way in
        would be wrong.

        An empty list means the DocType has no such permission recorded,
        which is itself the answer: nothing can do it.
        """
        if not doctype or not str(doctype).strip():
            return []
        try:
            meta = frappe.get_meta(str(doctype).strip())
        except Exception:
            return []

        roles = []
        for row in meta.permissions or []:
            if not row.get(ptype):
                continue
            if int(row.get("permlevel") or 0) != 0:
                continue
            role = str(row.get("role") or "").strip()
            if role and role not in roles:
                roles.append(role)
        return roles

    @staticmethod
    def _has_permission(doctype: str, ptype: str) -> bool:
        if not doctype or not str(doctype).strip():
            return False
        try:
            # `frappe.permissions.has_permission` rather than the shorter
            # `frappe.has_permission`: the top-level one has no
            # `print_logs`, and passing it raises a TypeError — which the
            # `except` below would turn into a silent refusal of every
            # write.
            import frappe.permissions

            return bool(
                frappe.permissions.has_permission(
                    str(doctype).strip(), ptype, print_logs=False
                )
            )
        except Exception:
            logger.exception("Permission check failed for %s (%s)", doctype, ptype)
            return False
