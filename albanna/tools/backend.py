"""The tool backend: the seam between the model and ERPNext.

The model speaks the manifest's contract — JSON in, JSON out — and this
module is the only place that knows the contract is implemented in Python
rather than in JSON.

Two things are checked before every call:

*   **the site.**  The tool must run against the site the request was
    resolved for, and never against one inferred from the environment.
*   **the actor.**  The tool must run as the person who asked.  The
    framework applies that person's roles and User Permissions to every
    read and every write the tool makes, so an assistant cannot read what
    its caller cannot read.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

import frappe

from albanna.core.tools import ToolSpec, compact_json, truncate_result
from albanna.tools import erpnext
from albanna.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

#: The tool the model calls, and the function that implements it.  The
#: manifest's contract *is* the implementation's signature — there is no
#: translation layer, because there is nothing to translate.
_BOUND_TOOLS: dict[str, Callable[..., str]] = {
    "list_docs": erpnext.list_docs,
    "get_doc": erpnext.get_doc,
    "get_doctype_meta": erpnext.get_doctype_meta,
    "run_report": erpnext.run_report,
    "create_doc": erpnext.create_doc,
    "update_doc": erpnext.update_doc,
    "bulk_update_doc": erpnext.bulk_update_doc,
    "submit_doc": erpnext.submit_doc,
    "cancel_doc": erpnext.cancel_doc,
    "amend_doc": erpnext.amend_doc,
    "delete_doc": erpnext.delete_doc,
}


class ToolNotBound(LookupError):
    """The manifest names a tool this backend cannot run."""


def _summarise(payload: Any) -> str:
    """A one-line summary of a payload that carries no message of its own.

    Most of the tools answer with an envelope whose ``message`` is the
    summary — "Found 24 Sales Order".  The ones that answer with raw JSON
    have no envelope to carry one, so it is made here from the shape of
    the payload.  A payload with nothing recognisable in it gets no
    summary, which is honest: a line that says nothing is worse than no
    line.
    """
    if not isinstance(payload, dict):
        return ""

    doctype = payload.get("doctype")
    if not doctype:
        return ""

    fields = payload.get("fields")
    if isinstance(fields, list):
        return f"{doctype}: {len(fields)} fields"
    return str(doctype)


class ErpnextBackend:
    """Runs the ERPNext tools."""

    def __init__(self, bound_tools: dict[str, Callable[..., str]] | None = None) -> None:
        self._bound = dict(bound_tools or _BOUND_TOOLS)

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
        handler = self._resolve(spec.name)

        self._assert_site(spec, context)
        self._assert_actor(spec, context)

        raw = self._invoke(spec, handler, arguments)
        result = self._interpret(spec, raw)
        return self._explain_missing_doctype(result)

    # -- internals --------------------------------------------------------

    def _resolve(self, name: str) -> Callable[..., str]:
        handler = self._bound.get(name)
        if handler is None:
            raise ToolNotBound(f"No tool is bound to '{name}'.")
        return handler

    def _assert_site(self, spec: ToolSpec, context: ToolContext) -> None:
        """Refuse to run a tool against the wrong site.

        This is the check that stands between a mistyped site name and a
        write to somebody else's database.  It is cheap, it runs before every
        call, and it fails closed.
        """
        expected = (context.site or "").strip()
        if not expected:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': no site was resolved for this call."
            )

        actual = str(getattr(frappe.local, "site", "") or "").strip()
        if actual != expected:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': this request is bound to site "
                f"'{actual or '(none)'}', not '{expected}'."
            )

    def _assert_actor(self, spec: ToolSpec, context: ToolContext) -> None:
        """Make sure the tool runs as the person who asked.

        The framework applies the session user's roles and User Permissions
        to every read and write, so this is what makes an assistant unable
        to see what its caller cannot see.
        """
        user = (context.principal.user or "").strip()
        if not user:
            raise RuntimeError(
                f"Refusing to run '{spec.name}': no user was resolved for this call."
            )

        current = str(getattr(frappe.session, "user", "") or "").strip()
        if current != user:
            # The request's own session is the right one; set it rather than
            # run the tool as somebody else.
            frappe.set_user(user)

    def _invoke(
        self,
        spec: ToolSpec,
        handler: Callable[..., str],
        arguments: dict[str, Any],
    ) -> str:
        """Call the tool, turning anything it raises into an envelope."""
        try:
            return handler(**arguments)
        except Exception as exc:  # noqa: BLE001 - a tool must not kill the turn
            logger.exception("Tool '%s' raised", spec.name)
            return erpnext.error(f"{type(exc).__name__}: {exc}")

    def _interpret(self, spec: ToolSpec, raw: Any) -> ToolResult:
        """Turn the tool's JSON into a :class:`ToolResult`.

        The envelope carries a ``status`` on the shapes that use one, and
        the shapes that do not — a report's rows, a doctype's fields — are
        returned as raw JSON.  Both are accepted, and a response that is not
        JSON at all is treated as text.
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
            succeeded = status in ("ok", "skipped", "accepted")

            parts = [message] if message else []
            if hints:
                parts.append("Hints: " + "; ".join(str(hint) for hint in hints))
            content = "\n".join(part for part in parts if part) or status
            if data is not None:
                content = f"{content}\n{compact_json(data)}"

            if succeeded:
                return ToolResult.success(
                    truncate_result(content, spec.max_result_chars),
                    data,
                    summary=message or status,
                )
            return ToolResult(
                ok=False,
                content=truncate_result(content, spec.max_result_chars),
                error=message or status,
                data=data,
                # A refusal is not a failure.  It says the *account* may not
                # do this, which is a fact about the organisation rather than
                # a broken tool — and the panel draws the two differently,
                # which it can only do when the tool says which one it is.
                denied=bool(payload.get("denied")),
                summary=message or status,
            )

        content = raw if payload is None else compact_json(payload)
        return ToolResult.success(
            truncate_result(content, spec.max_result_chars),
            payload,
            summary=_summarise(payload),
        )

    def _explain_missing_doctype(self, result: ToolResult) -> ToolResult:
        """When a DocType's name is wrong, name the ones that exist.

        The model asks for "Sales Taxes and Templates" and the site has
        "Sales Taxes and Charges Template".  A bare "not found" is a dead
        end: the model has no way to learn the right name, so it guesses
        again, and again, and each guess is another step.

        So the near-misses are looked up here and returned with the error.
        The tool set does not grow — the answer to "that does not exist"
        simply becomes an answer instead of a wall.
        """
        if result.ok:
            return result

        message = result.error or ""
        # Frappe's own message is "DocType <name> not found"; the name is
        # sometimes quoted, so both shapes are accepted.
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
                raw = erpnext.list_doctypes(search=word, limit=200)
            except Exception:
                continue
            for name in self._names_from(raw):
                found[name] = found.get(name, 0) + 1

        def score(item: tuple[str, int]) -> tuple[int, int, str]:
            name, shared = item
            lowered = name.lower()
            bonus = sum(1 for word in words if word in lowered or word.rstrip("s") in lowered)
            closeness = len(set(lowered.split()) & set(words))
            return (-shared - bonus, -closeness, name)

        ranked = sorted(found.items(), key=score)
        return [name for name, _ in ranked[:limit]]

    @staticmethod
    def _names_from(raw: str) -> list[str]:
        """The DocType names in a ``list_doctypes`` envelope."""
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
