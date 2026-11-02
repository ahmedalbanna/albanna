"""The question the assistant asks the reader.

This tool does not act on the site's data.  It acts on the conversation:
it puts a question in front of the reader, with the answers it found, and
leaves the turn there.  The reader's choice comes back as their next
message, and the assistant carries on with the whole thread in view.

The tool is a tool like any other — it is in the manifest, the model
calls it by name, and it travels over whatever backend the app is using.
An MCP backend would serve it without a line changing here, because the
port's context carries the conversation the question belongs to.

Two rules make the question honest, and both live in the service this
tool calls:

*   the question is a row, so it outlives the turn that asked it, and
*   only the reader it was asked of may answer it.
"""

from __future__ import annotations

import json
from typing import Any

from albanna.tools.base import ToolContext


def ask_question(
    question: str,
    options: list[dict[str, Any]],
    multiple: bool = False,
    context: ToolContext | None = None,
) -> str:
    """Ask the reader a question, and wait for their answer in the chat.

    The options are the answers the reader may choose from.  Each one
    carries two things: what the reader sees, and the value behind it —
    the document's name, the field value — because the assistant goes on
    to use the value while the reader goes on to see the label.

    The answer is not in this result, and that is the point: the reader
    has not answered yet.  What is in this result is the question, so
    that the card the reader is shown and the question the assistant
    asked are the same question.
    """
    from albanna.services.questions import ask as ask_the_reader

    if context is None:
        return _refusal("The question could not be asked: no context was resolved for this call.")

    conversation = (context.conversation or "").strip()
    if not conversation:
        return _refusal("The question could not be asked: this call is not part of a conversation.")

    try:
        card = ask_the_reader(
            conversation=conversation,
            user=context.principal.user,
            question=question,
            options=options,
            turn=context.request_id,
            multiple=bool(multiple),
        )
    except ValueError as exc:
        return _refusal(str(exc))

    return json.dumps(
        {
            "status": "ok",
            "message": (
                "The question has been asked and is waiting for the reader's "
                "answer. Do not answer it yourself, and do not call any more "
                "tools: say what you need, in the reader's language, and let "
                "the reader choose from the list."
            ),
            "data": {"question": card},
            "hints": [],
        },
        default=str,
    )


def _refusal(message: str) -> str:
    """A refusal, in the envelope the tools speak."""
    return json.dumps(
        {
            "status": "error",
            "message": message,
            "data": None,
            "hints": [],
        },
        default=str,
    )
