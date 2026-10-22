"""The authority layer.

This is the module that replaces the role gate the backend used to have at
its edge, so its cases are the security cases of the whole app.  They are
written as negatives on purpose: a test that only proves the happy path
proves very little about a gate.
"""

from __future__ import annotations

import pytest

from albanna.core.authority import Authority, Principal
from albanna.core.tools import CREATE_DOC, GET_DOC, LIST_DOCS, TOOL_MANIFEST, ToolRegistry


class Checker:
    """A permission checker that answers from a fixed table."""

    def __init__(
        self,
        creatable: set[str] | None = None,
        writable: set[str] | None = None,
        raises: bool = False,
    ):
        self.creatable = creatable or set()
        self.writable = writable or set()
        self.raises = raises

    def can_create(self, doctype: str) -> bool:
        if self.raises:
            raise RuntimeError("the permission engine is on fire")
        return doctype in self.creatable

    def can_write(self, doctype: str) -> bool:
        if self.raises:
            raise RuntimeError("the permission engine is on fire")
        return doctype in self.writable

    def can_read(self, doctype: str) -> bool:
        if self.raises:
            raise RuntimeError("the permission engine is on fire")
        return True

    def roles_for(self, doctype: str, ptype: str) -> list[str]:
        if self.raises:
            raise RuntimeError("the permission engine is on fire")
        if ptype == "create":
            return ["Accounts User", "Accounts Manager"]
        return ["Accounts User"]


def principal(*roles: str, system_manager: bool = False) -> Principal:
    return Principal(user="u@example.com", roles=frozenset(roles), is_system_manager=system_manager)


def test_a_tool_nobody_knows_is_refused():
    authority = Authority(TOOL_MANIFEST, principal(), Checker())
    decision = authority.authorize("delete_everything", {})
    assert not decision.allowed
    assert decision.code == "unknown_tool"


def test_a_disabled_tool_is_refused_and_never_offered():
    registry = TOOL_MANIFEST.without(["get_doc"])
    authority = Authority(registry, principal(), Checker())

    assert "get_doc" not in authority.visible_names()
    decision = authority.authorize("get_doc", {"doctype": "Item", "name": "X"})
    assert not decision.allowed
    assert decision.code == "tool_disabled"


def test_a_tool_needing_a_role_the_user_lacks_is_refused():
    registry = ToolRegistry([GET_DOC])
    # A read tool with a role requirement.
    from dataclasses import replace

    guarded = replace(GET_DOC, required_roles=("Sales Manager",))
    registry = ToolRegistry([guarded])

    authority = Authority(registry, principal("Sales User"), Checker())
    assert authority.visible() == []
    decision = authority.authorize("get_doc", {"doctype": "Item", "name": "X"})
    assert not decision.allowed
    assert decision.code == "missing_role"

    # A System Manager reaches it regardless.
    manager = Authority(registry, principal(system_manager=True), Checker())
    assert len(manager.visible()) == 1
    assert manager.authorize("get_doc", {"doctype": "Item", "name": "X"}).allowed


def test_a_write_tool_without_a_target_doctype_is_refused():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(creatable={"Item"}))
    decision = authority.authorize("create_doc", {"data": {}})
    assert not decision.allowed
    assert decision.code == "missing_doctype"


def test_a_write_tool_is_refused_when_the_user_may_not_create_the_doctype():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(creatable={"Item"}))
    decision = authority.authorize("create_doc", {"doctype": "Sales Invoice", "data": {}})
    assert not decision.allowed
    assert decision.code == "not_permitted"


def test_a_write_tool_is_allowed_when_the_user_may_create_the_doctype():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(creatable={"Item"}))
    decision = authority.authorize("create_doc", {"doctype": "Item", "data": {"item_code": "X"}})
    assert decision.allowed


def test_an_update_is_refused_when_the_user_may_not_write_the_doctype():
    """Changing a document is checked against the *write* permission.

    Not the create permission: a role model that grants one does not
    necessarily grant the other, and asking the wrong question is how a
    write path ends up more permissive than it was meant to be.
    """
    authority = Authority(
        TOOL_MANIFEST,
        principal(),
        Checker(creatable={"Sales Invoice"}, writable=set()),
    )
    decision = authority.authorize(
        "update_doc",
        {"doctype": "Sales Invoice", "name": "ACC-SINV-0001", "data": {"remarks": "x"}},
    )
    assert not decision.allowed
    assert decision.code == "not_permitted"


def test_an_update_is_allowed_when_the_user_may_write_the_doctype():
    authority = Authority(
        TOOL_MANIFEST,
        principal(),
        Checker(creatable=set(), writable={"Customer"}),
    )
    decision = authority.authorize(
        "update_doc",
        {"doctype": "Customer", "name": "CUST-0001", "data": {"customer_name": "x"}},
    )
    assert decision.allowed


def test_the_refusal_for_an_update_asks_for_an_edit_and_not_a_creation():
    """The refusal names the right the caller does not hold.

    "Creating a 'Customer' is done by these roles" would be the wrong
    sentence entirely when the assistant was asked to *change* one.
    """
    authority = Authority(
        TOOL_MANIFEST,
        principal(),
        Checker(creatable={"Customer"}, writable=set()),
    )
    decision = authority.authorize(
        "update_doc",
        {"doctype": "Customer", "name": "CUST-0001", "data": {"customer_name": "x"}},
    )
    assert not decision.allowed
    assert "Editing a 'Customer'" in decision.reason
    assert "create" not in decision.reason.lower()


def test_a_broken_permission_checker_denies_rather_than_allows():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(raises=True))
    decision = authority.authorize("create_doc", {"doctype": "Item", "data": {}})
    assert not decision.allowed
    assert decision.code == "permission_check_failed"


def test_a_broken_permission_checker_denies_an_update_rather_than_allows():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(raises=True))
    decision = authority.authorize(
        "update_doc",
        {"doctype": "Item", "name": "X", "data": {"description": "x"}},
    )
    assert not decision.allowed
    assert decision.code == "permission_check_failed"


def test_without_a_checker_a_write_tool_is_refused():
    authority = Authority(TOOL_MANIFEST, principal(), None)
    decision = authority.authorize("create_doc", {"doctype": "Item", "data": {}})
    assert not decision.allowed
    assert decision.code == "no_permission_checker"


def test_without_a_checker_an_update_is_refused():
    authority = Authority(TOOL_MANIFEST, principal(), None)
    decision = authority.authorize(
        "update_doc",
        {"doctype": "Item", "name": "X", "data": {"description": "x"}},
    )
    assert not decision.allowed
    assert decision.code == "no_permission_checker"


def test_read_tools_are_not_gated_on_a_doctype_permission():
    authority = Authority(TOOL_MANIFEST, principal(), Checker(creatable=set()))
    assert authority.authorize("list_docs", {"doctype": "Item"}).allowed
    assert authority.authorize("get_doc", {"doctype": "Item", "name": "X"}).allowed


def test_the_visible_list_is_what_the_model_is_told_about():
    authority = Authority(TOOL_MANIFEST.without(["run_report"]), principal(), Checker())
    names = authority.visible_names()
    assert "list_docs" in names
    assert "run_report" not in names
    assert len(names) == len(TOOL_MANIFEST) - 1


def test_the_registry_keeps_its_order():
    assert TOOL_MANIFEST.names()[0] == "list_docs"
    assert TOOL_MANIFEST.get("create_doc") is CREATE_DOC
    assert TOOL_MANIFEST.get("list_docs") is LIST_DOCS
    assert TOOL_MANIFEST.get("nope") is None
