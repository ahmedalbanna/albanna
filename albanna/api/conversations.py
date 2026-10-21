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

import frappe
from frappe import _

from albanna.permissions import require_chat_access

#: How many conversations one listing returns.
PAGE_SIZE = 30


@frappe.whitelist()
def list_conversations(limit: int = PAGE_SIZE, offset: int = 0) -> dict:
    """The caller's conversations, most recent first."""
    require_chat_access()

    from albanna.services.conversation_service import list_conversations as _list

    user = str(frappe.session.user or "")
    conversations = _list(user, limit=min(int(limit or PAGE_SIZE), PAGE_SIZE), offset=int(offset or 0))

    for conversation in conversations:
        conversation["preview"] = _preview(conversation["name"])

    return {"status": "ok", "conversations": conversations}


@frappe.whitelist()
def open_conversation(conversation: str = "") -> dict:
    """A conversation's transcript."""
    require_chat_access()

    from albanna.services.conversation_service import assert_owns, load_transcript

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    meta = frappe.db.get_value(
        "Albanna Conversation",
        conversation,
        ["name", "title", "page", "model", "last_activity"],
        as_dict=True,
    )

    return {
        "status": "ok",
        "conversation": dict(meta) if meta else {},
        "messages": load_transcript(conversation),
    }


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
