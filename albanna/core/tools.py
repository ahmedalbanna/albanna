"""The tool manifest: what the model is allowed to see, and what it may do.

This module is *data*, not code.  It answers four questions for every tool
the side chat can reach:

  what is it called        (``name``)
  what does it do          (``description`` — the only thing the model reads
                           before deciding to call it, so it is written for a
                           model, not for a developer)
  what arguments does it take (``parameters`` — a JSON Schema, validated
                           before the call ever reaches Frappe)
  what does calling it cost (``tier`` — read or write; what may invoke it
                           (``required_roles``); which argument names the
                           target DocType, when the permission of the call
                           depends on a document the arguments choose
                           (``doctype_arg``))

Why the manifest lives here and the implementations live elsewhere
-----------------------------------------------------------------
``core/`` may not import Frappe, and it may not import the
implementations.  So the functions that actually read and write documents
sit behind the :mod:`albanna.tools` port, and only the contract the model
sees lives here.

The cost of that split is that the two halves could drift: a manifest that
promises a tool the adapter cannot call, or an adapter that can call a tool
the manifest never described.  ``tests/test_tool_manifest.py`` closes that
gap by asserting the two sets are equal in both directions, so the drift
fails the suite instead of reaching a user.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

#: Capability tiers.  A tier is a statement about *what a call does*, never
#: about *who may make it* — the second question belongs to
#: :mod:`albanna.core.authority`.
READ = "read"
WRITE = "write"

#: The longest tool result handed back to the model, in characters.
#:
#: A tool that returns a 200 KB document set does not become a better answer;
#: it becomes a turn that exhausts the context window before the model has
#: formed a question.  The result is truncated with a marker that says so,
#: because a silently shortened answer reads as a complete one.
MAX_RESULT_CHARS = 8000


@dataclass(frozen=True)
class ToolSpec:
    """One tool, as the model and the authority layer both see it."""

    name: str
    description: str
    parameters: dict[str, Any]
    tier: str = READ
    required_roles: tuple[str, ...] = ()
    doctype_arg: str = ""
    max_result_chars: int = MAX_RESULT_CHARS
    enabled: bool = True

    @property
    def mutating(self) -> bool:
        """True when a call can change the site."""
        return self.tier == WRITE

    def to_wire(self) -> dict[str, Any]:
        """The OpenAI-shaped function declaration.

        The schema already forbids unknown arguments — that is what
        ``additionalProperties: false`` in the manifest means, and it is
        enforced by :func:`validate_arguments` before a call is ever made.
        An unexpected argument is a sign the model has misread the contract,
        and rejecting it here costs one round trip while passing it through
        costs a confusing tool error.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """An ordered, name-addressable collection of tool specifications."""

    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self._specs[spec.name] = spec

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def names(self) -> tuple[str, ...]:
        """Every known tool name, in manifest order."""
        return tuple(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def all(self) -> list[ToolSpec]:
        """Every known tool, in manifest order."""
        return list(self._specs.values())

    def enabled(self) -> list[ToolSpec]:
        """The tools that are switched on."""
        return [spec for spec in self._specs.values() if spec.enabled]

    def without(self, names: Iterable[str]) -> ToolRegistry:
        """A copy with the named tools switched off.

        Used when the operator disables a tool in the settings; the registry
        the model is shown is the result, so a disabled tool is not merely
        refused at call time — it is never mentioned.
        """
        disabled = set(names)
        return self._build({spec.name: spec.enabled and spec.name not in disabled for spec in self._specs.values()})

    def without_mutating(self) -> ToolRegistry:
        """A copy with every write tool switched off.

        The site's write switch works this way rather than by refusing a
        call: a write tool that is off is not in the *visible* set, so the
        model is never told it exists, and a call to it by name is refused.
        One filter, one truth.
        """
        return self._build({spec.name: not spec.mutating for spec in self._specs.values()})

    def _build(self, enabled: dict[str, bool]) -> ToolRegistry:
        """A copy of this registry with the given tools switched on or off."""
        return ToolRegistry(
            ToolSpec(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
                tier=spec.tier,
                required_roles=spec.required_roles,
                doctype_arg=spec.doctype_arg,
                max_result_chars=spec.max_result_chars,
                enabled=enabled.get(spec.name, spec.enabled),
            )
            for spec in self._specs.values()
        )


# --------------------------------------------------------------------------
# The manifest.
#
# The five tools are the whole surface.  They were chosen to cover the three
# questions a side chat actually gets asked — *what do I have*, *what is this
# one*, and *what does the numbers say* — plus one write, so the write path
# exists and is exercised from the first release.
#
# Deliberately absent:
#
#   ``run_sql_query``
#       It bypasses Frappe's permission engine completely, including User
#       Permissions and every row-level rule built on them.  A side chat is
#       reachable by ordinary users, so a raw SELECT is a privilege
#       escalation with a chat interface on top.  If it is ever added it must
#       be System Manager only, and it must not be part of this set.
#
#   ``find_tools``
#       It exists to let a model discover the tool set at runtime.  This app
#       *has* a fixed tool set of five, and a discovery tool inside a fixed
#       set is a way to spend a turn saying what is already known.
#
#   ``run_flow``
#       A flow is several tool calls with a transaction of its own.  It is a
#       good tool and the wrong first one: its failure modes belong to a
#       later release, once the single-step write path has proven itself.
# --------------------------------------------------------------------------

LIST_DOCS = ToolSpec(
    name="list_docs",
    description=(
        "Find documents of one DocType. Use this to answer 'what do I have' "
        "questions: which Sales Orders are open, which Items are low on "
        "stock, which Customers have a balance. Returns a compact list of "
        "matching documents. Always fetch the DocType schema with "
        "get_doctype_meta first if you are not certain which fields exist."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doctype": {
                "type": "string",
                "description": (
                    "The DocType to search, e.g. 'Sales Order', 'Item', "
                    "'Customer', 'Sales Invoice'."
                ),
            },
            "filters": {
                "type": "array",
                "description": (
                    "Filter conditions, each one exactly three strings: "
                    "[fieldname, operator, value]. "
                    "Operators: =, !=, >, <, >=, <=, like, not like, in, not in, "
                    "is, between. The value is always a plain string — for a "
                    "date use YYYY-MM-DD, for a number use digits, and for "
                    "'in' or 'not in' write one condition per value rather "
                    "than a list. A condition with a list or an object as its "
                    "value is rejected. Omit to list everything."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "fields": {
                "type": "array",
                "description": (
                    "Fieldnames of that DocType to return — the exact "
                    "fieldnames, not labels. Omit to get the DocType's "
                    "default title fields, which are usually enough to "
                    "identify a document."
                ),
                "items": {"type": "string"},
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "How many documents to return (default 20).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "How many documents to skip, for paging.",
            },
            "order_by": {
                "type": "string",
                "description": (
                    "Sort order, e.g. 'modified desc' or 'creation asc'."
                ),
            },
        },
        "required": ["doctype"],
    },
    tier=READ,
)

GET_DOC = ToolSpec(
    name="get_doc",
    description=(
        "Fetch one document by its DocType and name. Use this to read the "
        "detail behind a name you got from list_docs or from the page the "
        "user is looking at. Name the fields you need to keep the answer "
        "short — a full document can be very large."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doctype": {
                "type": "string",
                "description": "The DocType of the document, e.g. 'Sales Order'.",
            },
            "name": {
                "type": "string",
                "description": "The document's name, e.g. 'SAL-ORD-00042'.",
            },
            "fields": {
                "type": "array",
                "description": (
                    "Fieldnames of that DocType to return — the exact "
                    "fieldnames, not labels. Omit for the whole document, "
                    "including its child tables."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["doctype", "name"],
    },
    tier=READ,
)

GET_DOCTYPE_META = ToolSpec(
    name="get_doctype_meta",
    description=(
        "Get the field definitions of a DocType — fieldname, type, label, "
        "whether it is mandatory, and its options. Call this before you "
        "filter on or write to a field you are not certain about, so you use "
        "the real fieldname rather than a plausible guess."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doctype": {
                "type": "string",
                "description": "The DocType to describe, e.g. 'Sales Invoice'.",
            },
            "fields": {
                "type": "array",
                "description": (
                    "Fieldnames to describe. Omit to get every field."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["doctype"],
    },
    tier=READ,
)

RUN_REPORT = ToolSpec(
    name="run_report",
    description=(
        "Run an ERPNext report and return its rows. Use this for questions "
        "about totals and trends — receivables, stock balance, sales "
        "register — rather than reading documents one by one. Some reports "
        "require filters; if a filter is missing the tool says which one, "
        "and you should call it again with that filter added."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "report": {
                "type": "string",
                "description": (
                    "The report's name, exactly as ERPNext knows it — e.g. "
                    "'Accounts Receivable', 'General Ledger', 'Stock Balance', "
                    "'Sales Register'."
                ),
            },
            "filters": {
                "type": "object",
                "description": (
                    "Filter values for the report, as an object. Common keys: "
                    "company, from_date, to_date, fiscal_year, cost_center, "
                    "item_code, customer. A missing mandatory filter is "
                    "reported back with the key to add."
                ),
                "additionalProperties": True,
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5000,
                "description": "How many rows to return (default 1000).",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "How many rows to skip, for paging.",
            },
        },
        "required": ["report"],
    },
    tier=READ,
)

CREATE_DOC = ToolSpec(
    name="create_doc",
    description=(
        "Create a document. Use this only when the user has asked for the "
        "document to be created — never to test that something works, and "
        "never on a guess. If a required field is missing, ask the user "
        "for it rather than inventing a value. Some DocTypes can be "
        "submitted in the same call by passing submit."
    ),
    parameters={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "doctype": {
                "type": "string",
                "description": (
                    "The DocType to create, e.g. 'Customer', 'Item', "
                    "'Sales Order'."
                ),
            },
            "data": {
                "type": "object",
                "description": (
                    "The document's field values, as an object. Use the "
                    "fieldnames from get_doctype_meta. Child tables are "
                    "given as arrays of objects."
                ),
                "additionalProperties": True,
            },
            "submit": {
                "type": "boolean",
                "description": (
                    "Submit the document immediately after creating it. Only "
                    "for submittable DocTypes, and only when the user asked "
                    "for a submitted document."
                ),
            },
        },
        "required": ["doctype", "data"],
    },
    tier=WRITE,
    doctype_arg="doctype",
)

#: Every tool the app knows about.
TOOL_MANIFEST = ToolRegistry([LIST_DOCS, GET_DOC, GET_DOCTYPE_META, RUN_REPORT, CREATE_DOC])


def truncate_result(text: str, max_chars: int = MAX_RESULT_CHARS) -> str:
    """Shorten an over-long tool result, and say that it was shortened.

    The marker matters: a truncated answer that does not announce itself is
    indistinguishable from a complete one, and the model will answer as if
    it had seen everything.
    """
    if len(text) <= max_chars:
        return text
    dropped = len(text) - max_chars
    return (
        f"{text[:max_chars]}\n\n"
        f"[truncated: {dropped} more characters. "
        f"Narrow the request — fewer fields, a tighter filter, a smaller limit.]"
    )


def compact_json(value: Any) -> str:
    """Serialise a tool result for the model.

    Compact separators, because every character here is paid for twice: once
    in the request and once in the response.
    """
    return json.dumps(value, separators=(",", ":"), default=str)


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
    """Check *arguments* against *spec*'s schema.

    Returns ``None`` when the arguments are acceptable, and a short,
    model-readable sentence when they are not.  The sentence goes back to the
    model as the tool's result, so it has to say what to change rather than
    only that something is wrong.
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a declared dependency
        return None

    validator = jsonschema.Draft202012Validator(spec.parameters)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))
    if not errors:
        return None

    first = errors[0]
    location = ".".join(str(part) for part in first.absolute_path) or "(root)"
    return (
        f"Invalid arguments for '{spec.name}' at '{location}': {first.message}. "
        f"Expected: {json.dumps(spec.parameters.get('properties', {}).get(location, {}), default=str)}"
    )
