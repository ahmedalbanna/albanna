"""Page context helpers for the widget.

The widget asks the server for small facts about the page the reader is
looking at, so that the empty state can offer questions that fit what is
actually there rather than questions that only fit in general.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna.permissions import require_chat_access


def _count_readable(doctype: str, filters: list | None = None) -> int:
    """How many documents of *doctype* the caller may read.

    The count is the one the list view shows: it goes through the same
    query, so the permission query conditions, the row-level rules and
    the ownership constraint all apply.

    A raw ``frappe.db.count`` counts every row on the table — including
    the ones the reader may not see — and the difference between the two
    is the difference between "you have three invoices" and "there are
    forty invoices and three are yours".  The second is a leak, and it
    is a leak in the one place the reader is least suspicious: a number
    in an empty state, offered before they have asked anything.
    """
    try:
        from frappe.model.db_query import DatabaseQuery

        rows = DatabaseQuery(doctype).execute(
            fields=[f"count(`tab{doctype}`.`name`) as total_count"],
            filters=filters or None,
            limit_page_length=0,
        )
    except Exception:
        return 0

    if not rows:
        return 0

    first = rows[0]
    try:
        return int(first.get("total_count") or 0)
    except AttributeError:
        return 0


@frappe.whitelist()
def count_doctype(doctype: str) -> dict[str, Any]:
    """How many documents of *doctype* the caller may see.

    Used by the empty state to decide whether to offer "create one" rather
    than "which are still open".  The count goes through Frappe's
    permission engine, so a user who may not read a DocType gets zero
    rather than an error — and a user who may read only some of the rows
    gets the count of those rows.
    """
    require_chat_access()

    doctype = (doctype or "").strip()
    if not doctype:
        return {"count": 0}

    try:
        from frappe.permissions import has_permission as _has_permission

        if not _has_permission(doctype, "read", print_logs=False):
            return {"count": 0}
    except Exception:
        return {"count": 0}

    return {"count": _count_readable(doctype)}


@frappe.whitelist()
def nudge_for_page(doctype: str) -> dict[str, Any]:
    """A non-intrusive nudge for the list page, if any.

    Returns ``{"message": "..."}`` or ``{"message": ""}``.  Only a small
    number of high-value cases are nudged, so the chat does not become a
    notification system.

    The number in the nudge is the caller's own count: a reader who may
    not see an invoice does not get told that one is overdue.
    """
    require_chat_access()

    doctype = (doctype or "").strip()
    if doctype not in ("Sales Invoice", "Purchase Invoice"):
        return {"message": ""}

    try:
        from frappe.permissions import has_permission as _has_permission

        if not _has_permission(doctype, "read", print_logs=False):
            return {"message": ""}
    except Exception:
        return {"message": ""}

    count = _count_readable(doctype, [["status", "=", "Overdue"]])

    if not count:
        return {"message": ""}

    return {
        "message": frappe._(
            "{0} overdue {1} — want me to draft reminders?",
            [count, doctype],
        )
    }
