"""The wait for a reader's decision.

A write that the rail is on does not run until the reader has answered.
The worker that proposed it waits here, and the browser answers by writing
the decision to the cache under the reader's own namespace.

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

#: How long the reader is given, in seconds.
DEFAULT_TIMEOUT = 120.0

#: How long between two reads of the decision.  Short enough that the
#: reader's approval is acted on within a tenth of a second, long enough
#: that an idle turn does not hammer Redis.
DEFAULT_INTERVAL = 0.1

#: The answer when the reader does not answer in time.
TIMEOUT = "timeout"


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
