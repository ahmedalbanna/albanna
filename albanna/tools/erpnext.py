"""The five ERPNext tools, implemented in this app.

Why they live here
------------------
This app was originally built on top of the ``erpnext-mcp`` project, and it
called that project's tool functions in-process.  That cannot be published:
``erpnext-mcp`` on PyPI is a *different* project — an earlier release by
another author — so the version this app needs can never be installed by a
site that was not handed it by hand.  An app that cannot be installed is not
an app.

So the five tools are implemented here, against the framework's own APIs.
They are the small part of that project this app ever used, and they return
the same envelopes the chat service already speaks:
``{"status", "message", "data", "hints"}``.

The permissions are the framework's, and they are the *caller's*: a read
goes through ``frappe.get_list``/``frappe.get_doc``, which apply the
caller's roles and User Permissions, and a write goes through
``doc.insert()``, which applies the caller's create permission.  Nothing
here bypasses the permission engine.
"""

from __future__ import annotations

import difflib
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

#: The largest a listing may return.
MAX_LIMIT = 500


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

    try:
        raw = _execute_report(report_doc, report_filters)
    except Exception as exc:
        return error(f"Report '{report}' failed: {exc}", report=report)

    # A report is a read; it must not leave a transaction open.
    frappe.db.rollback()

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

    try:
        document = frappe.get_doc({"doctype": doctype, **data})
        document.insert()
    except frappe.PermissionError as exc:
        return error(
            f"Failed to create {doctype}: {exc}",
            doctype=doctype,
            actionable="This account may not create this kind of document.",
        )
    except frappe.DuplicateEntryError as exc:
        frappe.db.rollback()
        return error(f"Duplicate entry: {exc}", doctype=doctype)
    except frappe.ValidationError as exc:
        frappe.db.rollback()
        return error(f"Validation failed: {exc}", doctype=doctype)
    except Exception as exc:
        frappe.db.rollback()
        return error(f"Failed to create {doctype}: {exc}", doctype=doctype)

    submitted = False
    if submit:
        try:
            document.submit()
            submitted = True
        except Exception as exc:
            frappe.db.rollback()
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
