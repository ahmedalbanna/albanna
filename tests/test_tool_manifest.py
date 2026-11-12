"""The tool manifest and the tool implementations must agree.

The manifest (``albanna.core.tools``) is the contract the model sees: the
name, the description, and the JSON Schema of the arguments.  The
implementations (``albanna.tools.erpnext``, ``albanna.tools.questions``)
are what actually runs.

They live in different packages on purpose — the manifest may not import
Frappe, and the implementations must — so they could drift.  A manifest that
promises an argument the implementation does not accept is a tool that
fails on every call, and it fails in the middle of a turn, where it costs
the most.

The cost of that split is one test file, and it is here.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from albanna.core.tools import TOOL_MANIFEST, validate_arguments
from albanna.tools.backend import ErpnextBackend

#: Where each tool's implementation lives.  The implementations are split
#: by what they act on: the ERPNext tools act on the site's data, and the
#: question tool acts on the conversation.
IMPLEMENTATION_MODULES = {
    "list_docs": "albanna.tools.erpnext",
    "get_doc": "albanna.tools.erpnext",
    "get_doctype_meta": "albanna.tools.erpnext",
    "read_file": "albanna.tools.files",
    "write_file": "albanna.tools.files",
    "edit_file": "albanna.tools.files",
    "run_report": "albanna.tools.erpnext",
    "create_doc": "albanna.tools.erpnext",
    "update_doc": "albanna.tools.erpnext",
    "bulk_update_doc": "albanna.tools.erpnext",
    "submit_doc": "albanna.tools.erpnext",
    "cancel_doc": "albanna.tools.erpnext",
    "amend_doc": "albanna.tools.erpnext",
    "delete_doc": "albanna.tools.erpnext",
    "ask_question": "albanna.tools.questions",
}

#: The model's arguments and the implementation's parameters are the same
#: contract, so they must have the same names.
IMPLEMENTATIONS = {
    "list_docs": ("albanna.tools.erpnext", "list_docs"),
    "get_doc": ("albanna.tools.erpnext", "get_doc"),
    "get_doctype_meta": ("albanna.tools.erpnext", "get_doctype_meta"),
    "read_file": ("albanna.tools.files", "read_file"),
    "write_file": ("albanna.tools.files", "write_file"),
    "edit_file": ("albanna.tools.files", "edit_file"),
    "run_report": ("albanna.tools.erpnext", "run_report"),
    "create_doc": ("albanna.tools.erpnext", "create_doc"),
    "update_doc": ("albanna.tools.erpnext", "update_doc"),
    "ask_question": ("albanna.tools.questions", "ask_question"),
}


def _implementation(name: str):
    """The function that implements a tool."""
    module_name, attribute = IMPLEMENTATIONS[name]
    return getattr(importlib.import_module(module_name), attribute)


def test_the_manifest_and_the_backend_name_the_same_tools():
    backend = ErpnextBackend()
    assert set(TOOL_MANIFEST.names()) == set(backend.bound_names)


def test_every_tool_in_the_manifest_is_implemented():
    for name in TOOL_MANIFEST.names():
        module = importlib.import_module(IMPLEMENTATION_MODULES[name])
        assert hasattr(module, name), f"{name} has no implementation"


def test_the_implementation_accepts_exactly_what_the_schema_declares():
    """The schema's properties and the function's parameters must match.

    This is the drift the split allows: a schema that gains a property the
    function does not accept fails on every call, and a function that
    accepts a parameter the schema does not declare is a parameter the model
    can never fill.
    """
    for name in IMPLEMENTATIONS:
        spec = TOOL_MANIFEST.get(name)
        function = _implementation(name)
        parameters = set(inspect.signature(function).parameters) - {"self"}

        declared = set(spec.parameters.get("properties") or {})
        required = set(spec.parameters.get("required") or [])

        # Everything the schema declares, the function must accept.
        assert declared <= parameters, (
            f"{name}: the schema declares {declared - parameters}, which the function does not accept"
        )

        # Everything the function *requires* must be in the schema, or the
        # model is asked for a document without being told what it needs.
        needed = {
            name_
            for name_, parameter in inspect.signature(function).parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind not in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD)
        }
        assert needed <= declared, (
            f"{name}: the function requires {needed - declared}, which the schema does not declare"
        )
        assert required <= declared

        # And the required ones must be the ones the function cannot do
        # without.
        assert required <= needed, (
            f"{name}: the schema requires {required - needed}, which the function can do without"
        )


def test_the_manifest_schemas_reject_a_missing_required_argument():
    error = validate_arguments(TOOL_MANIFEST.get("get_doc"), {"doctype": "Item"})
    assert error is not None
    assert "name" in error


def test_the_manifest_schemas_accept_a_good_argument_set():
    assert (
        validate_arguments(TOOL_MANIFEST.get("get_doc"), {"doctype": "Item", "name": "X"}) is None
    )
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


def test_the_write_surface_is_the_nine_write_tools():
    """The writes are few, and each one is a thing a person asks for.

    A tool set that could make things and never change them would leave
    the person who mistyped a field with no way to fix it.  A tool set
    that could also submit, cancel, amend or delete would be a different
    kind of application — and now it is, deliberately, because a person
    asks for those things too.  The file writes joined for the same
    reason: a person asks for a file to be made and for a file's text to
    be put right.  What matters is that this list stays short enough to
    read.
    """
    writers = [spec.name for spec in TOOL_MANIFEST.all() if spec.mutating]
    assert writers == [
        "write_file",
        "edit_file",
        "create_doc",
        "update_doc",
        "bulk_update_doc",
        "submit_doc",
        "cancel_doc",
        "amend_doc",
        "delete_doc",
    ]


def test_the_two_writes_are_authorised_against_different_rights():
    """Creating a document and changing one are different permissions.

    A role model that grants the first does not necessarily grant the
    second, so the manifest has to say which right each write is checked
    against — otherwise the authority layer would ask the wrong question.
    """
    assert TOOL_MANIFEST.get("create_doc").write_permission == "create"
    assert TOOL_MANIFEST.get("update_doc").write_permission == "write"
    assert TOOL_MANIFEST.get("bulk_update_doc").write_permission == "write"


def test_the_lifecycle_writes_are_authorised_against_their_own_rights():
    """Each lifecycle write is authorised against its own Frappe right.

    A role model that grants submit does not necessarily grant cancel,
    amend or delete, so the manifest has to name the right each write is
    checked against — otherwise the authority layer would ask the wrong
    question and a refusal would name the wrong missing right.
    """
    assert TOOL_MANIFEST.get("submit_doc").write_permission == "submit"
    assert TOOL_MANIFEST.get("cancel_doc").write_permission == "cancel"
    assert TOOL_MANIFEST.get("amend_doc").write_permission == "amend"
    assert TOOL_MANIFEST.get("delete_doc").write_permission == "delete"


def test_a_read_tool_is_not_a_write():
    for spec in TOOL_MANIFEST.all():
        if spec.tier == "read":
            assert spec.write_permission == "create", (
                f"{spec.name} is a read, so the write permission it carries is never consulted"
            )


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
    spec = TOOL_MANIFEST.get(name)
    function = _implementation(name)
    parameters = inspect.signature(function).parameters

    required = set(spec.parameters.get("required") or [])
    missing = [p for p in required if p not in parameters]
    assert not missing
