"""The moat: the assistant may never see or do more than the person asking.

These tests need a site, and they are excluded from the default ``pytest``
run by the ``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna

What is under test
------------------
The app's stated moat is **governed autonomy with permission parity**.
That is a claim about a seam — between the reader and the assistant — and
a claim about a seam is only worth what the tests on both sides of it
are worth.  So these tests do not ask "does the app work?"  They ask the
one question that matters: *can the assistant reach past the person it is
answering?*

The holes they cover were found by reading the code against that
question, not by using the app:

*   a creation could arrive **submitted** — ``docstatus`` in the data —
    which is a document that is permanent without the submit permission
    and without the hooks a submission runs;
*   a **bulk** change reached past the permission engine to find its
    targets, and skipped the field checks a single change gets, so
    ``owner`` and ``docstatus`` were writable there and nowhere else;
*   a **read** handed the model every field of the document, including
    the ones hidden from the person at a higher permission level;
*   a **lifecycle action** could act on — and report the state of — a
    document the person may not read, because a write permission is not a
    read permission;
*   a **private file** belonging to somebody else could be copied into a
    document and published with it;
*   a **count** in the empty state was the size of the table, and the
    **catalogue** of DocTypes was the whole site's;
*   the **confirmation card** named documents the reader may not read,
    and counted rows they may not see;
*   the **page context** named whatever document the browser asked it to.

Each test names the hole it covers, because a test without a name is a
test nobody reads when it fails.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import current_principal
from albanna.services.conversation_service import ensure_conversation
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

SALES_USER = "albanna.test.parity.sales@albanna.dev"
ACCOUNTS_USER = "albanna.test.parity.accounts@albanna.dev"
OTHER_USER = "albanna.test.parity.other@albanna.dev"


@pytest.mark.integration
class TestPermissionParity(AlbannaTestCase):
    """The assistant may not reach past the person it is answering."""

    def setUp(self):
        super().setUp()
        self.sales_user = self._make_user(SALES_USER, "Sales User")
        self.accounts_user = self._make_user(ACCOUNTS_USER, "Accounts User")
        self.other_user = self._make_user(OTHER_USER, "Sales User")
        self.backend = ErpnextBackend()

    # -- helpers -----------------------------------------------------------

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            # The user is created as the administrator: the session may
            # still be somebody else — a user another test made, and one
            # this transaction has already rolled back — and the
            # framework makes the session's own settings for a new user.
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Parity"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role, "Albanna User")
        return email

    def _as(self, email: str):
        """Act as *email*, the way a request for that user would."""
        frappe.set_user(email)
        frappe.local.session.user = email
        # The role permissions are cached per request; a fresh identity needs
        # a fresh cache or it reads the previous one's.
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str) -> ToolContext:
        self._as(email)
        return ToolContext(principal=current_principal(), site=frappe.local.site)

    def _call(self, name: str, arguments: dict, email: str):
        context = self._context(email)
        return self.backend.call(TOOL_MANIFEST.get(name), arguments, context)

    def _customer(self, name: str) -> str:
        """A customer of this test's own."""
        if not frappe.db.exists("Customer", name):
            group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
            customer = frappe.new_doc("Customer")
            customer.customer_name = name
            customer.customer_type = "Company"
            customer.customer_group = group
            customer.flags.ignore_permissions = True
            customer.insert()
        return name

    def _customer_group(self) -> str:
        group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
        self.assertTrue(group, "the site needs a customer group")
        return group

    def _company(self) -> str:
        company = frappe.db.get_value("Company", {}, "name")
        self.assertTrue(company, "the site needs a company")
        return company

    def _item(self) -> str:
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")
        self.assertTrue(item, "the site needs an item")
        return item

    # -- a creation cannot arrive submitted ---------------------------------

    def test_a_creation_cannot_arrive_submitted(self):
        """``docstatus`` is not the assistant's to set.

        A document created with ``docstatus: 1`` is permanent from the
        start: it skips the submit permission and the hooks a submission
        runs, and the reader approved "create this", not "create this,
        already permanent".
        """
        name = f"Albanna Parity {self._testMethodName}"

        result = self._call(
            "create_doc",
            {
                "doctype": "Customer",
                "data": {
                    "customer_name": name,
                    "customer_type": "Company",
                    "customer_group": self._customer_group(),
                    "docstatus": 1,
                },
            },
            self.accounts_user,
        )

        self.assertFalse(result.ok, result.content)
        self.assertIn("docstatus", result.error or "")
        self.assertFalse(
            frappe.db.exists("Customer", name),
            "the document was created anyway",
        )

    def test_a_creation_cannot_claim_an_owner(self):
        """``owner`` is the framework's field, not the assistant's."""
        name = f"Albanna Parity {self._testMethodName}"

        result = self._call(
            "create_doc",
            {
                "doctype": "Customer",
                "data": {
                    "customer_name": name,
                    "customer_type": "Company",
                    "customer_group": self._customer_group(),
                    "owner": "Administrator",
                },
            },
            self.accounts_user,
        )

        self.assertFalse(result.ok, result.content)
        self.assertFalse(frappe.db.exists("Customer", name))

    # -- a bulk change is a change like any other --------------------------

    def test_a_bulk_change_cannot_set_the_fields_the_framework_owns(self):
        """The bulk path used to skip the checks the single path makes."""
        customer = self._customer(f"Albanna Parity Bulk {self._testMethodName}")

        result = self._call(
            "bulk_update_doc",
            {
                "doctype": "Customer",
                "filters": [["name", "=", customer]],
                "data": {"docstatus": 1},
            },
            self.accounts_user,
        )

        self.assertFalse(result.ok, result.content)
        self.assertIn("docstatus", result.error or "")
        self.assertEqual(frappe.db.get_value("Customer", customer, "docstatus"), 0)

    def test_a_bulk_change_reaches_only_the_documents_the_caller_may_read(self):
        """The targets of a bulk change are documents the caller may read.

        The rows of this app's own conversations are the cleanest case
        there is: the permission hooks already restrict them to their
        owner, so a bulk change that reached past the permission engine
        would change somebody else's conversation.
        """
        # The conversations are created *by* their owners: a row owned by
        # somebody else is exactly the row the permission engine hides,
        # and a test that hid it by accident would prove nothing.
        self._as(self.sales_user)
        mine = ensure_conversation(self.sales_user, "parity|bulk|mine|")
        self._as(self.other_user)
        theirs = ensure_conversation(self.other_user, "parity|bulk|theirs|")

        result = self._call(
            "bulk_update_doc",
            {
                "doctype": "Albanna Conversation",
                "filters": [["name", "like", "%"]],
                "data": {"title": "Bulk title"},
            },
            self.sales_user,
        )

        self.assertTrue(result.ok, result.content)
        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", mine, "title"),
            "Bulk title",
            f"the caller's own conversation was not changed: {result.content}",
        )
        self.assertNotEqual(
            frappe.db.get_value("Albanna Conversation", theirs, "title"),
            "Bulk title",
            "a conversation belonging to somebody else was changed",
        )

    # -- the reader's own mailbox ------------------------------------------

    def test_the_readers_own_mailbox_is_readable_when_the_reader_may_read_those_threads(self):
        """A reader linked to a mailbox sees that mailbox's threads — and only those.

        The framework hides email Communications from any reader without a
        ``User Email`` row, so an agent who is not linked to the mailbox
        sees no customer mail at all.  That half is the framework's rule
        and the app says so out loud rather than pretending the silence
        was the whole truth (the note in ``list_docs``).

        The other half matters as much, and it is the half a live run
        found.  Being linked is not enough on its own: the framework
        also limits a reader to the Communications they own, unless they
        hold a role that may read any — "Inbox User" is that role.  So
        an agent needs the link *and* the role, and the site setup that
        gives them both is site setup, not app code.  This test is what
        says the app's half works.
        """
        mailbox = self._mailbox()
        thread = self._email_communication(mailbox)

        # Linked, and holding the role that may read any thread.
        self._link_mailbox(self.sales_user, mailbox)
        self._grant(self.sales_user, "Inbox User")
        result = self._call("list_docs", {"doctype": "Communication"}, self.sales_user)
        self.assertTrue(result.ok, result.content)
        names = [row.get("name") for row in (result.data or [])]
        self.assertIn(thread, names, f"the reader's own mailbox was not read: {result.content}")

        # Linked, but not holding it: the framework limits the reader to
        # the threads they own, and an incoming customer's mail is not
        # theirs.
        self._link_mailbox(self.other_user, mailbox)
        result = self._call("list_docs", {"doctype": "Communication"}, self.other_user)
        self.assertTrue(result.ok, result.content)
        names = [row.get("name") for row in (result.data or [])]
        self.assertNotIn(thread, names, "a mailbox was read by a reader who may not read it")

        # Not linked at all.
        self._unlink_mailbox(self.other_user)
        self._grant(self.other_user, "Inbox User")
        result = self._call("list_docs", {"doctype": "Communication"}, self.other_user)
        self.assertTrue(result.ok, result.content)
        names = [row.get("name") for row in (result.data or [])]
        self.assertNotIn(thread, names, "a mailbox was read by a reader who is not linked to it")

    def test_the_list_says_why_the_email_threads_are_not_there(self):
        """A list that is silently short says so in the tool's own answer.

        A list of Communications that quietly omits the email threads is
        the one answer the reader cannot trust: the model cannot tell
        "there are no email threads" from "the thread exists and I
        cannot see it".  So the tool states the limitation — and it
        states *which* limitation, because there are two, and a reader
        who is told the wrong one will go and fix the wrong thing.
        """
        mailbox = self._mailbox()

        # No link at all.
        self._unlink_mailbox(self.sales_user)
        result = self._call("list_docs", {"doctype": "Communication"}, self.sales_user)
        self.assertTrue(result.ok, result.content)
        self.assertIn("no email account configured", result.content)

        # Linked, but the account may only read the threads it owns.
        self._link_mailbox(self.sales_user, mailbox)
        result = self._call("list_docs", {"doctype": "Communication"}, self.sales_user)
        self.assertTrue(result.ok, result.content)
        self.assertIn("limit it to the Communications it owns", result.content)

        # Linked, and holding the role that may read any thread: nothing
        # to say.
        self._grant(self.sales_user, "Inbox User")
        result = self._call("list_docs", {"doctype": "Communication"}, self.sales_user)
        self.assertTrue(result.ok, result.content)
        self.assertNotIn("email thread could not be read", result.content)

        # And a reader the framework exempts from the rule — a System
        # Manager — reads every thread, so it must not be told that it
        # cannot read the mail.  This case was found by a live run: the
        # note said "no email account configured" to an Administrator who
        # reads everything, and a false statement about a privileged
        # reader is the kind that gets believed.
        self._unlink_mailbox("Administrator")
        result = self._call("list_docs", {"doctype": "Communication"}, "Administrator")
        self.assertTrue(result.ok, result.content)
        self.assertNotIn("email thread could not be read", result.content)
        self.assertNotIn("no email account configured", result.content)

    def _mailbox(self) -> str:
        """An email account of this test's own."""
        name = "Albanna Parity Mailbox"
        if not frappe.db.exists("Email Account", name):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                account = frappe.new_doc("Email Account")
                account.email_account_name = name
                account.email_id = "albanna-parity@example.com"
                account.flags.ignore_permissions = True
                account.insert()
            finally:
                frappe.set_user(former)
        return name

    def _email_communication(self, mailbox: str) -> str:
        """A customer's email, in the mailbox."""
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            communication = frappe.new_doc("Communication")
            communication.communication_type = "Communication"
            communication.communication_medium = "Email"
            communication.email_account = mailbox
            communication.sender = "customer@example.com"
            communication.recipient = self.sales_user
            communication.content = "Where is my order?"
            communication.status = "Open"
            communication.flags.ignore_permissions = True
            communication.insert()
        finally:
            frappe.set_user(former)
        return communication.name

    def _link_mailbox(self, email: str, mailbox: str) -> None:
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.get_doc("User", email)
            if not any(row.email_account == mailbox for row in user.user_emails):
                user.append(
                    "user_emails",
                    {"email_account": mailbox, "email_id": "albanna-parity@example.com"},
                )
            user.flags.ignore_permissions = True
            user.save()
        finally:
            frappe.set_user(former)

    def _unlink_mailbox(self, email: str) -> None:
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.get_doc("User", email)
            if user.user_emails:
                user.user_emails = []
                user.flags.ignore_permissions = True
                user.save()
        finally:
            frappe.set_user(former)

    def _grant(self, email: str, role: str) -> None:
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.get_doc("User", email)
            if not any(row.role == role for row in user.roles):
                user.add_roles(role)
                user.flags.ignore_permissions = True
                user.save()
        finally:
            frappe.set_user(former)

    # -- a read returns what the person may read ---------------------------

    def test_a_count_is_the_count_of_what_the_caller_may_read(self):
        """A number offered before a question is asked is still a leak.

        The empty state asks the server how many documents there are, and
        the answer used to be the size of the table — every row, including
        the ones the reader may not see.  So the first thing the widget
        showed a restricted reader was a number that told them what they
        could not see.
        """
        from albanna.api.context import count_doctype

        self._as(self.sales_user)
        readable = len(frappe.get_list("Albanna Conversation", pluck="name"))
        counted = count_doctype("Albanna Conversation")["count"]

        self.assertEqual(
            counted,
            readable,
            "the count is not the count of what the caller may read",
        )

        # A conversation belonging to somebody else must not change the
        # caller's count.
        self._as(self.other_user)
        ensure_conversation(self.other_user, "parity|count|theirs|")

        self._as(self.sales_user)
        self.assertEqual(
            count_doctype("Albanna Conversation")["count"],
            counted,
            "a conversation the caller may not read changed their count",
        )

    def test_the_confirmation_card_does_not_name_what_the_reader_may_not_read(self):
        """The card is shown to the reader, so it may not describe a document
        they may not read.

        The card is the one place a write is described *before* it runs,
        and a description that names a document the reader cannot see is
        a leak with a confirmation button on it.  The values the model
        wants to change are on the card too, and the model may have read
        them from the document.
        """
        from albanna.services.approval import write_diff, write_preview

        customer = self._customer(f"Albanna Parity Card {self._testMethodName}")
        company = self._company()
        currency = frappe.db.get_value("Company", company, "default_currency")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.currency = currency
        invoice.customer = customer
        invoice.append("items", {"item_code": self._item(), "qty": 1, "rate": 10})
        invoice.flags.ignore_permissions = True
        invoice.insert()

        # A Sales User cannot read a Sales Invoice on this site, which
        # makes it the honest case.
        self._as(self.sales_user)
        arguments = {
            "doctype": "Sales Invoice",
            "name": invoice.name,
            "data": {"remarks": "Albanna parity marker"},
        }

        preview = write_preview("update_doc", arguments)
        self.assertNotIn(
            invoice.name,
            preview,
            "the card named a document the reader may not read",
        )
        self.assertNotIn(
            "Albanna parity marker",
            preview,
            "the card showed values the reader may not have seen",
        )
        self.assertIsNone(
            write_diff("update_doc", arguments),
            "the card carried a diff of a document the reader may not read",
        )

    def test_the_card_counts_only_what_the_reader_may_read(self):
        """The bulk card says how many documents will change.

        That number is the reader's number: a card that says "Change 42
        Sales Invoices" to a reader who may see three of them tells them
        what they cannot see, and asks them to approve it besides.
        """
        from albanna.services.approval import write_preview

        self._as(self.sales_user)
        mine = ensure_conversation(self.sales_user, "parity|card|mine|")
        self._as(self.other_user)
        theirs = ensure_conversation(self.other_user, "parity|card|theirs|")

        self._as(self.sales_user)
        readable = len(frappe.get_list("Albanna Conversation", pluck="name"))
        preview = write_preview(
            "bulk_update_doc",
            {
                "doctype": "Albanna Conversation",
                "filters": [["name", "like", "%"]],
                "data": {"title": "Card title"},
            },
        )

        self.assertNotIn(
            theirs,
            preview,
            "the card named a document the reader may not read",
        )
        self.assertIn(mine, preview, "the card did not name the caller's own document")
        self.assertIn(
            f"Change {readable} ",
            preview,
            f"the card counted the whole table: {preview}",
        )

    def test_a_read_does_not_return_the_fields_the_caller_may_not_read(self):
        """A field at a higher permission level is hidden in the form.

        It must be hidden from the model too: the Desk shows the reader
        the document *as they may see it*, and the assistant answers for
        that person, not for the administrator.  ``ignore_pricing_rule``
        is such a field — a Sales Manager may read it, a Sales User may
        not.
        """
        customer = self._customer(f"Albanna Parity Read {self._testMethodName}")

        order = frappe.new_doc("Sales Order")
        order.company = self._company()
        order.customer = customer
        order.delivery_date = frappe.utils.add_days(frappe.utils.nowdate(), 7)
        order.append("items", {"item_code": self._item(), "qty": 1, "rate": 10})
        order.flags.ignore_permissions = True
        order.insert()

        result = self._call(
            "get_doc",
            {"doctype": "Sales Order", "name": order.name},
            self.sales_user,
        )

        self.assertTrue(result.ok, result.content)
        data = result.data or {}
        self.assertIn("customer", data)
        self.assertNotIn(
            "ignore_pricing_rule",
            data,
            "a field the reader may not read reached the model",
        )

    # -- a lifecycle action needs a read ------------------------------------

    def test_a_lifecycle_action_refuses_a_document_the_caller_may_not_read(self):
        """A write permission is not a read permission.

        The roles that hold one do not always hold the other, and a User
        Permission that limits an account to one customer is a read
        permission.  So the document is loaded, the read is checked, and
        the refusal is the one a read would have produced — the reader is
        not told whether the document is a draft or a submitted one.
        """
        mine = self._customer(f"Albanna Parity Mine {self._testMethodName}")
        theirs = self._customer(f"Albanna Parity Theirs {self._testMethodName}")

        company = self._company()
        currency = frappe.db.get_value("Company", company, "default_currency")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.currency = currency
        invoice.customer = theirs
        invoice.append("items", {"item_code": self._item(), "qty": 1, "rate": 10})
        invoice.flags.ignore_permissions = True
        invoice.insert()

        # The account may read one customer, and this invoice belongs to
        # another.
        permission = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": self.accounts_user,
                "allow": "Customer",
                "for_value": mine,
                "apply_to_all_doctypes": 1,
            }
        )
        permission.flags.ignore_permissions = True
        permission.insert()

        result = self._call(
            "submit_doc",
            {"doctype": "Sales Invoice", "name": invoice.name},
            self.accounts_user,
        )

        self.assertFalse(result.ok, result.content)
        self.assertIn("could not be read", result.error or "")
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"),
            0,
            "the invoice was submitted anyway",
        )

    # -- a private file stays private ---------------------------------------

    def test_a_private_file_of_somebody_else_is_not_attached(self):
        """Adoption copies the file — and the copy is public.

        So a private file belonging to somebody else must not be copied
        into a document the caller can write: the bytes would leave the
        private folder and become the document's own picture, visible to
        everybody who may read it.
        """
        self._as(self.other_user)
        from frappe.utils.file_manager import save_file

        saved = save_file(
            "albanna-parity-private.png",
            b"not really a png",
            "User",
            self.other_user,
            is_private=1,
        )
        url = str(getattr(saved, "file_url", "") or "")
        self.assertTrue(url.startswith("/private/files/"))

        contact = frappe.new_doc("Contact")
        contact.first_name = "Albanna Parity"
        contact.flags.ignore_permissions = True
        contact.insert()

        result = self._call(
            "update_doc",
            {"doctype": "Contact", "name": contact.name, "data": {"image": url}},
            self.sales_user,
        )

        self.assertFalse(result.ok, result.content)
        self.assertIn("may not be read", result.error or "")
        self.assertFalse(
            frappe.db.get_value(
                "File",
                {
                    "attached_to_doctype": "Contact",
                    "attached_to_name": contact.name,
                    "is_private": 0,
                },
            ),
            "the private file was copied into a public file",
        )

    # -- the catalogue and the page are the reader's too --------------------

    def test_the_doctype_catalogue_lists_only_what_the_caller_may_read(self):
        """The model may not learn the site's structure from the catalogue.

        The lookup behind "that DocType does not exist" listed every
        DocType on the site.  So a reader who may not read a Salary Slip
        was told, by the assistant's own catalogue, that the site has
        Salary Slips.
        """
        import json

        from albanna.tools.erpnext import list_doctypes

        self._as(self.sales_user)
        payload = json.loads(list_doctypes())
        names = [row["name"] for row in payload.get("doctypes") or []]

        self.assertTrue(names, "the catalogue must not be empty for a reader")

        # A DocType the Sales User has no business reading: the payroll
        # ones are read by the Accounts User and the HR Manager only.
        for hidden in ("Salary Slip", "Salary Component", "Employee Checkin"):
            if frappe.db.exists("DocType", hidden):
                self.assertNotIn(
                    hidden,
                    names,
                    f"the catalogue listed a DocType the reader may not read: {hidden}",
                )

        # And the DocTypes the reader *can* read are in it — an empty
        # catalogue would be a different bug.
        self.assertIn("Customer", names)

    def test_the_page_context_does_not_name_a_document_the_caller_may_not_read(self):
        """The browser is not trusted to name only what the reader can see.

        The page context says "the reader is looking at this document",
        and the browser is free to say so about anything.  So the name is
        dropped when the reader may not read the document: the model is
        told what kind of page it is on, and not which row of it.
        """
        from albanna.api.chat import _render_page_context

        customer = self._customer(f"Albanna Parity Page {self._testMethodName}")

        company = self._company()
        currency = frappe.db.get_value("Company", company, "default_currency")
        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.currency = currency
        invoice.customer = customer
        invoice.append("items", {"item_code": self._item(), "qty": 1, "rate": 10})
        invoice.flags.ignore_permissions = True
        invoice.insert()

        # A Sales User cannot read a Sales Invoice on this site, so the
        # invoice is the document the page must not name.
        self._as(self.sales_user)
        rendered = _render_page_context(
            {
                "doctype": "Sales Invoice",
                "name": invoice.name,
                "title": "An invoice the reader may not read",
                "view": "/app/sales-invoice",
            }
        )
        self.assertNotIn(
            invoice.name,
            rendered,
            "the page context named a document the reader may not read",
        )
        self.assertNotIn(
            "An invoice the reader may not read",
            rendered,
            "the page context carried the title of a document the reader may not read",
        )

        # A document the reader *may* read is still named — otherwise the
        # context would be useless.
        rendered = _render_page_context(
            {
                "doctype": "Customer",
                "name": customer,
                "title": "A customer the reader may read",
                "view": "/app/customer",
            }
        )
        self.assertIn(customer, rendered, "the page context dropped a document the reader may read")
