"""The in-process tool backend.

This is where Albanna actually touches ERPNext.  It calls the tool
functions from the ``erpnext_mcp`` package directly — no HTTP, no MCP
session, no gateway, no licence check, no per-user API key.

Three things had to be got right for that to be safe, and each is a
deliberate, checked step rather than an assumption.

1.  **The site.**  The tool functions resolve their site through
    ``get_site()``, which reads ``FRAPPE_SITE`` and then
    ``sites/currentsite.txt`` — and on this bench that file names the
    *production* site.  A tool called from a request for another site, with
    no Frappe context initialised, would therefore read and write the
    production database while the user is looking at a different one.

    ``get_site()`` does prefer ``frappe.local.site`` when the context is
    initialised, which covers a web request.  It does not cover a worker
    thread whose ``frappe.local`` is fresh.  So the site is *asserted* here,
    before every call, against the site the request was resolved for.  A
    mismatch is an error, never a silent redirect.

2.  **The user.**  The tool functions are decorated with ``@with_frappe``,
    which commits the transaction on success and rolls it back on failure —
    and which, by default, lets write tools bypass Frappe's permission engine
    (``ignore_permissions=True``), because the backend used to be the
    authority and the backend ran as a mapped user.

    In-process there is no mapped user, so the bypass is switched off by
    setting ``frappe.local.mcp_per_call_user`` to the person who asked.  The
    backend's own decorator then re-applies that user and drops the cached
    role permissions before the call, so reads *and* writes run under the
    user's real permissions.  That marker is deliberately absent from the
    backend's authentication-marker list, so it does not disturb the
    site-authorisation check.

3.  **The arguments.**  The manifest speaks the model's language — real
    JSON types, ``data`` as an object.  The backend functions speak theirs —
    JSON *strings* for structured arguments.  The translation lives here, in
    one place per tool, so neither side has to know about the other.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any

from albanna.core.tools import ToolSpec, compact_json, truncate_result
from albanna.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

#: The attribute the backend's ``with_frappe`` decorator reads to learn which
#: user a call runs as.  It is not one of the backend's authentication
#: markers, so setting it does not make the call look authenticated.
PER_CALL_USER_ATTR = "mcp_per_call_user"


class ToolNotBound(LookupError):
    """The manifest names a tool this backend cannot run."""


def _join_fields(arguments: dict[str, Any]) -> str:
    """The model's ``fields`` array as the backend's comma-separated string."""
    fields = arguments.get("fields")
    if not isinstance(fields, list):
        return ""
    return ",".join(str(field).strip() for field in fields if str(field).strip())


def _translate_list_docs(arguments: dict[str, Any]) -> dict[str, Any]:
    filters = arguments.get("filters")
    translated: dict[str, Any] = {
        "doctype": arguments.get("doctype", ""),
        "filters_json": json.dumps(filters if isinstance(filters, list) else []),
        "fields": _join_fields(arguments),
    }
    if arguments.get("limit") is not None:
        translated["limit_page_length"] = int(arguments["limit"])
    if arguments.get("offset") is not None:
        translated["limit_start"] = int(arguments["offset"])
    if arguments.get("order_by"):
        translated["order_by"] = str(arguments["order_by"])
    return translated


def _translate_get_doc(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "doctype": arguments.get("doctype", ""),
        "name": arguments.get("name", ""),
        "fields": _join_fields(arguments),
    }


def _translate_get_doctype_meta(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "doctype": arguments.get("doctype", ""),
        "fields": _join_fields(arguments),
    }


def _translate_run_report(arguments: dict[str, Any]) -> dict[str, Any]:
    filters = arguments.get("filters")
    translated: dict[str, Any] = {
        "report_name": arguments.get("report", ""),
        "filters_json": json.dumps(filters if isinstance(filters, dict) else {}),
    }
    if arguments.get("limit") is not None:
        translated["limit"] = int(arguments["limit"])
    if arguments.get("offset") is not None:
        translated["offset"] = int(arguments["offset"])
    return translated


def _translate_create_doc(arguments: dict[str, Any]) -> dict[str, Any]:
    data = arguments.get("data")
    return {
        "doctype": arguments.get("doctype", ""),
        "data_json": json.dumps(data if isinstance(data, dict) else {}),
        "submit": bool(arguments.get("submit", False)),
    }


#: tool name -> (backend function, argument translator)
#
# The functions are imported lazily, inside :meth:`ErpnextMcpBackend._resolve`,
# so that importing this module does not import ``erpnext_mcp`` at all.  That
# keeps the Frappe-free half of the app importable without the tool package
# present, and it keeps the import cost off the request path until a tool is
# actually called.
_BOUND_TOOLS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "list_docs": ("erpnext_mcp.tools.crud_reads:list_docs", _translate_list_docs),
    "get_doc": ("erpnext_mcp.tools.crud_reads:get_doc", _translate_get_doc),
    "get_doctype_meta": ("erpnext_mcp.tools.discovery:get_doctype_meta", _translate_get_doctype_meta),
    "run_report": ("erpnext_mcp.tools.query:run_report", _translate_run_report),
    "create_doc": ("erpnext_mcp.tools.crud_writes:create_doc", _translate_create_doc),
}


def _import(target: str) -> Callable[..., str]:
    """Import ``package.module:function`` and return the function."""
    module_name, _, attribute = target.partition(":")
    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


class ErpnextMcpBackend:
    """Runs ERPNext tools by calling the ``erpnext_mcp`` functions in-process."""

    def __init__(self, bound_tools: dict[str, tuple[str, Callable]] | None = None) -> None:
        self._bound = dict(bound_tools or _BOUND_TOOLS)
        self._resolved: dict[str, Callable[..., str]] = {}

    @property
    def bound_names(self) -> tuple[str, ...]:
        return tuple(self._bound)

    def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run one tool."""
        handler, translator = self._resolve(spec.name)

        self._assert_site(spec, context)
        translated = translator(arguments)

        raw = self._invoke(spec, handler, translated, context)
        result = self._interpret(spec, raw, context)
        return self._explain_missing_doctype(result)

    # -- internals --------------------------------------------------------

    def _explain_missing_doctype(self, result: ToolResult) -> ToolResult:
        """When a DocType's name is wrong, name the ones that exist.

        The model asks for "Sales Taxes and Templates" and the site has
        "Sales Taxes and Charges Template".  A bare "not found" is a dead
        end: the model has no way to learn the right name, so it guesses
        again, and again, and each guess is another step.

        So the near-misses are looked up here, with the same lookup the
        backend provides for that purpose, and returned with the error.  The
        tool set does not grow — the answer to "that does not exist" simply
        becomes an answer instead of a wall.
        """
        if result.ok:
            return result

        message = result.error or ""
        # Frappe's own message is "DocType <name> not found"; the backend
        # sometimes quotes the name, so both shapes are accepted.
        match = re.search(r"DocType\s+'?([^'\"\n]+?)'?\s+not found", message)
        if not match:
            return result

        wanted = match.group(1)
        candidates = self._doctype_candidates(wanted)
        if not candidates:
            return result

        listed = ", ".join(candidates)
        explanation = (
            f"{message} The closest names on this site are: {listed}. "
            f"Use one of those, or call get_doctype_meta on one of them "
            f"before using it."
        )
        return ToolResult(
            ok=result.ok,
            content=explanation,
            data=result.data,
            error=explanation,
            denied=result.denied,
        )

    def _doctype_candidates(self, wanted: str, limit: int = 5) -> list[str]:
        """The DocType names on this site that most resemble *wanted*."""
        words = [
            word.lower()
            for word in re.split(r"[^A-Za-z0-9]+", wanted)
            if len(word) > 3 and word.lower() not in ("and", "the", "for", "with")
        ]
        if not words:
            return []

        # The search is a substring match, so "Taxes" never finds "Tax
        # Template".  Models pluralise freely, so each word is searched in
        # its singular form as well.
        searches: list[str] = []
        for word in words[:3]:
            for form in (word, word[:-1] if word.endswith("s") and len(word) > 4 else word):
                if form and form not in searches:
                    searches.append(form)

        found: dict[str, int] = {}
        for word in searches:
            try:
                raw = self._call_internal(
                    "erpnext_mcp.tools.misc:list_doctypes",
                    {"search": word, "limit": 200},
                )
            except Exception:
                continue
            for name in self._names_from(raw):
                found[name] = found.get(name, 0) + 1

        # Rank by how many of the wanted words the name shares, then by how
        # close it is to the wanted name.
        def score(item: tuple[str, int]) -> tuple[int, int, str]:
            name, shared = item
            lowered = name.lower()
            bonus = sum(1 for word in words if word in lowered or word.rstrip("s") in lowered)
            closeness = len(set(lowered.split()) & set(words))
            return (-shared - bonus, -closeness, name)

        ranked = sorted(found.items(), key=score)
        return [name for name, _ in ranked[:limit]]

    def _call_internal(self, target: str, arguments: dict[str, Any]) -> str:
        """Call a backend function that is not one of the model's tools."""
        handler = _import(target)
        return handler(**arguments)

    @staticmethod
    def _names_from(raw: str) -> list[str]:
        """The DocType names in a ``list_doctypes`` envelope.

        The backend's envelope carries the extra keyword arguments at the
        top level, with ``data`` left null, so both places are read.
        """
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(payload, dict):
            return []

        rows = payload.get("doctypes")
        if not isinstance(rows, list):
            data = payload.get("data")
            rows = data.get("doctypes") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []

        return [str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name")]

    def _resolve(self, name: str) -> tuple[Callable[..., str], Callable[[dict[str, Any]], dict[str, Any]]]:
        """The function that runs a tool, and the translator for its arguments."""
        binding = self._bound.get(name)
        if binding is None:
            raise ToolNotBound(f"No tool is bound to '{name}'.")

        target, translator = binding
        handler = self._resolved.get(name)
        if handler is None:
            handler = _import(target)
            self._resolved[name] = handler
        return handler, translator

    def _assert_site(self, spec: ToolSpec, context: ToolContext) -> None:
        """Refuse to run a tool against the wrong site.

        This is the check that stands between a mistyped site name and a
        write to somebody else's database.  It is cheap, it runs before every
        call, and it fails closed.
        """
        import frappe

        expected = (context.site or "").strip()
        if not expected:
            raise RuntimeError(f"Refusing to run '{spec.name}': no site was resolved for this call.")

        actual = str(getattr(frappe.local, "site", "") or "").strip()
        if actual != expected:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': this request is bound to site "
                f"'{actual or '(none)'}', not '{expected}'."
            )

    def _invoke(
        self,
        spec: ToolSpec,
        handler: Callable[..., str],
        translated: dict[str, Any],
        context: ToolContext,
    ) -> str:
        """Call the tool as the requesting user."""
        import frappe

        user = context.principal.user
        previous = getattr(frappe.local, PER_CALL_USER_ATTR, None)
        setattr(frappe.local, PER_CALL_USER_ATTR, user)
        try:
            return handler(**translated)
        except Exception as exc:  # noqa: BLE001 - the envelope is the contract
            logger.exception("Tool '%s' raised", spec.name)
            return compact_json(
                {
                    "status": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "data": None,
                    "hints": [],
                }
            )
        finally:
            if previous is None:
                with contextlib.suppress(AttributeError):
                    delattr(frappe.local, PER_CALL_USER_ATTR)
            else:
                setattr(frappe.local, PER_CALL_USER_ATTR, previous)

    def _interpret(self, spec: ToolSpec, raw: Any, context: ToolContext) -> ToolResult:
        """Turn the backend's JSON string into a :class:`ToolResult`.

        The backend's envelope has a ``status`` field on the shapes that use
        one, and the shapes that do not — a report's row array, a doctype's
        field list — are returned as raw JSON.  Both are accepted, and a
        response that is not JSON at all is treated as text.
        """
        if not isinstance(raw, str):
            raw = compact_json(raw)

        payload: Any = None
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            payload = None

        if isinstance(payload, dict) and "status" in payload:
            status = str(payload.get("status") or "")
            message = str(payload.get("message") or "")
            data = payload.get("data")
            hints = payload.get("hints") or []
            ok = status in ("ok", "skipped", "accepted")

            parts = [message] if message else []
            if hints:
                parts.append("Hints: " + "; ".join(str(hint) for hint in hints))
            content = "\n".join(part for part in parts if part) or status
            if data is not None:
                content = f"{content}\n{compact_json(data)}"

            if ok:
                return ToolResult.success(truncate_result(content, spec.max_result_chars), data)
            return ToolResult.failure(
                truncate_result(content, spec.max_result_chars),
                error=message or status,
                data=data,
            )

        # No envelope: a plain JSON document, or plain text.
        content = raw if payload is None else compact_json(payload)
        return ToolResult.success(truncate_result(content, spec.max_result_chars), payload)
