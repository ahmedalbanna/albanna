"""The thread's own earlier messages, reachable by the model.

A long thread is worked on for days and the model sees only the last
``history_limit`` of it.  ADR-0052 made that gap *visible* — the prompt
carries the count of what sits behind the window.  This tool gives the
count hands: the model may reach the words behind the window instead of
asking the reader to repeat a decision they have already made.

The tool reads one thread only — the conversation the turn is running
in, supplied by the port's context and never by the model — and returns
the user/assistant rows the panel already draws, paged and labelled
with their absolute positions.  It is a read of what the reader can
already see, at the size the manifest's ``max_result_chars`` bounds.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from albanna.tools.base import ToolContext, tool_handler
from albanna.tools.base import translate as _

#: How many messages one call returns.  Twenty is a page the model can
#: quote from without the answer outrunning a tool round's budget; the
#: whole envelope is bounded again by the manifest's truncation.
PAGE_SIZE = 20

#: The most of any one message's text that reaches the model.  A long
#: answer quoted whole would eat the page on its own, and the model
#: needs the decision, not the essay around it.
MESSAGE_CEILING = 400


@tool_handler
def read_thread_history(
    search: str = "",
    page: int = 0,
    context: ToolContext | None = None,
) -> str:
    """Return a page of the thread's earlier messages.

    With no ``search``, the page is drawn from *behind the model's
    window* — page 0 is the twenty messages immediately behind the
    edge, and each page steps further back.  With a ``search``, the
    match runs over the whole thread from its first message.  Either
    way every message carries its absolute position in the thread, so
    the model can say where a quoted word came from, and the reader
    can find it.
    """
    if context is None:
        return _refusal(_('The history could not be read: no context was resolved for this call.'))

    conversation = (context.conversation or "").strip()
    if not conversation:
        return _refusal(_('The history could not be read: this call is not part of a conversation.'))

    from albanna.services.conversation_service import PARENT_FIELD, _like_pattern
    from albanna.services.settings_service import get_settings

    try:
        page = int(page or 0)
    except (TypeError, ValueError):
        return _refusal(_('The page must be a whole number, counting from zero.'))
    if page < 0:
        return _refusal(_('The page counts from zero.'))

    term = str(search or "").strip()
    window = max(1, int(get_settings().history_limit))

    thread_where = "parent = %s and parentfield = %s and role in ('user', 'assistant')"
    thread_params: list[Any] = [conversation, PARENT_FIELD]

    total = int(
        frappe.db.sql(
            f"select count(*) from `tabAlbanna Message` where {thread_where}",  # noqa: S608 - built from constants
            tuple(thread_params),
        )[0][0]
    )
    behind = max(0, total - window)

    if term:
        pattern = _like_pattern(term)
        matching = int(
            frappe.db.sql(
                f"""
                select count(*) from `tabAlbanna Message`
                where {thread_where} and content like %s escape '\\\\'
                """,  # noqa: S608 - built from constants
                tuple(thread_params + [pattern]),
            )[0][0]
        )
        rows = frappe.db.sql(
            f"""
            select role, content, pos
            from (
                select role, content,
                       row_number() over (order by idx) as pos
                from `tabAlbanna Message`
                where {thread_where}
            ) ranked
            where content like %s escape '\\\\'
            order by pos asc
            limit %s offset %s
            """,  # noqa: S608 - built from constants
            tuple(thread_params + [pattern, PAGE_SIZE, page * PAGE_SIZE]),
            as_dict=True,
        )
        pages = max(1, -(-matching // PAGE_SIZE))
        if page >= pages and matching:
            return _refusal(_('The page counts from zero; this search has {0} pages.').format(pages))
    else:
        matching = behind
        if not behind:
            return json.dumps(
                {
                    "status": "ok",
                    "message": (
                        f"The thread holds {total} messages and you can see the last {min(total, window)}: "
                        "there is nothing behind the window to reach."
                    ),
                    "data": {"total": total, "window": window, "behind": 0, "page": 0, "messages": []},
                    "hints": [],
                },
                default=str,
            )
        pages = max(1, -(-behind // PAGE_SIZE))
        if page >= pages:
            return _refusal(_('The page counts from zero; the thread has {0} pages behind the window.').format(pages))

        # The page's positions: the newest behind first, twenty at a
        # time — page 0 is positions B..B-19, page 1 the twenty before
        # those, and so on down to the thread's first message.
        high = behind - page * PAGE_SIZE
        low = max(1, high - PAGE_SIZE + 1)
        rows = frappe.db.sql(
            f"""
            select role, content, pos
            from (
                select role, content,
                       row_number() over (order by idx) as pos
                from `tabAlbanna Message`
                where {thread_where}
            ) ranked
            where pos between %s and %s
            order by pos asc
            """,  # noqa: S608 - built from constants
            tuple(thread_params + [low, high]),
            as_dict=True,
        )

    messages = [
        {
            "position": int(row.pos),
            "role": row.role,
            "content": _clip(row.content),
        }
        for row in rows
    ]

    if not messages:
        return json.dumps(
            {
                "status": "ok",
                "message": f"No message in this thread matches '{term}'.",
                "data": {"total": total, "window": window, "page": page, "messages": []},
                "hints": [],
            },
            default=str,
        )

    first = messages[0]["position"]
    last = messages[-1]["position"]
    if term:
        span = f"Messages {first}–{last} of {total} in the thread, matching '{term}'"
        more = last < total
    else:
        span = f"Messages {first}–{last} of {total} ({behind} behind the recent window)"
        more = first > 1

    hints = []
    if more:
        hints.append(f"There are earlier messages: call again with page={page + 1}.")
    hints.append("Quote the words you found and name the message they came from.")

    return json.dumps(
        {
            "status": "ok",
            "message": f"{span}. {_page_note(term)}",
            "data": {
                "total": total,
                "window": window,
                "behind": behind,
                "page": page,
                "messages": messages,
            },
            "hints": hints,
        },
        default=str,
    )


def _page_note(term: str) -> str:
    """One sentence about what the page holds, in the model's terms."""
    if term:
        return "Matching messages, oldest first; quote them and say which message each came from."
    return (
        "The messages behind what you can already see, oldest of this page "
        "first; each earlier page goes further back."
    )


def _clip(content: str) -> str:
    """The message's text at the ceiling, honest about the cut."""
    text = (content or "").strip()
    if len(text) <= MESSAGE_CEILING:
        return text
    return text[:MESSAGE_CEILING] + " …[this message is cut; the page's budget is the reason]"


def _refusal(reason: str) -> str:
    """The refusal shape every tool's handler answers with."""
    return json.dumps({"status": "refused", "message": reason, "data": None, "hints": []})
