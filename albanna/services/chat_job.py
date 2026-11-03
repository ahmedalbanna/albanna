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

*   The marker is parked in the **site's** cache namespace, never the
    reader's.  ``frappe.cache`` namespaces anything written with
    ``user=`` under ``<db>|user:<user>:`` — the prefix the framework's
    ``clear_user_cache`` empties outright, on a login, a logout, a User
    save or a role change.  A marker parked there is deleted mid-turn by
    any of those, and the polling fallback then tells the reader the turn
    did not finish, about a job that returned ``OK`` and a row that says
    ``ok``.  ``albanna.api.chat.TURN_CACHE_KEY`` carries the same note.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import frappe

from albanna.api.chat import STALE_GRACE_SECONDS, STREAM_EVENT, TURN_CACHE_KEY
from albanna.core.attachments import read_attachment_list
from albanna.core.errors import reader_message

logger = logging.getLogger(__name__)

#: How long a finished turn stays readable for the polling fallback.
TURN_TTL_SECONDS = 1800


def _reader_error(exc: BaseException) -> str:
    """The sentence the reader is shown when the turn could not finish."""
    message = reader_message(exc)
    try:
        return frappe._(message)
    except Exception:
        return message


def run_turn_job(
    stream_id: str,
    conversation_id: str = "",
    page: str = "",
    question: str = "",
    page_context: str = "",
) -> None:
    """Run one turn and publish its progress.

    The question and the page description are read from the cache, where
    the endpoint left them, and *not* from the job's arguments: a job's
    arguments are logged, and the log is read by operators and copied off
    the host.  The two parameters are kept only so that a turn queued
    before the change still runs; nothing enqueues them any more.
    """
    from albanna.services.chat_service import ChatService, TurnRequest, turn_payload

    user = frappe.session.user
    emit = _realtime_emit(stream_id, user)

    if not question:
        parked = (
            frappe.cache().get_value(
                TURN_CACHE_KEY.format(stream_id=stream_id),
                # ``expires=True``: read the cache as it is and leave no
                # copy of it in this process.  ``frappe.cache`` keeps a
                # per-process mirror of every value read without it, and
                # a mirror left here would be served back to the events
                # at the end of the turn — see ``_mirror_to_marker``.
                expires=True,
            )
            or {}
        )
        question = str(parked.get("question") or "")
        page_context = str(parked.get("page_context") or "")
        # The marker parks them as a JSON list.  A turn queued before
        # that parks a single bare data URL, and a bare string is read as
        # a list of one.  Anything else is no attachment: a turn that
        # cannot read its own attachments must still answer.
        images, _readable = read_attachment_list(parked.get("images") or parked.get("image"))
        image_urls, _readable = read_attachment_list(parked.get("image_urls"))

    try:
        outcome = ChatService().run(
            TurnRequest(
                question=question,
                conversation_id=conversation_id,
                page=page,
                page_context=page_context,
                stream=True,
                images=images,
                image_urls=image_urls,
            ),
            emit=emit,
        )
        payload = turn_payload(outcome)
    except Exception as exc:  # noqa: BLE001 - the job must always answer
        logger.exception("Chat turn failed")
        # The detail is in the log above.  The reader is told what
        # happened in words they can act on: an exception's class and
        # message are the app's internals, and "JobTimeoutException: Task
        # exceeded maximum timeout value (600 seconds)" is not an
        # explanation.
        payload = {
            "status": "error",
            "reply": "",
            "error": _reader_error(exc),
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
        _mirror_to_marker(stream_id, user, event)
        try:
            frappe.publish_realtime(
                STREAM_EVENT,
                {"stream_id": stream_id, **event},
                user=user,
            )
        except Exception:
            logger.exception("Failed to publish chat progress for %s", stream_id)

    return emit


def _mirror_to_marker(stream_id: str, user: str, event: dict[str, Any]) -> None:
    """Put into the parked marker what the parked answer cannot say.

    The worker parks only the *final* answer.  Every event before it
    reaches the reader through the socket — and a socket that died
    mid-turn leaves the reader polling a marker that keeps saying
    ``running`` with nothing new in it.  One event matters beyond the
    rest: the approval card.  A write waiting for the reader whose card
    never arrived is a reader who sees a working turn and no way to
    answer it — the worker holds its slot asleep, and the reader watches
    it go to waste.

    So the ``confirm`` event is mirrored into the marker, and any later
    event clears it: the decision was taken, or the turn moved on, and
    the card belongs to the past.  The card keeps the *server's* clock
    (``at``, the moment the wait opened) so a card drawn late from the
    poll counts down the time that actually remains, not a fresh window
    that says the worker is waiting when it has already given up.

    Mirroring is best-effort, like the publish: a cache failure must
    never abort a turn whose answer is still being worked on.
    """
    if not isinstance(event, dict):
        return
    try:
        cache = frappe.cache()
        marker_key = TURN_CACHE_KEY.format(stream_id=stream_id)
        # Drop this process's own copy of the marker, if it holds one, and
        # read the cache as it is.  ``frappe.cache`` answers ``get_value``
        # from ``frappe.local.cache`` — the per-process mirror — before it
        # touches redis, and the mirror is written by any read without
        # ``expires=True``.  A mirror left from earlier in the turn would
        # be served here too: the mirror would say the turn is still
        # running, the event is not a card, and the marker would be
        # written back as ``running`` — over the answer the job parked a
        # moment ago.  The reader would then poll a turn that says it
        # never finished, while its work is committed and its row says
        # ``ok``.
        frappe.local.cache.pop(cache.make_key(marker_key), None)
        marker = cache.get_value(marker_key, expires=True)
        if not isinstance(marker, dict) or marker.get("status") != "running":
            return

        if event.get("event") == "confirm":
            marker["pending_approval"] = {
                "request_id": str(event.get("request_id") or ""),
                "at": float(event.get("at") or time.time() * 1000),
                "name": str(event.get("name") or ""),
                "arguments": event.get("arguments"),
                "preview": str(event.get("preview") or ""),
                "diff": event.get("diff"),
                "window_seconds": event.get("window_seconds"),
            }
        else:
            marker.pop("pending_approval", None)

        from albanna.services.settings_service import get_settings, job_budget_seconds

        cache.set_value(
            marker_key,
            marker,
            # The marker's own TTL was set when the turn started; each
            # mirror keeps it alive while the turn still runs by the
            # same full span, so a long wait for the reader's answer
            # cannot let the marker die under a live card.
            expires_in_sec=job_budget_seconds(get_settings()) + STALE_GRACE_SECONDS,
        )
    except Exception:
        logger.exception("Could not mirror chat progress for %s to the marker", stream_id)


def _park(stream_id: str, payload: dict[str, Any]) -> None:
    """Store the finished turn for the polling fallback."""
    try:
        frappe.cache().set_value(
            TURN_CACHE_KEY.format(stream_id=stream_id),
            payload,
            expires_in_sec=TURN_TTL_SECONDS,
        )
    except Exception:
        logger.exception("Could not park the chat result for %s", stream_id)
