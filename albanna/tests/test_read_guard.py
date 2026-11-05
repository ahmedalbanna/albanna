"""The read tools are all permission-gated.

A guard that reads what ships rather than a list somebody maintains: it
walks the read tools by name from the manifest, so a read tool added
next year is covered the day it is registered.  For each one, a caller
who may not read the target gets a refusal or an empty result — never
the data.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import current_principal
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

SALES_USER = "albanna.test.readguard.sales@albanna.dev"


@pytest.mark.integration
class TestReadToolsAreGated(AlbannaTestCase):
    """Every read tool refuses a caller who may not read its target."""

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("User", SALES_USER):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = SALES_USER
                user.first_name = "Albanna"
                user.last_name = "ReadGuard"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", SALES_USER)
        user.flags.ignore_permissions = True
        user.add_roles("Sales User", "Albanna User")
        self.sales_user = SALES_USER
        self.backend = ErpnextBackend()

    def _as(self, email: str):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str) -> ToolContext:
        self._as(email)
        return ToolContext(principal=current_principal(), site=frappe.local.site)

    #: A target each read tool is asked about, that a Sales User may not
    #: read.  Every read tool in the manifest must appear here, so that a
    #: tool added next year breaks this test until its denied case is
    #: written.
    DENIED = {
        "list_docs": {"doctype": "Salary Slip"},
        "get_doc": {"doctype": "Salary Slip", "name": "SAL-SLIP-00001"},
        "get_doctype_meta": {"doctype": "Salary Slip"},
        "run_report": {"report": "Salary Register"},
    }

    def test_every_read_tool_refuses_a_caller_who_may_not_read(self):
        # ``ask_question`` is a read-tier tool but it reads no site data:
        # it asks the reader a question.  It has no target a caller could
        # be refused for, so it is outside this guard's scope.
        read_tools = [
            spec.name
            for spec in TOOL_MANIFEST.all()
            if spec.tier == "read" and spec.name != "ask_question"
        ]

        missing = [name for name in read_tools if name not in self.DENIED]
        self.assertFalse(
            missing,
            "no denied case is written for the read tool(s): " + ", ".join(missing),
        )

        for name in read_tools:
            result = self.backend.call(
                TOOL_MANIFEST.get(name),
                self.DENIED[name],
                self._context(self.sales_user),
            )
            if result.ok:
                data = result.data
                self.assertTrue(
                    data is None or data == [] or data == {},
                    f"{name} returned data to a caller who may not read it: {result.content}",
                )
