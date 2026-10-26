"""Page context helpers for the widget.

The widget asks the server for small facts about the page the reader is
looking at, so that the empty state can offer questions that fit what is
actually there rather than questions that only fit in general.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna.permissions import require_chat_access


@frappe.whitelist()
def nudge_for_page(doctype: str) -> dict[str, Any]:
    """A non-intrusive nudge for the list page, if any.

    Returns ``{"message": "..."}`` or ``{"message": ""}``.  Only a small
    number of high-value cases are nudged, so the chat does not become a
    notification system.
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

    try:
        count = frappe.db.count(doctype, {"status": "Overdue"})
    except Exception:
        count = 0

    if not count:
        return {"message": ""}

    return {
        "message": frappe._(
            "{0} overdue {1} — want me to draft reminders?",
            [count, doctype],
        )
    }
    """How many documents of *doctype* the caller may see.

    Used by the empty state to decide whether to offer "create one" rather
    than "which are still open".  The count goes through Frappe's
    permission engine, so a user who may not read a DocType gets zero
    rather than an error.
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

    try:
        count = frappe.db.count(doctype)
    except Exception:
        count = 0

    return {"count": int(count or 0)}