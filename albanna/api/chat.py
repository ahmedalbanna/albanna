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

import json
import logging
import time
import uuid
from typing import Any

import frappe
from frappe import _

from albanna.core.attachments import DISABLED, check_attachments, read_attachment_list
from albanna.core.prompt import build_page_context
from albanna.permissions import require_chat_access
from albanna.privacy import redacted_request_text

logger = logging.getLogger(__name__)

#: The socket.io event the client listens on.
STREAM_EVENT = "albanna_chat_progress"

#: Where a running turn and its parked answer live.
#:
#: The key is written **without** ``user=``, which namespaces it under
#: ``<db>|user:<user>:`` — the namespace the framework's
#: ``clear_user_cache`` empties outright, on a login, a logout, a User
#: save or a role change.  A marker parked there is deleted mid-turn
#: whenever any of those happen, and the polling fallback then reads the
#: ledger's "the turn did not finish" about a turn whose job returned
#: ``OK`` and whose row says ``ok``.  The stream id is a random hex;
#: ``status`` requires the chat gate and the id itself, so the marker is
#: no more reachable than the browser that owns it — it just survives
#: the framework's housekeeping.
TURN_CACHE_KEY = "albanna:turn:{stream_id}"


def _prepare_image(image: str, settings: Any) -> tuple[list[str], str]:
    """The attachments a question carries, and why they may not be carried.

    ``image`` may be a single base64 data URL or a JSON-encoded list of
    them.  Returns ``(images, reason)``.  When ``reason`` is empty the
    images are ready to use; otherwise the turn must not start, and
    :func:`_read_attachments` says why.

    The reason is a code and not a sentence because this function is
    reached by the domain suite, which has no language to say a sentence
    in.  The wording lives with the endpoint that shows it.
    """
    if not image:
        return [], ""
    if not getattr(settings, "image_support", False):
        # The site has images switched off.  Saying so is the whole point:
        # dropping the attachment quietly leaves the reader believing the
        # model saw a picture it never received, and the model — which
        # really did receive nothing — says exactly that.
        return [], DISABLED
    max_bytes = int(getattr(settings, "max_image_size_kb", 0) or 0) * 1024
    return check_attachments(image, max_bytes)


def _read_attachments(
    image: str, image_urls: str, settings: Any
) -> tuple[list[str], list[str], str]:
    """The attachments a question carries, and why they may not be carried.

    Returns ``(images, stored_urls, error)``.  ``error`` is empty when the
    turn may go ahead.

    ``images`` are the bytes, as data URLs, for the model to read.
    ``stored_urls`` are the addresses the bytes were already written
    under, so the turn reuses the file instead of writing it twice.  A
    field of stored addresses that cannot be read is read as no addresses:
    the turn then stores the bytes itself, which is the safe answer to a
    field it does not understand.
    """
    from albanna.services.attachments import ceiling_in_kb, refusal_sentence

    images, reason = _prepare_image(image, settings)
    if reason:
        return [], [], refusal_sentence(reason, ceiling_in_kb(settings))
    stored, _readable = read_attachment_list(image_urls)
    return images, stored, ""


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
    image_urls: str = "",
) -> dict[str, Any]:
    """Ask a question and wait for the answer."""
    require_chat_access()

    from albanna.services.rate_limit import SURFACE_ASK, check_turn_allowed

    check_turn_allowed(str(frappe.session.user or ""), SURFACE_ASK)

    from albanna.services.chat_service import ChatService, TurnRequest, turn_payload
    from albanna.services.settings_service import get_settings

    settings = get_settings()
    images, stored_urls, error = _read_attachments(image, image_urls, settings)
    if error:
        return {"status": "error", "error": error}

    request = TurnRequest(
        question=question or "",
        conversation_id=conversation_id or "",
        page=page or "",
        page_context=_render_page_context(page_context),
        stream=False,
        images=images,
        image_urls=stored_urls,
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
    image_urls: str = "",
) -> dict[str, Any]:
    """Ask a question and get the answer as it happens.

    Returns a stream id straight away.  The turn runs in a worker, publishes
    its progress over socket.io, and parks its final answer in the cache.
    """
    require_chat_access()

    from albanna.services.rate_limit import SURFACE_STREAM, check_turn_allowed
    from albanna.services.settings_service import get_settings, job_budget_seconds

    check_turn_allowed(str(frappe.session.user or ""), SURFACE_STREAM)

    settings = get_settings()
    images, stored_urls, error = _read_attachments(image, image_urls, settings)
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
            "images": json.dumps(images),
            "image_urls": json.dumps(stored_urls),
            "page_context": _render_page_context(page_context),
        },
        # No ``user=``: the marker is parked in the site's namespace, not
        # the reader's — see ``TURN_CACHE_KEY``.  The marker has to
        # outlive the *job*, not the work: the job's
        # own clock covers the turn's labour plus the wait for the
        # reader's decision (see ``job_budget_seconds``), and the grace
        # after that is for the result to be written.  A marker that
        # expired while the reader was still answering a card is a
        # marker that lies — ``status`` would call the turn lost while
        # its worker sat waiting for the very answer the reader was
        # about to give.
        expires_in_sec=job_budget_seconds(settings) + STALE_GRACE_SECONDS,
    )

    frappe.enqueue(
        "albanna.services.chat_job.run_turn_job",
        # The chat's own queue.  A turn of many rounds held the *short*
        # queue for its whole length, and everything else the site
        # drops there — mail, reminders, the scheduler's own jobs —
        # waited behind it.  On the site's dedicated worker a slow
        # turn costs the chat alone; nothing else queues behind it.
        queue="chat",
        # The enqueue timeout has to cover the wait as well as the work,
        # because the wait is where the old clock killed real turns: a
        # turn of ten rounds left under two minutes of budget by the
        # time its card appeared, and a reader who thought before
        # clicking Approve was told the worker "did not complete the
        # turn".  The work keeps its own deadline; the reader's answer
        # time is a different budget, and the job holds the sum of both.
        timeout=job_budget_seconds(settings),
        job_id=f"albanna-turn-{stream_id}",
        stream_id=stream_id,
        conversation_id=conversation_id or "",
        page=page or "",
    )

    return {"status": "queued", "stream_id": stream_id, "event": STREAM_EVENT}


@frappe.whitelist()
def status(stream_id: str = "", conversation: str = "") -> dict[str, Any]:
    """Read a turn's result, for a client whose socket did not deliver it.

    Three answers are possible.  The turn finished and its answer is here.
    The turn is still running.  Or the turn is gone — its worker died, or
    the job never started — and the client is told so instead of polling
    for an answer that will never arrive.

    The *conversation* is the reader's, when the browser knows it: it
    names the turn whose audit row is the truth about what it wrote
    before it died.
    """
    require_chat_access()

    if not stream_id:
        return {"status": "unknown"}

    payload = frappe.cache().get_value(
        TURN_CACHE_KEY.format(stream_id=stream_id),
        # ``expires=True``: the marker is a key with a TTL, and this read
        # is not to be mirrored into this request's process cache — it is
        # asked for fresh every time the browser polls.
        expires=True,
    )

    if not payload:
        # The marker expired, which means the turn outlived its own budget.
        return _lost_turn(conversation)

    if payload.get("status") == "running":
        # A card the socket never delivered is still here: the worker
        # mirrors the confirm event into the marker as it asks, so the
        # polling fallback — and only it — can show a card that the
        # browser never got over the socket.  The pending record's own
        # TTL governs whether the answer is still worth anything;
        # ``confirm_write`` refuses a decision whose record expired.
        pending = payload.get("pending_approval")
        if isinstance(pending, dict) and pending.get("request_id"):
            return {"status": "awaiting_approval", "pending": pending}

        age = time.time() - float(payload.get("started_at") or time.time())
        if age > _turn_deadline():
            return _lost_turn(conversation)
        return {"status": "running"}

    return payload


def _lost_turn(conversation: str = "") -> dict[str, Any]:
    """The answer for a turn that will never finish.

    And, when the turn's audit row says what it did before it died,
    **what it did**.  The reader's question when the panel says the
    turn did not finish is *did it happen?*, and silence about a write
    is the worst answer there is: the reader cannot tell "nothing
    happened" from "everything happened and nobody said".  The audit row
    is the truth — a write in it is a write that was committed — so the
    row is read and its writes are named.

    The row also says what the reader **confirmed**.  A change the
    reader confirmed and that never ran is the worst of both: the
    reader believes it happened, and it did not.  So it is named too,
    and named as what it is — a change that was confirmed and did not
    run — rather than left to the reader's imagination.

    Nothing is named when the row is not certainly the reader's turn:
    a reader told about the wrong turn's writes goes looking for a
    change that was never made.
    """
    from albanna.services.audit_rows import unfinished_facts

    facts = unfinished_facts(frappe.session.user, conversation)
    writes = facts["writes"]
    approved = facts["approved"]

    parts = [
        _(
            "The assistant did not finish this question — the background worker "
            "did not complete the turn."
        )
    ]

    if writes:
        names = ", ".join(f"{write['doctype']} {write['name']}" for write in writes)
        parts.append(_("Before it stopped, it changed {documents}.").format(documents=names))

    if approved:
        changes = ", ".join(_approved_label(approval) for approval in approved)
        if len(approved) == 1:
            parts.append(
                _("The change you confirmed did not run: {changes}.").format(changes=changes)
            )
        else:
            parts.append(
                _("The changes you confirmed did not run: {changes}.").format(changes=changes)
            )

    if writes:
        if len(writes) == 1:
            parts.append(_("Please check it and try again."))
        else:
            parts.append(_("Please check them and try again."))
    else:
        parts.append(_("It may have been restarted. Please try again."))

    return {"status": "error", "error": " ".join(parts)}


def _approved_label(approval: dict[str, Any]) -> str:
    """What a confirmed change that never ran is called in the message.

    The document's type and — when the reader may read it — its name.
    The values the model wanted to write are not named: they were on the
    card the reader answered, and the ledger is not where they belong.
    """
    doctype = str(approval.get("doctype") or "").strip()
    name = str(approval.get("name") or "").strip()
    if name:
        return f"{doctype} {name}".strip()
    return doctype


def _turn_deadline() -> float:
    """How long a turn may run before it is declared lost.

    The job's clock covers the work *and* the wait (see
    ``job_budget_seconds``); the grace on top is for pickup and parking.
    """
    from albanna.services.settings_service import get_settings, job_budget_seconds

    return job_budget_seconds(get_settings()) + STALE_GRACE_SECONDS


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
        pending = record_decision(request_id, decision, ttl=ttl)
    except NoPendingWrite:
        frappe.throw(_("That request is not waiting for a decision."), frappe.ValidationError)
    except AlreadyAnswered:
        frappe.throw(_("That request has already been answered."), frappe.ValidationError)

    # The decision is written into the turn's audit row as well as into
    # the cache record the worker polls.  The cache record expires with
    # the wait it answers; the row does not.  A confirmation that lives
    # only in the cache is a confirmation nobody can be told about when
    # the worker dies between the approval and the write — and a reader
    # who confirmed a change must never be left believing it happened.
    _record_decision_in_row(request_id, decision, pending)

    return {"status": "ok", "decision": decision}


def _record_decision_in_row(request_id: str, decision: str, pending: dict[str, Any]) -> None:
    """Write the reader's decision into the turn's audit row, and commit it.

    A failure here is logged and not raised: the decision is already in
    the cache, and the worker is already acting on it.  Refusing the
    reader's answer because the ledger could not be written would be
    worse than the ledger missing it — the reader would be told their
    confirmation did not register, and it did.
    """
    row = str((pending or {}).get("row") or "")
    if not row:
        return

    from albanna.services.audit_rows import merge_payload

    try:
        merge_payload(
            row,
            {
                "approvals": [
                    {
                        "request_id": request_id,
                        "decision": decision,
                        "decided_at": frappe.utils.now(),
                    }
                ]
            },
        )
        frappe.db.commit()
    except Exception:
        logger.exception("Could not record the decision in the chat log row")
