"""A question the assistant asked the reader, and the answer the reader gave.

The assistant runs out of road in one way only: it needs something the
reader has and it does not — which customer, which item, which of two
ways.  The only way to get it was for the reader to *type* it, which
means the reader has to know the names, and the names are usually what
the assistant was looking for when it asked.

So the question is asked as a question.  The assistant offers the answers
it found, the reader picks one, and the thread carries on.

Three things make this honest, and they are the whole of this module.

**The question is a row, not a cache entry.**  The reader may answer it
minutes later, from another tab, tomorrow.  A record that expires while
the reader is thinking has thrown the question away, and the assistant
is left waiting for an answer to a question that no longer exists.  The
approval is different — it is bounded by the wait it answers — and it
lives in the cache for that reason.

**Only the reader may answer.**  The question names the account it was
asked of, and the endpoint that takes the answer refuses anybody else's
word for it.  The same rule the write rail uses for an approval, and for
the same reason: the answer is acted on.

**The first answer is the answer.**  A second click on a card whose
answer has already been acted on is refused rather than applied.
"""

from __future__ import annotations

import frappe

#: The states a question can be in.
PENDING = "Pending"
ANSWERED = "Answered"
CANCELLED = "Cancelled"

#: The most options one question may carry.
#:
#: A card with a hundred buttons is a list, not a choice.  The limit is
#: the app's, not the model's: the assistant is told to offer the
#: answers that matter, and to ask again — with a narrower set — when
#: the reader's answer is not among them.
MAX_OPTIONS = 50


class QuestionNotFound(Exception):
    """No question by that name."""


class NotTheReader(Exception):
    """This question was asked of somebody else."""


class AlreadyAnswered(Exception):
    """This question has already been answered."""


class NotAnOption(Exception):
    """That answer was not one of the question's options."""


# -- asking ---------------------------------------------------------------


def ask(
    conversation: str,
    user: str,
    question: str,
    options: list[dict] | None,
    turn: str = "",
) -> dict:
    """Record a question, and return the card the reader will be shown.

    The options are the answers the reader may choose from.  Each one
    carries two things: what the reader sees, and the value behind it —
    the document's name, the field value — because the assistant goes on
    to use the value and the reader goes on to see the label.

    An option with no value is dropped rather than half-kept: a card
    that offers an answer the assistant cannot use is a card that wastes
    the reader's time.
    """
    text = str(question or "").strip()
    if not text:
        raise ValueError("A question needs a question.")

    rows = []
    seen: set[str] = set()
    for option in options or []:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "").strip()
        value = str(option.get("value") or label).strip()
        if not label or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        rows.append({"label": label, "value": value})
        if len(rows) >= MAX_OPTIONS:
            break

    if not rows:
        raise ValueError("A question needs at least one answer to choose from.")

    document = frappe.new_doc("Albanna Question")
    document.question = text
    document.conversation = conversation or ""
    document.user = user or frappe.session.user
    document.turn = turn or ""
    document.status = PENDING
    document.asked_at = frappe.utils.now()
    for row in rows:
        document.append("options", row)
    document.insert(ignore_permissions=True)

    return payload(document)


# -- answering ------------------------------------------------------------


def answer(name: str, user: str, value: str) -> dict:
    """Record the reader's answer to a question.

    The answer must be one of the question's own options: an answer the
    reader was never offered is not an answer to this question, and
    accepting it would put a value into the thread that the assistant
    did not ask about and the reader did not see.
    """
    document = _the_question(name)

    if document.user and document.user != user:
        raise NotTheReader()

    if document.status != PENDING:
        raise AlreadyAnswered()

    chosen = str(value or "").strip()
    match = None
    for option in document.get("options") or []:
        if str(option.get("value") or "") == chosen:
            match = option
            break
    if match is None:
        raise NotAnOption()

    document.status = ANSWERED
    document.answer = str(match.get("label") or "")
    document.answer_value = str(match.get("value") or "")
    document.answered_by = user or frappe.session.user
    document.answered_at = frappe.utils.now()
    document.save(ignore_permissions=True)

    return payload(document)


def pending(conversation: str, user: str) -> list[dict]:
    """The questions this reader may still answer in this thread."""
    names = frappe.get_all(
        "Albanna Question",
        filters={"conversation": conversation or "", "user": user or "", "status": PENDING},
        pluck="name",
        order_by="asked_at asc",
    )
    if not names:
        return []

    # Two queries, not one per question.  A thread can hold several
    # questions the reader has not answered yet, and loading each one's
    # options on its own turns a listing into a crawl.
    rows = frappe.get_all(
        "Albanna Question",
        filters={"name": ["in", names]},
        fields=[
            "name",
            "question",
            "status",
            "answer",
            "answer_value",
            "conversation",
            "asked_at",
            "answered_at",
        ],
        order_by="asked_at asc",
    )
    options = _options_of(names)

    return [payload(row, options.get(str(row.get("name") or ""), [])) for row in rows]


def _options_of(names: list[str]) -> dict[str, list[dict]]:
    """The options of several questions, in one query."""
    rows = frappe.get_all(
        "Albanna Question Option",
        filters={"parent": ["in", names]},
        fields=["parent", "label", "value"],
        order_by="idx asc",
    )

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("parent") or ""), []).append(
            {
                "label": str(row.get("label") or ""),
                "value": str(row.get("value") or ""),
            }
        )
    return grouped


def _the_question(name: str):
    """The question by name, or a refusal."""
    if not name:
        raise QuestionNotFound()
    try:
        document = frappe.get_doc("Albanna Question", name)
    except frappe.DoesNotExistError as exc:
        raise QuestionNotFound() from exc
    return document


# -- the card -------------------------------------------------------------


def payload(document, options: list[dict] | None = None) -> dict:
    """The card's shape, as the browser is given it.

    It takes a document or a row of a listing: the pending list reads
    its rows with one query and hands them here with their options
    already collected.
    """

    def field(name: str) -> str:
        if isinstance(document, dict):
            return str(document.get(name) or "")
        return str(getattr(document, name, "") or "")

    if options is None:
        options = [
            {
                "label": str(option.get("label") or ""),
                "value": str(option.get("value") or ""),
            }
            for option in (getattr(document, "options", None) or [])
        ]

    return {
        "name": field("name"),
        "question": field("question"),
        "options": options,
        "status": field("status") or PENDING,
        "answer": field("answer"),
        "answer_value": field("answer_value"),
        "conversation": field("conversation"),
        "asked_at": field("asked_at"),
        "answered_at": field("answered_at"),
    }


# -- permission hooks -----------------------------------------------------
#
# The same two hooks the conversation has, and for the same reason: the
# permission rows grant the role, and these hooks narrow the rows to the
# account that owns them.  A question is as private as the thread it was
# asked in — it names what the assistant was looking for, and what the
# reader is being asked to choose.


def get_permission_query_conditions(user: str | None = None) -> str:
    """Restrict list views and reports to the reader's own questions."""
    user = user or frappe.session.user
    if user == "Administrator":
        return ""

    return f"`tabAlbanna Question`.`user` = {frappe.db.escape(user)}"


def has_permission(doc, user: str | None = None, ptype: str = "read") -> bool:
    """Allow the reader, and nobody else."""
    user = user or frappe.session.user

    if user == "Administrator":
        return True

    owner = doc.get("user") if hasattr(doc, "get") else getattr(doc, "user", "")
    return bool(owner) and owner == user
