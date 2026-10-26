"""The widget's options.

The launcher calls this on every Desk page load to find out whether the
widget should render at all.

A user who may not chat does not get the widget at all: a side chat that
cannot be used is not a thing that should be on the screen, and the
reason it is not there is already a permission fact that Frappe and the
operator's role assignment explain elsewhere.  The gate that matters is on
the endpoints that actually run a turn.

Nothing secret is returned, and no role names -- the payload says what the
widget may do, not who may do it.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna.core.authority import Authority
from albanna.services.toolset import tool_registry


@frappe.whitelist()
def options() -> dict[str, Any]:
    """What the widget should render, and what it may do."""
    from albanna.permissions import (
        FrappePermissionChecker,
        can_use_chat,
        current_principal,
    )
    from albanna.services.settings_service import get_settings

    settings = get_settings()

    chat_access = can_use_chat()
    enabled = bool(settings.enabled)
    visible = enabled and chat_access

    tools: list[str] = []
    if chat_access and visible:
        principal = current_principal()
        authority = Authority(
            tool_registry(principal.user),
            principal,
            FrappePermissionChecker(),
        )
        tools = list(authority.visible_names())

    return {
        "visible": visible,
        "locked": not chat_access,
        "chat_access": chat_access,
        "enabled": enabled,
        "position": settings.widget_position,
        "position_default": settings.widget_position,
        "tools": tools,
        "image_support": settings.image_support,
        "max_image_size_kb": settings.max_image_size_kb,
    }
