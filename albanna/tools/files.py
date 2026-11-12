"""The file tools: reading what the site has stored, and writing to it.

A file reaches a turn in two ways — as the picture a vision provider
looks at directly, or as the text the attachment note carried the turn
it was attached.  Both are one-shot: a picture in a later turn is a path
in words, and a note's text was read once, at whatever length fit.  The
model had no way to go back to the file itself.

``read_file`` is that way.  It is the same read the attachment note
performs — ``attachment_text`` for a PDF, a decode for a text file — but
on demand, with an offset for a document too long for one read, and
against any File on the site the account may read, not only the ones
this chat has stored.  The note's extract stops at its ceiling, because
it travels inside every turn that follows; a read on demand has no such
arithmetic, and reads the whole document in parts.

``write_file`` and ``edit_file`` are the way forward, not back: a file
made at the reader's request, and a file's text replaced.  Both are
writes — they wait for the reader's approval like every other write —
and both produce text, because text is what the model has.  A picture
is refused as a picture, in both directions.

The permission is the File's own: ``frappe.has_permission("File",
"read", doc=...)`` decides who reads, and the framework's own create and
write checks decide who makes and who changes — which is the same
decision the Desk's file list makes.  A private file belongs to its
owner and to nobody else, and a public file is everybody's.
"""

from __future__ import annotations

import mimetypes
from typing import Any

import frappe

from albanna.core.attachments import attachment_text
from albanna.core.tools import MAX_RESULT_CHARS
from albanna.tools.erpnext import _file_for_url, _may_read_file, error, ok

#: The most text one read returns, in characters.
#:
#: The same arithmetic as the attachment note's ceiling: a tool that
#: returns a whole book does not become a better answer, it becomes a
#: turn that exhausts the context window.  The spec's own
#: ``max_result_chars`` is set higher than this, so the envelope around
#: the text — the counts and the next offset — survives the backend's
#: truncation of the whole result.
READ_CHUNK_CHARS = MAX_RESULT_CHARS


def read_file(file: str, offset: Any = None) -> str:
    """Read the text of a stored file.

    Args:
        file: The file's URL (``/files/...`` or ``/private/files/...``)
            or the name of its File record.
        offset: The character to start reading from, for a file too long
            for one read.  Omit to read from the beginning.
    """
    if not isinstance(file, str) or not file.strip():
        return error("A file is required: its URL or the name of its File record.")

    file = file.strip()
    source = _resolve(file)
    if source is None:
        return error(
            f"No file was found at '{file}'.",
            actionable=(
                "Use the exact URL the attachment or the document named — "
                "a /files/... or /private/files/... path — or the name of "
                "its File record. Do not guess a path."
            ),
        )

    if not _may_read_file(source):
        return error(
            f"The file '{source.file_url or source.name}' could not be read: "
            "this account may not read it.",
            denied=True,
            actionable=(
                "A private file belongs to the account that uploaded it. "
                "State that as a fact about the account, and do not "
                "apologise for it."
            ),
        )

    mime = str(getattr(source, "mime_type", "") or "") or (
        mimetypes.guess_type(source.file_url or "")[0] or ""
    )
    if mime.startswith("image/"):
        return error(
            f"'{source.file_url or source.name}' is a picture, and a picture's "
            "pixels cannot be read as text.",
            actionable=(
                "A picture attached to a message travels to the model "
                "directly, when the model can see pictures; in later turns "
                "of the same conversation only its address remains. Say "
                "what you can see or that you cannot see it, and do not "
                "call read_file on a picture again."
            ),
        )

    try:
        content = source.get_content()
    except Exception as exc:
        return error(
            f"The file '{source.file_url or source.name}' could not be read: {exc}",
            actionable=(
                "The file's row exists but its bytes do not — it may be "
                "stored elsewhere, or removed. Do not retry the same read."
            ),
        )
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")

    text = attachment_text(content or b"", mime, ceiling=None)
    if not text:
        return error(
            f"The file '{source.file_url or source.name}' holds no text that "
            "could be extracted.",
            actionable=(
                "It may be a scan — pictures of words, which read as no "
                "words at all — or a binary kind this site cannot read. "
                "Say so as a fact about the file, and do not describe "
                "what it says."
            ),
        )

    total = len(text)
    start = 0
    if offset not in (None, ""):
        try:
            start = int(offset)
        except (TypeError, ValueError):
            return error(
                f"The offset {offset!r} is not a character offset.",
                actionable="Read again with a whole number of characters, or without an offset.",
            )
        if start < 0:
            start = 0
        if start >= total:
            return error(
                f"The offset {start} is past the end of the file: it holds "
                f"{total} characters.",
                actionable="Read again with a smaller offset, or without one.",
            )

    chunk = text[start : start + READ_CHUNK_CHARS]
    more = start + len(chunk) < total
    return ok(
        f"Read characters {start}–{start + len(chunk)} of {total} "
        f"from '{source.file_url or source.name}'",
        data={
            "file": source.file_url or source.name,
            "is_private": bool(getattr(source, "is_private", 1)),
            "total_characters": total,
            "offset": start,
            "returned_characters": len(chunk),
            "more_remain": more,
            "next_offset": start + len(chunk) if more else None,
            "text": chunk,
        },
    )


def _resolve(file: str):
    """The File document behind a URL, a record name, or a bare path.

    A URL is the shape the attachment note and a document's own field
    carry, so it is tried first.  A File record's name is the shape a
    previous read returned.  Both are looked up; neither is guessed.
    """
    if file.startswith(("/files/", "/private/files/")):
        return _file_for_url(file)
    if frappe.db.exists("File", file):
        try:
            return frappe.get_doc("File", file)
        except Exception:
            return None
    return _file_for_url(file)


def write_file(file_name: str, content: str, is_private: Any = None) -> str:
    """Create a new file with the text content the model provides.

    Args:
        file_name: The file's name, with its extension.
        content: The full text of the file.
        is_private: True for a private file (the default), false for public.
    """
    if not isinstance(file_name, str) or not file_name.strip():
        return error("A file name is required, with its extension — e.g. 'customers.csv'.")
    if not isinstance(content, str) or not content:
        return error(
            "The file's content is required, as text.",
            actionable=(
                "A binary kind — a picture, a PDF — cannot be written by "
                "this tool. Say so rather than sending bytes you do not have."
            ),
        )

    file_name = file_name.strip()
    # A private file is the default, and the safe one: a public file is
    # served to anybody on the internet without a login, and "the model
    # did not say" must not read as "make it public".
    private = True if is_private is None else bool(is_private)

    document = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "content": content,
            "is_private": 1 if private else 0,
            "folder": "Home",
        }
    )
    try:
        # The framework's own permission check runs here: an account that
        # may not create a File does not create one, whatever the
        # authority layer believed about the manifest.
        document.insert()
    except Exception as exc:
        return error(f"The file could not be created: {exc}")

    return ok(
        f"Created file '{document.file_url}'",
        data={
            "name": document.name,
            "file_url": document.file_url,
            "file_name": document.file_name,
            "is_private": bool(document.is_private),
            "size": int(document.file_size or 0),
        },
    )


def edit_file(file: str, content: str) -> str:
    """Replace the text content of a file that already exists.

    Args:
        file: The file's URL or the name of its File record.
        content: The full new text, replacing what the file held.
    """
    if not isinstance(content, str) or not content:
        return error("The file's new content is required, as text.")

    source = _resolve((file or "").strip()) if isinstance(file, str) else None
    if source is None:
        return error(
            f"No file was found at '{file}'.",
            actionable=(
                "Use the exact URL the attachment or the document named — "
                "a /files/... or /private/files/... path — or the name of "
                "its File record. Do not guess a path."
            ),
        )

    if not _may_read_file(source):
        return error(
            f"The file '{source.file_url or source.name}' could not be read: "
            "this account may not read it.",
            denied=True,
            actionable=(
                "A file this account cannot read is a file it cannot "
                "change either. State that as a fact about the account."
            ),
        )
    if not frappe.has_permission("File", "write", doc=source):
        return error(
            f"The file '{source.file_url or source.name}' could not be "
            "changed: this account may not write files.",
            denied=True,
            actionable="State that as a fact about the account, and do not apologise for it.",
        )

    mime = str(getattr(source, "mime_type", "") or "") or (
        mimetypes.guess_type(source.file_url or "")[0] or ""
    )
    if mime.startswith("image/"):
        return error(
            f"'{source.file_url or source.name}' is a picture, and a picture's "
            "pixels cannot be written as text.",
            actionable="Say that the picture cannot be edited this way.",
        )

    try:
        # Frappe's own replacement path: the same file name, the same
        # URL, new bytes, and the old content kept for the transaction's
        # rollback.  The save that follows persists the new hash and size.
        source.save_file(content=content, overwrite=True)
        source.save()
    except Exception as exc:
        return error(f"The file could not be changed: {exc}")

    return ok(
        f"Changed file '{source.file_url}'",
        data={
            "name": source.name,
            "file_url": source.file_url,
            "file_name": source.file_name,
            "is_private": bool(source.is_private),
            "size": int(source.file_size or 0),
        },
    )
