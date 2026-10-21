"""The background job that runs a turn.

Frappe's request model gives a whitelisted method one response, so a turn
that takes a minute cannot stream over it.  The worker moves the wait off
the request: the endpoint returns a stream id immediately, this job runs
the turn, and the progress is pushed over socket.io.

Two details make this reliable rather than merely clever:

*   The final answer is **parked in the cache** as well as published.  A
    socket that drops mid-turn would otherwise lose the answer entirely, and
    the client would sit on a spinner forever.  ``albanna.api.chat.status``
    reads the parked copy.

*   The realtime publish is **best-effort**.  A socket failure must never
    abort the turn, because the answer is already computed and stored.
"""

from __future__ import annotations

import logging
from typing import Any

import frappe

from albanna.api.chat import STREAM_EVENT, TURN_CACHE_KEY

logger = logging.getLogger(__name__)

#: How long a finished turn stays readable for the polling fallback.
TURN_TTL_SECONDS = 1800


def run_turn_job(
    stream_id: str,
    question: str = "",
    conversation_id: str = "",
    page: str = "",
    page_context: str = "",
) -> None:
    """Run one turn and publish its progress."""
    from albanna.services.chat_service import ChatService, TurnRequest

    user = frappe.session.user
    emit = _realtime_emit(stream_id, user)

    try:
        outcome = ChatService().run(
            TurnRequest(
                question=question,
                conversation_id=conversation_id,
                page=page,
                page_context=page_context,
                stream=True,
            ),
            emit=emit,
        )
        payload = {
            "status": "ok" if outcome.ok else "error",
            "reply": outcome.reply,
            "conversation_id": outcome.conversation_id,
            "provider": outcome.provider,
            "model": outcome.model,
            "rounds": outcome.rounds,
            "tool_calls": outcome.tool_calls,
            "capped": outcome.capped,
            "error": outcome.error,
            # The rows the turn wrote, so that the browser can address
            # this turn later — a row that can be named is a row that can
            # be removed.
            "written": [{"name": name, "role": role} for name, role in outcome.written],
        }
    except Exception as exc:  # noqa: BLE001 - the job must always answer
        logger.exception("Chat turn failed")
        payload = {
            "status": "error",
            "reply": "",
            "error": f"{type(exc).__name__}: {exc}",
            "conversation_id": conversation_id,
        }

    _park(stream_id, payload)
    emit({"event": "done", "result": payload})

    try:
        frappe.db.commit()
    except Exception:
        logger.exception("Could not commit the chat turn")


def _realtime_emit(stream_id: str, user: str):
    """Build the emit callback that publishes progress to one user."""

    def emit(event: dict[str, Any]) -> None:
        try:
            frappe.publish_realtime(
                STREAM_EVENT,
                {"stream_id": stream_id, **event},
                user=user,
            )
        except Exception:
            logger.exception("Failed to publish chat progress for %s", stream_id)

    return emit


def _park(stream_id: str, payload: dict[str, Any]) -> None:
    """Store the finished turn for the polling fallback."""
    try:
        frappe.cache().set_value(
            TURN_CACHE_KEY.format(stream_id=stream_id),
            payload,
            user=frappe.session.user,
            expires_in_sec=TURN_TTL_SECONDS,
        )
    except Exception:
        logger.exception("Could not park the chat result for %s", stream_id)
