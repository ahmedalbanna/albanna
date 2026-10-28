"""The chat endpoints.

Three ways to run a turn, and they differ only in how the answer comes
back:

``ask``
    One request, one response, the whole turn.  Simple, and the right shape
    for a script or a test.

``ask_stream``
    Returns immediately with a stream id and runs the turn in a background
    worker.  Progress is pushed over socket.io; the final answer is also
    parked in the cache so that a client whose socket died still gets it.

``status``
    Reads that parked answer back.

Why the background worker exists at all: a turn is a model call plus
several tool calls, and each of those can take seconds.  Gunicorn's request
timeout is minutes, not hours, and a browser that waits on a request that
long will have it cut off.  The worker moves the wait off the request.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import base64

import frappe
from frappe import _

from albanna.core.prompt import build_page_context
from albanna.permissions import require_chat_access
from albanna.privacy import redacted_request_text

logger = logging.getLogger(__name__)

#: The socket.io event the client listens on.
STREAM_EVENT = "albanna_chat_progress"


def _prepare_image(image: str, settings: Any) -> tuple[str, str]:
    """Validate an attached image against the site's settings.

    Returns ``(``image``, ``error)``.  When ``error`` is empty the image is
    ready to use; otherwise the turn must not start, and the error is shown
    to the caller — dropping the attachment silently would leave the user
    convinced the model saw it.
    """
    image = image or ""
    if not image:
        return "", ""
    if not getattr(settings, "image_support", False):
        # The site has images switched off.  Saying so is the whole point:
        # dropping the attachment quietly leaves the reader believing the
        # model saw a picture it never received, and the model — which
        # really did receive nothing — says exactly that.
        return "", "Image attachments are not enabled on this site."
    try:
        payload = image.split(",", 1)[-1]
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        return "", "The attached file could not be read."
    max_bytes = int(getattr(settings, "max_image_size_kb", 0) or 0) * 1024
    if max_bytes and len(raw) > max_bytes:
        return "", (
            f"The attached image is too large. The maximum is "
            f"{getattr(settings, 'max_image_size_kb', 0)} KB."
        )
    return image, ""

#: Where a finished turn is parked for the polling fallback.
TURN_CACHE_KEY = "albanna:turn:{stream_id}"

#: How long a parked "running" marker is trusted before the turn is declared
#: lost.  The worker's own timeout is the yardstick, with a minute of slack
#: for the job to be picked up and for the result to be written.
STALE_GRACE_SECONDS = 90


def _as_int(value: Any) -> int:
    """A number from the browser, or zero.

    The browser's value is untrusted, and ``int("abc")`` raises — which
    would turn a wrong value into a failed turn.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _may_read_page_document(doctype: str, name: str) -> bool:
    """Whether the caller may read the document the page names.

    A document that does not exist, or a DocType that does not exist, is
    "may not read" — there is nothing to describe, and the name is
    dropped either way.
    """
    from albanna.permissions import may_read

    try:
        document = frappe.get_doc(doctype, name)
    except Exception:
        return False
    return may_read(document)


def _render_page_context(raw: Any) -> str:
    """Turn the client's page description into the untrusted block.

    The client sends a description of what the user is looking at.  It is
    attacker-controlled — it is whatever the browser says it is — so it is
    rendered here, truncated, and framed as data.  Nothing from the browser
    reaches the model as an instruction.

    The name of the document on the page is dropped when the reader may
    not read it.  The browser is not trusted to name only what the reader
    can see, and the model is told "the reader is looking at this
    document" — a claim about the reader's own page that has to be true.
    """
    if not raw:
        return ""

    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except (ValueError, TypeError):
            return build_page_context(selection=raw[:500])

    if not isinstance(raw, dict):
        return ""

    doctype = str(raw.get("doctype") or "")[:120]
    name = str(raw.get("name") or "")[:140]
    title = str(raw.get("title") or "")[:200]

    if doctype and name and not _may_read_page_document(doctype, name):
        # The kind of page is still true; the row on it is not the
        # reader's to name.
        name = ""
        title = ""

    return build_page_context(
        view=str(raw.get("route") or raw.get("view") or "")[:120],
        doctype=doctype,
        name=name,
        title=title,
        filters=str(raw.get("filters") or "")[:300],
        selection=str(raw.get("selection") or "")[:500],
        recent_questions=str(raw.get("recent_questions") or "")[:300],
        rows=_as_int(raw.get("rows")),
        report=str(raw.get("report") or "")[:120],
        columns=str(raw.get("columns") or "")[:300],
        sort=str(raw.get("sort") or "")[:120],
    )


@frappe.whitelist()
@redacted_request_text("question", "page_context", "image")
def ask(
    question: str = "",
    conversation_id: str = "",
    page: str = "",
    page_context: Any = None,
    image: str = "",
) -> dict[str, Any]:
    """Ask a question and wait for the answer."""
    require_chat_access()

    from albanna.services.rate_limit import SURFACE_ASK, check_turn_allowed

    check_turn_allowed(str(frappe.session.user or ""), SURFACE_ASK)

    from albanna.services.chat_service import ChatService, TurnRequest, turn_payload
    from albanna.services.settings_service import get_settings

    settings = get_settings()
    image, error = _prepare_image(image, settings)
    if error:
        return {"status": "error", "error": error}

    request = TurnRequest(
        question=question or "",
        conversation_id=conversation_id or "",
        page=page or "",
        page_context=_render_page_context(page_context),
        stream=False,
        image=image or "",
    )
    outcome = ChatService().run(request)

    return turn_payload(outcome)


@frappe.whitelist()
@redacted_request_text("question", "page_context", "image")
def ask_stream(
    question: str = "",
    conversation_id: str = "",
    page: str = "",
    page_context: Any = None,
    image: str = "",
) -> dict[str, Any]:
    """Ask a question and get the answer as it happens.

    Returns a stream id straight away.  The turn runs in a worker, publishes
    its progress over socket.io, and parks its final answer in the cache.
    """
    require_chat_access()

    from albanna.services.rate_limit import SURFACE_STREAM, check_turn_allowed
    from albanna.services.settings_service import get_settings

    check_turn_allowed(str(frappe.session.user or ""), SURFACE_STREAM)

    settings = get_settings()
    image, error = _prepare_image(image, settings)
    if error:
        return {"status": "error", "error": error}

    stream_id = uuid.uuid4().hex

    # A "running" marker, written before the job is queued.  It exists for
    # one reason: a job that dies before it can park its answer — a worker
    # that cannot import the app, a worker killed mid-turn — would
    # otherwise leave the client polling a turn that will never finish, for
    # ever.  The marker is what lets `status` notice that the turn is gone.
    # The question and the page description travel in the cache, and the
    # job is given the key.
    #
    # A job's arguments are logged: the queue writes them out when the
    # job runs, so the question would end up in the bench's worker log,
    # where it is read by operators and copied off the host.  The cache
    # holds the answer already — the turn parks it there for the polling
    # fallback — so the question belongs there too, and the log holds a
    # stream id instead of a sentence.
    frappe.cache().set_value(
        TURN_CACHE_KEY.format(stream_id=stream_id),
        {
            "status": "running",
            "started_at": time.time(),
            "question": question or "",
            "image": image or "",
            "page_context": _render_page_context(page_context),
        },
        user=frappe.session.user,
        expires_in_sec=settings.turn_timeout + STALE_GRACE_SECONDS,
    )

    frappe.enqueue(
        "albanna.services.chat_job.run_turn_job",
        queue="short",
        timeout=settings.turn_timeout,
        job_id=f"albanna-turn-{stream_id}",
        stream_id=stream_id,
        conversation_id=conversation_id or "",
        page=page or "",
    )

    return {"status": "queued", "stream_id": stream_id, "event": STREAM_EVENT}


@frappe.whitelist()
def status(stream_id: str = "") -> dict[str, Any]:
    """Read a turn's result, for a client whose socket did not deliver it.

    Three answers are possible.  The turn finished and its answer is here.
    The turn is still running.  Or the turn is gone — its worker died, or
    the job never started — and the client is told so instead of polling
    for an answer that will never arrive.
    """
    require_chat_access()

    if not stream_id:
        return {"status": "unknown"}

    payload = frappe.cache().get_value(
        TURN_CACHE_KEY.format(stream_id=stream_id),
        user=frappe.session.user,
    )

    if not payload:
        # The marker expired, which means the turn outlived its own budget.
        return _lost_turn()

    if payload.get("status") == "running":
        age = time.time() - float(payload.get("started_at") or time.time())
        if age > _turn_deadline():
            return _lost_turn()
        return {"status": "running"}

    return payload


def _lost_turn() -> dict[str, Any]:
    """The answer for a turn that will never finish."""
    return {
        "status": "error",
        "error": _(
            "The assistant did not finish this question — the background worker "
            "did not complete the turn. It may have been restarted. Please try again."
        ),
    }


def _turn_deadline() -> float:
    """How long a turn may run before it is declared lost."""
    from albanna.services.settings_service import get_settings

    return get_settings().turn_timeout + STALE_GRACE_SECONDS


@frappe.whitelist()
def confirm_write(request_id: str = "", decision: str = "") -> dict[str, Any]:
    """Record the reader's decision on a write that is waiting for review.

    The worker that proposed the write records it as pending before the
    reader is asked, and polls the record for an answer; this endpoint
    writes the answer into it.

    The record is what makes the answer mean something.  A decision that
    names no pending write is refused — there is nobody waiting for it —
    and the first decision is the decision: a second one on the same
    write is refused rather than applied.

    The decision must be ``approve`` or ``reject``; anything else is a
    refusal, because a write that is neither approved nor declined is
    not a thing that can be acted on.
    """
    from albanna.permissions import require_chat_access

    require_chat_access()

    request_id = (request_id or "").strip()
    decision = (decision or "").strip().lower()
    if not request_id:
        frappe.throw(_("A request is required."), frappe.ValidationError)
    if decision not in ("approve", "reject"):
        frappe.throw(_("That is not a decision."), frappe.ValidationError)

    user = str(frappe.session.user or "")

    # The TTL outlives the wait it answers: a decision recorded near the
    # end of a long window must still be there when the worker's next
    # poll comes, and a worker polling every tenth of a second reads it
    # long before it could expire.  The grace is for the poll, not for
    # the reader.
    from albanna.services.approval import (
        AlreadyAnswered,
        NoPendingWrite,
        record_decision,
        wait_seconds,
    )
    from albanna.services.settings_service import get_settings

    ttl = int(wait_seconds(get_settings().confirm_timeout)) + 60

    try:
        record_decision(request_id, user, decision, ttl=ttl)
    except NoPendingWrite:
        frappe.throw(_("That request is not waiting for a decision."), frappe.ValidationError)
    except AlreadyAnswered:
        frappe.throw(_("That request has already been answered."), frappe.ValidationError)

    return {"status": "ok", "decision": decision}
