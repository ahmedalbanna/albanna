"""The question endpoints.

A question is asked by the assistant and answered by the reader, and the
two halves live on either side of a turn: the question is written during
the turn, and the answer is written by the reader afterwards, in their
own time, from wherever they are.

So these endpoints are about the *reader's* side of that, and every one of
them:

*   gates on chat access, and
*   touches only the questions the caller was asked.

The second point is not implied by the first.  A question names the
account it was asked of, and the endpoint that takes the answer refuses
anybody else's word for it — the same rule the write rail uses for an
approval, and for the same reason: the answer is acted on.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from albanna.permissions import require_chat_access
from albanna.services import questions as service


@frappe.whitelist()
def pending_questions(conversation: str = "") -> dict[str, Any]:
    """The questions the caller may still answer in this thread.

    The widget asks for them when it opens a conversation, because a
    question outlives the turn that asked it: the reader may close the
    tab, come back tomorrow, and answer it then.
    """
    require_chat_access()

    user = str(frappe.session.user or "")
    conversation = str(conversation or "").strip()
    if not conversation:
        return {"questions": []}

    from albanna.services.conversation_service import assert_owns

    assert_owns(conversation, user)

    return {"questions": service.pending(conversation, user)}


@frappe.whitelist()
def answer_question(name: str, value: str = "", values: Any = None) -> dict[str, Any]:
    """Record the reader's answer to a question.

    The answer must be one of the question's own options.  An answer the
    reader was never offered is not an answer to this question, and
    accepting it would put a value into the thread that the assistant
    did not ask about and the reader did not see.

    The first answer is the answer: a second click on a card whose
    answer has already been acted on is refused, not applied.
    """
    require_chat_access()

    user = str(frappe.session.user or "")
    parsed_values = None
    if values not in (None, ""):
        if isinstance(values, str):
            try:
                parsed_values = json.loads(values)
            except (TypeError, ValueError):
                parsed_values = [v.strip() for v in str(values).split(",") if v.strip()]
        elif isinstance(values, (list, tuple)):
            parsed_values = list(values)
    try:
        card = service.answer(str(name or ""), user, str(value or ""), values=parsed_values)
    except service.QuestionNotFound:
        frappe.throw(_("That question is not here."), frappe.DoesNotExistError)
    except service.NotTheReader:
        frappe.throw(_("That question was asked of somebody else."), frappe.PermissionError)
    except service.AlreadyAnswered:
        frappe.throw(_("That question has already been answered."), frappe.PermissionError)
    except service.QuestionCancelled:
        frappe.throw(_("That question is no longer waiting for an answer."), frappe.PermissionError)
    except service.NotAnOption:
        frappe.throw(_("That answer was not one of the options."), frappe.ValidationError)

    return {"question": card, "answer": card.get("answer_value", "")}
