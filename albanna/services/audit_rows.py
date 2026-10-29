"""The audit rows, read for the question the panel has to answer.

A turn writes an ``Albanna Chat Log`` row: the model, the tools it ran,
what each of them did, and whether the turn finished.  The row is the
truth about a turn, and it outlives the turn — which matters most when
the turn does not finish at all.

A turn that dies leaves its row behind, and the row says what it did
before it died.  That is the answer to the question a reader is left
with when the panel says *the assistant did not finish this question*:
**did it happen?**  Without the row the answer is silence, and silence
about a write is the worst answer there is — the reader cannot tell
"nothing happened" from "everything happened and nobody said".

So the row is read here, and it is read carefully:

*   only a turn that **has not finished** counts — a turn that ended
    with an answer is not the turn the reader is asking about;
*   only a turn of the **reader's own** counts;
*   and when **more than one** unfinished turn could be meant, nothing
    is said.  A reader told about the wrong turn's writes goes looking
    for a change that was never made, and that is worse than being told
    nothing.

The reader's own unfinished turn is usually found by its conversation,
but not always: the first question on a page is asked before the
conversation exists, and the browser only learns its name when the turn
ends — which is exactly when it did not.  So the conversation is used
when it is known, and the reader's own unfinished turns are used when
it is not.

The row is *written* here too, because it is written from three places:
the worker as the turn runs, the endpoint that takes the reader's
decision on a write, and the worker again when the turn ends.  Three
writers, one row, one merge — in one place, under a lock, because a
decision lost to a read-modify-write race is a decision nobody hears
about.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import frappe

logger = logging.getLogger(__name__)

#: The table the ledger is written to.
LOG_DOCTYPE = "Albanna Chat Log"

#: The key the approvals are stored under, inside the row's ``tools``
#: payload.  The payload is one JSON object: the calls the turn made,
#: the per-round timings, and the approvals it asked for.
APPROVALS_KEY = "approvals"

#: How long after a turn's start its row can still be the row of a turn
#: that has just died.  A turn cannot outlive its own timeout, and the
#: reader hears about it a little after that; five minutes of slack is
#: generous.  It also keeps last week's interrupted rows out of the
#: question.
DEAD_TURN_SLACK = 300

#: How many documents are named.  A turn that changed fifty tickets is
#: not a sentence a reader can read; the count and the first few are
#: enough to know where to look.
MAX_WRITES_NAMED = 5


def unfinished_turn(user: str, conversation: str = "") -> dict[str, Any] | None:
    """The reader's one unfinished turn's row, or ``None``.

    ``None`` when there is no such row, or when more than one could be
    meant: a reader told about the wrong turn's writes goes looking for
    a change that was never made, and that is worse than being told
    nothing.
    """
    from albanna.services.settings_service import get_settings

    settings = get_settings()
    cutoff = frappe.utils.now_datetime() - timedelta(
        seconds=int(settings.turn_timeout or 600) + DEAD_TURN_SLACK
    )

    filters: dict[str, Any] = {
        "user": user,
        "status": ("in", ("running", "interrupted")),
        "creation": (">", cutoff),
    }
    if conversation:
        filters["conversation"] = conversation

    rows = frappe.get_all(
        LOG_DOCTYPE,
        filters=filters,
        fields=["name", "tools"],
        order_by="creation desc",
        limit=2,
    )
    if len(rows) != 1:
        # Two unfinished turns, or none: either way this row is not
        # certainly the reader's turn, and a wrong answer is worse than
        # no answer.
        return None

    return rows[0]


def unfinished_writes(user: str, conversation: str = "") -> list[dict[str, str]]:
    """The documents the reader's unfinished turn wrote.

    Empty when there is nothing to say: no unfinished turn, an
    unfinished turn that only read, or more than one unfinished turn
    that could be meant.
    """
    return unfinished_facts(user, conversation)["writes"]


def approved_not_run(user: str, conversation: str = "") -> list[dict[str, Any]]:
    """The writes the reader approved, and that never ran.

    The approval is recorded in the row before the reader is asked, and
    the decision is recorded in it when the reader answers — both in the
    database, not in the cache the turn polls.  So a turn that dies
    between the approval and the write still says what was approved, and
    the panel can tell the reader that the change they confirmed did
    not happen.
    """
    return unfinished_facts(user, conversation)["approved"]


def unfinished_facts(user: str, conversation: str = "") -> dict[str, Any]:
    """What the reader's one unfinished turn did, and never did.

    Both facts come from the same row, so they are read together: the
    panel's answer to *did it happen?* is one sentence about the writes
    that ran and the ones that did not, and two queries could disagree
    about which turn they are talking about.
    """
    row = unfinished_turn(user, conversation)
    if not row:
        return {"writes": [], "approved": []}

    return {
        "writes": _writes_of(row),
        "approved": _approved_not_run_of(row),
    }


def _approved_not_run_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The approvals in one row that were given and did not run."""
    approved: list[dict[str, Any]] = []
    for approval in approvals_of(row):
        if str(approval.get("decision") or "") != "approve":
            continue
        if approval.get("ran"):
            # The write ran: it is in the calls, and the panel names it
            # as a change rather than as something that did not happen.
            continue
        approved.append(approval)
    return approved


def _writes_of(row: dict[str, Any]) -> list[dict[str, str]]:
    """The documents one row says the turn wrote.

    A write in the row is a write that was committed: the turn commits
    each write as it runs, and the row is written after it.  A refused
    write is not there, and neither is a dry run — neither changed
    anything.
    """
    writes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for call in _calls_of(row):
        if not call.get("write") or not call.get("ok") or call.get("dry_run"):
            continue
        for document in call.get("documents") or []:
            if not isinstance(document, dict):
                continue
            name = str(document.get("name") or "").strip()
            doctype = str(document.get("doctype") or "").strip()
            if not name or (doctype, name) in seen:
                continue
            seen.add((doctype, name))
            writes.append({"doctype": doctype, "name": name})
            if len(writes) >= MAX_WRITES_NAMED:
                return writes

    return writes


def _calls_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The calls one row keeps."""
    payload = _payload_of(row)
    calls = payload.get("calls") if isinstance(payload, dict) else payload
    return [call for call in (calls or []) if isinstance(call, dict)]


def approvals_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The approvals one row keeps."""
    payload = _payload_of(row)
    approvals = payload.get(APPROVALS_KEY) if isinstance(payload, dict) else None
    return [item for item in (approvals or []) if isinstance(item, dict)]


def _payload_of(row: dict[str, Any]) -> Any:
    """The row's ``tools`` payload, parsed.

    The column holds an object with the calls, the per-round timings and
    the approvals.  Rows written before that shape held the calls alone,
    and are still read.
    """
    raw = row.get("tools")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


# -- writing --------------------------------------------------------------


def lock_row(row_name: str) -> bool:
    """Take the ledger row's lock, and say whether the row is there.

    Every writer of the row's payload takes this lock before it reads
    the row, and holds it until it commits.  Without it two writers can
    read the same payload, and the second one's write is the only one
    that survives — and what is lost is the reader's answer, silently,
    in the one case where the reader needs it most.

    Returns ``False`` when there is no row to lock.  There is then
    nothing to write into either, and a writer that believes it wrote
    something is worse than one that knows it did not.
    """
    if not row_name:
        return False

    try:
        rows = frappe.db.sql(
            f"select name from `tab{LOG_DOCTYPE}` where name = %s for update",
            (row_name,),
        )
    except Exception:
        logger.exception("Could not lock the audit row %s", row_name)
        return False

    return bool(rows)


def merge_payload(row_name: str, changes: dict[str, Any]) -> bool:
    """Merge *changes* into the row's ``tools`` payload, and save it.

    The row's ``tools`` column holds one JSON object, and three writers
    put things in it: the worker as the turn runs, the endpoint that
    takes the reader's decision, and the worker again when the turn
    ends.  They must not overwrite each other, so the read and the write
    happen under a lock on the row.

    The lock is not decoration.  Without it the worker can read the row,
    the endpoint can write the reader's decision into it, and the worker
    can then write its own version over the top — and what is lost is
    the reader's decision, silently, in the one case where the reader
    needs it most.

    The merge is by key, not by replacement: the calls are appended to
    the ones the row already holds — the worker adds a call as it runs,
    and the turn's own final payload replaces the list wholesale when
    the turn ends — and the approvals are merged by their request id, so
    a decision updates the approval it belongs to.

    The caller commits.  A write that ran records itself in the same
    transaction as the change it made, so the row can never say the
    reader approved a change that in fact ran.
    """
    if not row_name or not changes:
        return False

    # The lock is taken before the row is read, so the payload this
    # merge is based on is the one the writer sees.
    if not lock_row(row_name):
        logger.warning("The audit row %s is not there to merge into", row_name)
        return False

    try:
        current = frappe.db.get_value(LOG_DOCTYPE, row_name, "tools")
    except Exception:
        logger.exception("Could not read the audit row %s", row_name)
        return False

    payload = _payload_of({"tools": current})
    if not isinstance(payload, dict):
        # A row written before the payload had a shape keeps its calls as
        # a bare list.  They are kept, not dropped: the row is the truth
        # about a turn, and a merge is not a reason to lose what it said.
        payload = {"calls": payload if isinstance(payload, list) else []}

    for key, value in changes.items():
        if key == APPROVALS_KEY:
            payload[APPROVALS_KEY] = _merge_approvals(payload.get(APPROVALS_KEY) or [], value or [])
        elif key == "calls":
            payload["calls"] = _append_calls(payload.get("calls") or [], value or [])
        else:
            payload[key] = value

    try:
        frappe.db.set_value(
            LOG_DOCTYPE,
            row_name,
            "tools",
            json.dumps(payload, default=str),
            update_modified=False,
        )
    except Exception:
        logger.exception("Could not write the audit row %s", row_name)
        return False

    return True


def _append_calls(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
    """Add the calls a turn made since the row was last written.

    The row's call list grows as the turn runs, so that a turn which
    dies mid-way still says what it had already changed.  The turn's own
    final payload replaces the list when it ends, so nothing is counted
    twice.

    A call that is already there is not added again: the same call
    recorded twice is one call in the ledger's eyes, and a turn that is
    retried must not make the row say it did the same thing twice.
    """
    calls: list[dict[str, Any]] = [item for item in existing if isinstance(item, dict)]
    seen = {_call_key(item) for item in calls}

    for item in incoming:
        if not isinstance(item, dict):
            continue
        key = _call_key(item)
        if key in seen:
            continue
        seen.add(key)
        calls.append(item)

    return calls


def _call_key(call: dict[str, Any]) -> tuple:
    """What makes two recorded calls the same call.

    A call is what it did: the tool, and the documents it touched.  Two
    records with the same key are the same call, whoever wrote them.
    """
    documents = call.get("documents") or []
    names = tuple(sorted(str(doc.get("name") or "") for doc in documents if isinstance(doc, dict)))
    return (str(call.get("name") or ""), names, bool(call.get("ok")))


def _merge_approvals(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
    """Merge new approval records into the ones the row already holds."""
    merged: list[dict[str, Any]] = [item for item in existing if isinstance(item, dict)]

    for item in incoming:
        if not isinstance(item, dict):
            continue
        request_id = str(item.get("request_id") or "")
        if not request_id:
            # An approval without a request id belongs to no decision,
            # and a record nobody can answer is a record nobody reads.
            continue
        record = next(
            (held for held in merged if str(held.get("request_id") or "") == request_id),
            None,
        )
        if record is None:
            merged.append(dict(item))
        else:
            record.update(item)

    return merged
