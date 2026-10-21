"""The tool manifest and the tool implementations must agree.

The manifest (``albanna.core.tools``) is the contract the model sees: the
name, the description, and the JSON Schema of the arguments.  The
implementations (``albanna.tools.erpnext``) are what actually runs.

They live in different packages on purpose — the manifest may not import
Frappe, and the implementations must — so they could drift.  A manifest that
promises an argument the implementation does not accept is a tool that
fails on every call, and it fails in the middle of a turn, where it costs
the most.

The cost of that split is one test file, and it is here.
"""

from __future__ import annotations

import inspect

import pytest

from albanna.core.tools import TOOL_MANIFEST, validate_arguments
from albanna.tools.backend import ErpnextBackend

#: The model's arguments and the implementation's parameters are the same
#: contract, so they must have the same names.
IMPLEMENTATIONS = {
    "list_docs": "list_docs",
    "get_doc": "get_doc",
    "get_doctype_meta": "get_doctype_meta",
    "run_report": "run_report",
    "create_doc": "create_doc",
}


def test_the_manifest_and_the_backend_name_the_same_tools():
    backend = ErpnextBackend()
    assert set(TOOL_MANIFEST.names()) == set(backend.bound_names)


def test_every_tool_in_the_manifest_is_implemented():
    from albanna.tools import erpnext

    for name in TOOL_MANIFEST.names():
        assert hasattr(erpnext, name), f"{name} has no implementation"


def test_the_implementation_accepts_exactly_what_the_schema_declares():
    """The schema's properties and the function's parameters must match.

    This is the drift the split allows: a schema that gains a property the
    function does not accept fails on every call, and a function that
    accepts a parameter the schema does not declare is a parameter the model
    can never fill.
    """
    from albanna.tools import erpnext

    for name, attribute in IMPLEMENTATIONS.items():
        spec = TOOL_MANIFEST.get(name)
        function = getattr(erpnext, attribute)
        parameters = set(inspect.signature(function).parameters) - {"self"}

        declared = set(spec.parameters.get("properties") or {})
        required = set(spec.parameters.get("required") or [])

        # Everything the schema declares, the function must accept.
        assert declared <= parameters, f"{name}: the schema declares {declared - parameters}, which the function does not accept"

        # Everything the function *requires* must be in the schema, or the
        # model is asked for a document without being told what it needs.
        needed = {
            name_
            for name_, parameter in inspect.signature(function).parameters.items()
            if parameter.default is inspect.Parameter.empty and parameter.kind
            not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        }
        assert needed <= declared, f"{name}: the function requires {needed - declared}, which the schema does not declare"
        assert required <= declared

        # And the required ones must be the ones the function cannot do
        # without.
        assert required <= needed, f"{name}: the schema requires {required - needed}, which the function can do without"


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


def test_the_manifest_does_not_import_the_implementations():
    """``core/`` may not import Frappe, and it certainly may not import the
    implementations — that is the boundary the layering exists to hold."""
    import ast
    import pathlib

    import albanna.core as core

    core_path = pathlib.Path(core.__file__).parent
    for path in core_path.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.startswith("frappe"), f"{path.name} imports {name}"
                assert "tools.erpnext" not in name, f"{path.name} imports {name}"


@pytest.mark.parametrize("name", sorted(IMPLEMENTATIONS))
def test_the_implementation_is_callable_with_the_manifests_required_arguments(name):
    """Every tool can be called with only its required arguments.

    A tool that cannot be called with the minimum is a tool the model can
    only use wrongly.
    """
    from albanna.tools import erpnext

    spec = TOOL_MANIFEST.get(name)
    function = getattr(erpnext, IMPLEMENTATIONS[name])
    parameters = inspect.signature(function).parameters

    required = set(spec.parameters.get("required") or [])
    missing = [p for p in required if p not in parameters]
    assert not missing
