"""The manifest and the adapter must agree.

The manifest (``albanna.core.tools``) is the contract the model sees; the
adapter (``albanna.tools.erpnext_mcp``) is the code that runs.  They live
in different packages on purpose — the manifest may not import Frappe, and
the adapter must — and the cost of that split is that they can drift.

A tool the manifest describes but the adapter cannot run is a tool the model
is told about and then cannot use.  A tool the adapter can run but the
manifest never described is a tool that is reachable but invisible.  Both
are bugs, and both are caught here.
"""

from __future__ import annotations

import inspect

import pytest

from albanna.core.tools import TOOL_MANIFEST, validate_arguments
from albanna.tools.erpnext_mcp import _BOUND_TOOLS, ErpnextMcpBackend


def test_the_manifest_and_the_adapter_name_the_same_tools():
    adapter_names = set(ErpnextMcpBackend().bound_names)
    manifest_names = set(TOOL_MANIFEST.names())
    assert manifest_names == adapter_names


def test_every_bound_tool_resolves_to_a_function():
    erpnext_mcp = pytest.importorskip("erpnext_mcp")
    assert erpnext_mcp is not None

    for name, (target, _translator) in _BOUND_TOOLS.items():
        module_name, _, attribute = target.partition(":")
        module = __import__(module_name, fromlist=[attribute])
        handler = getattr(module, attribute)
        assert callable(handler), f"{name} does not resolve to a callable"
        assert inspect.isfunction(handler) or callable(handler)


def test_the_translators_produce_arguments_the_backend_accepts():
    pytest.importorskip("erpnext_mcp")

    from albanna.tools.erpnext_mcp import _translate_create_doc, _translate_list_docs

    translated = _translate_list_docs(
        {"doctype": "Item", "filters": [["item_group", "=", "X"]], "limit": 5, "offset": 10}
    )
    assert translated["doctype"] == "Item"
    assert translated["filters_json"] == '[["item_group", "=", "X"]]'
    assert translated["limit_page_length"] == 5
    assert translated["limit_start"] == 10

    translated = _translate_create_doc({"doctype": "Item", "data": {"item_code": "X"}})
    assert translated["data_json"] == '{"item_code": "X"}'
    assert translated["submit"] is False


def test_the_backend_signatures_accept_what_the_translators_produce():
    """The translated argument names must be real parameters of the backend function."""
    pytest.importorskip("erpnext_mcp")

    from albanna.tools.erpnext_mcp import (
        _translate_get_doc,
        _translate_get_doctype_meta,
        _translate_list_docs,
        _translate_run_report,
    )

    cases = {
        "list_docs": _translate_list_docs,
        "get_doc": _translate_get_doc,
        "get_doctype_meta": _translate_get_doctype_meta,
        "run_report": _translate_run_report,
    }

    for name, translator in cases.items():
        target, _ = _BOUND_TOOLS[name]
        module_name, _, attribute = target.partition(":")
        module = __import__(module_name, fromlist=[attribute])
        handler = getattr(module, attribute)
        parameters = set(inspect.signature(handler).parameters)

        translated = translator({"doctype": "X", "name": "Y", "report": "Z", "filters": {}})
        unknown = set(translated) - parameters
        assert not unknown, f"{name} would be called with unknown arguments: {sorted(unknown)}"


def test_the_manifest_schemas_reject_a_missing_required_argument():
    error = validate_arguments(TOOL_MANIFEST.get("get_doc"), {"doctype": "Item"})
    assert error is not None
    assert "name" in error


def test_the_manifest_schemas_accept_a_good_argument_set():
    assert validate_arguments(TOOL_MANIFEST.get("get_doc"), {"doctype": "Item", "name": "X"}) is None
    assert validate_arguments(TOOL_MANIFEST.get("list_docs"), {"doctype": "Item"}) is None
    assert (
        validate_arguments(
            TOOL_MANIFEST.get("create_doc"),
            {"doctype": "Item", "data": {"item_code": "X"}},
        )
        is None
    )


def test_the_manifest_schemas_reject_an_unknown_argument():
    error = validate_arguments(
        TOOL_MANIFEST.get("list_docs"),
        {"doctype": "Item", "nonsense": True},
    )
    assert error is not None


def test_the_manifest_schemas_reject_a_wrong_type():
    error = validate_arguments(TOOL_MANIFEST.get("list_docs"), {"doctype": 42})
    assert error is not None


def test_the_wire_form_of_a_tool_is_an_openai_function():
    wire = TOOL_MANIFEST.get("list_docs").to_wire()
    assert wire["type"] == "function"
    assert wire["function"]["name"] == "list_docs"
    assert wire["function"]["description"]
    assert wire["function"]["parameters"]["additionalProperties"] is False


def test_every_tool_is_classified():
    for spec in TOOL_MANIFEST.all():
        assert spec.tier in ("read", "write")
        assert spec.description.strip()
        assert spec.parameters.get("type") == "object"
        assert spec.parameters.get("properties") is not None


def test_exactly_one_tool_writes():
    writers = [spec.name for spec in TOOL_MANIFEST.all() if spec.mutating]
    assert writers == ["create_doc"]
