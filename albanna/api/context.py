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


#: How many documents the hint names.  Three is enough for the reader to
#: recognise the row they meant, and few enough that the panel stays a
#: hint rather than a list.
NUDGE_NAMES = 3


def _readable_documents(
    doctype: str, filters: list | None = None, limit: int = NUDGE_NAMES
) -> list[dict[str, str]]:
    """The documents the caller may read, with the names the reader sees.

    The same query the count came from — the permission query conditions,
    the row-level rules and the ownership constraint all apply — so a name
    that appears here is a row the reader may open, and a row that does
    not appear is not theirs to see.  A count and a list of names drawn
    from two different queries would be two answers to the same question.

    Each document carries two names: its own ``name`` — the series it was
    filed under — and the DocType's title, which is what the reader sees
    in the list.  On an invoice the title is the customer, and the
    reader recognises the customer at a glance and the series by
    reference; carrying both lets the panel show either.

    The order is the DocType's own — the order of the list the reader is
    looking at — so the names are the first rows of that list rather than
    a sample from somewhere else.
    """
    try:
        from frappe.model.db_query import DatabaseQuery

        meta = frappe.get_meta(doctype)
        title_field = meta.get_title_field()
        fields = ["name"]
        if title_field and title_field != "name" and meta.has_field(title_field):
            fields.append(title_field)

        rows = DatabaseQuery(doctype).execute(
            fields=fields,
            filters=filters or None,
            limit_page_length=limit,
        )
    except Exception:
        return []

    documents: list[dict[str, str]] = []
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        title = ""
        if title_field and title_field != "name":
            title = str(row.get(title_field) or "").strip()
        documents.append({"name": name, "title": title})

    return documents


def _doctype_label(doctype: str) -> str:
    """The DocType's name, in the reader's language.

    ERPNext ships no Arabic catalogue of its own, so the two invoice
    names the hint uses are translated by the app's own catalogue.  They
    are written out rather than read from a table, so that the catalogue
    check can see that the app uses them — a translation nobody can see
    being used is a translation nobody knows is there.
    """
    if doctype == "Sales Invoice":
        return frappe._("Sales Invoice")
    if doctype == "Purchase Invoice":
        return frappe._("Purchase Invoice")
    return frappe._(doctype)


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


def _empty_nudge(doctype: str) -> dict[str, Any]:
    """The nudge when there is nothing to nudge about."""
    return {
        "message": "",
        "question": "",
        "doctype": doctype,
        "documents": [],
        "more": 0,
    }


@frappe.whitelist()
def nudge_for_page(doctype: str) -> dict[str, Any]:
    """A non-intrusive nudge for the list page, if any.

    Returns ``{"message": "...", "question": "...", "doctype": ...,
    "documents": [...], "more": 0}`` — or the same shape with an empty
    message, so that the caller never has to guess which keys are there.
    Only a small number of high-value cases are nudged, so the chat does
    not become a notification system.

    The number in the nudge is the caller's own count: a reader who may
    not see an invoice does not get told that one is overdue.  The names
    are the caller's own rows too, drawn from the same query as the
    count — a count with no names is a number the reader has to look up,
    and a name the reader may not see is a leak.

    The ``question`` is what the reader's "Go" button sends.  It is a
    question of its own, in the reader's language: the message is the
    chat's way of saying something, and a sentence that says "3 overdue
    Sales Invoice — want me to draft reminders?" is not a question the
    reader would have typed.
    """
    require_chat_access()

    doctype = (doctype or "").strip()
    if doctype not in ("Sales Invoice", "Purchase Invoice"):
        return _empty_nudge(doctype)

    try:
        from frappe.permissions import has_permission as _has_permission

        if not _has_permission(doctype, "read", print_logs=False):
            return _empty_nudge(doctype)
    except Exception:
        return _empty_nudge(doctype)

    count = _count_readable(doctype, [["status", "=", "Overdue"]])

    if not count:
        return _empty_nudge(doctype)

    documents = _readable_documents(doctype, [["status", "=", "Overdue"]])

    # The numbers go into the string *after* the translation, never
    # through it: ``frappe._`` takes a language as its second argument,
    # and it never fills a ``{0}`` on its own.  So the message is
    # translated first and formatted second — otherwise the reader is
    # shown ``{0} overdue {1}`` and the count is nowhere.  The DocType's
    # name is translated too, because an interface in Arabic that says
    # "Sales Invoice" is half in Arabic.
    return {
        "message": frappe._("{0} overdue {1} — want me to draft reminders?").format(
            count,
            _doctype_label(doctype),
        ),
        "question": frappe._("Can you draft reminders for the overdue invoices?"),
        "doctype": doctype,
        "documents": documents,
        "more": max(0, count - len(documents)),
    }
