"""Conversations: creating them, appending to them, reading them, and
keeping them private.

Two decisions are worth stating, because both are visible in the code and
neither is obvious.

**Rows are written with direct SQL, not through the ORM.**  A conversation
is a list that grows by one turn at a time, and the ORM's way of adding a
child row is to load the parent, append, and save the parent — which
rewrites every row in the table on every turn.  A conversation with two
hundred messages would rewrite two hundred rows on every question.  The
rows are inserted instead, and the parent is updated with the handful of
fields that change.

**The parent grants the chat role, and the hooks narrow it.**  The
permission rows name ``Albanna User`` (``if_owner``) and ``System
Manager``; the permission hooks then decide who actually reaches a row.
Putting the rule in the doctype's permissions instead would mean granting
a role per user, which is not a thing a doctype can express -- so the
rows name the roles and the hooks do the narrowing.
"""

from __future__ import annotations

import json
import logging

import frappe
from frappe import _

from albanna.core.messages import Message, ToolCall

logger = logging.getLogger(__name__)

#: The parent field the message rows hang off.
PARENT_FIELD = "messages"

#: The title a conversation carries until it has a question to be named
#: after.  It is a *sentinel*, not a translation: the drawer renders its
#: own translated "New conversation" for a conversation with no title, and
#: the first question asked in a conversation replaces this with the
#: question itself.
PLACEHOLDER_TITLE = "New conversation"

#: How many messages a conversation keeps.  The model only ever sees the
#: last ``history_limit`` of them, so this is a storage bound rather than a
#: context bound.
MAX_STORED_MESSAGES = 400


def ensure_conversation(user: str, page: str = "", title: str = "") -> str:
    """Return the name of the user's conversation for *page*, creating it if needed.

    A conversation belongs to a page: the same question asked on the Sales
    Order list and on the Customer form are two different threads, because
    the context behind them is different.  The page identity is
    ``view|doctype|name``.
    """
    existing = frappe.db.get_value(
        "Albanna Conversation",
        {"user": user, "page": page or ""},
        "name",
        order_by="last_activity desc",
    )
    if existing:
        return existing

    return new_conversation(user, page=page, title=title)


def new_conversation(user: str, page: str = "", title: str = "") -> str:
    """Create a conversation for *page*, whether one exists there or not.

    ``ensure_conversation`` returns the page's conversation, because a
    page's context is the context behind every question asked on it.  This
    creates a *second* one on the same page, which is what the panel's
    "New" button means: a fresh thread on the same page, with the same
    context behind it and none of the previous thread's questions in it.

    The title is the placeholder, which the doctype puts there for any
    conversation with no title of its own.  A conversation is named after
    the question that started it, and the button is pressed before there
    is such a question; the first question that arrives names it.
    """
    doc = frappe.new_doc("Albanna Conversation")
    doc.user = user
    doc.page = page or ""
    doc.title = title or ""
    doc.last_activity = frappe.utils.now_datetime()
    doc.insert(ignore_permissions=True)
    return doc.name


def conversation_for_page(user: str, page: str = "") -> str:
    """The user's conversation for *page*, or an empty string.

    Unlike :func:`ensure_conversation` this does not create one: the
    panel asks what is there, and a page with no thread is a page with
    nothing to show.
    """
    return (
        frappe.db.get_value(
            "Albanna Conversation",
            {"user": user, "page": page or ""},
            "name",
            order_by="last_activity desc",
        )
        or ""
    )


def name_after_question(conversation: str, question: str) -> None:
    """Name a conversation after the question that started it.

    A conversation created by the "New" button has no title yet, because
    the button is pressed before there is a question to name it after.
    The first question that arrives in it is what the drawer should show,
    and that is the same rule ``ensure_conversation`` already follows.

    Only the placeholder is replaced: a conversation the user has renamed
    keeps the name they gave it.
    """
    title = (frappe.db.get_value("Albanna Conversation", conversation, "title") or "").strip()
    if title and title != PLACEHOLDER_TITLE:
        return

    name = " ".join(str(question or "").split())[:120]
    if not name:
        return

    frappe.db.set_value("Albanna Conversation", conversation, "title", name)


def append_messages(conversation: str, rows: list[dict]) -> list[tuple[str, str]]:
    """Append message rows to a conversation.

    Returns the rows it wrote, as ``(name, role)`` pairs, so that the
    caller can tell the browser what was stored.  A row that can be named
    is a row that can be addressed later.

    Each row is a dict with ``role``, ``content`` and optionally
    ``tool_name``, ``round_no`` and ``tool_calls``.

    The rows continue the conversation's existing order.  The index is *not*
    restarted at one: a conversation whose second turn is indexed from one
    again has two rows at every index, and a history ordered by that index
    interleaves the turns — so the model reads its own earlier answer as
    though it came *after* the question that prompted it, and then
    contradicts itself.
    """
    if not rows:
        return []

    now = frappe.utils.now()
    owner = frappe.session.user
    index = _next_index(conversation)
    written: list[tuple[str, str]] = []

    for row in rows:
        name = frappe.generate_hash(length=10)
        written.append((name, str(row.get("role") or "assistant")))
        frappe.db.sql(
            """
            insert into `tabAlbanna Message`
                (name, owner, creation, modified, modified_by, docstatus, idx,
                 parent, parentfield, parenttype,
                 role, content, tool_name, round_no, tool_calls)
            values
                (%s, %s, %s, %s, %s, 0, %s,
                 %s, %s, %s,
                 %s, %s, %s, %s, %s)
            """,
            (
                name,
                owner,
                now,
                now,
                owner,
                index,
                conversation,
                PARENT_FIELD,
                "Albanna Conversation",
                row.get("role") or "assistant",
                row.get("content") or "",
                row.get("tool_name") or "",
                int(row.get("round_no") or 0),
                row.get("tool_calls") or "",
            ),
        )
        index += 1

    frappe.db.set_value(
        "Albanna Conversation",
        conversation,
        {"last_activity": frappe.utils.now_datetime()},
        update_modified=False,
    )

    return written


def _next_index(conversation: str) -> int:
    """The index the next message row should take."""
    current = frappe.db.sql(
        """
        select coalesce(max(idx), 0)
        from `tabAlbanna Message`
        where parent = %s and parentfield = %s
        """,
        (conversation, PARENT_FIELD),
    )
    return int(current[0][0]) + 1 if current else 1


def load_messages(conversation: str, limit: int = 20) -> list[Message]:
    """The last *limit* messages of a conversation, oldest first.

    Only the tail is loaded.  A conversation with four hundred messages must
    not send four hundred messages to the model, and must not load them into
    memory to send twenty.

    The stored tool calls are the *executed* ones — the name of each tool,
    whether it worked, and what a write created.  The domain does not need
    their arguments: history is replayed with the tool calls stripped (see
    :func:`albanna.core.messages.as_plain_history`), because the assistant's
    own answer already says what it learned.
    """
    rows = frappe.db.sql(
        """
        select role, content, tool_name, tool_calls
        from `tabAlbanna Message`
        where parent = %s and parentfield = %s
        order by idx asc
        limit %s
        """,
        (conversation, PARENT_FIELD, int(limit) * 4),
        as_dict=True,
    )

    if len(rows) > limit:
        rows = rows[-limit:]

    messages: list[Message] = []
    for row in rows:
        role = row.role if row.role in ("user", "assistant", "tool") else "assistant"
        tool_calls: tuple[ToolCall, ...] = ()
        if row.tool_calls:
            try:
                raw = json.loads(row.tool_calls)
                tool_calls = tuple(
                    ToolCall(
                        id=str(item.get("id") or ""),
                        name=str(item.get("name") or ""),
                        arguments=item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
                    )
                    for item in (raw if isinstance(raw, list) else [])
                    if isinstance(item, dict) and item.get("name")
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                tool_calls = ()

        messages.append(
            Message(
                role=role,
                content=row.content or "",
                tool_calls=tool_calls,
                tool_call_id="",
            )
        )

    return messages


def load_transcript(conversation: str, limit: int = 50, before_idx: int = 0) -> list[dict]:
    """A window of a conversation, as the widget draws it.

    The shape the browser wants: a flat list of turns, each with the text
    and the tool calls that produced it.  The domain's
    :func:`load_messages` is not it, because the domain wants the *model's*
    view of a conversation and the widget wants the *person's*.

    The window is the newest *limit* messages, or the *limit* messages
    whose stored index is below *before_idx* when the client is walking
    back through the thread.

    **The window is bounded in the query.**  The reader used to load every
    message of a conversation and slice the list in Python, so the cost of
    a long thread was paid on every open — and the widget drew all of
    it.  A conversation of two hundred messages is twenty thousand nodes,
    and laying them out costs the better part of a second.
    """
    # The numbers are turned into numbers here as well as at the
    # endpoint: a caller that is not the endpoint — a job, a script —
    # would otherwise have to know that they arrive as strings.
    before_idx = int(before_idx or 0)
    limit = max(1, int(limit or 1))

    if before_idx > 0:
        rows = frappe.db.sql(
            """
            select name, role, content, tool_calls, creation, idx, rating
            from `tabAlbanna Message`
            where parent = %s and parentfield = %s and idx < %s
            order by idx desc
            limit %s
            """,
            (conversation, PARENT_FIELD, before_idx, limit),
            as_dict=True,
        )
    else:
        rows = frappe.db.sql(
            """
            select name, role, content, tool_calls, creation, idx, rating
            from `tabAlbanna Message`
            where parent = %s and parentfield = %s
            order by idx desc
            limit %s
            """,
            (conversation, PARENT_FIELD, limit),
            as_dict=True,
        )

    # The query reads backwards, because the tail is the window; the
    # transcript is read forwards, because that is how it was said.
    rows.reverse()

    transcript: list[dict] = []
    for row in rows:
        role = row.role if row.role in ("user", "assistant") else "assistant"
        tools: list[dict] = []
        if row.tool_calls:
            try:
                raw = json.loads(row.tool_calls)
                tools = [
                    {
                        "name": str(item.get("name") or ""),
                        "ok": bool(item.get("ok", True)),
                        "denied": bool(item.get("denied", False)),
                        "summary": str(item.get("summary") or ""),
                        "documents": _documents(item.get("documents")),
                    }
                    for item in (raw if isinstance(raw, list) else [])
                    if isinstance(item, dict) and item.get("name")
                ]
            except (json.JSONDecodeError, ValueError, TypeError):
                tools = []

        transcript.append(
            {
                # The row's own name, so that the widget can address this
                # message: a turn is removed by naming it, and a name is
                # stable where an index is not.
                "name": row.name,
                # The stored index, which is how the widget asks for the
                # page of messages behind this one.  It is the index and
                # not the position, because a transcript is spliced — a
                # retry removes the failed turn — and a position moves
                # when it is spliced.
                "idx": int(row.idx or 0),
                "role": role,
                "content": row.content or "",
                "rating": row.rating or "",
                "tools": tools,
                # When it was said, so that the transcript can say so.
                # The epoch is what the browser reads: the stored value is
                # a naive string written in the *site's* timezone, and a
                # browser reading it as its own would be wrong by hours.
                "creation_ts": _epoch(row.creation),
            }
        )

    return transcript


def transcript_window(conversation: str, limit: int = 50, before_idx: int = 0) -> dict:
    """A window of a conversation, and what is behind it.

    The window is what the widget draws.  ``has_more`` says whether older
    messages are still behind it, and ``total`` says how many the
    conversation holds — so the widget can offer "show the earlier
    messages" and the reader can know there are more.

    ``has_more`` is counted, not guessed: it is the number of messages
    older than the oldest one in the window, which is the question the
    button asks.
    """
    messages = load_transcript(conversation, limit, before_idx)

    total = frappe.db.sql(
        """
        select count(*) from `tabAlbanna Message`
        where parent = %s and parentfield = %s
        """,
        (conversation, PARENT_FIELD),
    )[0][0]

    oldest = min((int(message.get("idx") or 0) for message in messages), default=0)
    behind = 0
    if oldest > 0:
        behind = frappe.db.sql(
            """
            select count(*) from `tabAlbanna Message`
            where parent = %s and parentfield = %s and idx < %s
            """,
            (conversation, PARENT_FIELD, oldest),
        )[0][0]

    return {
        "messages": messages,
        "total": int(total),
        "has_more": bool(behind),
    }


def _documents(raw) -> list[dict[str, str]]:
    """The documents a stored tool call looked at.

    They were stored with the call, so that a conversation that is opened
    again links to the same documents the answer names.  A stored value
    that is not a list of documents is dropped rather than trusted.
    """
    if not isinstance(raw, list):
        return []

    documents = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        doctype = str(item.get("doctype") or "").strip()
        name = str(item.get("name") or "").strip()
        if doctype and name:
            documents.append({"doctype": doctype, "name": name})
    return documents


def display_title(title: str) -> str:
    """The title as the widget should be told it.

    The placeholder is a storage detail.  What the widget is told is that
    the conversation has no title yet, and the drawer renders its own
    translated "New conversation" for it.
    """
    text = (title or "").strip()
    return "" if text == PLACEHOLDER_TITLE else text


def list_conversations(user: str, limit: int = 20, offset: int = 0) -> list[dict]:
    """The user's conversations, most recent first.

    Each one carries ``last_activity_ts``: the moment as epoch seconds.

    The stored ``last_activity`` is a naive string — "2026-10-21 03:20:00" —
    with no timezone, so a browser in a different timezone from the server
    reads it as a different moment.  The epoch has no such ambiguity, and it
    is what the drawer formats.
    """
    rows = frappe.db.sql(
        """
        select name, title, page, model, last_activity
        from `tabAlbanna Conversation`
        where user = %s
        order by last_activity desc
        limit %s offset %s
        """,
        (user, int(limit), int(offset)),
        as_dict=True,
    )

    conversations = []
    for row in rows:
        conversation = dict(row)
        conversation["last_activity_ts"] = _epoch(conversation.get("last_activity"))
        conversation["title"] = display_title(conversation.get("title"))
        # Per-conversation totals, so the reader can see what a thread cost
        # them.  Aggregated in one query for the whole page, not per row.
        conversation["turns"] = 0
        conversation["tokens"] = 0
        conversation["cost"] = 0.0
        conversations.append(conversation)

    if conversations:
        names = tuple(c["name"] for c in conversations)
        placeholders = ", ".join(["%s"] * len(names))
        try:
            totals = frappe.db.sql(
                f"""
                select conversation,
                       count(*) as turns,
                       coalesce(sum(input_tokens), 0) + coalesce(sum(output_tokens), 0) as tokens,
                       coalesce(sum(cost), 0) as cost
                from `tabAlbanna Chat Log`
                where conversation in ({placeholders})
                group by conversation
                """,
                names,
                as_dict=True,
            )
        except Exception:
            totals = []
        by_name = {row["conversation"]: row for row in totals}
        for conversation in conversations:
            row = by_name.get(conversation["name"])
            if row:
                conversation["turns"] = int(row.get("turns") or 0)
                conversation["tokens"] = int(row.get("tokens") or 0)
                conversation["cost"] = float(row.get("cost") or 0.0)

    return conversations


def _epoch(value) -> float | None:
    """A naive timestamp as epoch seconds, or ``None``.

    The stored ``last_activity`` is a naive string written by
    ``frappe.utils.now_datetime()``, which is *the site's* timezone — and
    the site's timezone is not the operating system's, and on a site whose
    System Settings leave ``time_zone`` blank it is neither: Frappe falls
    back to Asia/Kolkata.

    So the naive string cannot be read with ``time.mktime`` (which would use
    the operating system's zone) or with the browser's ``new Date(string)``
    (which would use the reader's).  Both are wrong, and both are wrong by
    hours.  The conversion is done here, in the zone the string was written
    in, so the drawer says "2 minutes ago" wherever it is read from.
    """
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    try:
        import pytz
        from frappe.utils import get_datetime, get_system_timezone

        moment = get_datetime(str(value))
        if moment is None:
            return None
        return pytz.timezone(get_system_timezone()).localize(moment).timestamp()
    except Exception:
        logger.exception("Could not read the timestamp %r", value)
        return None


def assert_owns(conversation: str, user: str) -> str:
    """Refuse a conversation that is not the caller's.

    The conversation's rows are read with direct SQL, which does not go
    through the ORM and therefore does not consult the permission hooks.
    The hooks are the right place for *list views*; for a name handed in by
    a request, the check has to be explicit, or a caller who knows (or
    guesses) another user's conversation name can read their history.

    A System Manager is not exempt here: an administrator reading somebody
    else's chat is a different act from an administrator running the site,
    and the audit trail should not contain a conversation that nobody asked
    for.
    """
    if not conversation:
        frappe.throw(_("A conversation is required."), frappe.ValidationError)

    owner = frappe.db.get_value("Albanna Conversation", conversation, "user")
    if not owner:
        frappe.throw(_("That conversation does not exist."), frappe.DoesNotExistError)
    if owner != user:
        frappe.throw(
            _("That conversation belongs to somebody else."),
            frappe.PermissionError,
        )
    return conversation


def delete_turn(conversation: str, message: str) -> int:
    """Delete a turn: the question asked, and the answer that followed it.

    A turn is two rows — the question and the answer — and a reader who has
    been told something wrong, or who asked the wrong question, wants it
    gone rather than buried under the turns that came after it.  Asking
    the assistant to forget is not a thing it can do: the thread is what
    the model reads, so the row has to go.

    Either row of the turn may be named.  Naming the answer removes the
    question that led to it, because a turn is removed whole — an answer
    with no question is not a conversation.

    Returns the number of rows removed.
    """
    row = frappe.db.sql(
        """
        select name, role from `tabAlbanna Message`
        where name = %s and parent = %s and parentfield = %s
        """,
        (message, conversation, PARENT_FIELD),
        as_dict=True,
    )
    if not row:
        frappe.throw(_("That message does not exist."), frappe.DoesNotExistError)

    row = row[0]
    if row.role == "user":
        # The answer is the assistant row that came after it.
        partner = frappe.db.sql(
            """
            select name from `tabAlbanna Message`
            where parent = %s and parentfield = %s and role = 'assistant'
              and idx > (
                select idx from `tabAlbanna Message` where name = %s
              )
            order by idx asc limit 1
            """,
            (conversation, PARENT_FIELD, row.name),
        )
    else:
        # The question is the user row that came before it.
        partner = frappe.db.sql(
            """
            select name from `tabAlbanna Message`
            where parent = %s and parentfield = %s and role = 'user'
              and idx < (
                select idx from `tabAlbanna Message` where name = %s
              )
            order by idx desc limit 1
            """,
            (conversation, PARENT_FIELD, row.name),
        )

    names = [row.name] + [item[0] for item in partner]
    frappe.db.sql(
        "delete from `tabAlbanna Message` where name in %(names)s",
        {"names": tuple(names)},
    )
    return len(names)


def rate_message(conversation: str, message: str, rating: str) -> None:
    """Record the reader's rating of an answer.

    Only the caller's own conversations may be rated, and only assistant
    rows carry a rating.  A blank rating clears it.
    """
    assert_owns(conversation, frappe.session.user or "")

    if rating not in ("", "up", "down"):
        frappe.throw(_("That is not a rating."), frappe.ValidationError)

    row = frappe.db.sql(
        """
        select name, role from `tabAlbanna Message`
        where name = %s and parent = %s and parentfield = %s
        """,
        (message, conversation, PARENT_FIELD),
        as_dict=True,
    )
    if not row:
        frappe.throw(_("That message does not exist."), frappe.DoesNotExistError)
    if row[0]["role"] != "assistant":
        frappe.throw(_("Only answers can be rated."), frappe.ValidationError)

    frappe.db.set_value("Albanna Message", message, "rating", rating or None)


def rename_conversation(conversation: str, title: str) -> None:
    """Give a conversation a title of the user's choosing."""
    frappe.db.set_value(
        "Albanna Conversation",
        conversation,
        {"title": title},
        update_modified=False,
    )


def delete_conversation(conversation: str) -> None:
    """Delete a conversation and its messages."""
    frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (conversation,))
    frappe.delete_doc("Albanna Conversation", conversation, ignore_permissions=True, force=True)


def trim_conversation(conversation: str, keep: int = MAX_STORED_MESSAGES) -> None:
    """Drop the oldest messages once a conversation outgrows its bound."""
    count = frappe.db.sql(
        "select count(*) from `tabAlbanna Message` where parent = %s and parentfield = %s",
        (conversation, PARENT_FIELD),
    )[0][0]
    if count <= keep:
        return

    excess = count - keep
    frappe.db.sql(
        """
        delete from `tabAlbanna Message`
        where name in (
            select name from `tabAlbanna Message`
            where parent = %s and parentfield = %s
            order by idx asc limit %s
        )
        """,
        (conversation, PARENT_FIELD, excess),
    )


# -- permission hooks ----------------------------------------------------


def get_permission_query_conditions(user: str | None = None) -> str:
    """Restrict list views and reports to the caller's own conversations."""
    user = user or frappe.session.user
    if user == "Administrator" or "System Manager" in frappe.get_roles():
        return ""

    return f"`tabAlbanna Conversation`.`user` = {frappe.db.escape(user)}"


def has_permission(doc, user: str | None = None, ptype: str = "read") -> bool:
    """Allow the owner, and a System Manager, and nobody else."""
    user = user or frappe.session.user

    if user == "Administrator" or "System Manager" in frappe.get_roles():
        return True

    owner = doc.get("user") if hasattr(doc, "get") else getattr(doc, "user", "")
    return bool(owner) and owner == user
