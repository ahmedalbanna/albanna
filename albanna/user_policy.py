"""Per-user overrides for the safety rails.

Site defaults apply to everyone.  A policy row narrows or widens them for
one account, and a blank override means "use the site default" — the same
rule the connector used, and for the same reason: a missing override is
the inheritance, not a refusal.
"""

from __future__ import annotations

from typing import Any

import frappe

POLICY_DOCTYPE = "Albanna User Policy"


def get_user_policy_doc(user: str | None = None) -> Any | None:
    """The user's policy, or None when they have none.

    Never raises: a missing table (pre-migration) or any db error reads as
    "no overrides", so the site defaults apply untouched.
    """
    try:
        name = user or str(frappe.session.user or "")
        if not name or name == "Guest":
            return None
        docname = frappe.db.get_value(POLICY_DOCTYPE, {"user": name}, "name")
        if not docname:
            return None
        return frappe.get_cached_doc(POLICY_DOCTYPE, docname)
    except Exception:
        return None


def confirm_writes_for(user: str | None = None) -> bool:
    """Whether *user* must confirm writes before they happen.

    The site default is the floor and the ceiling both: a policy row may
    turn the rail on for a user who would not otherwise have it, or off
    for a user who would.  A blank override inherits the site default.
    """
    from albanna.services.settings_service import get_settings

    site_default = bool(getattr(get_settings(), "confirm_writes", False))

    doc = get_user_policy_doc(user)
    if doc is None:
        return site_default

    override = str(getattr(doc, "confirm_writes_override", "") or "").strip().lower()
    if override == "always":
        return True
    if override == "never":
        return False
    return site_default
