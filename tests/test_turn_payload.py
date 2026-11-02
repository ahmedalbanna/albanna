"""The wire shape of a turn, and the two ways a turn reaches the reader.

A turn reaches the browser twice over: the endpoint that runs it here and
now, and the worker that runs it there and now.  Both send the same shape.
A field that is added to one of them and forgotten in the other is a
field the reader never sees — and the bug is invisible until someone
waits for an answer that was never announced.
"""

from __future__ import annotations

from albanna.services.chat_service import TurnOutcome, turn_payload


def _outcome(**overrides) -> TurnOutcome:
    values = {
        "ok": True,
        "reply": "an answer",
        "conversation_id": "a-conversation",
        "provider": "openai",
        "model": "a-model",
        "rounds": 1,
        "tool_calls": [],
        "truncated": False,
    }
    values.update(overrides)
    return TurnOutcome(**values)


def test_the_payload_carries_the_turn():
    payload = turn_payload(_outcome())

    assert payload["status"] == "ok"
    assert payload["reply"] == "an answer"
    assert payload["conversation_id"] == "a-conversation"
    assert payload["model"] == "a-model"


def test_the_payload_carries_the_question():
    """A turn that asked the reader something says so.

    The card the reader is shown is built from this, and a turn that
    asked a question and said nothing about it is a turn that asked for
    nothing.
    """
    card = {"name": "Q-0001", "question": "which customer?", "options": []}
    payload = turn_payload(_outcome(question=card))

    assert payload["question"]["name"] == "Q-0001"


def test_a_turn_that_asked_no_question_carries_none():
    assert turn_payload(_outcome())["question"] is None


def test_a_turn_that_asked_a_question_gives_the_model_no_tools():
    """Once the reader has been asked, the assistant may only speak.

    A question that is asked and then acted on in the same breath is a
    question that was never asked.
    """
    from albanna.core.tools import TOOL_MANIFEST
    from albanna.services.chat_service import _round_tools

    visible = TOOL_MANIFEST.all()

    assert _round_tools(visible, None) == visible
    assert _round_tools(visible, {"name": "Q-0001"}) == []


def test_only_the_question_tool_asks_a_question():
    """A document with a field called "question" is not a question.

    The reader is offered a choice when the assistant asked for one in
    the app's own words — not because some tool's payload happened to
    carry that key.
    """
    from albanna.core.messages import ToolCall
    from albanna.services.chat_service import _question_asked
    from albanna.tools.base import ToolResult

    card = {"name": "Q-0001", "question": "which customer?"}

    asked = ToolCall(id="1", name="ask_question", arguments={})
    assert _question_asked(asked, ToolResult.success("ok", {"question": card})) == card

    other = ToolCall(id="2", name="get_doc", arguments={})
    assert _question_asked(other, ToolResult.success("ok", {"question": card})) is None

    # And a failed question is not a question.
    assert _question_asked(asked, ToolResult.failure("no", "no")) is None


def test_the_payload_says_the_answer_was_cut_off():
    assert turn_payload(_outcome(truncated=True))["truncated"] is True


def test_a_failed_turn_is_an_error():
    payload = turn_payload(_outcome(ok=False, reply="", error="it broke"))

    assert payload["status"] == "error"
    assert payload["error"] == "it broke"


def test_the_two_paths_send_the_same_shape():
    """The endpoint and the worker build the same payload, from the same
    place — so a field cannot reach one and not the other."""

    import inspect

    from albanna.api import chat as chat_api
    from albanna.services import chat_job

    endpoint = inspect.getsource(chat_api.ask)
    worker = inspect.getsource(chat_job)

    assert "turn_payload(outcome)" in endpoint
    assert "turn_payload(outcome)" in worker


def test_the_payload_carries_cancelled_questions():
    """A turn that cancelled the thread's pending questions says so.

    The widget drops their cards from this, and a turn that cancelled
    some and said nothing about it is a turn whose cards stay on screen
    after their question is gone.
    """
    card = {"name": "Q-0001", "question": "which customer?", "options": []}
    payload = turn_payload(_outcome(cancelled_questions=[card]))

    assert payload["cancelled_questions"][0]["name"] == "Q-0001"
