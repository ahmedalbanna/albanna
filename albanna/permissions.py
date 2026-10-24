"""Who is asking, and what may they do.

This is the Frappe half of the authority story.  :mod:`albanna.core.authority`
decides whether a principal may reach a tool; this module decides three
things that come *before* that:

  * who the principal is (the session user, their roles),
  * whether they may use the chat at all,
  * whether they may create, change or read a given DocType.

The permission checker lives here rather than in ``core/`` because it calls
Frappe, and ``core/`` may not.

The chat gate is not a rule of this app's.  It is a permission row on
``Albanna Conversation``, read through the framework — so the operator
grants the chat the same way they grant anything else on the site, and the
answer cannot drift from what the permission matrix says.
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


def require_system_manager() -> None:
    """Refuse the call when the session user is not a System Manager.

    The counterpart to :func:`require_chat_access`: the chat's gate is
    about the reader, and this one is about the operator.  They are not
    the same question — a reader may use the chat without being allowed
    to know what the site spends on it — so they are not the same gate.
    """
    if not is_system_manager():
        frappe.throw(
            _("Only a System Manager may do that."),
            frappe.PermissionError,
        )


#: The DocType whose permission decides whether a person may chat.
#:
#: The app ships one role — ``Albanna User`` — with read, write, create and
#: delete rows on this DocType, every one of them ``if_owner``.  Read on it
#: is therefore the answer to "may this person use the chat", and it is the
#: *framework's* answer: the operator grants and withdraws it in the same
#: permission matrix they use for every other DocType on the site, and there
#: is no second list of role names in this app to fall out of step with it.
#:
#: ``if_owner`` is what keeps a conversation private once the person is in:
#: the row grants read, and the row also says whose.
CHAT_DOCTYPE = "Albanna Conversation"


def can_use_chat() -> bool:
    """True when the session user may start a conversation.

    Frappe answers this, not the app.  A person may chat when they hold
    read on :data:`CHAT_DOCTYPE`, which the app ships as the ``Albanna
    User`` role and an operator widens or narrows with the permission
    matrix.

    A System Manager is not a special case here, and does not need to be:
    the shipped rows grant them read outright, so the framework's own
    answer already covers them.  A special case would be a second rule
    that could disagree with the matrix, and the matrix is the one the
    operator can see.
    """
    user = frappe.session.user
    if not user or user == GUEST_USER:
        return False

    try:
        from frappe.permissions import has_permission as _has_permission

        return bool(_has_permission(CHAT_DOCTYPE, "read", print_logs=False))
    except Exception:
        logger.exception("Could not establish chat access for %s", user)
        return False


def require_chat_access() -> None:
    """Refuse the call when the session user may not use the chat.

    Every endpoint that carries a user's own data calls this first.  It is
    the same rule the connector used and for the same reason: a gate that
    some endpoints remember and others forget is a gate that fails open.

    The refusal names what is missing rather than only that something is.
    "You do not have access" is a wall; "reading Albanna Conversation is
    done by the Albanna User role" is a fact about the organisation that
    the person can act on, and it is the same sentence shape the authority
    layer uses for a refused write.
    """
    if can_use_chat():
        return

    roles = FrappePermissionChecker().roles_for(CHAT_DOCTYPE, "read")
    if roles:
        frappe.throw(
            frappe._(
                "You do not have access to the chat. Reading {0} is done by "
                "these roles: {1}."
            ).format(CHAT_DOCTYPE, ", ".join(roles)),
            frappe.PermissionError,
        )

    frappe.throw(
        frappe._(
            "You do not have access to the chat. No role on this site holds "
            "read on {0}."
        ).format(CHAT_DOCTYPE),
        frappe.PermissionError,
    )


def _doctypes_for_permission(user: str, ptype: str) -> list[str]:
    """The DocTypes this account holds *ptype* on.

    One query over the permission table, and it takes milliseconds.

    Only the rows at the top level count: a permission recorded at a deeper
    level (``permlevel``) is not the same right, and offering it as the way
    in would be wrong.
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
            f"where role in %s and `{ptype}` = 1 and permlevel = 0",
            (roles,),
        )
    except Exception:
        logger.exception("Could not read the %s DocTypes for %s", ptype, user)
        return []

    return sorted({str(name) for name in names if name})


def creatable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may create.

    The answer the assistant needs *before* it starts, so it does not spend
    a dozen calls discovering it.  A request to create a Sales Invoice,
    made by an account that has no Accounts role, is not going to work — and
    the assistant can know that in the first round if it is told.
    """
    return _doctypes_for_permission(user, "create")


def writable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may change.

    The same answer as :func:`creatable_doctypes`, asked about a different
    right, and for the same reason: a person who says "change the phone
    number on this customer" should not be answered with a refusal, and
    should not have to be told what they already know.

    This is a statement about *kinds* of document, not about particular
    ones.  A User Permission can still limit the account to some rows and
    not others, and when it does, the refusal says so.
    """
    return _doctypes_for_permission(user, "write")


def submittable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may submit."""
    return _doctypes_for_permission(user, "submit")


def cancellable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may cancel."""
    return _doctypes_for_permission(user, "cancel")


def amendable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may amend."""
    return _doctypes_for_permission(user, "amend")


def deletable_doctypes(user: str) -> list[str]:
    """The DocTypes this account may delete."""
    return _doctypes_for_permission(user, "delete")


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

    def can_write(self, doctype: str) -> bool:
        return self._has_permission(doctype, "write")

    def can_submit(self, doctype: str) -> bool:
        return self._has_permission(doctype, "submit")

    def can_cancel(self, doctype: str) -> bool:
        return self._has_permission(doctype, "cancel")

    def can_amend(self, doctype: str) -> bool:
        return self._has_permission(doctype, "amend")

    def can_delete(self, doctype: str) -> bool:
        return self._has_permission(doctype, "delete")

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
