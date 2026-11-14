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
    """The caller's conversations, most recent first.

    The preview — the first question of each thread — is gathered with
    the rest of the page's per-conversation facts, in one query for the
    whole page.  It used to be fetched one conversation at a time, so a
    page of the drawer cost thirty-one queries to say one thing.
    """
    require_chat_access()

    from albanna.services.conversation_service import list_conversations as _list

    conversations = _list(
        str(frappe.session.user or ""),
        limit=min(int(limit or PAGE_SIZE), PAGE_SIZE),
        offset=int(offset or 0),
        search=str(search or ""),
    )

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
def new_conversation(page: str = "") -> dict:
    """Start a new conversation.

    The panel's "New" button asks for this rather than clearing its own
    state.  Clearing the state alone would be a lie: the server resolves
    a turn with no id into the reader's most recent thread, so a "new"
    conversation with no id would land back in the thread the button was
    meant to leave, and the assistant would answer with the old thread's
    context.

    The new conversation carries no page.  A conversation belongs to the
    reader; the page they were on is context of the questions they ask,
    not of the thread that holds them.  The *page* argument is accepted
    and ignored, so a client that still sends it is not broken — but it
    is not stored, and nothing reads it.

    The new conversation has no title.  It is named after the first
    question asked in it, which is the same rule every other conversation
    follows.
    """
    require_chat_access()

    from albanna.services.conversation_service import new_conversation as _new

    user = str(frappe.session.user or "")
    conversation = _new(user)

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

    return {"status": "ok"}


@frappe.whitelist()
def escalate_conversation(conversation: str = "") -> dict:
    """Hand a conversation off to a human: create a Frappe Issue carrying
    the transcript, so a person can pick it up with full context.

    The conversation must belong to the caller.  The Issue is created as
    the caller, so Frappe's own permission engine applies.

    When the thread is anchored on an open Issue — the conversation's
    page identity is that ticket's form page — the handover lands on the
    ticket the reader is already in: a ToDo carrying the same
    transcript, not a second ticket for the same words (ADR-0103).  The
    caller must be allowed to write to *that Issue document*; a reader
    who may not is refused with the permission named.  Every other
    anchor — a list page, a report, a closed Issue — takes the original
    path.
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

    handover = _handover_text(subject, messages)

    issue_name = _issue_anchor(conversation)
    if issue_name:
        # The thread says it was born on a ticket.  Either the handover
        # lands on that ticket, or the reader is refused with the
        # permission named — a reader standing in a ticket is never
        # handed a *second* ticket as a side effect of being refused
        # (ADR-0103).  Only an anchor that is not a live, open ticket
        # falls through to the original path.
        issue_name = _handover_target(user, issue_name)
    if issue_name:
        todo, allocated_to = _handover_todo(user, issue_name, subject, handover)
        return {"todo": todo, "issue": issue_name, "allocated_to": allocated_to}

    issue = frappe.new_doc("Issue")
    issue.subject = subject
    issue.description = handover
    issue.raised_by = user
    issue.insert()

    return {"issue": issue.name}


def _issue_anchor(conversation: str) -> str:
    """The Issue this thread was born on, when it was born on one.

    The panel's page identity is ``form|<doctype>|<name>`` for a form
    page and the route itself for everything else, so the doctype decides
    and the route never pretends to be a ticket.
    """
    page = str(frappe.db.get_value("Albanna Conversation", conversation, "page") or "")
    parts = page.split("|")
    if len(parts) == 3 and parts[0] == "form" and parts[1] == "Issue":
        return parts[2]
    return ""


def _handover_target(user: str, issue_name: str) -> str:
    """The ticket the handover may land on, or the refusal, or nothing.

    Returns the Issue's name when the anchor is a live, open ticket this
    reader may read; ``""`` when the anchor is not a destination — the
    ticket is gone, or closed — so the caller falls through to the
    original new-Issue path; and raises :class:`frappe.PermissionError`
    naming the missing right when the ticket is live and open but the
    reader may not even see it.

    The gate is the one the framework's own assignment UI applies:
    ``frappe.desk.form.assign_to.add`` gates on the *reference
    document's* permission and inserts the ToDo bypassing the ToDo's own
    — because ToDo's controller hook admits only the roles explicitly
    granted on ToDo, and by default that is System Manager alone.  A
    handover onto a ticket is an assignment; its gate is the ticket.

    The framework's gate is *read*, and this endpoint matches it: the
    handover changes the ticket's assignment state, which is exactly
    what the Desk's assign panel changes for a reader who can open the
    ticket.
    """
    if not frappe.db.exists("Issue", issue_name):
        return ""
    status = str(frappe.db.get_value("Issue", issue_name, "status") or "")
    if status == "Closed":
        return ""
    issue = frappe.get_doc("Issue", issue_name)
    if not frappe.has_permission("Issue", "read", doc=issue, user=user):
        raise frappe.PermissionError(
            _(
                "You may not read this ticket, so the conversation cannot be handed over on it."
            )
        )
    return issue_name


def _handover_todo(
    user: str, issue_name: str, subject: str, handover: str
) -> tuple[str, str]:
    """The ToDo that carries the handover, and who it went to.

    The assignee is the Issue's existing assignee — read from the open
    assignment ToDos the assignment system writes, the one source there
    is.  Nobody assigned means an unallocated ToDo and an honest answer:
    the endpoint's reply says ``allocated_to: ""``, and the way forward is
    the ticket's own assignment UI.
    """
    assigned = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": "Issue",
            "reference_name": issue_name,
            "allocated_to": ("is", "set"),
        },
        order_by="creation desc",
        limit_page_length=1,
        pluck="allocated_to",
    )
    allocated_to = str(assigned[0]) if assigned else ""

    todo = frappe.new_doc("ToDo")
    todo.description = f"# {subject}\n\n{handover}"
    todo.reference_type = "Issue"
    todo.reference_name = issue_name
    if allocated_to:
        todo.allocated_to = allocated_to
    # The framework's own assignment path inserts the ToDo with the
    # ToDo's own permission checks bypassed
    # (``frappe.desk.form.assign_to.add``), because ToDo's controller
    # hook admits only the roles explicitly granted on ToDo — System
    # Manager, by default — and assignment would otherwise be an
    # admin-only act.  The gate this endpoint applies is the reference
    # document's (``_handover_target``); the ToDo itself follows the
    # framework's practice, and is recorded as created by the caller.
    todo.flags.ignore_permissions = True
    todo.insert()

    return todo.name, allocated_to


def _handover_text(subject: str, messages: list[dict]) -> str:
    """The handover block both escalation shapes carry.

    One builder for the Issue path and the ToDo path: a handover whose
    two shapes drift apart is a handover the person picking it up cannot
    trust to be the whole truth.
    """
    lines = [f"# {subject}", "", "Escalated from an Albanna conversation.", ""]
    for message in messages:
        role = "User" if message.get("role") == "user" else "Assistant"
        content = (message.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"**{role}:** {content}")
        tool_lines = _tool_lines(message.get("tools") or [])
        if tool_lines:
            # The calls sit under the answer that made them, and a
            # blank line separates the two: a list that runs straight on
            # from the sentence above it reads as part of the answer.
            lines.append("")
            lines.extend(tool_lines)
        lines.append("")

    return "\n".join(lines).strip()


def _tool_lines(tools: list[dict]) -> list[str]:
    """What the assistant did, as lines under the answer that did it.

    A hand-off that carries the questions and the answers and not the
    tool calls is a hand-off the human has to reconstruct by re-running
    the conversation — and the tool calls are the part that says what
    the assistant *read* and what it *changed*.  So each call is a line
    of its own, carrying the summary the transcript already stores: the
    summary is written for a human, and it is the informative version —
    "Read Sales Order 'SAL-ORD-00042'" rather than a count of calls.

    The tool's own name is not on the line.  ``get_doc`` is the model's
    name for the call and not the reader's, and the summary already
    says what was read and what was changed.

    A call with no summary is skipped rather than rendered as an empty
    bullet: a line that says nothing is worse than no line.

    A refused call is marked, because a refusal and a failure read
    alike and they are different facts.  A refusal says the *account*
    may not do it — a fact about the organisation, and the one the
    person picking the ticket up most needs to know, because it is the
    difference between "the assistant did not find it" and "the
    assistant was not allowed to look".
    """
    lines = []
    for tool in tools:
        summary = str(tool.get("summary") or "").strip()
        if not summary:
            continue
        if tool.get("denied"):
            lines.append(f"  · **refused:** {summary}")
        elif not tool.get("ok", True):
            lines.append(f"  · **failed:** {summary}")
        else:
            lines.append(f"  · {summary}")
    return lines


@frappe.whitelist()
def undo_turn(conversation: str = "", message: str = "") -> dict:
    """Undo the writes of one turn.

    The rules live in :mod:`albanna.core.undo`, and the carrying-out of
    them in :mod:`albanna.services.undo` — so that the endpoint that
    undoes and the transcript that offers can never disagree about what
    may be taken back.

    The transcript comes back with it, because an undo changes what the
    turn can still be asked to do: a turn that has been undone has nothing
    left to take back, and the reader must not be offered a button for it
    again.
    """
    require_chat_access()

    from albanna.services.conversation_service import assert_owns, transcript_window
    from albanna.services.undo import undo_message

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    result = undo_message(conversation, message)

    window = transcript_window(conversation, TRANSCRIPT_WINDOW)

    return {
        "status": result.get("status") or "nothing to undo",
        "undone": result.get("undone") or [],
        "messages": window["messages"],
        "total": window["total"],
        "has_more": window["has_more"],
    }


@frappe.whitelist()
def delete_conversation(conversation: str = "") -> dict:
    """Delete a conversation and its messages."""
    require_chat_access()

    from albanna.services.conversation_service import assert_owns
    from albanna.services.conversation_service import delete_conversation as _delete

    user = str(frappe.session.user or "")
    assert_owns(conversation, user)

    _delete(conversation)

    return {"status": "ok"}
