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
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe

#: The table the ledger is written to.
LOG_DOCTYPE = "Albanna Chat Log"

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


def unfinished_writes(user: str, conversation: str = "") -> list[dict[str, str]]:
    """The documents the reader's unfinished turn wrote.

    Empty when there is nothing to say: no unfinished turn, an
    unfinished turn that only read, or more than one unfinished turn
    that could be meant.
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
        return []

    return _writes_of(rows[0])


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
    """The calls one row keeps.

    The column holds an object with the calls and the per-round timings.
    Rows written before that shape held the calls alone.
    """
    raw = row.get("tools")
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    calls = payload.get("calls") if isinstance(payload, dict) else payload
    return [call for call in (calls or []) if isinstance(call, dict)]
