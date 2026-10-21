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
