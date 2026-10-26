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
    known = {df.fieldname for df in (getattr(meta, "fields", []) or []) if getattr(df, "fieldname", None)}
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
    watchers.  Nothing here writes to the filesystem.
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


def _may_read(document) -> bool:
    """Whether the session user may read this document.

    ``frappe.get_doc`` applies no permission check at all, which is how a
    Sales User came to read a Sales Invoice in full — customer, totals, every
    line item — through this tool while ``list_docs`` refused the same one.
    The listing goes through ``frappe.get_list``, which checks; the single
    read goes through the ORM, which does not.

    The document is passed rather than only its DocType so that the
    row-level rules count: a User Permission that limits an account to one
    customer is a read permission, and it applies here.

    An exception is a "no".  A permission engine that cannot answer has not
    said yes.
    """
    try:
        return bool(frappe.has_permission(document.doctype, ptype="read", doc=document))
    except Exception:
        logger.exception("Could not check read permission for %s", document.doctype)
        return False


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


# --------------------------------------------------------------------------
# The tools
# --------------------------------------------------------------------------


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
    if field_list:
        invalid = _validate_fields(meta, doctype, field_list)
        if invalid:
            return invalid

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

    return ok(f"Found {len(documents)} {doctype}", data=documents, doctype=doctype)


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
    if not _may_read(document):
        return _read_refusal(doctype, name)

    field_list = [str(field).strip() for field in (fields or []) if str(field).strip()]
    if field_list:
        invalid = _validate_fields(frappe.get_meta(doctype), doctype, field_list)
        if invalid:
            return invalid
        data = {field: document.get(field) for field in field_list}
        data["name"] = document.name
        return ok(f"Read {doctype} '{name}'", data=data, doctype=doctype, name=name)

    data = document.as_dict()
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

    refusal = _report_refusal(report_doc, report)
    if refusal:
        return refusal

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
        **{key: value for key, value in payload.items() if key not in ("status", "columns", "rows")},
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


def _report_refusal(report_doc, report: str) -> str | None:
    """An error envelope when the caller may not run this report.

    The same access the desk applies before it runs one: the report's own
    role restriction, the report permission on the DocType it is about, and
    the disabled flag.
    """
    try:
        permitted = report_doc.is_permitted()
    except Exception:
        permitted = True
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
    if not doctype:
        return error("A doctype is required.")
    if not isinstance(data, dict) or not data:
        return error("The document's data is required, as an object of field values.")
    if "doctype" in data:
        # The DocType is the first argument, and the authority layer
        # authorised *that* one.  A DocType inside the data would be a
        # second, unchecked answer to the same question.
        return error(
            "The document's data must not name a doctype: the doctype is the "
            "first argument.",
            doctype=doctype,
        )

    savepoint = _savepoint("create_doc")
    try:
        document = frappe.get_doc({"doctype": doctype, **data})
        document.insert()
        # The attachments are adopted now that the document has a name to
        # be attached to.
        if _adopt_attachments(document, dict(data)):
            document.save()
    except Exception as exc:
        return _create_refusal(exc, doctype, savepoint)

    submitted = False
    if submit:
        # A savepoint of its own, taken after the insert: rolling back to
        # the insert's savepoint would undo the creation as well, and the
        # message below says the document was created.
        submit_savepoint = _savepoint("create_submit")
        try:
            document.submit()
            submitted = True
        except Exception as exc:
            _rollback_to(submit_savepoint)
            return error(f"Created {doctype} '{document.name}' but could not submit it: {exc}", doctype=doctype)

    message = f"Created {doctype} '{document.name}'"
    if submitted:
        message += " and submitted it"
    return ok(
        message,
        data={"doctype": doctype, "name": document.name, "submitted": submitted},
        doctype=doctype,
        name=document.name,
    )


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

    _adopt_attachments(document, changes)

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


def _load_for_update(doctype: str, name: str, data: dict[str, Any]):
    """The document to change, or an error envelope saying why there is not one.

    The refusals that do not need the document come first: a field that does
    not exist, a field the framework owns, a field the form would not let a
    person change.  They are cheaper, and they are the ones a model most
    often gets wrong.
    """
    meta = _meta(doctype)
    if isinstance(meta, str):
        return meta

    invalid = _validate_fields(meta, doctype, list(data))
    if invalid:
        return invalid

    protected = sorted(set(data) & PROTECTED_FIELDS)
    if protected:
        return error(
            f"These field(s) belong to the framework and cannot be set: "
            f"{', '.join(protected)}.",
            doctype=doctype,
            name=name,
            actionable="Give only the fields the user asked to change.",
        )

    readonly = _read_only_fields(meta, data)
    if readonly:
        return error(
            f"These field(s) are read-only and cannot be changed: "
            f"{', '.join(readonly)}.",
            doctype=doctype,
            name=name,
            actionable="Give only the fields the user asked to change.",
        )

    try:
        return frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)


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


def _adopt_attachments(document, changes: dict[str, Any]) -> dict[str, Any]:
    """Make every attached file the document's own, as an upload would.

    A file the chat stored is private and attached to the person who
    attached it: it renders in their session and nowhere else, so the
    Desk preview of an image behind a private URL is a broken image for
    everybody else.  An image set on a document is not that -- it is the
    document's picture, and it has to render for everyone who may read
    the document.

    So the document gets its own copy: the same bytes, a public file
    attached to this document, which is what a person uploading through
    the form produces.  Frappe's own attach hook then finds that row
    already attached to this document and leaves it alone -- without
    this, the hook makes a second copy of its own and the field is left
    holding the private URL that does not render.

    The chat's own attachment is left as it is: private, and the
    uploader's.  Only the copy the document owns is public.
    """
    for fieldname, value in list(changes.items()):
        if not isinstance(value, str) or not value.startswith(("/files/", "/private/files/")):
            continue
        df = document.meta.get_field(fieldname)
        if df is None or df.fieldtype not in ATTACH_FIELDTYPES:
            continue
        source = _file_for_url(value)
        if source is None:
            continue
        try:
            content = source.get_content()
            if isinstance(content, str):
                content = content.encode()
            owned = frappe.utils.file_manager.save_file(
                source.file_name,
                content,
                document.doctype,
                document.name,
                folder="Home/Attachments",
                is_private=0,
                df=fieldname,
            )
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
    try:
        # `update` assigns `name` first when it is present, so it is never
        # present: the protected fields were refused above.
        document.reload()
        document.update(changes)
        document.save()
    except frappe.PermissionError as exc:
        _rollback_to(savepoint)
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
    except frappe.ValidationError as exc:
        _rollback_to(savepoint)
        return error(
            f"Validation failed for {doctype} '{name}': {exc}",
            doctype=doctype,
            name=name,
        )
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to update {doctype} '{name}': {exc}", doctype=doctype, name=name)
    return None


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
            message += (
                f" — the {before - after} line(s) that were not in the new "
                f"list are gone"
            )

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

    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

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

    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

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

    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

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

    try:
        document = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return error(f"{doctype} '{name}' not found", doctype=doctype, name=name)
    except Exception as exc:
        return error(f"Failed to read {doctype} '{name}': {exc}", doctype=doctype, name=name)

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
    except Exception as exc:
        _rollback_to(savepoint)
        return error(f"Failed to delete {doctype} '{name}': {exc}", doctype=doctype, name=name)

    return ok(
        f"Deleted {doctype} '{name}'.",
        data={"doctype": doctype, "name": name, "deleted": True},
        doctype=doctype,
        name=name,
    )



def bulk_update_doc(doctype: str, filters: Any, data: Any, limit: int = 50) -> str:
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

    try:
        limit = int(limit or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    # Build the filter list in the shape Frappe expects.
    frappe_filters = []
    for entry in filters:
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            return error("Each filter must be a [field, operator, value] triple.")
        frappe_filters.append([str(entry[0]), str(entry[1]), entry[2]])

    try:
        names = frappe.get_all(doctype, filters=frappe_filters, pluck="name", limit=limit)
    except Exception as exc:
        return error(f"Could not look up {doctype}: {exc}", doctype=doctype)

    if not names:
        return ok(
            f"No {doctype} documents matched the filters; nothing was changed.",
            data={"doctype": doctype, "changed": 0, "names": []},
            doctype=doctype,
        )

    changed = 0
    failed: list[str] = []
    for name in names:
        savepoint = _savepoint("bulk_update_doc")
        try:
            document = frappe.get_doc(doctype, name)
            if document.docstatus:
                failed.append(f"{name}: submitted")
                _rollback_to(savepoint)
                continue
            changes = _actual_changes(document, data)
            if changes:
                _adopt_attachments(document, changes)
                document.update(changes)
                document.save()
                changed += 1
        except Exception as exc:
            _rollback_to(savepoint)
            failed.append(f"{name}: {exc}")

    message = f"Changed {changed} of {len(names)} {doctype} document(s)."
    if failed:
        message += " Failed: " + "; ".join(failed[:5])
        if len(failed) > 5:
            message += f" (and {len(failed) - 5} more)"

    return ok(
        message,
        data={"doctype": doctype, "changed": changed, "total": len(names), "failed": failed},
        doctype=doctype,
    )


def list_doctypes(
    module: str = "",
    search: str = "",
    custom_only: bool = False,
    limit: int = 100,
) -> str:
    """The DocTypes installed on this site.

    Not one of the assistant's tools: it is the lookup behind the answer to
    "that DocType does not exist", which is otherwise a dead end — the model
    has no way to learn the right name and guesses again.
    """
    filters: list[list[Any]] = []
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
