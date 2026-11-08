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
from frappe import _

from albanna.api.chat import MAX_QUESTION_LENGTH
from albanna.core.attachments import (
    ATTACHABLE_TYPES,
    DISABLED,
    NOT_STORED,
    REQUIRED,
    UNREADABLE,
    check_attachment,
    decode_data_url,
)
from albanna.core.authority import Authority
from albanna.permissions import require_chat_access
from albanna.privacy import redacted_request_text
from albanna.services.toolset import tool_registry


@frappe.whitelist()
@redacted_request_text("file_data_url")
def upload_file(file_data_url: str = "") -> dict[str, Any]:
    """Store an attached file as a private Frappe File.

    The file lands under Home/Albanna before the turn is sent.  The same
    bytes still travel with the turn as a data URL for the model; this is
    what lets the reader set the file on a document later.

    The parameter carries the reader's whole file, so it is redacted from
    the request log before the body runs: the log is read by operators and
    copied off the host, and a picture of a payslip is not something that
    belongs there.

    The destination is the app's, not the caller's: the folder is fixed,
    because a folder is a path on the server and a path is not something
    a browser gets to name.

    Every refusal is said in words the reader can act on, and they are
    the words every other door says and the words the browser says: a
    reader refused here and allowed there cannot tell which rule they
    broke.  The rule itself is asked, not written here.
    """
    require_chat_access()
    from albanna.services.attachments import (
        ceiling_in_kb,
        max_attachment_bytes,
        refusal_sentence,
        store_attached_bytes,
    )
    from albanna.services.settings_service import get_settings

    if not file_data_url:
        frappe.throw(refusal_sentence(REQUIRED), frappe.ValidationError)

    settings = get_settings()
    if not getattr(settings, "attachment_support", False):
        frappe.throw(refusal_sentence(DISABLED), frappe.ValidationError)

    raw, mime = decode_data_url(file_data_url)
    if not raw:
        frappe.throw(refusal_sentence(UNREADABLE), frappe.ValidationError)

    reason = check_attachment(mime, len(raw), max_attachment_bytes())
    if reason:
        frappe.throw(
            refusal_sentence(reason, ceiling_in_kb(settings)),
            frappe.ValidationError,
        )

    result = store_attached_bytes(raw, mime, frappe.session.user or "")
    if not result:
        frappe.throw(refusal_sentence(NOT_STORED), frappe.ValidationError)
    return result


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
        "attachment_support": settings.attachment_support,
        "max_attachment_size_kb": settings.max_attachment_size_kb,
        # The question's ceiling, published for the same reason the
        # attachable types are: the browser enforces it so the reader is
        # told before they send, and the endpoint enforces it because the
        # browser is one client.  Two copies of the number is two numbers
        # that drift, and a composer that lets a reader type more than the
        # door will take is a composer that wastes their time.
        "max_question_length": MAX_QUESTION_LENGTH,
        # The types the site attaches, published so the browser does not
        # keep a copy of them.  A browser that keeps a copy is a browser
        # whose copy goes stale, and a stale copy is a browser that
        # accepts a file the server refuses.
        "attachable_types": [
            {"mime": candidate.mime, "name": candidate.name} for candidate in ATTACHABLE_TYPES
        ],
    }
