"""The attachments the site accepts, stores and refuses.

The half that needs the framework: the folder the files live in, the
write that puts them there, and the sentences a reader is refused in.

The rules themselves are in ``albanna.core.attachments``, which imports
no Frappe.  A rule that lives beside the code that needs a database is a
rule that can only be tested where a database is, and this one is tested
without one.

The file rules live here and not in the turn orchestrator because they
are not the turn's: the upload endpoint writes files without a turn ever
running, and an endpoint that has to reach into the orchestrator for the
rules it follows is an endpoint that cannot be changed without changing
the turn.
"""

from __future__ import annotations

import logging
from typing import Any

import frappe
from frappe import _

from albanna.core.attachments import (
    DISABLED,
    NOT_STORED,
    REQUIRED,
    TOO_LARGE,
    UNREADABLE,
    UNSUPPORTED_TYPE,
    attachable_names,
    attachable_type,
    check_attachment,
    decode_data_url,
)

logger = logging.getLogger(__name__)

#: The folder attachments are stored under.
ALBANNA_FOLDER = "Home/Albanna"


def ensure_albanna_folder() -> str:
    """Ensure the 'Home/Albanna' folder exists and return its name."""
    folder_name = ALBANNA_FOLDER
    if frappe.db.exists("File", folder_name):
        return folder_name
    try:
        folder = frappe.new_doc("File")
        folder.file_name = "Albanna"
        folder.is_folder = 1
        folder.folder = "Home"
        folder.insert(ignore_permissions=True)
        return folder.name
    except Exception:
        if frappe.db.exists("File", "Home/Attachments"):
            return "Home/Attachments"
        return "Home"


def max_attachment_bytes() -> int:
    """The site's ceiling on an attachment, in bytes.  Zero means none.

    The setting is named for attachments because attachments were the only thing
    that could be attached when it was written; it is the site's only
    ceiling on a file, so it is the one that applies to a PDF too.
    """
    from albanna.services.settings_service import get_settings

    try:
        settings = get_settings()
        return int(getattr(settings, "max_attachment_size_kb", 0) or 0) * 1024
    except Exception:
        logger.exception("Could not read the site's attachment ceiling")
        return 0


def store_attached_bytes(raw: bytes, mime: str, user: str) -> dict[str, str] | None:
    """Store bytes as a private Frappe File, and say where they went.

    Returns ``{"file_url", "name", "size", "mime"}`` or ``None`` when the
    file may not be stored, or could not be.  The file is private so that
    only the uploader's session can read it.

    The rule is enforced here, at the door that writes the bytes, and not
    only at the doors that ask for them: a caller that reaches this
    function directly is a caller that was never told the rule, and the
    browser's own check is not the one that fills the disk.
    """
    reason = check_attachment(mime, len(raw), max_attachment_bytes())
    if reason:
        logger.warning("Refused an attached file: %s", reason)
        return None

    kind = attachable_type(mime)
    if kind is None:
        return None
    try:
        filename = f"albanna-{frappe.generate_hash(length=8)}{kind.extension}"
        folder = ensure_albanna_folder()
        saved = frappe.utils.file_manager.save_file(
            filename, raw, "User", user, is_private=1, folder=folder
        )
        file_url = str(getattr(saved, "file_url", "") or "")
        if not file_url:
            return None
        return {
            "file_url": file_url,
            "name": str(getattr(saved, "name", "") or ""),
            "size": len(raw),
            "mime": mime,
        }
    except Exception:
        logger.exception("Could not store an attached file")
        return None


def store_attached_file(data_url: str, user: str) -> dict[str, str] | None:
    """Store an attached file as a private Frappe File.

    Returns ``{"file_url", "name", "size", "mime"}`` or ``None`` when the
    file could not be stored.  The file is private so that only the
    uploader's session can read it.

    This is the turn's door: it refuses silently, because a turn that
    cannot store a picture still answers, and the reader is told that the
    attachment did not make it.  The endpoint that uploads on its own
    says the same refusals in words, because there the reader is waiting
    for an answer and can do something about it.
    """
    if not data_url:
        return None
    raw, mime = decode_data_url(data_url)
    if not raw:
        return None
    return store_attached_bytes(raw, mime, user)


def refusal_sentence(reason: str, max_kb: int = 0) -> str:
    """The sentence a refusal is shown to the reader in.

    One sentence per reason, and the same sentence wherever the reader is
    refused: a reader refused at the upload and allowed at the turn
    cannot tell which rule they broke.

    The names of the types are a list inside the sentence and not part
    of it: they are product names, and a sentence that carried them
    would be a sentence the translator could not translate.
    """
    if reason == DISABLED:
        return _("Image attachments are not enabled on this site.")
    if reason == UNSUPPORTED_TYPE:
        # The types are named, because "only attachments" is not an answer a
        # reader can act on: an SVG *is* an image, and an SVG cannot be
        # stored, because it executes as HTML.
        #
        # The list is the site's own, so the sentence cannot name types
        # the site no longer takes.
        return _("Only {0} files can be attached.").format(", ".join(attachable_names()))
    if reason == TOO_LARGE:
        # The number is a placeholder, not part of the sentence: a
        # sentence with a number baked into it is a sentence the
        # translator cannot translate.
        return _("The file is larger than {0} KB.").format(max_kb)
    if reason == UNREADABLE:
        return _("The file could not be read.")
    if reason == REQUIRED:
        return _("A file is required.")
    if reason == NOT_STORED:
        return _("The file could not be stored.")
    return ""


def ceiling_in_kb(settings: Any) -> int:
    """The site's ceiling on an attachment, in kilobytes.

    The size the refusal names is the site's own setting, in the unit the
    setting is written in, so the reader is told the number the operator
    set rather than a number converted twice.
    """
    try:
        return int(getattr(settings, "max_attachment_size_kb", 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return 0
