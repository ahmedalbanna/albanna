"""The wait for a reader's decision, and what the reader is told about it.

A write that the rail is on does not run until the reader has answered.
The worker that proposed it waits here, and the browser answers by writing
the decision to the cache under the reader's own namespace.

Everything a turn needs to *speak* about the wait lives here too: the
human-readable preview the confirmation card opens with
(:func:`write_preview`) and the sentence the model is told when the write
was not made (:func:`denial_message`).  They sit beside the wait because
they are three parts of one answer to one question — what is about to
happen, can I go on, and what happened instead.


The one subtlety this module exists for
----------------------------------------
``frappe.cache().get_value()`` keeps what it read in the request's local
cache — *including a miss*.  A poll that does not ask for ``expires=True``
therefore reads the miss back on every later iteration instead of asking
Redis again, and the reader's answer — written by another request, after
the first poll — is never seen.  The wait then times out whatever the
reader did, and the only symptom is a turn that says the write was not
approved.

So the poll asks for ``expires=True``: the value is read from Redis every
time, and never kept.
"""

from __future__ import annotations

import time
from typing import Callable

import frappe

#: The prefix every pending decision is stored under.
KEY_PREFIX = "albanna:confirm:"

#: How long the reader is given, in seconds, when the operator has not
#: said.  The same default the settings field carries.
DEFAULT_TIMEOUT = 120.0

#: The shortest and longest a wait may be set to.
#:
#: A floor, because a wait shorter than a reader's pause is a rail that
#: refuses writes nobody was given the chance to approve; a ceiling,
#: because the worker holds its slot for as long as the wait lasts, and
#: a wait that can be set to an hour is a worker held for an hour.
MIN_TIMEOUT = 30.0
MAX_TIMEOUT = 600.0


def wait_seconds(configured) -> float:
    """The wait to use, from whatever the operator set.

    A number outside the bounds is clamped rather than refused: an
    operator who typed 5000 meant "a long time", and refusing the turn
    over a typo in a setting is a worse answer than honouring the
    intent.
    """
    try:
        seconds = float(configured)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if seconds <= 0:
        return DEFAULT_TIMEOUT
    return min(max(seconds, MIN_TIMEOUT), MAX_TIMEOUT)

#: How long between two reads of the decision.  Short enough that the
#: reader's approval is acted on within a tenth of a second, long enough
#: that an idle turn does not hammer Redis.
DEFAULT_INTERVAL = 0.1

#: The answer when the reader does not answer in time.
TIMEOUT = "timeout"


def write_preview(name: str, arguments: dict) -> str:
    """A compact, human-readable summary of a pending write.

    The reader approves a *change*, not a JSON blob, so the confirmation
    dialog says what will happen in the reader's words: "Create Customer:
    Acme (type Company)" rather than the raw arguments.

    The words are deliberately the *app's* fixed verbs — Create, Change —
    because this string is composed in the worker, which has no reader's
    language; the card around it carries the sentence around it.
    """
    arguments = arguments or {}
    doctype = str(arguments.get("doctype") or "").strip()
    data = arguments.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if name == "create_doc":
        title = _preview_title(doctype, data)
        if title:
            return f"Create {doctype}: {title}"
        return f"Create a {doctype}"

    if name == "update_doc":
        docname = str(arguments.get("name") or "").strip()
        fields = ", ".join(f"{key} = {value}" for key, value in list(data.items())[:6])
        if docname and fields:
            return f"Change {doctype} {docname}: {fields}"
        if docname:
            return f"Change {doctype} {docname}"
        return f"Change a {doctype}"

    return f"{name}({doctype})"


def _preview_title(doctype: str, data: dict) -> str:
    """The most identifying value in a new document's data."""
    for key in ("customer_name", "supplier_name", "full_name", "item_name", "subject", "title", "name"):
        value = data.get(key)
        if value:
            return str(value)
    # Fall back to the first non-empty value.
    for value in data.values():
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value)
    return ""


def denial_message(decision: str) -> str:
    """What the model is told when the write did not run.

    The wording must let the model explain itself to the reader without
    pretending the change happened.
    """
    if decision == "reject":
        return "The reader did not approve this change, so it was not made."
    return "The reader did not respond in time, so the change was not made."


def decision_key(request_id: str) -> str:
    """The cache key one pending decision is stored under."""
    return f"{KEY_PREFIX}{request_id}"


def await_decision(
    request_id: str,
    user: str,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Wait for the reader's decision, and return it.

    Returns ``"approve"``, ``"reject"``, or ``"timeout"`` when the reader
    did not answer in time.
    """
    key = decision_key(request_id)
    deadline = clock() + timeout

    while clock() < deadline:
        # ``expires=True`` is the whole trick: without it the cache keeps
        # the miss and every later poll reads that miss back.
        value = frappe.cache().get_value(key, user=user, expires=True)
        if value is not None:
            try:
                frappe.cache().delete_value(key, user=user)
            except Exception:
                pass
            return str(value)
        sleep(interval)

    return TIMEOUT
