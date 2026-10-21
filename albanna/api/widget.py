"""The widget's options.

The launcher calls this on every Desk page load to find out whether the
widget should render at all.

It is deliberately **not** gated on chat access.  A user who may not chat
still gets the widget, in its locked state: a panel that says why it is
locked is information, and a widget that silently does not appear looks
like a broken install.  The gate that matters is on the endpoints that
actually run a turn.

Nothing secret is returned, and no role names — the payload says what the
widget may do, not who may do it.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna.core.authority import Authority
from albanna.core.tools import TOOL_MANIFEST


@frappe.whitelist()
def options() -> dict[str, Any]:
    """What the widget should render, and what it may do."""
    from albanna.permissions import FrappePermissionChecker, can_use_chat, current_principal
    from albanna.services.settings_service import get_settings

    settings = get_settings()

    chat_access = can_use_chat()
    enabled = bool(settings.enabled) and bool(settings.widget_enabled)

    widget_roles = set(settings.widget_roles)
    if widget_roles:
        try:
            roles = set(frappe.get_roles())
        except Exception:
            roles = set()
        visible = enabled and bool(widget_roles & roles)
    else:
        visible = enabled

    tools: list[str] = []
    if chat_access and visible:
        authority = Authority(
            TOOL_MANIFEST.without(settings.disabled_tools),
            current_principal(),
            FrappePermissionChecker(),
        )
        tools = list(authority.visible_names())

    return {
        "visible": visible,
        "locked": not chat_access,
        "chat_access": chat_access,
        "enabled": bool(settings.enabled),
        "position": settings.widget_position,
        "position_default": settings.widget_position,
        "tools": tools,
    }
