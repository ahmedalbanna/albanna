"""Tests for the tool registry's switches.

Pure: no Frappe, no site.
"""

from albanna.core.authority import Authority, Principal
from albanna.core.tools import TOOL_MANIFEST


def test_without_mutating_switches_the_write_tool_off():
    registry = TOOL_MANIFEST.without_mutating()
    assert registry.get("create_doc").enabled is False
    # The read tools are untouched.
    for name in ("list_docs", "get_doc", "get_doctype_meta", "run_report"):
        assert registry.get(name).enabled is True


def test_a_write_tool_that_is_off_is_never_visible_to_the_model():
    registry = TOOL_MANIFEST.without_mutating()
    authority = Authority(registry, Principal(user="u@example.com", roles=frozenset()))
    assert "create_doc" not in authority.visible_names()
    assert "list_docs" in authority.visible_names()


def test_a_write_tool_that_is_off_is_refused_when_called_by_name():
    registry = TOOL_MANIFEST.without_mutating()
    authority = Authority(registry, Principal(user="u@example.com", roles=frozenset()))
    decision = authority.authorize("create_doc", {"doctype": "Item", "data": {}})
    assert not decision.allowed


def test_without_mutating_keeps_the_specification_of_what_it_removed():
    registry = TOOL_MANIFEST.without_mutating()
    spec = registry.get("create_doc")
    assert spec is not None
    assert spec.tier == "write"
    assert spec.description


def test_without_disables_only_the_named_tools():
    registry = TOOL_MANIFEST.without(["run_report"])
    assert "run_report" in registry.names()
    assert registry.get("run_report").enabled is False
    assert registry.get("list_docs").enabled is True


def test_the_original_registry_is_not_mutated():
    before = TOOL_MANIFEST.names()
    TOOL_MANIFEST.without_mutating()
    TOOL_MANIFEST.without(["list_docs"])
    assert TOOL_MANIFEST.names() == before
    assert all(spec.enabled for spec in TOOL_MANIFEST.all())
