"""Carrying out a turn's undo.

The *rules* live in :mod:`albanna.core.undo`, where they are pure and
testable; this module is the part that touches the documents.  A turn's
writes are taken back in reverse order — the last change first — and each
one is a single document action:

*   a creation is undone by deleting the document;
*   a change is undone by writing the old values back;
*   a submission is undone by cancelling the document.

Only calls that carried an undo entry *and* came from a tool that may be
undone are reverted.  Reads, refused writes, cancels, amends and deletes
are not undone at all: the app does not offer to take back what it
cannot honestly take back.

**The undo is spent once it has been carried out.**  The entry is taken
out of the message's stored tool calls, so the turn is not offered for
undo again — the change has been taken back, and a button that stays
would say it can be taken back twice.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import frappe

from albanna.core.undo import entry, is_undoable, spend

logger = logging.getLogger(__name__)


def undo_message(conversation: str, message: str) -> dict[str, Any]:
    """Take back the writes of one turn.

    Reads the tool calls stored on the message, reverts each write in
    reverse order, and reports what was taken back.  Only writes that
    carried an undo entry *and* came from a tool that may be undone are
    reverted; reads and refused writes are skipped.

    The undo stops at the first failure: the changes that were taken back
    stay taken back, and the failure goes to the log rather than to the
    reader, who is told that there is nothing left to undo.
    """
    calls = _stored_calls(conversation, message)
    if not calls:
        return {"undone": [], "status": "nothing to undo"}

    undone: list[dict[str, Any]] = []
    for call in reversed(calls):
        if not is_undoable(call):
            continue
        try:
            taken = _take_back(entry(call) or {})
        except Exception as exc:
            frappe.log_error(str(exc), "Albanna undo")
            break
        if taken:
            undone.append(taken)

    if undone:
        _spend(calls, undone, message)

    return {"undone": undone, "status": "ok" if undone else "nothing to undo"}


def _stored_calls(conversation: str, message: str) -> list[Any]:
    """The tool calls stored on a message."""
    row = frappe.db.sql(
        """
        select tool_calls from `tabAlbanna Message`
        where name = %s and parent = %s and parentfield = 'messages'
        """,
        (message, conversation),
        as_dict=True,
    )
    if not row or not row[0].get("tool_calls"):
        return []

    try:
        calls = frappe.parse_json(row[0]["tool_calls"]) or []
    except Exception:
        return []
    return calls if isinstance(calls, list) else []


def _take_back(undo: dict[str, Any]) -> dict[str, Any] | None:
    """Carry out one undo entry.

    Returns what was taken back, or nothing when there was nothing to
    take back — a document that was never submitted cannot be cancelled.
    """
    action = str(undo.get("action") or "").strip()
    doctype = str(undo.get("doctype") or "").strip()
    name = str(undo.get("name") or "").strip()

    if action == "delete":
        frappe.delete_doc(doctype, name, ignore_permissions=False)
        return {"action": "deleted", "doctype": doctype, "name": name}

    if action == "update":
        data = undo.get("data") or {}
        doc = frappe.get_doc(doctype, name)
        for field, value in data.items():
            doc.set(field, value)
        doc.save()
        return {"action": "reverted", "doctype": doctype, "name": name}

    if action == "cancel":
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.cancel()
            return {"action": "cancelled", "doctype": doctype, "name": name}

    return None


def _spend(calls: list[Any], undone: list[dict[str, Any]], message: str) -> None:
    """Take the spent entries out of the message's stored tool calls."""
    remaining = spend(calls, undone)
    frappe.db.sql(
        "update `tabAlbanna Message` set tool_calls = %s where name = %s",
        (json.dumps(remaining, default=str), message),
    )
