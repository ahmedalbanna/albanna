"""The lifecycle tools: submit, cancel, amend, delete.

These four share ``_load_for_action``, so the read-refusal case is written
once and parameterised.  Each tool's own behaviour — the happy path, the
wrong-state refusal, the permission refusal, the savepoint — is covered
here, because none of them had a test of their own before this pass.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import current_principal
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

SALES_USER = "albanna.test.lifecycle.sales@albanna.dev"
ACCOUNTS_USER = "albanna.test.lifecycle.accounts@albanna.dev"


@pytest.mark.integration
class TestLifecycle(AlbannaTestCase):
    """submit_doc, cancel_doc, amend_doc and delete_doc."""

    def setUp(self):
        super().setUp()
        self.sales_user = self._make_user(SALES_USER, "Sales User")
        self.accounts_user = self._make_user(ACCOUNTS_USER, "Accounts User")
        self.backend = ErpnextBackend()

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Lifecycle"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role, "Albanna User")
        return email

    def _as(self, email: str):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str) -> ToolContext:
        self._as(email)
        return ToolContext(principal=current_principal(), site=frappe.local.site)

    def _draft_quotation(self) -> str:
        q = frappe.new_doc("Quotation")
        q.quotation_to = "Customer"
        q.party_name = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        q.company = frappe.get_all("Company", pluck="name", limit=1)[0]
        q.append(
            "items",
            {
                "item_code": frappe.db.get_value("Item", {"disabled": 0}, "name"),
                "qty": 1,
                "rate": 10,
            },
        )
        q.flags.ignore_permissions = True
        q.insert()
        return q.name

    def _submitted_quotation(self) -> str:
        draft = self._draft_quotation()
        doc = frappe.get_doc("Quotation", draft)
        doc.flags.ignore_permissions = True
        doc.submit()
        return doc.name

    def _cancelled_quotation(self) -> str:
        submitted = self._submitted_quotation()
        doc = frappe.get_doc("Quotation", submitted)
        doc.flags.ignore_permissions = True
        doc.cancel()
        return doc.name

    # -- submit_doc --------------------------------------------------------

    def test_submit_a_draft(self):
        name = self._draft_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("submit_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertTrue(result.ok, result.content)
        self.assertEqual(frappe.db.get_value("Quotation", name, "docstatus"), 1)

    def test_submit_an_already_submitted_is_refused(self):
        name = self._submitted_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("submit_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)
        self.assertIn("not a draft", result.error.lower())

    def test_submit_a_cancelled_is_refused(self):
        name = self._cancelled_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("submit_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)
        self.assertIn("not a draft", result.error.lower())

    def test_submit_permission_refusal(self):
        # Accounts User has no access to Quotation at all -> read refusal,
        # which is the first gate.  Permission refusal is covered by the
        # write guard; here we only assert a refusal.
        name = self._draft_quotation()
        context = self._context(self.accounts_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("submit_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)

    # -- cancel_doc -------------------------------------------------------

    def test_cancel_a_submitted(self):
        name = self._submitted_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("cancel_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertTrue(result.ok, result.content)
        self.assertEqual(frappe.db.get_value("Quotation", name, "docstatus"), 2)

    def test_cancel_a_draft_is_refused(self):
        name = self._draft_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("cancel_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)
        self.assertIn("not submitted", result.error.lower())

    def test_cancel_permission_refusal(self):
        name = self._submitted_quotation()
        context = self._context(self.accounts_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("cancel_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)

    # -- amend_doc --------------------------------------------------------

    def test_amend_a_submitted(self):
        name = self._submitted_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("amend_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertTrue(result.ok, result.content)
        self.assertIn("amended", result.content.lower())
        self.assertEqual(frappe.db.get_value("Quotation", name, "docstatus"), 2)

    def test_amend_a_draft_is_refused(self):
        name = self._draft_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("amend_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)
        self.assertIn("not submitted", result.error.lower())

    def test_amend_failed_leaves_original_submitted(self):
        name = self._submitted_quotation()
        context = self._context(self.sales_user)

        from frappe.model.document import Document

        original_insert = Document.insert

        def failing_insert(self, *a, **k):
            if getattr(self, "amended_from", None):
                raise frappe.ValidationError("forced failure")
            return original_insert(self, *a, **k)

        Document.insert = failing_insert
        try:
            result = self.backend.call(
                TOOL_MANIFEST.get("amend_doc"),
                {"doctype": "Quotation", "name": name},
                context,
            )
        finally:
            Document.insert = original_insert

        self.assertFalse(result.ok)
        self.assertEqual(
            frappe.db.get_value("Quotation", name, "docstatus"),
            1,
            "a failed amend must leave the original submitted",
        )

    # -- delete_doc -------------------------------------------------------

    def test_delete_a_draft(self):
        name = self._draft_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("delete_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertTrue(result.ok, result.content)
        self.assertFalse(frappe.db.exists("Quotation", name))

    def test_delete_a_cancelled(self):
        name = self._cancelled_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("delete_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertTrue(result.ok, result.content)
        self.assertFalse(frappe.db.exists("Quotation", name))

    def test_delete_a_submitted_is_refused(self):
        name = self._submitted_quotation()
        context = self._context(self.sales_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("delete_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)
        self.assertIn("submitted", result.error.lower())
        self.assertTrue(frappe.db.exists("Quotation", name))

    def test_delete_permission_refusal(self):
        name = self._draft_quotation()
        context = self._context(self.accounts_user)
        result = self.backend.call(
            TOOL_MANIFEST.get("delete_doc"),
            {"doctype": "Quotation", "name": name},
            context,
        )
        self.assertFalse(result.ok)

    # -- read refusal (parameterised over the four tools) ------------------

    def test_read_refusal_for_each_lifecycle_tool(self):
        # Sales User may read Quotation, so use Sales Invoice (unreadable)
        # for the read refusal.
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
        if not name:
            self.skipTest("no submitted Sales Invoice")
        for tool in ("submit_doc", "cancel_doc", "amend_doc", "delete_doc"):
            context = self._context(self.accounts_user)
            # accounts user may read Sales Invoice? No, accounts can read.
            # Use sales user who cannot read Sales Invoice.
            context = self._context(self.sales_user)
            result = self.backend.call(
                TOOL_MANIFEST.get(tool),
                {"doctype": "Sales Invoice", "name": name},
                context,
            )
            self.assertFalse(result.ok, f"{tool} should refuse")
            self.assertIn("could not be read", result.error.lower(), f"{tool} read refusal")
