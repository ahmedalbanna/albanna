"""The conversation endpoints.

The drawer in the widget lists the caller's conversations, opens one, and
lets them rename or delete it.  Every endpoint is about the *caller's own*
conversations, so every one of them:

*   gates on chat access, and
*   checks that the conversation it was handed belongs to the caller.

The second point is not implied by the first.  The permission hooks narrow
*list views*; a name that arrives in a request is checked explicitly, in
``assert_owns``, because the rows are read with direct SQL and the ORM's
permission engine never sees them.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from albanna.permissions import require_chat_access

#: How many conversations one listing returns.
PAGE_SIZE = 30

#: How many messages one transcript window holds.
#:
#: The widget draws a window and asks for the page behind it when the
#: reader wants more — a conversation of two hundred messages is twenty
#: thousand nodes, and drawing them all costs the better part of a
#: second every time the panel re-renders.
TRANSCRIPT_WINDOW = 50


def _as_int(value: Any, default: int = 0) -> int:
    """A number from the request, or *default*.

    The numbers in a request arrive as strings, and they have to be
    turned into numbers here: this module uses ``from __future__ import
    annotations``, so the framework's own type validation sees the
    annotations as strings and leaves the values alone.  Every endpoint
    that takes a number converts it for itself.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@frappe.whitelist()
def list_conversations(limit: int = PAGE_SIZE, offset: int = 0, search: str = "") -> dict:
    """The caller's conversations, most recent first."""
    require_chat_access()

    from albanna.services.conversation_service import list_conversations as _list

    conversations = _list(
        str(frappe.session.user or ""),
        limit=min(int(limit or PAGE_SIZE), PAGE_SIZE),
        offset=int(offset or 0),
        search=str(search or ""),
    )

    for conversation in conversations:
        conversation["preview"] = _preview(conversation["name"])

    return {"status": "ok", "conversations": conversations}


@frappe.whitelist()
def open_conversation(conversation: str = "", limit: int = 0, before_idx: int = 0) -> dict:
    """A window of a conversation's transcript.

    The window is the newest messages; the older ones are behind it, and
    *before_idx* asks for the page of them that sits below the index
    given.  The answer says how many messages the conversation holds and
    whether there are more behind the window, so the widget can offer
    them rather than hide them.
    """
    require_chat_access()

    from albanna.services.conversation_service import assert_owns, display_title, transcript_window

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    limit = _as_int(limit)
    before_idx = _as_int(before_idx)

    meta = frappe.db.get_value(
        "Albanna Conversation",
        conversation,
        ["name", "title", "page", "model", "last_activity"],
        as_dict=True,
    )

    conversation_meta = dict(meta) if meta else {}
    conversation_meta["title"] = display_title(conversation_meta.get("title"))

    window = transcript_window(conversation, limit or TRANSCRIPT_WINDOW, before_idx)

    return {
        "status": "ok",
        "conversation": conversation_meta,
        "messages": window["messages"],
        "total": window["total"],
        "has_more": window["has_more"],
    }


@frappe.whitelist()
def conversation_for_page(page: str = "", limit: int = 0, before_idx: int = 0) -> dict:
    """The caller's conversation on *page*, and its transcript.

    The panel asks this when it opens on a page.  The server resolves a
    page's conversation by page, so the thread the assistant will answer
    in is the page's thread — and the reader should be shown the same one
    rather than an empty panel that pretends the thread does not exist.

    Nothing is created: a page with no thread is a page with nothing to
    show, and that is an answer, not an error.
    """
    require_chat_access()

    from albanna.services.conversation_service import conversation_for_page as _for
    from albanna.services.conversation_service import display_title, transcript_window

    user = str(frappe.session.user or "")
    limit = _as_int(limit)
    before_idx = _as_int(before_idx)
    conversation = _for(user, page or "")
    if not conversation:
        return {
            "status": "ok",
            "conversation": "",
            "title": "",
            "messages": [],
            "total": 0,
            "has_more": False,
        }

    title = frappe.db.get_value("Albanna Conversation", conversation, "title") or ""
    window = transcript_window(conversation, limit or TRANSCRIPT_WINDOW, before_idx)
    return {
        "status": "ok",
        "conversation": conversation,
        "title": display_title(title),
        "messages": window["messages"],
        "total": window["total"],
        "has_more": window["has_more"],
    }


@frappe.whitelist()
def new_conversation(page: str = "") -> dict:
    """Start a new conversation on *page*.

    The panel's "New" button asks for this rather than clearing its own
    state.  Clearing the state alone would be a lie: the server resolves a
    page's conversation by page, so a "new" conversation with no id would
    land back in the thread the button was meant to leave, and the
    assistant would answer with the old thread's context.

    The new conversation has no title.  It is named after the first
    question asked in it, which is the same rule every other conversation
    follows.
    """
    require_chat_access()

    from albanna.services.conversation_service import new_conversation as _new

    user = str(frappe.session.user or "")
    conversation = _new(user, page or "")
    frappe.db.commit()

    return {"status": "ok", "conversation": conversation}


@frappe.whitelist()
def rename_conversation(conversation: str = "", title: str = "") -> dict:
    """Give a conversation a new title."""
    require_chat_access()

    from albanna.services.conversation_service import assert_owns
    from albanna.services.conversation_service import rename_conversation as _rename

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    title = " ".join(str(title or "").split())[:120]
    if not title:
        frappe.throw(_("A title is required."), frappe.ValidationError)

    _rename(conversation, title)
    frappe.db.commit()

    return {"status": "ok", "title": title}


@frappe.whitelist()
def toggle_pin(conversation: str = "", pinned: int = 0) -> dict:
    """Pin or unpin a conversation."""
    require_chat_access()

    from albanna.services.conversation_service import assert_owns
    from albanna.services.conversation_service import toggle_pin as _toggle

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    _toggle(conversation, bool(int(pinned or 0)))
    frappe.db.commit()

    return {"status": "ok"}


@frappe.whitelist()
def delete_turn(conversation: str = "", message: str = "") -> dict:
    """Remove a turn from a conversation: the question asked and the answer given.

    A turn is two rows, and they go together — an answer with no question is
    not a conversation.  Either row may be named.

    The transcript comes back with it, because a deletion moves everything
    after it: the caller should not have to ask twice to find out what the
    thread looks like now.
    """
    require_chat_access()

    from albanna.services.conversation_service import assert_owns, transcript_window
    from albanna.services.conversation_service import delete_turn as _delete

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    removed = _delete(conversation, message)
    frappe.db.commit()

    # The window the removal leaves behind, and whether there is more
    # behind it: the reader may have been reading further back, and the
    # button that shows it has to come back with it.
    window = transcript_window(conversation, TRANSCRIPT_WINDOW)

    return {
        "status": "ok",
        "removed": removed,
        "messages": window["messages"],
        "total": window["total"],
        "has_more": window["has_more"],
    }


@frappe.whitelist()
def rate_message(conversation: str = "", message: str = "", rating: str = "") -> dict:
    """Record the reader's rating of an answer: "up", "down", or "" to clear."""
    require_chat_access()

    from albanna.services.conversation_service import rate_message as _rate

    _rate(conversation, message, rating)
    frappe.db.commit()

    return {"status": "ok"}


@frappe.whitelist()
def escalate_conversation(conversation: str = "") -> dict:
    """Hand a conversation off to a human: create a Frappe Issue carrying
    the transcript, so a person can pick it up with full context.

    The conversation must belong to the caller.  The Issue is created as
    the caller, so Frappe's own permission engine applies.
    """
    require_chat_access()

    from albanna.services.conversation_service import (
        assert_owns,
        transcript_window,
    )

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    title = frappe.db.get_value("Albanna Conversation", conversation, "title") or ""
    subject = (title or "AI conversation").strip()[:140] or "AI conversation"

    window = transcript_window(conversation, limit=400, before_idx=0)
    messages = window.get("messages") or []

    lines = [f"# {subject}", "", "Escalated from an Albanna conversation.", ""]
    for message in messages:
        role = "User" if message.get("role") == "user" else "Assistant"
        content = (message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"**{role}:** {content}")
        lines.append("")

    description = "\n".join(lines).strip()

    issue = frappe.new_doc("Issue")
    issue.subject = subject
    issue.description = description
    issue.raised_by = user
    issue.insert()

    return {"issue": issue.name}


@frappe.whitelist()
def undo_turn(conversation: str = "", message: str = "") -> dict:
    """Undo the writes of one turn.

    Reads the tool calls stored on the message, reverts each write in
    reverse order, and reports what was undone.  Only writes that carried
    an ``undo`` entry are reverted; reads and refused writes are skipped.
    """
    require_chat_access()

    from albanna.services.conversation_service import assert_owns

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    row = frappe.db.sql(
        """
        select tool_calls from `tabAlbanna Message`
        where name = %s and parent = %s and parentfield = 'messages'
        """,
        (message, conversation),
        as_dict=True,
    )
    if not row or not row[0].get("tool_calls"):
        return {"undone": [], "status": "nothing to undo"}

    try:
        calls = frappe.parse_json(row[0]["tool_calls"]) or []
    except Exception:
        calls = []

    undone = []
    for call in reversed(calls):
        undo = call.get("undo") if isinstance(call, dict) else None
        if not undo or not isinstance(undo, dict):
            continue
        action = undo.get("action")
        doctype = str(undo.get("doctype") or "").strip()
        name = str(undo.get("name") or "").strip()
        if not doctype or not name:
            continue
        try:
            if action == "delete":
                frappe.delete_doc(doctype, name, ignore_permissions=False)
                undone.append({"action": "deleted", "doctype": doctype, "name": name})
            elif action == "update":
                data = undo.get("data") or {}
                if isinstance(data, dict) and data:
                    doc = frappe.get_doc(doctype, name)
                    for field, value in data.items():
                        doc.set(field, value)
                    doc.save()
                    undone.append({"action": "reverted", "doctype": doctype, "name": name})
            elif action == "cancel":
                doc = frappe.get_doc(doctype, name)
                if doc.docstatus == 1:
                    doc.cancel()
                    undone.append({"action": "cancelled", "doctype": doctype, "name": name})
        except Exception as exc:
            frappe.log_error(str(exc), "Albanna undo")
            break

    frappe.db.commit()
    return {"undone": undone, "status": "ok" if undone else "nothing to undo"}


def delete_conversation(conversation: str = "") -> dict:
    """Delete a conversation and its messages."""
    require_chat_access()

    from albanna.services.conversation_service import assert_owns
    from albanna.services.conversation_service import delete_conversation as _delete

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    _delete(conversation)
    frappe.db.commit()

    return {"status": "ok"}


def _preview(conversation: str, limit: int = 140) -> str:
    """The first question of a conversation, for the drawer's list.

    The list shows a title, which is the first question; the preview is the
    same text, clipped, for the moment before the title has been generated.
    """
    first = frappe.db.sql(
        """
        select content from `tabAlbanna Message`
        where parent = %s and parentfield = %s and role = 'user'
        order by idx asc limit 1
        """,
        (conversation, "messages"),
    )
    text = " ".join((first[0][0] if first else "").split())
    return text[:limit]
