"""The attachments a question carries, and the shape they cross the wire in.

The wire
--------

The browser sends the reader's files in two fields:

*   ``image`` — the bytes, as data URLs, so a vision-capable provider can
    read them;
*   ``image_urls`` — the addresses the bytes were already stored under, so
    the turn reuses the file instead of writing the same bytes twice.

Both fields are **one string parameter** on the wire, because that is what
the Desk's endpoint carries without a schema change.  A field therefore
arrives as a JSON-encoded list, and a turn queued before the field held a
list arrives as a single bare string.  All of those mean the same thing,
so :func:`read_attachment_list` reads all of them — and it is the only
place that does.  Four parsers with four meanings is how a turn that runs
here and now and a turn that runs in a worker come to disagree about the
same payload.

The rules
---------

The file types that may be attached are the same on both sides of the
wire, and they are published by the site rather than written twice: the
browser asks ``options()`` which types it takes.  A browser that accepts
a file the server would refuse is a reader who waited for an upload that
was going to be refused.

An SVG is the case that matters.  It is an image, the file picker shows
it as one, and it cannot be stored: it executes as HTML in a browser.

One rule, one place
-------------------

:func:`check_attachment` decides whether one file may be attached, and
every caller asks it.  The browser asks the site what the rule is rather
than keeping its own copy, so a rule that changed changes in one place,
and a reader refused in the browser and allowed on the server cannot
happen.

This module is the *rule*, and never the sentence.  It has no language of
its own, because it is imported by code that has no language of its own:
a rule that carries its own wording is a rule that has to be translated
in every place it is used, and a rule that is translated in one place and
not in the next is a rule the reader cannot predict.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AttachableType:
    """One file type an attachment may carry.

    The three names are one type seen three ways: what the browser calls
    it, what the stored file is called, and what a sentence calls it when
    it names the types the reader may attach.
    """

    #: The type the browser sends and the file itself carries.
    mime: str

    #: The extension the stored file gets, which is the type's own.
    extension: str

    #: The name the type is called by when a sentence names it.
    name: str


#: The file types an attachment may carry.  Anything else is rejected
#: rather than stored under a guessed extension: a broad accept would
#: happily file ``image/svg+xml`` (which executes as HTML) or
#: ``text/html`` away as a ``.bin`` name the chromium postfix would not.
ATTACHABLE_TYPES: tuple[AttachableType, ...] = (
    AttachableType("image/png", ".png", "PNG"),
    AttachableType("image/jpeg", ".jpg", "JPEG"),
    AttachableType("image/webp", ".webp", "WebP"),
    AttachableType("image/gif", ".gif", "GIF"),
    AttachableType("application/pdf", ".pdf", "PDF"),
)

#: The site has attachments switched off.  Nothing is carried, and the
#: reader is told: dropping the attachment quietly leaves the reader
#: believing the model saw a picture it never received.
DISABLED = "disabled"

#: The attachment could not be read — it is not a data URL, or its bytes
#: are not what they claim to be.
UNREADABLE = "unreadable"

#: The attachment is not one of the types that may be attached.
UNSUPPORTED_TYPE = "unsupported_type"

#: The attachment is over the site's ceiling.
TOO_LARGE = "too_large"

#: No file was given at all.
REQUIRED = "required"

#: The file could not be written.  This one is not a rule about the
#: file: it is the site failing to keep it.
NOT_STORED = "not_stored"


def attachable_type(mime: str) -> AttachableType | None:
    """The type the file is, if it is one this site attaches.

    :param mime the type the file claims to be
    :returns the type, or ``None`` when it is not one that may be attached
    """
    for candidate in ATTACHABLE_TYPES:
        if candidate.mime == mime:
            return candidate
    return None


def attachable_mimes() -> tuple[str, ...]:
    """The types an attachment may carry, in the order they are named."""
    return tuple(candidate.mime for candidate in ATTACHABLE_TYPES)


def attachable_names() -> tuple[str, ...]:
    """The names the types are called by, in the order they are named.

    These are the names a sentence uses when it tells the reader which
    types it takes.  They are product names and are not translated, which
    is why a sentence may carry them as a list.
    """
    return tuple(candidate.name for candidate in ATTACHABLE_TYPES)


def read_attachment_list(value: Any) -> tuple[list[str], bool]:
    """The attachments a wire field holds, and whether the field was readable.

    Returns ``(items, readable)``.  ``readable`` is False when the field
    held something that is not a list of strings — rubbish in, and the
    caller decides what to say about it.

    The field arrives in three shapes, and they all mean the same thing: a
    list of strings.

    *   a list, from a caller that speaks JSON to the server;
    *   a JSON-encoded list, which is what the browser's one string
        parameter carries;
    *   a single bare string, from a turn that was queued before the field
        held a list.

    A string that tries to be JSON and is not is rubbish, not an
    attachment: ``"[not json"`` is a broken field, and reading it as a
    file name would put a broken path into a turn.
    """
    if value is None:
        return [], True
    if isinstance(value, list):
        return _strings(value)
    if not isinstance(value, str):
        return [], False

    text = value.strip()
    if not text:
        return [], True

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        if text.startswith(("[", "{")):
            return [], False
        return [text], True

    if isinstance(parsed, list):
        return _strings(parsed)
    if isinstance(parsed, str):
        return ([parsed] if parsed else []), True
    return [], False


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """The bytes and the type a data URL carries.

    Returns ``(b"", "")`` when the payload cannot be read.  The type is
    the one the URL claims, and it is only a claim: whether it may be
    stored is :func:`check_attachment`'s decision, not this function's.

    A payload without a ``data:`` header is not a data URL.  The header is
    what says what the bytes are, and the file rules are a list of types:
    a payload with no type is on no list.
    """
    if not isinstance(data_url, str) or not data_url:
        return b"", ""

    header, _, payload = data_url.partition(",")
    if not header.startswith("data:") or not payload:
        return b"", ""

    mime = header[len("data:") :].split(";")[0].strip().lower()
    try:
        raw = base64.b64decode(payload, validate=True)
    except (TypeError, ValueError):
        return b"", ""
    if not raw:
        return b"", ""
    return raw, mime


def check_attachment(mime: str, size: int, max_bytes: int = 0) -> str:
    """Why one attachment may not be carried, or ``""`` when it may.

    This is the rule.  Every caller — the turn, the upload endpoint, the
    storage door — asks this function, so a file that is refused in one
    place is refused in all of them for the same reason.

    :param mime the type the file claims to be
    :param size the file's size in bytes
    :param max_bytes the site's ceiling in bytes; zero means no ceiling
    :returns the reason, or an empty string when the file may be carried
    """
    if attachable_type(mime) is None:
        return UNSUPPORTED_TYPE
    if max_bytes and size > max_bytes:
        return TOO_LARGE
    return ""


def check_attachments(value: Any, max_bytes: int = 0) -> tuple[list[str], str]:
    """The attachments a field holds, and why they may not be carried.

    Returns ``(images, reason)``.  ``reason`` is empty when the
    attachments may be carried, and otherwise names the rule they broke.
    The wording is the caller's.

    A field that cannot be read yields **no** attachments, not the ones
    read so far.  A turn that carried two pictures and could not read the
    second must not reach the model carrying the first: the reader
    attached both, and the model would answer about half of what it was
    given.

    A ceiling of zero means no ceiling.
    """
    images, readable = read_attachment_list(value)
    if not readable:
        return [], UNREADABLE

    for entry in images:
        raw, mime = decode_data_url(entry)
        if not raw:
            return [], UNREADABLE
        reason = check_attachment(mime, len(raw), max_bytes)
        if reason:
            return [], reason

    return images, ""


def paired_addresses(count: int, urls: list[str]) -> list[str]:
    """The stored addresses that can be matched to the turn's pictures.

    The addresses and the bytes are parallel lists: the address at one
    place is the address of the bytes at the same place.  The turn reuses
    a file rather than storing its bytes again, and reusing the *wrong*
    address is worse than storing the bytes twice — the model would be
    asked about one picture and pointed at another.

    So the addresses are used only when there is one for every picture.  A
    client that sends fewer, or more, has not said which address belongs
    to which picture, and the bytes are stored again instead.

    :param count how many pictures the turn carries
    :param urls the addresses the client sent
    :returns the addresses to reuse, in order, or an empty list when they
        cannot be told apart
    """
    if len(urls) != count:
        return []
    return list(urls)


def _strings(items: list[Any]) -> tuple[list[str], bool]:
    """The string entries of a list, and whether they all were strings.

    An empty entry carries nothing and is dropped.  An entry that is not a
    string at all means the field is malformed, and the caller is told.
    """
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            return [], False
        if item:
            out.append(item)
    return out, True
