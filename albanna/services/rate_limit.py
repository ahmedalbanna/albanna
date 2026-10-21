"""How many questions one person may ask in a minute.

A turn costs a model call, a worker slot for as long as the model takes, and
a little of the provider's budget.  The widget is reachable by every Desk
User, so without a ceiling one person — or one script that found the
endpoint — could spend all three.

The bucket is per user *and* per surface, so a user never loses allowance
they already had; what changes is that no path is unlimited.  The two
surfaces are the blocking endpoint and the queued one.

This is a cost-control measure, not a security boundary, and the difference
matters: the counter is read and then written, so two simultaneous requests
from the same user can both see the same count and both be let through.  The
window is a millisecond and the consequence is one extra question, not a
bypass.  A boundary that needed to be exact would need an atomic counter,
and the cache wrapper does not offer one.
"""

from __future__ import annotations

import logging

import frappe
from frappe import _

logger = logging.getLogger(__name__)

#: The blocking endpoint — one request, one answer.
SURFACE_ASK = "ask"

#: The queued endpoint — a stream id now, the answer later.
SURFACE_STREAM = "stream"

#: How long a bucket lives.
BUCKET_SECONDS = 60


def check_turn_allowed(user: str, surface: str) -> None:
    """Refuse a turn that is over the limit.

    A cache failure must never break a turn — the chat is more useful than
    the cap — so it is logged and the turn proceeds.  An explicit over-limit
    refusal always propagates.
    """
    limit = _limit()
    if limit <= 0:
        return

    key = f"albanna:turns:{surface}:{user}"
    try:
        # `expires=True` means "this key has a TTL, so do not memoise it in
        # the request-local cache".  Without it, the *first* read of a
        # counter that has not expired yet caches its value — and a counter
        # that has *not* been written yet caches the miss — so the second
        # read in the same request returns the same answer as the first and
        # the counter never rises.  The limit would then only apply to the
        # first question of every request, which is the same as no limit.
        hits = frappe.cache().get_value(key, expires=True) or 0
        if int(hits) >= limit:
            frappe.throw(
                _("Too many questions. Wait a minute and try again."),
                frappe.TooManyRequestsError,
            )
        frappe.cache().set_value(key, int(hits) + 1, expires_in_sec=BUCKET_SECONDS)
    except frappe.TooManyRequestsError:
        raise
    except Exception:
        logger.exception("Could not check the turn rate limit")


def _limit() -> int:
    """The configured ceiling. Zero means unlimited."""
    from albanna.services.settings_service import get_settings

    try:
        return int(get_settings().turns_per_minute)
    except Exception:
        logger.exception("Could not read the turn rate limit")
        return 0
