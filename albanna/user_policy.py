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


def chat_access_override(user: str | None = None) -> str:
    """The per-user override on chat access: ``"on"``, ``"off"`` or ``""``.

    The empty string means "no opinion" — the permission matrix decides,
    which is the ordinary case and the only one most accounts are in.

    "Off" and "On" are the operator's last word about one account, in
    either direction: "off" refuses a person the matrix would allow (the
    chat comes with a shared role, and this account is the exception),
    and "on" allows a person the matrix would refuse (the account has a
    Desk role of its own, and the chat is wanted on top of it).

    The permission matrix stays the rule for everyone else.  There is no
    list of role names in this app, and a policy row is not one: it is a
    visible, per-account exception to the matrix, kept by the same
    people who own the matrix.
    """
    doc = get_user_policy_doc(user)
    if doc is None:
        return ""

    override = str(getattr(doc, "chat_access_override", "") or "").strip().lower()
    if override == "on":
        return "on"
    if override == "off":
        return "off"
    return ""
