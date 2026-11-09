"""Tests for the tool registry's switches.

Pure: no Frappe, no site.
"""

import pytest

from albanna.core.authority import Authority, Principal
from albanna.core.tools import TOOL_MANIFEST

#: Every write tool, and the right it is offered against.
#:
#: The pairing is the whole of FR-7.6: a tool is offered when the caller
#: holds *this* right on at least one DocType, and not otherwise.  It is
#: a dict literal inside ``without_writes_out_of_reach``, and a literal
#: that named the wrong key would switch a tool against the wrong list —
#: the tool would still be offered to somebody, just not the right
#: somebody, and nothing above the registry would notice.
WRITE_TOOLS = {
    "create_doc": "create",
    "update_doc": "write",
    "bulk_update_doc": "write",
    "submit_doc": "submit",
    "cancel_doc": "cancel",
    "amend_doc": "amend",
    "delete_doc": "delete",
}

#: Where each right's list sits in ``without_writes_out_of_reach``'s
#: signature, in order.  The order is the wiring, and it is spelled out
#: here so the tests below name it rather than counting parameters.
RIGHT_ORDER = ("create", "write", "submit", "cancel", "amend", "delete")

#: The tools that are not writes, and must survive every filter below.
READ_TOOLS = ("list_docs", "get_doc", "get_doctype_meta", "run_report", "ask_question")


def _lists(holding: str) -> tuple[frozenset, ...]:
    """The six lists, with only *holding* non-empty."""
    return tuple(
        frozenset({"A DocType"}) if right == holding else frozenset() for right in RIGHT_ORDER
    )


def test_without_writes_out_of_reach_switches_off_a_write_tool_with_no_right():
    registry = TOOL_MANIFEST.without_writes_out_of_reach(set(), set())
    assert registry.get("create_doc").enabled is False
    assert registry.get("update_doc").enabled is False
    # The read tools are untouched.
    for name in ("list_docs", "get_doc", "get_doctype_meta", "run_report"):
        assert registry.get(name).enabled is True


def test_a_write_tool_is_visible_when_the_caller_holds_its_right():
    registry = TOOL_MANIFEST.without_writes_out_of_reach({"Item"}, set())
    assert registry.get("create_doc").enabled is True
    assert registry.get("update_doc").enabled is False

    registry = TOOL_MANIFEST.without_writes_out_of_reach(set(), {"Customer"})
    assert registry.get("create_doc").enabled is False
    assert registry.get("update_doc").enabled is True


def test_a_write_tool_that_is_off_is_never_visible_to_the_model():
    registry = TOOL_MANIFEST.without_writes_out_of_reach(set(), set())
    authority = Authority(registry, Principal(user="u@example.com", roles=frozenset()))
    assert "create_doc" not in authority.visible_names()
    assert "update_doc" not in authority.visible_names()
    assert "list_docs" in authority.visible_names()


def test_a_write_tool_that_is_off_is_refused_when_called_by_name():
    registry = TOOL_MANIFEST.without_writes_out_of_reach(set(), set())
    authority = Authority(registry, Principal(user="u@example.com", roles=frozenset()))
    decision = authority.authorize("create_doc", {"doctype": "Item", "data": {}})
    assert not decision.allowed


def test_without_writes_out_of_reach_keeps_the_specification_of_what_it_removed():
    registry = TOOL_MANIFEST.without_writes_out_of_reach(set(), set())
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
    TOOL_MANIFEST.without_writes_out_of_reach(set(), set())
    TOOL_MANIFEST.without(["list_docs"])
    assert TOOL_MANIFEST.names() == before
    assert all(spec.enabled for spec in TOOL_MANIFEST.all())


# -- FR-7.6: every write tool, not two of them -----------------------------


@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
def test_a_write_tool_is_off_when_its_right_is_held_nowhere(tool):
    """FR-7.6, for all seven write tools rather than two of them.

    The tests above cover ``create_doc`` and ``update_doc``.  The other
    five are switched by the same dict literal, and a mapping that named
    the wrong key would leave a tool offered against a list that has
    nothing to do with it — offered to a caller who holds no such right
    anywhere on the site.
    """
    registry = TOOL_MANIFEST.without_writes_out_of_reach(*_lists(""))

    assert registry.get(tool).enabled is False, (
        f"{tool} was offered to a caller who holds no right anywhere on the site"
    )


@pytest.mark.parametrize("tool", sorted(WRITE_TOOLS))
def test_a_write_tool_is_on_only_when_its_own_right_is_held(tool):
    """The mirror, and the exactness of the mapping.

    Holding one right switches on the tools that right governs and
    nothing else.  A mapping that pointed two tools at the same list
    would pass the test above and fail this one — which is the
    difference between a filter that is merely conservative and one that
    is correct.
    """
    right = WRITE_TOOLS[tool]
    registry = TOOL_MANIFEST.without_writes_out_of_reach(*_lists(right))

    assert registry.get(tool).enabled is True, (
        f"{tool} was not offered to a caller who holds {right} somewhere"
    )
    for other, other_right in WRITE_TOOLS.items():
        if other == tool:
            continue
        assert registry.get(other).enabled is (other_right == right), (
            f"holding only {right} switched {other} "
            f"{'on' if other_right == right else 'off'} when it should have done "
            f"the opposite"
        )


def test_the_read_tools_survive_every_filter():
    """A filter that dropped the read tools would make the assistant
    useless, and it would pass every test above."""
    registry = TOOL_MANIFEST.without_writes_out_of_reach(*_lists(""))

    for name in READ_TOOLS:
        assert registry.get(name).enabled is True, f"{name} was switched off by a write filter"
