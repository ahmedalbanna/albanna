"""The write tools are all permission-gated.

Mirrors ``test_read_guard.py``: it walks the write tools by name from the
manifest, so a write tool added next year is covered the day it is
registered.  For each one, a caller who lacks the right for that action
gets a refusal and not a write.

The denied cases are built by factories rather than static arguments,
because a lifecycle tool needs a document in a particular state and a
static name rots the day the site's data changes.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import current_principal
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

ACCOUNTS_USER = "albanna.test.writeguard.accounts@albanna.dev"
STOCK_USER = "albanna.test.writeguard.stock@albanna.dev"


@pytest.mark.integration
class TestWriteToolsAreGated(AlbannaTestCase):
    """Every write tool refuses a caller who lacks the right for it."""

    def setUp(self):
        super().setUp()
        self.accounts_user = self._make_user(ACCOUNTS_USER, "Accounts User")
        self.stock_user = self._make_user(STOCK_USER, "Stock User")
        self.backend = ErpnextBackend()

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "WriteGuard"
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

    def _draft_invoice(self) -> str:
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 0}, "name")
        if name:
            return name
        company = frappe.get_all("Company", pluck="name", limit=1)[0]
        currency = frappe.db.get_value("Company", company, "default_currency")
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.currency = currency
        invoice.customer = customer
        invoice.append("items", {"item_code": item, "qty": 1, "rate": 10})
        invoice.flags.ignore_permissions = True
        invoice.insert()
        return invoice.name

    def _submitted_invoice(self) -> str:
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
        if name:
            return name
        draft = self._draft_invoice()
        doc = frappe.get_doc("Sales Invoice", draft)
        doc.flags.ignore_permissions = True
        doc.submit()
        return doc.name

    #: Factories: each returns (user, arguments) for a case the user may
    #: not perform.  A factory, not a static dict, because the document
    #: names come from the site.
    def _factory_create_doc(self):
        return self.stock_user, {"doctype": "Sales Invoice", "data": {"remarks": "x"}}

    def _factory_update_doc(self):
        return self.stock_user, {
            "doctype": "Sales Invoice",
            "name": self._draft_invoice(),
            "data": {"remarks": "x"},
        }

    def _factory_bulk_update_doc(self):
        return self.stock_user, {
            "doctype": "Sales Invoice",
            "filters": [["docstatus", "=", 0]],
            "data": {"remarks": "x"},
        }

    def _factory_submit_doc(self):
        return self.stock_user, {"doctype": "Sales Order", "name": self._draft_sales_order()}

    def _factory_cancel_doc(self):
        return self.accounts_user, {"doctype": "Sales Invoice", "name": self._submitted_invoice()}

    def _factory_amend_doc(self):
        return self.stock_user, {"doctype": "Sales Order", "name": self._submitted_sales_order()}

    def _factory_delete_doc(self):
        return self.accounts_user, {"doctype": "Sales Invoice", "name": self._draft_invoice()}

    def _draft_sales_order(self) -> str:
        name = frappe.db.get_value("Sales Order", {"docstatus": 0}, "name")
        if name:
            return name
        company = frappe.get_all("Company", pluck="name", limit=1)[0]
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")
        order = frappe.new_doc("Sales Order")
        order.company = company
        order.customer = customer
        order.delivery_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
        order.append("items", {"item_code": item, "qty": 1, "rate": 10})
        order.flags.ignore_permissions = True
        order.insert()
        return order.name

    def _submitted_sales_order(self) -> str:
        name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
        if name:
            return name
        draft = self._draft_sales_order()
        doc = frappe.get_doc("Sales Order", draft)
        doc.flags.ignore_permissions = True
        doc.submit()
        return doc.name

    def test_every_write_tool_refuses_a_caller_who_lacks_the_right(self):
        write_tools = [spec.name for spec in TOOL_MANIFEST.all() if spec.tier == "write"]

        factories = {
            "create_doc": self._factory_create_doc,
            "update_doc": self._factory_update_doc,
            "bulk_update_doc": self._factory_bulk_update_doc,
            "submit_doc": self._factory_submit_doc,
            "cancel_doc": self._factory_cancel_doc,
            "amend_doc": self._factory_amend_doc,
            "delete_doc": self._factory_delete_doc,
        }

        missing = [name for name in write_tools if name not in factories]
        self.assertFalse(missing, "no denied case for write tool(s): " + ", ".join(missing))

        for name in write_tools:
            user, arguments = factories[name]()
            context = self._context(user)
            result = self.backend.call(TOOL_MANIFEST.get(name), arguments, context)
            data = result.data if isinstance(result.data, dict) else {}
            wrote = False
            if name == "bulk_update_doc":
                wrote = bool(result.ok) and int(data.get("changed") or 0) > 0
            else:
                wrote = bool(result.ok)
            self.assertFalse(
                wrote,
                f"{name} wrote for a caller who lacks the right: {result.content}",
            )
