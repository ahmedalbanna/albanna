"""The five ERPNext tools, implemented in this app.

Why they live here
------------------
This app was originally built on top of the ``erpnext-mcp`` project, and it
called that project's tool functions in-process.  That cannot be published:
``erpnext-mcp`` on PyPI is a *different* project — an earlier release by
another author — so the version this app needs can never be installed by a
site that was not handed it by hand.  An app that cannot be installed is not
an app.

So the six tools are implemented here, against the framework's own APIs.
They are the small part of that project this app ever used, and they return
the same envelopes the chat service already speaks:
``{"status", "message", "data", "hints"}``.

The permissions are the framework's, and they are the *caller's*: a listing
goes through ``frappe.get_list``, which applies the caller's roles and User
Permissions; a write goes through ``doc.insert()`` or ``doc.save()``, which
apply the caller's create or write permission.

``get_doc`` is the one exception, and it is the reason the read permission is
checked by hand below: ``frappe.get_doc`` applies *no* permission check at
all.  A single document read through the ORM would otherwise return in full
what a listing of the same DocType refuses.
"""

from __future__ import annotations

import difflib
import itertools
import json
import logging
from typing import Any

import frappe

from albanna.permissions import may_read, readable_doctypes

logger = logging.getLogger(__name__)

#: The columns every document table has, whatever the DocType's meta says.
#: A child row's ``parent`` is how it is joined to its parent, and
#: ``frappe.get_all`` accepts it, so refusing it would refuse a query the
#: framework would have run.
STANDARD_DOC_FIELDS = frozenset(
    {
        "name",
        "owner",
        "creation",
        "modified",
        "modified_by",
        "parent",
        "parentfield",
        "parenttype",
        "idx",
        "docstatus",
        "amended_from",
    }
)

#: The fields the framework owns.
#:
#: They are not the assistant's to set, and a document whose ``owner`` or
#: ``docstatus`` had been rewritten by a chat would be a document nobody
#: could reason about afterwards.  ``name`` is here for a second reason:
#: ``Document.update()`` assigns ``name`` *first*, so a data object that
#: carried one would rename the document rather than change it.
PROTECTED_FIELDS = frozenset(
    {
        "name",
        "doctype",
        "owner",
        "creation",
        "modified",
        "modified_by",
        "docstatus",
        "amended_from",
        "parent",
        "parenttype",
        "parentfield",
        "idx",
    }
)

#: The largest a listing may return.
MAX_LIMIT = 500

#: The savepoints are numbered, because a savepoint name can only be used
#: once in a transaction: a second attempt with the same name is an error.
_savepoints = itertools.count(1)


# --------------------------------------------------------------------------
# The envelope
# --------------------------------------------------------------------------


def ok(message: str, data: Any = None, **state: Any) -> str:
    """A successful result, as a JSON string."""
    return json.dumps(
        {"status": "ok", "message": message, "data": data, "hints": [], **state},
        default=str,
    )


def error(
    message: str,
    actionable: str | None = None,
    hints: list[str] | None = None,
    **state: Any,
) -> str:
    """A failed result, as a JSON string.

    The message says what went wrong; the hints say what to do about it.
    A failure the caller cannot act on is a failure the caller will retry
    identically.
    """
    all_hints = list(hints or [])
    if actionable and actionable not in all_hints:
        all_hints.append(actionable)
    return json.dumps(
        {"status": "error", "message": message, "data": None, "hints": all_hints, **state},
        default=str,
    )


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _meta(doctype: str):
    """The DocType's meta, or an error envelope naming what was not found."""
    try:
        return frappe.get_meta(doctype)
    except Exception as exc:
        return error(f"DocType '{doctype}' not found: {exc}", doctype=doctype)


def _known_fields(meta) -> set[str]:
    """The fieldnames a query may name for this DocType."""
    known = {
        df.fieldname for df in (getattr(meta, "fields", []) or []) if getattr(df, "fieldname", None)
    }
    try:
        from frappe.model.meta import DEFAULT_FIELD_LABELS

        known.update(DEFAULT_FIELD_LABELS.keys())
    except Exception:
        pass
    known |= STANDARD_DOC_FIELDS
    return known


def _validate_fields(meta, doctype: str, fields: list[str]) -> str | None:
    """An error envelope when a field does not exist, else ``None``.

    The message names the closest matches, because a fieldname the model
    invented is worth correcting: without the correction the model has no
    way to know the right name and guesses again.
    """
    known = _known_fields(meta)
    if not known:
        return None

    problems = []
    for field in fields:
        if field in known:
            continue
        matches = difflib.get_close_matches(field, sorted(known), n=3, cutoff=0.45)
        hint = ", ".join(f"'{match}'" for match in matches) if matches else "none"
        problems.append(f"field '{field}' (closest: {hint})")

    if not problems:
        return None

    return error(
        f"Unknown field(s) for DocType '{doctype}': " + "; ".join(problems),
        doctype=doctype,
        actionable="Call get_doctype_meta for this DocType to see its fieldnames.",
    )


_VALID_FILTER_OPS = frozenset(
    {"=", "!=", ">", "<", ">=", "<=", "like", "not like", "in", "not in", "is", "between"}
)


def _validate_filters(filters: Any, doctype: str = "") -> str | None:
    """An error envelope when a filter is malformed, else ``None``."""
    if not filters:
        return None

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (json.JSONDecodeError, TypeError):
            return None

    if isinstance(filters, dict):
        for key, value in filters.items():
            if not isinstance(key, str) or not str(key).strip():
                return error(
                    f"Filter keys must be fieldnames (strings) for DocType '{doctype}'.",
                    doctype=doctype,
                    actionable="Filters are [fieldname, operator, value] triples.",
                )
            if not isinstance(value, str):
                return error(
                    f"A filter value must be a plain string, not a "
                    f"{type(value).__name__}. For 'in' or 'not in' write one "
                    f"condition per value rather than a list.",
                    doctype=doctype,
                    actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
                )
        return None

    if not isinstance(filters, list):
        return error(
            f"Filters must be a list of [fieldname, operator, value] triples "
            f"for DocType '{doctype}'.",
            doctype=doctype,
            actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
        )

    for condition in filters:
        if not isinstance(condition, (list, tuple)):
            return error(
                f"Each filter must be a three-element list "
                f"[fieldname, operator, value] for DocType '{doctype}'.",
                doctype=doctype,
                actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
            )
        if len(condition) != 3:
            return error(
                f"A filter must have exactly three elements "
                f"[fieldname, operator, value]; got {len(condition)}.",
                doctype=doctype,
                actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
            )
        fieldname, operator, value = condition
        if not isinstance(fieldname, str) or not str(fieldname).strip():
            return error(
                f"A filter's fieldname must be a string for DocType '{doctype}'.",
                doctype=doctype,
                actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
            )
        if not isinstance(operator, str) or operator not in _VALID_FILTER_OPS:
            return error(
                f"Unknown filter operator '{operator}' for DocType '{doctype}'.",
                doctype=doctype,
                actionable=(
                    "Allowed operators: =, !=, >, <, >=, <=, like, not like, "
                    "in, not in, is, between."
                ),
            )
        if not isinstance(value, str):
            return error(
                f"A filter value must be a plain string, not a "
                f"{type(value).__name__}. For 'in' or 'not in' write one "
                f"condition per value rather than a list.",
                doctype=doctype,
                actionable="Filters are [fieldname, operator, value] triples; the value is always a plain string.",
            )

    return None


def _validate_order_by(meta, doctype: str, order_by: Any) -> str | None:
    """An error envelope when a sort is not a known field, else ``None``."""
    if not order_by:
        return None

    known = _known_fields(meta)
    text = str(order_by).strip()
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        tokens = chunk.split()
        if len(tokens) == 1:
            field, direction = tokens[0], None
        elif len(tokens) == 2:
            field, direction = tokens
            if str(direction).lower() not in ("asc", "desc"):
                return error(
                    f"Unknown sort direction '{direction}' for DocType '{doctype}'.",
                    doctype=doctype,
                    actionable="Sort as 'fieldname asc' or 'fieldname desc'.",
                )
        else:
            return error(
                f"Sort must be 'fieldname' or 'fieldname asc|desc' for DocType '{doctype}'.",
                doctype=doctype,
                actionable="Sort as 'fieldname asc' or 'fieldname desc'.",
            )

        if field.lower() in ("asc", "desc"):
            return error(
                f"A sort needs a fieldname, not just a direction, for DocType '{doctype}'.",
                doctype=doctype,
                actionable="Sort as 'fieldname asc' or 'fieldname desc'.",
            )

        if field not in known:
            matches = difflib.get_close_matches(field, sorted(known), n=3, cutoff=0.45)
            hint = ", ".join(f"'{match}'" for match in matches) if matches else "none"
            return error(
                f"Unknown sort field '{field}' for DocType '{doctype}' (closest: {hint}).",
                doctype=doctype,
                actionable="Call get_doctype_meta for this DocType to see its fieldnames.",
            )

    return None


def _title_field(meta) -> str:
    """The DocType's title field — the name the reader sees.

    It is the field a list view puts first, and the one a reader
    recognises a document by.  A DocType whose title field is its own
    name has nothing to add, and a DocType with no title field at all
    has nothing to show.
    """
    try:
        title_field = meta.get_title_field()
    except Exception:
        return ""

    if not title_field or title_field == "name":
        return ""
    if not meta.has_field(title_field):
        return ""
    return title_field


def _savepoint(label: str) -> str:
    """Take a savepoint for this write, and name it.

    The savepoint is *taken* here, not merely named: a name that was
    never created cannot be rolled back to, and a rollback that fails
    quietly leaves the failed write's state in the transaction.

    The label is part of the name so that a failure to roll back says
    *which* write it was — a name nobody can read is a name nobody can
    act on.
    """
    name = f"albanna_{label}_{next(_savepoints)}"
    frappe.db.savepoint(name)
    return name


def _rollback_to(savepoint: str) -> None:
    """Undo this write, and only this write.

    A rollback is transaction-wide unless it is given a savepoint, and a
    transaction-wide rollback in the middle of a turn undoes *everything*
    the turn has done so far — including a document the assistant has
    already told the reader it created.  So every write takes a savepoint
    first, and a failure rolls back to it.

    Only the database is undone: a savepoint does not run Frappe's rollback
    watchers.  A write that stored a file on disk takes it back itself, with
    ``_discard_written``.
    """
    try:
        frappe.db.rollback(save_point=savepoint)
    except Exception:
        # The savepoint is gone when the transaction was committed or
        # rolled back underneath it — a report that commits, say.  There is
        # then nothing left to undo, so this is not a failure of the write.
        logger.warning("Could not roll back to the savepoint %s", savepoint, exc_info=True)


def _normalise_filters(filters: Any) -> list:
    """The filters as the framework wants them: a list of triples."""
    if not filters:
        return []
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(filters, dict):
        return [[key, "=", value] for key, value in filters.items()]
    return list(filters)


def _roles_for(doctype: str, ptype: str) -> list[str]:
    """The roles that hold *ptype* on *doctype*, as the framework records them.

    Read from the DocType's own permission rows rather than from a copy of
    them, so the answer is the organisation's own.  Only the rows that apply
    at the top level count: a permission recorded at a deeper level
    (``permlevel``) is not the same right, and offering it as the way in
    would be wrong.
    """
    meta = _meta(doctype)
    if isinstance(meta, str):
        return []

    roles: list[str] = []
    for row in getattr(meta, "permissions", None) or []:
        try:
            if not row.get(ptype):
                continue
            if int(row.get("permlevel") or 0) != 0:
                continue
        except (AttributeError, TypeError, ValueError):
            continue
        role = str(row.get("role") or "").strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _read_refusal(doctype: str, name: str) -> str:
    """The envelope for a document the caller may not read.

    The wording names the roles that *can* read it, because "you may not
    read this" is a wall and "a Sales Invoice is read by an Accounts User"
    is a fact about the organisation the reader can act on.  It is the same
    sentence :mod:`albanna.core.authority` uses for a refused write, for the
    same reason: the reader is told who could, and is not apologised to for
    a limit that is not the assistant's.
    """
    roles = _roles_for(doctype, "read")
    if roles:
        return error(
            f"{doctype} '{name}' could not be read: this account may not read it.",
            doctype=doctype,
            name=name,
            denied=True,
            actionable=(
                f"Reading a '{doctype}' is done by these roles: {', '.join(roles)}. "
                f"Say that as a fact about the account, and do not apologise for it."
            ),
        )

    return error(
        f"{doctype} '{name}' could not be read: this account may not read it.",
        doctype=doctype,
        name=name,
        denied=True,
        actionable=(
            f"No role on this site holds read on '{doctype}'. State that as a "
            f"fact about the site, and do not apologise for it."
        ),
    )


def _load_for_action(doctype: str, name: str):
    """The document a lifecycle action is about, or an error envelope.

    A write permission is not a read permission, and the two are held by
    different roles on most sites.  So a user who may *submit* a document
    but may not *read* it could have it submitted by this chat, and could
    learn from the answer that it exists and what state it is in.

    The Desk would not show that document to them.  So the chat does not
    act on it either: the document is loaded, the read is checked, and the
    refusal is the same one a read would have produced.
    """
    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

    if not may_read(document):
        return _read_refusal(doctype, name)

    return document


# --------------------------------------------------------------------------
# The tools
# --------------------------------------------------------------------------


def _validate_list_docs_inputs(meta, doctype, filters, field_list, order_by):
    """All of list_docs' argument checks, in one place."""
    if field_list:
        invalid = _validate_fields(meta, doctype, field_list)
        if invalid:
            return invalid
    if filters is not None:
        invalid = _validate_filters(filters, doctype)
        if invalid:
            return invalid
    if order_by:
        invalid = _validate_order_by(meta, doctype, order_by)
        if invalid:
            return invalid
    return None


#: The filter fieldname that means "assigned to the reader".
#:
#: It is not a column and not in any DocType's meta, because an
#: assignment is not a field: Frappe keeps it in ``tabToDo``, keyed by
#: (reference_type, reference_name, allocated_to).  A filter the model can
#: write has to be a fieldname, so this one is a fieldname the tool
#: resolves rather than passes on.
#:
#: It exists because "my open tickets" was a suggestion the assistant
#: could not answer.  The reader was named in the system prompt already,
#: but nothing let the model turn "mine" into a condition — so it listed
#: every open ticket and called them the reader's.  A confident wrong
#: answer is the worst kind, and this is the fix for it.
ASSIGNED_TO_FILTER = "assigned_to"


def _resolve_assigned_to(doctype: str, filters: Any) -> tuple[Any, str | None]:
    """Replace an ``assigned_to`` filter with the reader's own documents.

    Returns the filters with the condition rewritten as a ``name in
    (...)`` over the documents ``tabToDo`` says are allocated to the
    session's user, and an error envelope when the rewrite cannot be
    made.

    The value is ignored.  Whatever the model wrote there, the question
    is "which documents are mine", and the answer is the session's — a
    filter that named somebody else would be a filter that answered a
    question about a third party, which is not what the reader asked.
    """
    if not isinstance(filters, list):
        return filters, None

    user = str(frappe.session.user or "")
    if not user:
        return filters, error(
            "Cannot tell which documents are yours: no reader is signed in.",
            doctype=doctype,
        )

    names = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": doctype,
            "allocated_to": user,
            "status": ["not in", ("Cancelled", "Closed")],
        },
        pluck="reference_name",
        limit=MAX_LIMIT,
    )

    rewritten: list[Any] = []
    replaced = False
    for condition in filters:
        if (
            isinstance(condition, (list, tuple))
            and len(condition) == 3
            and str(condition[0]).strip() == ASSIGNED_TO_FILTER
        ):
            # An empty assignment list is not an error: it is the honest
            # answer to "what is on my desk?" when nothing is.  The
            # condition becomes one that matches nothing, rather than
            # being dropped — dropping it would list everything, which is
            # the bug this exists to fix.
            rewritten.append(["name", "in", [str(name) for name in names] or ["__none__"]])
            replaced = True
            continue
        rewritten.append(condition)

    return (rewritten if replaced else filters), None


def list_docs(
    doctype: str,
    filters: Any = None,
    fields: Any = None,
    limit: int = 20,
    offset: int = 0,
    order_by: str = "",
) -> str:
    """Find documents of one DocType.

    Args:
        doctype: The DocType to search, e.g. "Sales Order".
        filters: Conditions as ``[fieldname, operator, value]`` triples.
        fields: The fieldnames to return.  Omit for the DocType's defaults.
        limit: How many documents to return.
        offset: How many to skip, for paging.
        order_by: The sort order, e.g. "modified desc".
    """
    if not doctype:
        return error("A doctype is required.")

    meta = _meta(doctype)
    if isinstance(meta, str):
        return meta

    field_list = [str(field).strip() for field in (fields or []) if str(field).strip()]

    invalid = _validate_list_docs_inputs(meta, doctype, filters, field_list, order_by)
    if invalid:
        return invalid

    # "Assigned to me" is resolved here, before the query is built: the
    # assignment lives in ``tabToDo`` and not on the document, so there is
    # no column for the condition to name.
    filters, refusal = _resolve_assigned_to(doctype, filters)
    if refusal:
        return refusal

    # Every listing carries the document's name and the DocType's title
    # field.  The name is the document's identity — the Desk shows it in
    # every list, and the app's citations link by it — and the title is
    # the name the reader sees: the customer on an invoice.  A model
    # that sees only "ف-2026-0011" cannot say "the invoice for أحمد محمد
    # عبدربه", and a reader told a series number has to look it up.
    for field in ("name", _title_field(meta)):
        if field and field not in field_list:
            field_list.append(field)

    try:
        limit = max(1, min(int(limit or 20), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0

    try:
        documents = frappe.get_list(
            doctype,
            filters=_normalise_filters(filters) or None,
            fields=field_list or None,
            limit_start=offset,
            limit_page_length=limit,
            order_by=order_by or None,
        )
    except Exception as exc:
        return error(f"Failed to list {doctype}: {exc}", doctype=doctype)

    # A listing of Communications is silently filtered by Frappe's
    # permission engine: a user with no User Email account sees only
    # non-email Communications, and the result is a successful list with
    # no error.  The model cannot tell "there are no email threads" from
    # "the thread exists and I cannot see it", so the limitation is
    # stated in the tool's own answer rather than left for the model to
    # guess.
    #
    # It goes in the hints, because that is the channel the tool's
    # answer carries to the model: a key the envelope does not read is
    # a statement nobody hears.
    hints: list[str] = []
    if doctype == "Communication":
        limitation = _communication_limitation(frappe.session.user)
        if limitation:
            hints.append(
                f"{limitation} Say in the answer that the email thread could "
                "not be read and why, rather than treating the silence as the "
                "whole truth."
            )

    return ok(
        f"Found {len(documents)} {doctype}",
        data=documents,
        doctype=doctype,
        hints=hints,
    )


def _email_threads_are_hidden_from(user: str) -> bool:
    """Whether this reader is missing email Communications the site holds.

    Both halves of the comparison are the framework's: the count is the
    site's own truth, and the listing is the reader's own view of it.
    The app only asks whether the second is smaller than the first.

    That comparison is what keeps the note honest.  A note about threads
    that do not exist is a false statement about the site, and it is the
    kind of false statement a reader believes — a live run showed the
    assistant telling a reader, on a site with no customer mail at all,
    that the email thread could not be read.

    The reader's half is counted by listing the threads and counting the
    rows, and not by asking the framework for a ``count(name)``
    aggregate.  The two versions of Frappe this app is measured against
    parse a field expression differently: upstream v16 routes a listing
    through the query builder, which refuses an aggregate expression
    outright — *"Could not parse field: count(name) as count"* — while
    the version the site runs on builds the SQL itself and accepts it.
    A note that disappears when the framework changes its parser is a
    note nobody hears, and the CI, which runs the upstream release, heard
    nothing at all.

    The listing asks for at most as many rows as the site holds, so a
    reader who may read every thread is counted in full and a reader
    who may read fewer is counted short.  It costs the site one query
    and the reader one page of names.
    """
    total = frappe.db.count("Communication", {"communication_medium": "Email"})
    if not total:
        return False
    visible = frappe.get_list(
        "Communication",
        filters={"communication_medium": "Email"},
        fields=["name"],
        limit_page_length=total,
        user=user,
    )
    return len(visible) < total


def _communication_limitation(user: str) -> str:
    """Why this account cannot read the email threads, if it cannot.

    There are three reasons, and the third is the one that hides.

    The first is the link: Frappe hides email Communications from any
    reader whose account has no ``User Email`` row, so an agent who is
    not linked to the mailbox sees none of the customer's mail.

    The second is the owner constraint: Frappe limits a reader to the
    Communications they own, unless they hold a role that may read any
    ("Inbox User" is that role).  An incoming customer's mail is owned
    by the account that fetched it, not by the agent who should read
    it.  So an agent who *is* linked but does not hold that role sees no
    customer mail either — and the first reason does not apply, so a
    note that only knew about the link would stay silent exactly when
    it should have spoken.

    The third is the scope of the link: a reader linked to one mailbox
    may read that mailbox's threads and not the others'.  It looks like
    a correctly set-up account, and it is hiding the rest of the mail.

    And a reader the framework exempts from the rule (a System Manager,
    a Super Email User) reads every thread, so it is told nothing: a
    false statement about a privileged reader is the worst kind of note,
    because it is believed.

    So the framework's own rule decides all of it rather than a copy of
    it: if the framework changes what it restricts, the app follows.
    And when the app cannot tell, it says nothing: a wrong limitation
    is worse than no limitation.

    When the app cannot tell *because something broke*, it says nothing
    as well — but it says so in the log, because a note that quietly
    stops being written looks exactly like a note that was never
    needed.  That is how the CI found the last one: the note was gone,
    the failure was silent, and nothing said why.
    """
    try:
        if not _email_threads_are_hidden_from(user):
            return ""
    except Exception:
        logger.exception("Could not compare the email threads %s may read", user)
        return ""

    try:
        linked = bool(
            frappe.get_all(
                "User Email",
                filters={"parent": user},
                limit=1,
            )
        )
    except Exception:
        logger.exception("Could not work out whether %s is linked to a mailbox", user)
        return ""

    if not linked:
        return (
            "This account has no email account configured, so the email "
            "Communications on this site are not in this list."
        )

    try:
        from frappe.model.db_query import requires_owner_constraint
        from frappe.permissions import get_role_permissions

        permissions = get_role_permissions(frappe.get_meta("Communication"), user=user)
        if requires_owner_constraint(permissions):
            return (
                "This account is linked to an email account, but its "
                "permissions limit it to the Communications it owns, so the "
                "email threads that arrived from a customer are not in this "
                "list: only the threads it owns are shown."
            )
    except Exception:
        logger.exception("Could not work out what %s may read of the mail", user)
        return ""

    return (
        "This account is linked to an email account, and it may read only "
        "the email Communications in the mailbox it is linked to, so the "
        "email Communications in the other mailboxes are not in this list."
    )


def _hidden_fields(document) -> set[str]:
    """The fields of this document the caller may not read.

    A field at a higher permission level is hidden in the form, and the
    person asking does not know whether it is set.  The model must not
    know either — not even by seeing a field that is not there.
    """
    try:
        access = document.get_permlevel_access("read")
    except Exception:
        logger.exception("Could not work out the readable fields of %s", document.doctype)
        return set()

    return {
        df.fieldname for df in document.meta.fields if df.permlevel and df.permlevel not in access
    }


def get_doc(doctype: str, name: str, fields: Any = None) -> str:
    """Read one document.

    Args:
        doctype: The DocType of the document.
        name: The document's name.
        fields: The fieldnames to return.  Omit for the whole document.
    """
    if not doctype or not name:
        return error("A doctype and a name are required.")

    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

    # The read is loaded first and checked second, and the order is
    # deliberate: loading is what gives the check something to check.  A
    # check made without the document would answer a question about the
    # *kind* of document, and the one that matters here is about *this* one.
    if not may_read(document):
        return _read_refusal(doctype, name)

    # The fields a person may not read are removed before the document is
    # handed over — the same thing Frappe's own API does, and the reason
    # it does it: a field at a higher permission level is hidden in the
    # form, and a value the reader cannot see must not reach the model
    # either.  It is done before the fields are chosen, so that naming a
    # hidden field explicitly does not bring it back.
    hidden = _hidden_fields(document)
    document.apply_fieldlevel_read_permissions()

    field_list = [str(field).strip() for field in (fields or []) if str(field).strip()]
    if field_list:
        invalid = _validate_fields(frappe.get_meta(doctype), doctype, field_list)
        if invalid:
            return invalid
        data = {field: document.get(field) for field in field_list if field not in hidden}
        data["name"] = document.name
        hints: list[str] = []
        if any(field in hidden for field in field_list):
            hints.append(
                "one of the fields you asked for is not readable by this "
                "account and was not returned."
            )
        return ok(
            f"Read {doctype} '{name}'",
            data=data,
            doctype=doctype,
            name=name,
            hints=hints,
        )

    data = document.as_dict()
    # Frappe's own API leaves a hidden field in the payload with its
    # default value, which is a false statement about the document: the
    # model would report that a flag is off when it may well be on.  A
    # field the reader may not see is not in the answer at all.
    for field in hidden:
        data.pop(field, None)
    return ok(f"Read {doctype} '{name}'", data=data, doctype=doctype, name=name)


def get_doctype_meta(doctype: str, fields: Any = None) -> str:
    """The field definitions of a DocType.

    Args:
        doctype: The DocType to describe.
        fields: The fieldnames to describe.  Omit for every field.
    """
    if not doctype:
        return error("A doctype is required.")

    try:
        meta = frappe.get_meta(doctype)
    except Exception as exc:
        return error(f"DocType '{doctype}' not found: {exc}", doctype=doctype)

    # The field definitions are the DocType's own, and a DocType the
    # caller may not read is not theirs to describe: its fieldnames,
    # labels and Select options are the same knowledge the Desk hides.
    # Fail closed — a permission engine that cannot answer has not said
    # yes.
    try:
        readable = readable_doctypes(str(frappe.session.user or ""))
    except Exception:
        logger.exception("Could not read the readable DocTypes for %s", frappe.session.user)
        readable = []

    if doctype not in readable:
        roles = _roles_for(doctype, "read")
        if roles:
            actionable = (
                f"Reading a '{doctype}' is done by these roles: {', '.join(roles)}. "
                f"Say that as a fact about the account, and do not apologise for it."
            )
        else:
            actionable = (
                f"No role on this site holds read on '{doctype}'. State that as a "
                f"fact about the site, and do not apologise for it."
            )
        return error(
            f"DocType '{doctype}' could not be read: this account may not read it.",
            doctype=doctype,
            denied=True,
            actionable=actionable,
        )

    described = [
        {
            "fieldname": df.fieldname,
            "fieldtype": df.fieldtype,
            "label": df.label,
            "reqd": df.reqd,
            "options": df.options,
            "default": df.default,
        }
        for df in (meta.fields or [])
        if getattr(df, "fieldname", None)
    ]

    payload: dict[str, Any] = {"doctype": doctype, "fields": described}

    wanted = [str(field).strip() for field in (fields or []) if str(field).strip()]
    if wanted:
        by_name = {field["fieldname"]: field for field in described}
        unknown = [name for name in wanted if name not in by_name]
        payload["fields"] = [by_name[name] for name in wanted if name in by_name]
        payload["projected_fields"] = wanted
        if unknown:
            payload["unknown_fields"] = unknown
            payload["hints"] = [f"'{name}' is not a field of {doctype}" for name in unknown]

    return json.dumps(payload, default=str)


def run_report(
    report: str,
    filters: Any = None,
    limit: int = 1000,
    offset: int = 0,
) -> str:
    """Run an ERPNext report and return its rows.

    Args:
        report: The report's name, e.g. "Accounts Receivable".
        filters: The report's filters, as an object.
        limit: How many rows to return.
        offset: How many rows to skip, for paging.
    """
    if not report:
        return error("A report name is required.")

    resolved = _resolve_report(report, filters)
    if isinstance(resolved, str):
        return resolved
    report_doc, report_filters = resolved

    # The permission check comes first, and the order is the point: a
    # reader who may not run this report is not told which filters it
    # takes.  The mandatory filters are the report's own shape, and the
    # shape of a thing the reader cannot reach is the same knowledge the
    # DocType catalogue withholds — a model that knew a restricted report
    # needed a `company` could tell the reader something about it they
    # could not find out for themselves.
    refusal = _report_refusal(report_doc, report)
    if refusal:
        return refusal

    missing = _missing_mandatory_filters(report_doc, report_filters)
    if missing:
        return error(
            f"Report '{report}' requires filter(s): {', '.join(missing)}",
            report=report,
            missing_filters=missing,
            actionable="Call run_report again with these filters added.",
        )

    bounds = _report_bounds(limit, offset)
    if isinstance(bounds, str):
        return bounds
    limit, offset = bounds

    # A report is a read, and some reports write as they go.  The savepoint
    # is what lets those writes be discarded without a transaction-wide
    # rollback undoing the turn's own writes.
    savepoint = _savepoint("run_report")
    try:
        raw = _execute_report(report_doc, report_filters)
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Report '{report}' failed: {exc}", report=report)

    _rollback_to(savepoint)

    columns, rows = _report_shape(raw)
    formatted = _as_dicts(columns, rows)
    payload = _report_payload(report, report_doc, columns, formatted, limit, offset)
    return ok(
        f"Report '{report}' returned {payload['total_rows']} row(s)",
        data={"columns": payload["columns"], "rows": payload["rows"]},
        **{
            key: value for key, value in payload.items() if key not in ("status", "columns", "rows")
        },
    )


def _resolve_report(report: str, filters: Any) -> Any:
    """The report document and its filters, or an error envelope."""
    try:
        report_doc = frappe.get_doc("Report", report)
    except frappe.DoesNotExistError:
        return error(f"Report '{report}' not found", report=report)
    except Exception as exc:
        return error(f"Failed to read report '{report}': {exc}", report=report)

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (json.JSONDecodeError, TypeError):
            filters = {}
    if not isinstance(filters, dict):
        filters = {}

    return report_doc, filters


def _missing_mandatory_filters(report_doc, filters: Any) -> list[str]:
    """The mandatory filters the caller did not supply.

    A mandatory filter that carries a default is not missing: the report
    fills it itself.  So the check is mandatory, no default, and not in
    the filters the model sent.  Getting that wrong refuses reports that
    would have run, which is worse than the current silence.
    """
    filters = filters if isinstance(filters, dict) else {}
    missing: list[str] = []
    for row in getattr(report_doc, "filters", None) or []:
        try:
            if hasattr(row, "get"):
                fieldname = row.get("fieldname")
                mandatory = row.get("mandatory")
                default = row.get("default")
            else:
                fieldname = getattr(row, "fieldname", None)
                mandatory = getattr(row, "mandatory", None)
                default = getattr(row, "default", None)
        except Exception:
            continue
        if not fieldname:
            continue
        if not mandatory:
            continue
        if default is not None and str(default).strip() != "":
            continue
        if str(fieldname) in filters:
            continue
        missing.append(str(fieldname))
    return missing


def _report_refusal(report_doc, report: str) -> str | None:
    """An error envelope when the caller may not run this report.

    The same access the desk applies before it runs one: the report's own
    role restriction, the report permission on the DocType it is about, and
    the disabled flag.  A role check that cannot answer has not said yes.
    """
    try:
        permitted = bool(report_doc.is_permitted())
    except Exception:
        logger.exception("Could not check the roles that may run report %s", report)
        permitted = False
    if not permitted:
        return error(
            f"You do not have access to report '{report}'",
            report=report,
            actionable="This report is restricted to specific roles.",
        )

    ref_doctype = report_doc.ref_doctype
    if ref_doctype and not frappe.has_permission(ref_doctype, ptype="report"):
        return error(
            f"You do not have permission to run reports on '{ref_doctype}'",
            report=report,
            ref_doctype=ref_doctype,
        )

    if report_doc.get("disabled"):
        return error(
            f"Report '{report}' is disabled",
            report=report,
            actionable="An administrator has turned this report off.",
        )
    return None


def _report_bounds(limit: Any, offset: Any) -> Any:
    """The page bounds, or an error envelope."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return error("limit must be an integer")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        return error("offset must be an integer")
    if limit < 1 or limit > 5000:
        return error("limit must be between 1 and 5000")
    if offset < 0:
        return error("offset must be >= 0")
    return limit, offset


def _as_dicts(columns: list, rows: list) -> list:
    """The rows as dictionaries, where the report's columns line up."""
    formatted = []
    for row in rows:
        if columns and len(columns) == len(row):
            formatted.append(dict(zip(columns, row, strict=False)))
        else:
            formatted.append(row)
    return formatted


def _report_payload(
    report: str,
    report_doc,
    columns: list,
    formatted: list,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """The report's result, as a page."""
    total = len(formatted)
    page = formatted[offset : offset + limit]
    truncated = (offset + limit) < total
    return {
        "report": report,
        "report_type": report_doc.report_type,
        "columns": list(columns),
        "rows": page,
        "row_count": len(page),
        "total_rows": total,
        "truncated": truncated,
        "next_offset": offset + limit if truncated else None,
        "limit": limit,
        "offset": offset,
    }


def _execute_report(report_doc, filters: Any) -> Any:
    """Run a report, whatever kind it is.

    A Script Report and a Query Report each have their own runner; a
    Report Builder report and a Custom Report both go through
    ``get_data``.
    """
    if report_doc.report_type == "Script Report":
        return report_doc.execute_script_report(filters)
    if report_doc.report_type == "Query Report":
        return report_doc.execute_query_report(filters)
    return report_doc.get_data(filters=filters)


def _report_shape(raw: Any) -> tuple[list, list]:
    """The columns and the rows of a report's result, whatever shape it is.

    Script Reports return a 6-tuple (columns, rows, message, chart, summary,
    …); Query Reports return a dict; a plain report returns a list.
    """
    columns: Any = []
    rows: Any = []

    if isinstance(raw, tuple) and len(raw) >= 2 and isinstance(raw[1], list):
        columns, rows = raw[0], raw[1]
    elif isinstance(raw, tuple) and len(raw) == 2:
        columns, rows = raw
    elif isinstance(raw, dict):
        columns = raw.get("columns", raw.get("colnames", []))
        rows = list(raw.get("result", raw.get("values", [])) or [])
    elif isinstance(raw, list):
        columns, rows = [], raw

    if columns and isinstance(columns[0], dict):
        columns = [column.get("label") or column.get("fieldname") for column in columns]

    return list(columns or []), list(rows or [])


def create_doc(doctype: str, data: Any, submit: bool = False) -> str:
    """Create a document.

    Args:
        doctype: The DocType to create, e.g. "Sales Order".
        data: The document's field values, as an object.
        submit: Submit it immediately, for a submittable DocType.
    """
    refusal = _create_refusal_for(doctype, data)
    if refusal:
        return refusal

    savepoint = _savepoint("create_doc")
    written: list = []
    try:
        document = frappe.get_doc({"doctype": doctype, **data})
        document.insert()
        # The attachments are adopted now that the document has a name to
        # be attached to.
        if _adopt_attachments(document, dict(data), written):
            document.save()
    except Exception as exc:
        refusal = _create_refusal(exc, doctype, savepoint)
        _discard_written(written)
        return refusal

    submitted = False
    if submit:
        submitted, message = _submit_created(document, doctype)
        if not submitted:
            return error(message, doctype=doctype)

    message = f"Created {doctype} '{document.name}'"
    if submitted:
        message += " and submitted it"
    return ok(
        message,
        data={"doctype": doctype, "name": document.name, "submitted": submitted},
        doctype=doctype,
        name=document.name,
    )


def _submit_created(document, doctype: str) -> tuple[bool, str]:
    """Submit a document that has just been created, or say why it could not be.

    The savepoint is of its own, taken after the insert: rolling back to
    the insert's savepoint would undo the creation as well, and the
    message says the document was created.
    """
    savepoint = _savepoint("create_submit")
    try:
        document.submit()
        return True, ""
    except Exception as exc:
        _rollback_to(savepoint)
        return False, f"Created {doctype} '{document.name}' but could not submit it: {exc}"


def _child_table_refusal(meta, doctype: str, data: dict[str, Any]) -> str | None:
    """The refusal for a fieldname invented inside a child table.

    A table field is replaced whole, so the rows the model sends are the
    rows the document will have — and a fieldname that is not in the
    *child* DocType's meta is dropped by the framework without a word.
    The model believes it set something, the reader believes it, and
    nobody discovers otherwise until somebody opens the form.

    The top level has had this check since the FR-4 pass.  This is the
    same check one level down, and it is the level a model is *more*
    likely to get wrong: the child DocType's fieldnames are the ones it
    has never been shown, because the schema it was given names the
    parent's fields and says "items" without saying what an item holds.

    Only the rows' keys are checked, and only against the child
    DocType's own meta.  The correction names the closest matches from
    that meta, which is safe to show: the caller is creating the parent
    document, so they can already see the parent's form, and the form
    shows the child table's columns.
    """
    for df in getattr(meta, "fields", []) or []:
        if getattr(df, "fieldtype", "") != "Table":
            continue
        fieldname = getattr(df, "fieldname", "")
        rows = data.get(fieldname)
        if not isinstance(rows, list) or not rows:
            continue

        child = getattr(df, "options", "") or ""
        if not child:
            continue

        child_meta = _meta(child)
        if isinstance(child_meta, str):
            # A child DocType that cannot be read is not a child DocType
            # whose fields may be named.  Refuse rather than guess: the
            # rows would be written against a meta nobody has seen.
            return child_meta

        keys: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                keys.extend(str(key) for key in row if key)

        invalid = _validate_fields(child_meta, child, keys)
        if invalid:
            # The sentence names the child DocType, because "field 'quntity'
            # (closest: 'qty')" on its own does not say *where* the model
            # put it — and the same wrong fieldname is plausible at the
            # top level too.
            return error(
                f"Unknown field(s) in the rows of '{fieldname}' for DocType '{child}': "
                + invalid.split(": ", 1)[-1],
                doctype=doctype,
                actionable=(
                    f"Call get_doctype_meta for '{child}' to see the fieldnames a row may carry."
                ),
            )

    return None


def _create_refusal_for(doctype: str, data: Any) -> str | None:
    """The refusal for a creation that may not be made, or ``None``.

    Four rules, and all of them are about the *shape* of the creation
    rather than about the document: the DocType has to be named, the data
    has to be an object of field values, the data must not name a
    DocType of its own, and the fields the framework owns are not the
    assistant's to set.
    """
    if not doctype:
        return error("A doctype is required.")
    if not isinstance(data, dict) or not data:
        return error("The document's data is required, as an object of field values.")
    if "doctype" in data:
        # The DocType is the first argument, and the authority layer
        # authorised *that* one.  A DocType inside the data would be a
        # second, unchecked answer to the same question.
        return error(
            "The document's data must not name a doctype: the doctype is the first argument.",
            doctype=doctype,
        )

    protected = _protected_refusal(doctype, data)
    if protected:
        return protected

    # The fieldnames are checked before the attachment check, and before
    # the document is loaded: a field that does not exist is refused with
    # the close-match correction, the same sentence the update path gives.
    # A protected field is refused before its existence is questioned,
    # which is the order ``_field_refusal`` uses.
    meta = _meta(doctype)
    if isinstance(meta, str):
        return meta

    invalid = _validate_fields(meta, doctype, list(data))
    if invalid:
        return invalid

    # And the rows of any child table, against the child DocType's own
    # meta.  A table field is replaced whole, so an invented fieldname in
    # a row is dropped without a word — the one place a model can be
    # silently ignored about something it just wrote.
    invalid = _child_table_refusal(meta, doctype, data)
    if invalid:
        return invalid

    # A file the caller may not read is not attached to the new document:
    # the document would hand it to its own readers.
    return _attachment_refusal(meta, doctype, data)


def _create_refusal(exc: Exception, doctype: str, savepoint: str) -> str:
    """The envelope for a create that failed.

    The order of the tests is the order of the exception classes:
    ``DuplicateEntryError`` is a ``ValidationError``, and a duplicate is
    worth more to the reader than "validation failed".
    """
    _rollback_to(savepoint)

    if isinstance(exc, frappe.PermissionError):
        return error(
            f"Failed to create {doctype}: {exc}",
            doctype=doctype,
            actionable="This account may not create this kind of document.",
        )
    if isinstance(exc, frappe.DuplicateEntryError):
        return error(f"Duplicate entry: {exc}", doctype=doctype)
    if isinstance(exc, frappe.ValidationError):
        return error(f"Validation failed: {exc}", doctype=doctype)
    return error(f"Failed to create {doctype}: {exc}", doctype=doctype)


def update_doc(doctype: str, name: str, data: Any, submit: bool = False) -> str:
    """Change the fields of a document that already exists.

    Args:
        doctype: The DocType of the document, e.g. "Customer".
        name: The document's name, e.g. "CUST-0001".
        data: The field values to change, as an object.
        submit: Submit it afterwards, for a submittable DocType in draft.
    """
    if not doctype:
        return error("A doctype is required.")
    if not name:
        return error("A document name is required.")
    if not isinstance(data, dict) or not data:
        return error("The changes are required, as an object of field values.")

    document = _load_for_update(doctype, name, data)
    if isinstance(document, str):
        return document

    if document.docstatus:
        # A submitted document is read-only in the form, and the framework
        # would let a server-side save rewrite it: the guard is in the
        # client, not in `db_update`.  So the guard is here, where the chat
        # can state it, and the answer names the way a person does it.
        return error(
            f"{doctype} '{name}' is submitted and cannot be changed.",
            doctype=doctype,
            name=name,
            actionable=(
                "A submitted document is changed by cancelling it and amending "
                "it, which this tool does not do. Say so rather than trying "
                "again."
            ),
        )

    changes = _actual_changes(document, data)
    if not changes:
        return ok(
            f"{doctype} '{name}' already has those values; nothing was changed.",
            data={"doctype": doctype, "name": name, "changed": {}},
            doctype=doctype,
            name=name,
        )

    # The values the document held before this change, so that the change
    # can be taken back.  Only the fields that actually changed are kept.
    before = {field: document.get(field) for field in changes}

    lines_before = _table_lengths(document, changes)

    refusal = _apply_update(document, changes, doctype, name)
    if refusal is not None:
        return refusal

    submitted = False
    if submit:
        refusal = _submit_update(document, doctype, name)
        if refusal is not None:
            return refusal
        submitted = True

    return ok(
        _update_message(doctype, name, changes, document, lines_before, submitted),
        data={
            "doctype": doctype,
            "name": name,
            "changed": changes,
            "before": before,
            "submitted": submitted,
        },
        doctype=doctype,
        name=name,
    )


def _protected_refusal(doctype: str, data: dict, name: str = "") -> str | None:
    """The refusal for a change that names a field the framework owns.

    ``docstatus`` is the one that matters: a document created with
    ``docstatus: 1`` arrives submitted, without the submit permission and
    without the hooks that a submission runs.  The reader approved
    "create this"; they did not approve "create this, already permanent".
    """
    protected = sorted(set(data) & PROTECTED_FIELDS)
    if not protected:
        return None
    return error(
        f"These field(s) belong to the framework and cannot be set: {', '.join(protected)}.",
        doctype=doctype,
        name=name,
        actionable="Give only the fields the user asked to change.",
    )


def _field_refusal(meta, doctype: str, data: dict, name: str = "") -> str | None:
    """The refusal for a change that names a field it may not set.

    Three rules, in the order a model most often breaks them: the field
    has to exist, it must not be one the framework owns, and the form
    must not have made it read-only.  The refusals that do not need the
    document come first — they are cheaper, and they are the ones a model
    gets wrong most often.

    **One place**, because a bulk change that skipped these checks would
    be the one path where ``owner`` and ``docstatus`` could be written:
    it is the one write that does not go through the single change's
    loader.
    """
    invalid = _validate_fields(meta, doctype, list(data))
    if invalid:
        return invalid

    protected = _protected_refusal(doctype, data, name)
    if protected:
        return protected

    readonly = _read_only_fields(meta, data)
    if readonly:
        return error(
            f"These field(s) are read-only and cannot be changed: {', '.join(readonly)}.",
            doctype=doctype,
            name=name,
            actionable="Give only the fields the user asked to change.",
        )

    return None


def _load_for_update(doctype: str, name: str, data: dict[str, Any]):
    """The document to change, or an error envelope saying why there is not one.

    The document is loaded and the read is checked *before* the field
    checks.  The field checks are cheaper, and they are the ones a model
    most often gets wrong — but running them first would tell a reader who
    may not read a row which fieldnames its DocType has, because an
    invented fieldname comes back with "closest: 'customer'".  The
    document is loaded either way, so the cost of moving the read check
    first is nil, and the leak is closed.  This is a real trade-off — the
    cheap checks now run after an expensive one — and it is made
    deliberately.
    """
    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

    # A change is a write, and a write is not a read: the roles that hold
    # one do not always hold the other.  The read check comes first, so
    # that a reader who may not see the row is not told its fieldnames.
    if not may_read(document):
        return _read_refusal(doctype, name)

    meta = _meta(doctype)
    if isinstance(meta, str):
        return meta

    refusal = _field_refusal(meta, doctype, data, name)
    if refusal:
        return refusal

    # A file the caller may not read is not attached: the document would
    # hand it to its own readers.
    refusal = _attachment_refusal(meta, doctype, data)
    if refusal:
        return refusal

    return document


#: The field types that hold a file, and so need the file to belong to
#: the document rather than to whoever happened to upload it.
ATTACH_FIELDTYPES = ("Attach", "Attach Image")


def _file_for_url(file_url: str):
    """The File document behind a ``/files/`` or ``/private/files/`` URL."""
    if not isinstance(file_url, str) or not file_url.startswith(("/files/", "/private/files/")):
        return None
    name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if not name:
        return None
    try:
        return frappe.get_doc("File", name)
    except Exception:
        return None


def _may_read_file(source) -> bool:
    """Whether the session user may read this file.

    A private file is its owner's, and the public ones are everybody's —
    the file's own permission rules decide, and a rule that cannot answer
    has not said yes.
    """
    try:
        return bool(frappe.has_permission("File", "read", doc=source))
    except Exception:
        logger.exception("Could not check read permission for File %s", source.name)
        return False


def _copy_is_public(source) -> bool:
    """Whether the document's copy of *source* may be a public file.

    A public file is served to anybody on the internet, without a login.
    Reading a private file is not the right to publish it: Frappe lets
    everybody who may read the document a file is attached to read the
    file, and none of them may make it public on its owner's behalf.  So
    the copy is public only when the source already is, or when the caller
    is the one who uploaded it -- the chat's own attachment, say.
    """
    if not frappe.utils.cint(getattr(source, "is_private", 1)):
        return True
    user = frappe.session.user
    return bool(user) and user != "Guest" and getattr(source, "owner", None) == user


def _discard_written(written: list) -> None:
    """Take back the files a failed write stored on disk.

    A savepoint rollback undoes the File rows but not the bytes behind
    them, and a refused change must not leave a copy behind.  A file that
    another row still points at -- the same bytes, already on the site --
    is that row's and is left alone.
    """
    for owned in written:
        file_url = str(getattr(owned, "file_url", "") or "")
        if not file_url:
            continue
        try:
            if frappe.db.exists("File", {"file_url": file_url}):
                continue
            owned.delete_file_data_content()
        except Exception:
            logger.exception("Could not remove the stored file %s", file_url)


def _attachment_refusal(meta, doctype: str, changes: dict[str, Any]) -> str | None:
    """The refusal for a change that attaches a file the caller may not read.

    Adopting a file copies it into the document, and the copy is readable
    by everybody who may read the document.  A private file belonging to
    somebody else would leave its private folder and become the
    document's own picture.

    So the write is refused rather than half-applied: a document whose
    image points at a file its readers cannot see is a broken document, and
    a broken document is a quieter lie than a refused change.
    """
    for fieldname, value in changes.items():
        if not isinstance(value, str) or not value.startswith(("/files/", "/private/files/")):
            continue
        df = meta.get_field(fieldname) if meta else None
        if df is None or df.fieldtype not in ATTACH_FIELDTYPES:
            continue
        source = _file_for_url(value)
        if source is None:
            # No such file: there is nothing to copy, and the value is the
            # reader's own business.
            continue
        if not _may_read_file(source):
            return error(
                f"{doctype}: the file in '{fieldname}' may not be read by this account.",
                doctype=doctype,
                actionable=(
                    "Only a file this account may read can be attached to a "
                    "document. Do not try again with this file."
                ),
            )
    return None


def _adopt_attachments(
    document, changes: dict[str, Any], written: list | None = None
) -> dict[str, Any]:
    """Make every attached file the document's own, as an upload would.

    A file the chat stored is private and attached to the person who
    attached it: it renders in their session and nowhere else, so the
    Desk preview of an image behind a private URL is a broken image for
    everybody else.  An image set on a document is not that -- it is the
    document's picture, and it has to render for everyone who may read
    the document.

    So the document gets its own copy: the same bytes, a file attached to
    this document, which is what a person uploading through the form
    produces.  Frappe's own attach hook then finds that row already
    attached to this document and leaves it alone -- without this, the
    hook makes a second copy of its own and the field is left holding the
    private URL that does not render.

    The copy is public only when ``_copy_is_public`` says so: a private
    file somebody else uploaded stays private, attached to the document,
    so the document's readers may read it and the internet may not.

    The chat's own attachment is left as it is: private, and the
    uploader's.  Every File this stores is appended to *written*, so a
    write that fails afterwards can take the bytes back.
    """
    for fieldname, value in list(changes.items()):
        if not isinstance(value, str) or not value.startswith(("/files/", "/private/files/")):
            continue
        df = document.meta.get_field(fieldname)
        if df is None or df.fieldtype not in ATTACH_FIELDTYPES:
            continue
        source = _file_for_url(value)
        if source is None or not _may_read_file(source):
            continue
        is_private = 0 if _copy_is_public(source) else 1
        try:
            content = source.get_content()
            if isinstance(content, str):
                content = content.encode()
            # The document may already own this image: setting it again
            # must not leave a second File row behind it.  The bytes are
            # the same file, so the content hash is the same row.
            owned_url = frappe.db.get_value(
                "File",
                {
                    "attached_to_doctype": document.doctype,
                    "attached_to_name": document.name,
                    "attached_to_field": fieldname,
                    "is_private": is_private,
                    "content_hash": frappe.utils.file_manager.get_content_hash(content),
                },
                "file_url",
            )
            if owned_url:
                changes[fieldname] = owned_url
                continue
            # The File itself writes the bytes, once, and says where.
            owned = frappe.get_doc(
                {
                    "doctype": "File",
                    "file_name": source.file_name,
                    "content": content,
                    "attached_to_doctype": document.doctype,
                    "attached_to_name": document.name,
                    "attached_to_field": fieldname,
                    "folder": "Home/Attachments",
                    "is_private": is_private,
                }
            )
            try:
                owned.insert(ignore_permissions=True)
            except frappe.DuplicateEntryError:
                owned = frappe.get_doc("File", owned.duplicate_entry)
            except Exception:
                # The bytes may be on disk already, with no row to own them.
                _discard_written([owned])
                raise
            if written is not None:
                written.append(owned)
        except Exception:
            # A file that cannot be copied still saves as a value: the
            # reader sees the URL and the image may not render, which is
            # better than refusing the whole change.
            continue
        changes[fieldname] = str(getattr(owned, "file_url", "") or value)
    return changes


def _apply_update(document, changes: dict[str, Any], doctype: str, name: str) -> str | None:
    """Save the change, or say why it could not be saved.

    ``None`` means it saved.  The refusals name what happened, because a
    failure the model cannot act on is a failure it will retry identically.
    """
    savepoint = _savepoint("update_doc")
    written: list = []
    try:
        # `update` assigns `name` first when it is present, so it is never
        # present: the protected fields were refused above.
        document.reload()
        # Inside the savepoint, so a save that is refused takes back the
        # files the change stored as well as its rows.
        _adopt_attachments(document, changes, written)
        document.update(changes)
        document.save()
    except Exception as exc:
        _rollback_to(savepoint)
        _discard_written(written)
        return _update_refusal(exc, doctype, name)
    return None


def _update_refusal(exc: Exception, doctype: str, name: str) -> str:
    """The envelope for a change that could not be saved."""
    if isinstance(exc, frappe.PermissionError):
        return error(
            f"Failed to update {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
            actionable=(
                "This account's roles allow this kind of document but not this "
                "one — a User Permission limits which rows it may change. Say "
                "that as a fact about the account, and do not apologise for it."
            ),
        )
    if isinstance(exc, frappe.ValidationError):
        return error(
            f"Validation failed for {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
        )
    return error(f"Failed to update {doctype} '{name}': {exc}", doctype=doctype, name=name)


def _submit_update(document, doctype: str, name: str) -> str | None:
    """Submit the changed document, or say why it could not be submitted.

    The savepoint is taken *after* the change was saved, so a failure here
    undoes the submission and leaves the change — which is what the message
    says.
    """
    savepoint = _savepoint("update_submit")
    try:
        document.submit()
    except Exception as exc:
        _rollback_to(savepoint)
        return error(
            f"Updated {doctype} '{name}' but could not submit it: {exc}",
            doctype=doctype,
            name=name,
        )
    return None


def _read_only_fields(meta, data: dict[str, Any]) -> list[str]:
    """The fields in *data* that the DocType marks read-only.

    A read-only field is a field the *form* will not let a person change.
    The chat must not be a way around that: it would make the assistant the
    only actor on the site who can set a field nobody else can.
    """
    readonly = []
    for field in data:
        try:
            field_def = meta.get_field(field)
        except Exception:
            continue
        if field_def is None:
            continue
        if getattr(field_def, "read_only", 0):
            readonly.append(field)
    return sorted(readonly)


def _actual_changes(document, data: dict[str, Any]) -> dict[str, Any]:
    """The values in *data* that are not already the document's.

    A change that changes nothing is not a change.  Saving a document to
    write the value it already has would touch its modified timestamp, run
    every hook on it, and tell the reader that something was done when
    nothing was.
    """
    changes = {}
    for field, value in data.items():
        if _same(document.get(field), value):
            continue
        changes[field] = value
    return changes


def _same(current: Any, value: Any) -> bool:
    """Whether a value is already the document's.

    Compared as text, because the model sends text and the document holds
    whatever the framework keeps: a date is a ``date`` in one and a string
    in the other, and "2026-10-21" is the same date either way.
    """
    if current is None or current == "":
        return value is None or value == ""
    if value is None or value == "":
        return False
    return str(current) == str(value)


def _table_lengths(document, data: dict[str, Any]) -> dict[str, int]:
    """How many lines each table field in *data* has.

    A table field is replaced whole, so the number of lines before and
    after is the only way to say plainly what the change did.
    """
    lengths = {}
    for field in data:
        value = document.get(field)
        if isinstance(value, list):
            lengths[field] = len(value)
    return lengths


def _update_message(
    doctype: str,
    name: str,
    changes: dict[str, Any],
    document,
    lines_before: dict[str, int],
    submitted: bool,
) -> str:
    """What the update did, in a sentence the reader can check.

    The changed fields are named, because "something was updated" is not
    something anybody can check, and a table that lost a line is named too,
    because a replacement is not a change of one field.
    """
    message = f"Updated {doctype} '{name}': {', '.join(sorted(changes))}"

    for field in sorted(lines_before):
        before = lines_before.get(field, 0)
        after = len(document.get(field) or [])
        if after == before:
            continue
        message += f". Replaced the {before} line(s) of '{field}' with {after}"
        if after < before:
            message += f" — the {before - after} line(s) that were not in the new list are gone"

    if submitted:
        message += ", and submitted it"
    return message


def submit_doc(doctype: str, name: str) -> str:
    """Submit a draft document, making it permanent.

    Args:
        doctype: The DocType of the document, e.g. "Sales Invoice".
        name: The document's name, e.g. "ACC-SINV-00042".
    """
    if not doctype:
        return error("A doctype is required.")
    if not name:
        return error("A document name is required.")

    document = _load_for_action(doctype, name)
    if isinstance(document, str):
        return document

    if document.docstatus != 0:
        return error(
            f"{doctype} '{name}' is not a draft and cannot be submitted.",
            doctype=doctype,
            name=name,
            actionable=(
                "Only a draft document can be submitted. Say that as a fact "
                "about the document, and do not apologise for it."
            ),
        )

    savepoint = _savepoint("submit_doc")
    try:
        document.submit()
    except frappe.PermissionError as exc:
        _rollback_to(savepoint)
        return error(
            f"Failed to submit {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
            actionable=(
                "This account's roles allow this kind of document but not its "
                "submission — the submit permission is held by other roles. "
                "Say that as a fact about the account, and do not apologise "
                "for it."
            ),
        )
    except frappe.ValidationError as exc:
        _rollback_to(savepoint)
        return error(f"Validation failed for {doctype} '{name}': {exc}", doctype=doctype, name=name)
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to submit {doctype} '{name}': {exc}", doctype=doctype, name=name)

    return ok(
        f"Submitted {doctype} '{name}'.",
        data={"doctype": doctype, "name": name, "submitted": True},
        doctype=doctype,
        name=name,
    )


def cancel_doc(doctype: str, name: str) -> str:
    """Cancel a submitted document.

    Args:
        doctype: The DocType of the document, e.g. "Sales Invoice".
        name: The document's name, e.g. "ACC-SINV-00042".
    """
    if not doctype:
        return error("A doctype is required.")
    if not name:
        return error("A document name is required.")

    document = _load_for_action(doctype, name)
    if isinstance(document, str):
        return document

    if document.docstatus != 1:
        return error(
            f"{doctype} '{name}' is not submitted and cannot be cancelled.",
            doctype=doctype,
            name=name,
            actionable=(
                "Only a submitted document can be cancelled. Say that as a "
                "fact about the document, and do not apologise for it."
            ),
        )

    savepoint = _savepoint("cancel_doc")
    try:
        document.cancel()
    except frappe.PermissionError as exc:
        _rollback_to(savepoint)
        return error(
            f"Failed to cancel {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
            actionable=(
                "This account's roles allow this kind of document but not its "
                "cancellation — the cancel permission is held by other roles. "
                "Say that as a fact about the account, and do not apologise "
                "for it."
            ),
        )
    except frappe.ValidationError as exc:
        _rollback_to(savepoint)
        return error(f"Validation failed for {doctype} '{name}': {exc}", doctype=doctype, name=name)
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to cancel {doctype} '{name}': {exc}", doctype=doctype, name=name)

    return ok(
        f"Cancelled {doctype} '{name}'.",
        data={"doctype": doctype, "name": name, "cancelled": True},
        doctype=doctype,
        name=name,
    )


def amend_doc(doctype: str, name: str) -> str:
    """Amend a submitted document: cancel it and create a new draft.

    Args:
        doctype: The DocType of the document, e.g. "Sales Invoice".
        name: The document's name, e.g. "ACC-SINV-00042".
    """
    if not doctype:
        return error("A doctype is required.")
    if not name:
        return error("A document name is required.")

    document = _load_for_action(doctype, name)
    if isinstance(document, str):
        return document

    if document.docstatus != 1:
        return error(
            f"{doctype} '{name}' is not submitted and cannot be amended.",
            doctype=doctype,
            name=name,
            actionable=(
                "Only a submitted document can be amended. Say that as a fact "
                "about the document, and do not apologise for it."
            ),
        )

    # Cancel the original and create a new draft based on it.  The
    # savepoint covers both: if the new draft cannot be created, the
    # cancellation is undone, so the original is left as it was.  The
    # original's on_cancel hooks may still have run their side effects —
    # those are not undone by a savepoint — but the document itself is.
    savepoint = _savepoint("amend_doc")
    try:
        document.cancel()
        new_doc = frappe.get_doc(document.as_dict())
        new_doc.name = None
        new_doc.docstatus = 0
        new_doc.amended_from = name
        new_doc.insert()
    except frappe.PermissionError as exc:
        _rollback_to(savepoint)
        return error(
            f"Failed to amend {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
            actionable=(
                "This account's roles allow this kind of document but not its "
                "amendment — the amend permission is held by other roles. Say "
                "that as a fact about the account, and do not apologise for it."
            ),
        )
    except frappe.ValidationError as exc:
        _rollback_to(savepoint)
        return error(f"Validation failed for {doctype} '{name}': {exc}", doctype=doctype, name=name)
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to amend {doctype} '{name}': {exc}", doctype=doctype, name=name)

    return ok(
        f"Amended {doctype} '{name}': created '{new_doc.name}' (draft).",
        data={"doctype": doctype, "name": name, "amended": new_doc.name},
        doctype=doctype,
        name=name,
    )


def delete_doc(doctype: str, name: str) -> str:
    """Delete a document.

    Args:
        doctype: The DocType of the document, e.g. "Customer".
        name: The document's name, e.g. "CUST-0001".
    """
    if not doctype:
        return error("A doctype is required.")
    if not name:
        return error("A document name is required.")

    document = _load_for_action(doctype, name)
    if isinstance(document, str):
        return document

    if document.docstatus not in (0, 2):
        return error(
            f"{doctype} '{name}' is submitted and cannot be deleted.",
            doctype=doctype,
            name=name,
            actionable=(
                "A submitted document is deleted by cancelling it first, which "
                "this tool does not do. Say so rather than trying again."
            ),
        )

    savepoint = _savepoint("delete_doc")
    try:
        frappe.delete_doc(doctype, name, ignore_permissions=False)
    except frappe.PermissionError as exc:
        _rollback_to(savepoint)
        return error(
            f"Failed to delete {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
            actionable=(
                "This account's roles allow this kind of document but not its "
                "deletion — the delete permission is held by other roles. Say "
                "that as a fact about the account, and do not apologise for it."
            ),
        )
    except frappe.ValidationError as exc:
        _rollback_to(savepoint)
        return error(f"Validation failed for {doctype} '{name}': {exc}", doctype=doctype, name=name)
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to delete {doctype} '{name}': {exc}", doctype=doctype, name=name)

    return ok(
        f"Deleted {doctype} '{name}'.",
        data={"doctype": doctype, "name": name, "deleted": True},
        doctype=doctype,
        name=name,
    )


def _bulk_approved_set_refusal(doctype: str, names: list, approved_names: Any) -> str | None:
    """The refusal when the approved set moved, or ``None``.

    A document that appeared or disappeared since the card was shown is a
    row the reader never approved, and the change is refused rather than
    made on their behalf.
    """
    if approved_names is None:
        return None
    approved = {str(n) for n in (approved_names or [])}
    current = {str(n) for n in (names or [])}
    appeared = sorted(current - approved)
    disappeared = sorted(approved - current)
    if not appeared and not disappeared:
        return None
    parts = []
    if appeared:
        parts.append("appeared: " + ", ".join(appeared))
    if disappeared:
        parts.append("disappeared: " + ", ".join(disappeared))
    return error(
        f"The set of {doctype} documents changed since approval "
        f"({' ; '.join(parts)}); nothing was changed.",
        doctype=doctype,
        actionable="Read the documents again and propose the change afresh.",
    )


def _bulk_lookup_names(doctype: str, filters: Any, limit: Any) -> tuple[list, str | None]:
    """Resolve the bulk change's target names, or an error envelope.

    Returns ``(names, None)`` on success and ``([], error)`` on failure.
    """
    try:
        limit = int(limit or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    frappe_filters = _bulk_filters(filters)
    if isinstance(frappe_filters, str):
        return [], frappe_filters

    try:
        # ``get_list`` and not ``get_all``: the targets of a bulk change
        # are documents the caller may read.  ``get_all`` ignores the
        # permission engine, and a bulk change that reached past it would
        # name — and change — rows the reader cannot see.
        names = frappe.get_list(doctype, filters=frappe_filters, pluck="name", limit=limit)
    except Exception as exc:
        return [], error(f"Could not look up {doctype}: {exc}", doctype=doctype)

    return list(names), None


def bulk_update_doc(
    doctype: str, filters: Any, data: Any, limit: int = 50, _approved_names: Any = None
) -> str:
    """Change the same fields on many documents of one DocType at once.

    Args:
        doctype: The DocType to change, e.g. "Sales Order".
        filters: A list of [field, operator, value] triples.
        data: The field values to change on every matching document.
        limit: The most documents to change (default 50, max 200).
    """
    if not doctype:
        return error("A doctype is required.")
    if not isinstance(filters, list) or not filters:
        return error("At least one filter is required.")
    if not isinstance(data, dict) or not data:
        return error("The changes are required, as an object of field values.")

    # The same field checks a single change gets — a bulk change that
    # skipped them would be the one place where the framework's own
    # fields could be written.
    meta = _meta(doctype)
    if isinstance(meta, str):
        return meta

    refusal = _field_refusal(meta, doctype, data)
    if refusal:
        return refusal

    names, lookup_error = _bulk_lookup_names(doctype, filters, limit)
    if lookup_error:
        return lookup_error

    refusal = _bulk_approved_set_refusal(doctype, names, _approved_names)
    if refusal:
        return refusal

    if not names:
        return ok(
            f"No {doctype} documents matched the filters; nothing was changed.",
            data={"doctype": doctype, "changed": 0, "names": []},
            doctype=doctype,
        )

    changed = 0
    failed: list[str] = []
    # The values each document carried before this change, for the fields
    # that actually changed — so a bulk change can be taken back.  One
    # entry per document that was changed, in the order it was changed.
    documents: list[dict[str, Any]] = []
    for name in names:
        was_changed, reason, before = _bulk_change_one(doctype, name, data)
        if was_changed:
            changed += 1
            if before:
                documents.append({"name": name, "before": before})
        elif reason:
            failed.append(f"{name}: {reason}")

    message = f"Changed {changed} of {len(names)} {doctype} document(s)."
    if failed:
        message += " Failed: " + "; ".join(failed[:5])
        if len(failed) > 5:
            message += f" (and {len(failed) - 5} more)"

    return ok(
        message,
        data={
            "doctype": doctype,
            "changed": changed,
            "total": len(names),
            "failed": failed,
            "documents": documents,
        },
        doctype=doctype,
    )


def _bulk_filters(filters: Any) -> list | str:
    """The filters as the framework wants them, or an error envelope.

    A bulk change is filtered by triples — field, operator, value — and a
    filter that is not one is refused rather than guessed at: a guess
    would change the wrong rows.
    """
    triples: list[list[Any]] = []
    for entry in filters:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            return error("Each filter must be a [field, operator, value] triple.")
        triples.append([str(entry[0]), str(entry[1]), entry[2]])
    return triples


def _bulk_change_one(
    doctype: str, name: str, data: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    """Change one document of a bulk change.

    Returns ``(changed, reason, before)``: the reason is empty when the
    document was changed or needed no change, and says why when it was
    left alone; ``before`` holds the values the document carried for the
    fields that actually changed, so the change can be taken back.  Each
    document gets its own savepoint, so one that cannot be changed does
    not undo the ones that were.
    """
    savepoint = _savepoint("bulk_update_doc")
    written: list = []
    try:
        document = frappe.get_doc(doctype, name)
        if not may_read(document):
            _rollback_to(savepoint)
            return False, "may not be read", {}
        if document.docstatus:
            _rollback_to(savepoint)
            return False, "submitted", {}
        changes = _actual_changes(document, data)
        if not changes:
            return False, "", {}
        before = {field: document.get(field) for field in changes}
        _adopt_attachments(document, changes, written)
        document.update(changes)
        document.save()
        return True, "", before
    except Exception as exc:
        _rollback_to(savepoint)
        _discard_written(written)
        return False, str(exc), {}


def list_doctypes(
    module: str = "",
    search: str = "",
    custom_only: bool = False,
    limit: int = 100,
) -> str:
    """The DocTypes this caller may read.

    Not one of the assistant's tools: it is the lookup behind the answer to
    "that DocType does not exist", which is otherwise a dead end — the model
    has no way to learn the right name and guesses again.

    The list is the caller's.  The Desk's own search hides the DocTypes
    a reader may not read, and a model that knew the site had a "Salary
    Slip" could tell the reader something the reader could not find out
    for themselves.
    """
    from albanna.permissions import readable_doctypes

    readable = readable_doctypes(str(frappe.session.user or ""))
    if not readable:
        return ok("Found 0 DocType(s)", data=None, count=0, doctypes=[])

    filters: list[list[Any]] = [["name", "in", readable]]
    if module:
        filters.append(["module", "=", module])
    if search:
        filters.append(["name", "like", f"%{search}%"])
    if custom_only:
        filters.append(["custom", "=", 1])

    try:
        rows = frappe.get_all(
            "DocType",
            filters=filters or None,
            fields=["name", "module", "custom", "istable", "issingle", "is_submittable"],
            order_by="module asc, name asc",
            limit_page_length=min(max(int(limit or 100), 1), 500),
        )
    except Exception as exc:
        return error(f"Failed to list DocTypes: {exc}")

    return ok(
        f"Found {len(rows)} DocType(s)",
        data=None,
        count=len(rows),
        doctypes=rows,
    )
