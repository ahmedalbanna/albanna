"""The app's health check: what a monitor may ask, and what it gets back.

A monitor cannot hold a Desk session, so the endpoint admits a guest —
the one guest door the app opens, and it opens it for exactly this:
booleans, a status word and the app version.  Nothing the site has not
already published somewhere: no site name, no user, no setting value,
no error detail.  The SEC3 pin (no endpoint admits a guest) carries
this endpoint in its allowlist, with the reasoning recorded in
ADR-0112.

A check that fails is reported, not raised: ``status`` becomes
``degraded`` and the failed check reads ``false``.  A monitor wants a
200 with ``degraded`` in it, not a 500 it cannot read a body from.

The logic lives in :func:`_health` and the whitelisted wrapper only
forwards to it, so the bench-free suite can test the logic without
going through Frappe's request-context validation.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna import __version__

#: The keys the response may carry.  A walker in
#: ``tests/test_observability_pins.py`` holds the endpoint to this set:
#: a key added here must be judged against what a guest may read.
ALLOWED_KEYS = ("status", "checks", "version", "chat")


def _db_probe() -> None:
    """The database answers."""
    frappe.db.sql("select 1")


def _cache_probe() -> None:
    """The cache redis answers."""
    frappe.cache().ping()


def _chat_ready() -> bool:
    """Whether the chat is configured: a settings row with a model set.

    The values themselves are not returned — whether the operator has
    chosen a model is a configuration fact, and the endpoint says only
    whether one was chosen.
    """
    try:
        settings = frappe.get_cached_doc("Albanna Settings")
        return bool(str(getattr(settings, "model", "") or "").strip())
    except Exception:
        return False


def _health() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for name, probe in (
        ("database", _db_probe),
        ("cache", _cache_probe),
    ):
        try:
            probe()
            checks[name] = True
        except Exception:
            checks[name] = False

    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks,
        "version": __version__,
        "chat": _chat_ready(),
    }


@frappe.whitelist(allow_guest=True)
def check() -> dict[str, Any]:
    """The app's health, as booleans a monitor can alert on."""
    return _health()
