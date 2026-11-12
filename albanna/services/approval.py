"""The wait for a reader's decision, and what the reader is told about it.

A write that the rail is on does not run until the reader has answered.
The worker that proposed it waits here, and the browser answers by writing
the decision to the cache under the reader's own namespace.

Everything a turn needs to *speak* about the wait lives here too: the
human-readable preview the confirmation card opens with
(:func:`write_preview`) and the sentence the model is told when the write
was not made (:func:`denial_message`).  They sit beside the wait because
they are three parts of one answer to one question — what is about to
happen, can I go on, and what happened instead.


The one subtlety this module exists for
----------------------------------------
``frappe.cache().get_value()`` keeps what it read in the request's local
cache — *including a miss*.  A poll that does not ask for ``expires=True``
therefore reads the miss back on every later iteration instead of asking
Redis again, and the reader's answer — written by another request, after
the first poll — is never seen.  The wait then times out whatever the
reader did, and the only symptom is a turn that says the write was not
approved.

So the poll asks for ``expires=True``: the value is read from Redis every
time, and never kept.


The second subtlety: the reader's answer must not live in the reader's
namespace
--------------------------------------------------------------------
``frappe.cache()`` namespaces anything written with ``user=`` under
``<db>|user:<user>:``, and the framework's own
``frappe.cache_manager.clear_user_cache(user)`` deletes **everything**
under that prefix — ``delete_keys("user:" + user)`` — on a login, a
logout, a User document save, a role change.  A pending write stored
there is deleted the moment any of those happens, whatever the reader
did: their answer, already written, vanishes; the worker's poll reads a
record that is no longer there, waits out the whole window, and tells
the model the reader did not approve.  The change the reader confirmed
is then not made — the one failure whose symptom is a lie, because the
reader is told the write was refused while they had approved it.

So the pending record is stored under the *site's* namespace instead —
``make_key`` without ``user`` — where the framework's housekeeping never
reaches, and *who may answer* is a field in the record rather than a
prefix of the key: the request id is a 128-bit random hex, the record
names the reader it belongs to, and the endpoint refuses anybody else's
word for it.  A record that survives a cache clear, binds one reader's
answer, and dies with its own TTL is the record that keeps the reader's
word.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import frappe

from albanna.permissions import may_read

logger = logging.getLogger(__name__)

#: The prefix every pending write is stored under.
PENDING_PREFIX = "albanna:pending:"

#: The message the model is told when the document moved under the
#: reader's feet.
CHANGED_MESSAGE = (
    "The document changed while the reader was deciding, so the change was "
    "not made. Read the document again and propose the change afresh."
)

#: How long the reader is given, in seconds, when the operator has not
#: said.  The same default the settings field carries.
DEFAULT_TIMEOUT = 120.0

#: The shortest and longest a wait may be set to.
#:
#: A floor, because a wait shorter than a reader's pause is a rail that
#: refuses writes nobody was given the chance to approve; a ceiling,
#: because the worker holds its slot for as long as the wait lasts, and
#: a wait that can be set to an hour is a worker held for an hour.
MIN_TIMEOUT = 30.0
MAX_TIMEOUT = 600.0


def wait_seconds(configured) -> float:
    """The wait to use, from whatever the operator set.

    A number outside the bounds is clamped rather than refused: an
    operator who typed 5000 meant "a long time", and refusing the turn
    over a typo in a setting is a worse answer than honouring the
    intent.
    """
    try:
        seconds = float(configured)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if seconds <= 0:
        return DEFAULT_TIMEOUT
    return min(max(seconds, MIN_TIMEOUT), MAX_TIMEOUT)


#: How long between two reads of the decision.  Short enough that the
#: reader's approval is acted on within a tenth of a second, long enough
#: that an idle turn does not hammer Redis.
DEFAULT_INTERVAL = 0.1

#: The answer when the reader does not answer in time.
TIMEOUT = "timeout"


def _readable_document(doctype: str, name: str):
    """The document, if the reader may read it; otherwise ``None``.

    The confirmation card is shown to the reader, so everything on it is
    shown to them.  A document they may not read must not be named on
    the card, and the values the model wants to change must not be on it
    either — the model may have read them from the document.
    """
    if not doctype or not name:
        return None

    try:
        document = frappe.get_doc(doctype, name)
    except Exception:
        return None

    if not may_read(document):
        return None

    return document


def write_preview(name: str, arguments: dict) -> str:
    """A compact, human-readable summary of a pending write.

    The reader approves a *change*, not a JSON blob, so the confirmation
    dialog says what will happen in the reader's words: "Create Customer:
    Acme (type Company)" rather than the raw arguments.

    The words are deliberately the *app's* fixed verbs — Create, Change —
    because this string is composed in the worker, which has no reader's
    language; the card around it carries the sentence around it.

    The card never names a document the reader may not read.  It is the
    one place a write is described *before* it runs, and a description
    that names a document the reader cannot see is a leak with a
    confirmation button on it.
    """
    arguments = arguments or {}
    doctype = str(arguments.get("doctype") or "").strip()
    data = arguments.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if name == "create_doc":
        return _preview_create(doctype, data)
    if name == "update_doc":
        return _preview_update(doctype, arguments, data)
    if name == "bulk_update_doc":
        return _preview_bulk(doctype, arguments, data)
    if name == "write_file":
        return _preview_write_file(arguments)
    if name == "edit_file":
        return _preview_edit_file(arguments)

    return f"{name}({doctype})"


#: The most content a file card quotes, in characters.
#:
#: The card is read by a person deciding in seconds, and a diff of a
#: whole document is a wall of text nobody reads — the same arithmetic
#: that bounds a tool result.  The card quotes the head and says how
#: much more there is.
FILE_PREVIEW_CHARS = 600


def _preview_write_file(arguments: dict) -> str:
    """The card for a new file."""
    file_name = str(arguments.get("file_name") or "").strip()
    content = str(arguments.get("content") or "")
    if not file_name:
        return "Create a file"
    size = len(content)
    if size > FILE_PREVIEW_CHARS:
        return f"Create file {file_name} ({size} characters)"
    return f"Create file {file_name}: {content}"


def _preview_edit_file(arguments: dict) -> str:
    """The card for a change to a file that already exists."""
    file = str(arguments.get("file") or "").strip()
    if not file:
        return "Change a file"
    return f"Change file {file}"


def _preview_create(doctype: str, data: dict) -> str:
    """The card for a new document."""
    title = _preview_title(doctype, data)
    if title:
        return f"Create {doctype}: {title}"
    return f"Create a {doctype}"


def _preview_update(doctype: str, arguments: dict, data: dict) -> str:
    """The card for a change to a document that already exists."""
    docname = str(arguments.get("name") or "").strip()
    if not _readable_document(doctype, docname):
        # Not named, and not described: the values may have come from
        # the document.
        return f"Change a {doctype}"

    fields = ", ".join(f"{key} = {value}" for key, value in list(data.items())[:6])
    if docname and fields:
        return f"Change {doctype} {docname}: {fields}"
    if docname:
        return f"Change {doctype} {docname}"
    return f"Change a {doctype}"


def _current_values(doctype: str, filters: Any, field: str, limit: int) -> dict[str, int]:
    """How the matched documents currently hold *field*, as value → count.

    The reader approves a change *from* a state, and across a set of
    documents that state is not one value.  Saying "status = Paid" without
    saying what the status is now asks the reader to approve a change they
    cannot picture — they may be moving twelve drafts and thirty billed
    invoices, or forty-two documents that are already paid.

    The distribution is the reader's own, drawn from the same filtered
    query the count and the sample names come from, so a card never tells
    a reader what they cannot see.

    Counted in Python rather than by a grouped query: the set is already
    bounded by the change's own limit, and a ``group_by`` over a field the
    model named is one more thing that can fail on a site whose reports
    are somebody else's.
    """
    try:
        rows = frappe.get_list(
            doctype,
            filters=filters,
            fields=[field],
            limit=limit,
        )
    except Exception:
        return {}

    counts: dict[str, int] = {}
    for row in rows or []:
        value = row.get(field) if isinstance(row, dict) else None
        key = "" if value is None else str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _distribution(counts: dict[str, int]) -> str:
    """The distribution as a sentence fragment: "Draft 12, To Bill 30"."""
    if not counts:
        return ""
    # Largest first, so the reader sees what most of the set is before
    # they see the tail.  An empty value is named rather than dropped:
    # "unset 4" is a fact about the documents, and a missing bucket is a
    # count that does not add up.
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{value or 'unset'} {count}" for value, count in ordered)


def _preview_bulk(doctype: str, arguments: dict, data: dict) -> str:
    """The card for a change to many documents at once."""
    filters = arguments.get("filters") or []
    limit = arguments.get("limit") or 50
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    fields = ", ".join(f"{key} = {value}" for key, value in list(data.items())[:6])
    try:
        # ``get_list`` and not ``get_all``: the count on the card is the
        # reader's count, and the sample names are the names of documents
        # the reader may read.  A card that says "Change 42 Sales
        # Invoices" to a reader who may see three of them tells them
        # what they cannot see, and asks them to approve it besides.
        names = frappe.get_list(doctype, filters=filters, pluck="name", limit=limit)
    except Exception:
        names = []

    count = len(names)
    sample = ", ".join(names[:5])
    if count == 0:
        return f"Change {doctype}: no documents match the filters"

    # What the set holds now, for the fields being changed.  Only the
    # fields the card actually names, so a change of six fields costs six
    # bounded queries and a change of one costs one.
    current = ""
    shown = list(data.items())[:6]
    if shown:
        parts = []
        for field, _value in shown:
            distribution = _distribution(_current_values(doctype, filters, field, limit))
            if distribution:
                parts.append(f"{field} is currently {distribution}")
        if parts:
            current = " (" + "; ".join(parts) + ")"

    suffix = f" (showing {sample})" if sample else ""
    if fields:
        return f"Change {count} {doctype} document(s): {fields}{current}{suffix}"
    return f"Change {count} {doctype} document(s){current}{suffix}"


def _preview_title(doctype: str, data: dict) -> str:
    """The most identifying value in a new document's data."""
    for key in (
        "customer_name",
        "supplier_name",
        "full_name",
        "item_name",
        "subject",
        "title",
        "name",
    ):
        value = data.get(key)
        if value:
            return str(value)
    # Fall back to the first non-empty value.
    for value in data.values():
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value)
    return ""


def write_diff(name: str, arguments: dict):
    """The before/after diff for a pending write, or None.

    Only ``update_doc`` carries a diff today: it is the only tool that
    changes existing fields.  ``create_doc`` makes a new document (there is
    no "before"), and the lifecycle tools change status rather than fields.

    The diff is computed from the document as it is now and the values the
    model proposed.  It is a *preview*: the real validation happens when
    the tool runs, and a refused write carries no diff.

    A document the reader may not read carries no diff either.  The
    "before" column is the document's own content, and the card is shown
    to the reader.
    """
    arguments = arguments or {}
    if name == "edit_file":
        return _file_diff(arguments)
    if name != "update_doc":
        return None

    doctype = str(arguments.get("doctype") or "").strip()
    docname = str(arguments.get("name") or "").strip()
    data = arguments.get("data") or {}
    if not doctype or not docname or not isinstance(data, dict):
        return None

    document = _readable_document(doctype, docname)
    if document is None:
        return None

    before = {field: document.get(field) for field in data}
    from albanna.core.diff import diff_fields

    return diff_fields(before, data, list(data.keys()))


def _file_diff(arguments: dict):
    """The before/after of a file's text, as the card shows it.

    The "field" is the file's content, and both sides are capped: a card
    that quotes a whole document is a card nobody reads to the end.  The
    cap is on the *card*, not on the write — the tool replaces the whole
    content whatever the card shows.
    """
    file = str(arguments.get("file") or "").strip()
    after = arguments.get("content")
    if not file or not isinstance(after, str):
        return None

    from albanna.tools.erpnext import _may_read_file
    from albanna.tools.files import _resolve

    source = _resolve(file)
    if source is None or not _may_read_file(source):
        return None

    try:
        current = source.get_content()
    except Exception:
        return None
    if isinstance(current, str):
        current = current.encode("utf-8", errors="replace")

    from albanna.core.attachments import attachment_text

    before_text = attachment_text(current or b"", str(getattr(source, "mime_type", "") or ""))
    return {"content": {"before": _clamped(before_text), "after": _clamped(after)}}


def _clamped(text: str, limit: int = FILE_PREVIEW_CHARS) -> str:
    """The head of a text, with a marker when there was more."""
    if len(text) <= limit:
        return text
    return text[:limit] + f" … ({len(text) - limit} more characters)"


def denial_message(decision: str) -> str:
    """What the model is told when the write did not run.

    The wording must let the model explain itself to the reader without
    pretending the change happened.
    """
    if decision == "reject":
        return "The reader did not approve this change, so it was not made."
    return "The reader did not respond in time, so the change was not made."


class NoPendingWrite(Exception):
    """No write is waiting for a decision under this request."""


class AlreadyAnswered(Exception):
    """This write has already been answered."""


def pending_key(request_id: str) -> str:
    """The cache key one pending write is stored under."""
    return f"{PENDING_PREFIX}{request_id}"


def arguments_digest(arguments: dict) -> str:
    """A fingerprint of a write's arguments.

    The decision is bound to the write by this: the reader approves
    *these* arguments and the worker runs *these* arguments.  A digest
    rather than the arguments themselves, because the record has to stay
    small and the arguments are whatever the model wrote.
    """
    try:
        payload = json.dumps(arguments or {}, sort_keys=True, default=str)
    except Exception:
        payload = repr(arguments)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_pending(
    request_id: str,
    user: str,
    name: str,
    arguments: dict,
    ttl: float = DEFAULT_TIMEOUT,
    row: str = "",
) -> None:
    """Remember that a write is waiting for the reader's decision.

    The record is what makes the decision mean something.  It is written
    by the worker, before the reader is asked, and it is the only place a
    decision may be recorded: an endpoint that named a request nobody is
    waiting on would be answering a question that was not asked.

    ``row`` is the audit row of the turn that proposed the write.  It is
    kept here so that the decision can be written into that row: the
    cache record expires with the wait it answers, and the row does
    not.  A reader's approval that is only in the cache is an approval
    that vanishes if the worker dies, and the panel then cannot say
    that the change they confirmed did not happen.
    """
    frappe.cache().set_value(
        pending_key(request_id),
        {
            "name": name,
            "digest": arguments_digest(arguments),
            "decision": "",
            "row": row or "",
            # Who may answer.  A *field*, and deliberately not the key's
            # namespace: the answer belongs to the reader the write was
            # asked of, and that binding must survive the framework's
            # user-cache clears — a namespace dies with them, a field
            # does not.
            "user": user or "",
        },
        expires_in_sec=int(ttl),
    )


def read_pending(request_id: str) -> dict:
    """The pending write, or an empty dict when there is not one."""
    try:
        value = frappe.cache().get_value(pending_key(request_id), expires=True)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def record_decision(request_id: str, decision: str, ttl: float = DEFAULT_TIMEOUT) -> dict:
    """Record the reader's decision on a pending write — once.

    The first decision is the decision.  A second one is refused rather
    than applied: the reader's answer to "shall this change happen?" is
    one answer, and a page that can send two is a page whose second click
    may land after the first has already been acted on.
    """
    pending = read_pending(request_id)
    if not pending:
        raise NoPendingWrite()
    if pending.get("decision"):
        raise AlreadyAnswered()

    # The answer is the reader's own: the record names who was asked, and
    # the session speaking now must be that account.  An endpoint that
    # took any account's word for any pending write would let one reader
    # approve another reader's change — and the worker runs it.
    if pending.get("user") and pending.get("user") != frappe.session.user:
        raise NoPendingWrite()

    pending["decision"] = decision
    frappe.cache().set_value(
        pending_key(request_id),
        pending,
        expires_in_sec=int(ttl),
    )
    return pending


def await_decision(
    request_id: str,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Wait for the reader's decision, and return it.

    Returns ``"approve"``, ``"reject"``, or ``"timeout"`` when the reader
    did not answer in time.
    """
    deadline = clock() + timeout

    while clock() < deadline:
        # ``expires=True`` is the whole trick: without it the cache keeps
        # the miss and every later poll reads that miss back.
        pending = read_pending(request_id)
        decision = str(pending.get("decision") or "")
        if decision:
            return decision
        sleep(interval)

    return TIMEOUT


def write_target(name: str, arguments: dict) -> dict:
    """The document a write is about, and the stamp it had when asked.

    ``modified`` is the document's own timestamp: the reader approves a
    change to *that* document, and a document that has moved since they
    were asked is not the one they were asked about.  An empty result
    means the write is not about an existing document — a creation has
    nothing to compare, and the lifecycle tools carry their own state
    check.
    """
    arguments = arguments or {}
    if name == "bulk_update_doc":
        # The approved set: the documents the card counted.  Carried through
        # to the write so it can tell which of them moved.
        from albanna.tools.erpnext import _bulk_filters

        doctype = str(arguments.get("doctype") or "").strip()
        filters = arguments.get("filters") or []
        try:
            limit = int(arguments.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 200))

        frappe_filters = _bulk_filters(filters)
        if isinstance(frappe_filters, str):
            return {}
        try:
            names = frappe.get_list(doctype, filters=frappe_filters, pluck="name", limit=limit)
        except Exception:
            return {}
        return {"doctype": doctype, "names": [str(n) for n in names]}

    if name == "edit_file":
        return _file_target(arguments)

    if name != "update_doc":
        return {}

    doctype = str(arguments.get("doctype") or "").strip()
    docname = str(arguments.get("name") or "").strip()
    document = _readable_document(doctype, docname)
    if document is None:
        return {}

    return {
        "doctype": doctype,
        "name": docname,
        "modified": str(document.modified or ""),
    }


def _file_target(arguments: dict) -> dict:
    """The file a change is about, and the stamp it had when asked.

    The same stamp a document change carries: the reader approves a
    change to the file as it was, and a file that has moved since is not
    the one they were asked about.
    """
    from albanna.tools.erpnext import _may_read_file
    from albanna.tools.files import _resolve

    file = str(arguments.get("file") or "").strip()
    source = _resolve(file) if file else None
    if source is None or not _may_read_file(source):
        return {}

    return {
        "doctype": "File",
        "name": source.name,
        "modified": str(getattr(source, "modified", "") or ""),
    }


def still_unchanged(target: dict) -> bool:
    """Whether the document a write was about is still the one it was about.

    The reader approved a change to a document as it was when they were
    asked.  If it has changed since, the change would land on top of
    somebody else's edit, and the approval would be an approval of
    something else.
    """
    if not target:
        return True

    # A bulk change carries an approved set rather than one document's
    # stamp.  The set is compared as a whole: a document that appeared or
    # disappeared since the card was shown means the write would touch a
    # row the reader never counted.
    if "names" in target:
        # The detailed comparison happens in bulk_update_doc itself, which
        # has the filters.  Here we only say "unchanged" so the write runs
        # and reports the difference in its own words.
        return True

    doctype = str(target.get("doctype") or "")
    name = str(target.get("name") or "")
    modified = str(target.get("modified") or "")
    if not doctype or not name or not modified:
        return True

    try:
        current = frappe.db.get_value(doctype, name, "modified")
    except Exception:
        logger.exception("Could not read the current state of %s %s", doctype, name)
        return False

    return str(current or "") == modified
