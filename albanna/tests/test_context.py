"""The live hint on the list page.

The panel opens on a list and says one thing about it: *there is one
overdue invoice — want me to draft reminders?*  It is the only thing the
chat says before the reader has asked anything, so it has to be right in
a way that is hard to get right: the count must be the reader's own
count, the words must be in the reader's language, the numbers must be
in the sentence at all, and the documents it names must be the reader's
own documents.

This file holds the first and the last of those.  The hint is a
translated string with two holes in it, and a translated string is
filled *after* the translation — ``frappe._`` takes a language as its
second argument and never fills a ``{0}`` on its own.  Getting that
wrong leaves the reader looking at ``{0} overdue {1}``, which is what
happened.

And a count with no names is a number the reader has to look up: they
are told that three invoices are overdue, and they have to find which
three.  So the hint names them — and the names come from the same
permission-filtered query as the count, because a name the reader may
not see is a leak, and it is a leak in the one place the reader is least
suspicious: a name in an empty state, offered before they have asked
anything.

These tests need a site, and they are excluded from the default
``pytest`` run by the ``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
import pytest

from albanna.api import context as context_api
from albanna.tests.base import AlbannaTestCase

READER = "albanna.test.context.reader@albanna.dev"

#: The hint's own string.  It is spelled out here rather than imported so
#: that a change to the sentence is a change the test notices: a test
#: that reads the string from the code proves only that the code is
#: consistent with itself.
HINT = "{0} overdue {1} — want me to draft reminders?"


def _make_user(email: str, roles: tuple[str, ...] = ("Albanna User",)) -> str:
    """A user with the given roles.

    The chat's own role is one of them, but not the only one that
    matters here: the hint counts the reader's *own* invoices, so the
    reader must also be somebody who may read a Sales Invoice — the
    count of a reader who may not read the rows is zero, and a test
    that wanted a count would see an empty hint.
    """
    if not frappe.db.exists("User", email):
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "Albanna"
            user.last_name = "Context"
            user.flags.ignore_permissions = True
            user.insert()
        finally:
            frappe.set_user(former)
    user = frappe.get_doc("User", email)
    user.flags.ignore_permissions = True
    user.add_roles(*roles)
    return email


def _as(email: str) -> None:
    """Act as *email*, the way a request for that user would."""
    frappe.set_user(email)
    frappe.local.session.user = email
    frappe.local.role_permissions = {}
    frappe.local.perms = {}


@pytest.mark.integration
class TestTheLiveHint(AlbannaTestCase):
    """What the panel says before the reader has asked anything."""

    def setUp(self):
        super().setUp()
        self.reader = _make_user(READER, ("Albanna User", "Accounts User"))
        _as(self.reader)

    def test_the_hint_carries_the_count_it_found(self):
        """The count is in the sentence.

        Not the template of the sentence: the reader must see *one*, not
        ``{0}``.
        """
        with patch.object(context_api, "_count_readable", return_value=1):
            result = context_api.nudge_for_page("Sales Invoice")

        message = result["message"]
        assert "1" in message
        assert "Sales Invoice" in message
        assert "{" not in message
        assert "}" not in message

    def test_the_hint_is_translated_and_still_carries_the_numbers(self):
        """The Arabic catalogue is used, and its holes are filled too.

        The translation is a sentence with two holes in it as well, so
        translating without filling would show the reader
        ``{0}: {1} منها متأخرة`` — the same defect in the other
        language.  The second hole is the DocType's name, which is
        translated as well.
        """
        former = frappe.local.lang
        frappe.local.lang = "ar"
        try:
            with patch.object(context_api, "_count_readable", return_value=3):
                result = context_api.nudge_for_page("Sales Invoice")
        finally:
            frappe.local.lang = former

        message = result["message"]
        assert "3" in message
        assert "فاتورة المبيعات" in message
        assert "{" not in message
        assert "}" not in message
        # The sentence is the Arabic one, not the English one.
        assert message != HINT.format(3, "Sales Invoice")

    def test_no_hint_when_nothing_is_overdue(self):
        """Nothing to say is nothing said."""
        with patch.object(context_api, "_count_readable", return_value=0):
            result = context_api.nudge_for_page("Sales Invoice")

        assert result["message"] == ""
        assert result["question"] == ""

    def test_the_hint_names_the_doctype_in_the_readers_language(self):
        """The DocType's name is in the reader's language too.

        An interface in Arabic that says "Sales Invoice" is half in
        Arabic.  ERPNext ships no Arabic catalogue of its own, so the
        app carries the two invoice names the hint uses.
        """
        former = frappe.local.lang
        frappe.local.lang = "ar"
        try:
            with patch.object(context_api, "_count_readable", return_value=1):
                result = context_api.nudge_for_page("Sales Invoice")
        finally:
            frappe.local.lang = former

        message = result["message"]
        assert "فاتورة المبيعات" in message
        assert "Sales Invoice" not in message

    def test_the_go_button_sends_a_question_of_its_own(self):
        """The question is a question, and it is not the hint.

        The hint is the chat's way of saying something.  A reader who
        presses "Go" means "yes, do that", and the sentence that says
        "3 overdue Sales Invoice — want me to draft reminders?" is not
        what the reader would have typed.
        """
        with patch.object(context_api, "_count_readable", return_value=1):
            result = context_api.nudge_for_page("Sales Invoice")

        question = result["question"]
        assert question
        assert question != result["message"]
        assert question.endswith("?")
        assert "overdue invoices" in question

    def test_the_question_is_in_the_readers_language(self):
        """The question the button sends is a question in Arabic too."""
        former = frappe.local.lang
        frappe.local.lang = "ar"
        try:
            with patch.object(context_api, "_count_readable", return_value=1):
                result = context_api.nudge_for_page("Sales Invoice")
        finally:
            frappe.local.lang = former

        question = result["question"]
        assert "هل يمكنك" in question
        assert "overdue invoices" not in question

    def test_no_hint_for_a_doctype_the_chat_does_not_nudge(self):
        """The nudge is for the two invoice lists and nothing else."""
        result = context_api.nudge_for_page("ToDo")

        assert result["message"] == ""

    def test_the_reader_must_be_allowed_to_chat(self):
        """The hint is said to a reader who may chat, and to nobody else."""
        # This account may read a Sales Invoice — it holds the accounts
        # role — but the chat is closed for it: the hint says something
        # about the reader's own data, so it is not said to somebody the
        # chat is closed for.
        outsider = _make_user(
            "albanna.test.context.outsider@albanna.dev",
            ("Accounts User",),
        )
        _as(outsider)

        with pytest.raises(frappe.PermissionError):
            context_api.nudge_for_page("Sales Invoice")


@pytest.mark.integration
class TestTheHintNamesItsDocuments(AlbannaTestCase):
    """The documents the hint names are the reader's own documents.

    The count and the names have to agree, and they have to agree because
    they come from the same query: the permission query conditions, the
    row-level rules, the ownership constraint and the User Permissions
    all apply to both.  A count that sees forty invoices and a list of
    names that sees three of somebody else's would be worse than no hint
    at all.
    """

    def setUp(self):
        super().setUp()
        self.reader = _make_user(READER, ("Albanna User", "Accounts User"))
        _as(self.reader)

    # -- the rows of this test ----------------------------------------------

    def _customer(self, name: str) -> str:
        """A customer of this test's own."""
        if not frappe.db.exists("Customer", name):
            group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                customer = frappe.new_doc("Customer")
                customer.customer_name = name
                customer.customer_type = "Company"
                customer.customer_group = group
                customer.flags.ignore_permissions = True
                customer.insert()
            finally:
                _as(former)
        return name

    def _overdue_invoice(self, customer: str) -> str:
        """An invoice of this test's own, marked overdue.

        The invoice is a draft: the suite does not submit an invoice of
        its own, because a submission runs whatever hooks the site's
        apps have put on it.  What the hint reads is the ``status``
        column, so the status is written in the database — the row the
        query finds is the row the reader would see, and no submission is
        needed to prove it.

        The invoice is made by the Administrator, so that the reader's
        own rows are not the only rows they may see: what hides a row
        here is a permission, not an owner.
        """
        company = frappe.db.get_value("Company", {}, "name")
        currency = frappe.db.get_value("Company", company, "default_currency")
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")

        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            invoice = frappe.new_doc("Sales Invoice")
            invoice.company = company
            invoice.currency = currency
            invoice.customer = customer
            invoice.append("items", {"item_code": item, "qty": 1, "rate": 10})
            invoice.flags.ignore_permissions = True
            invoice.insert()
            frappe.db.set_value("Sales Invoice", invoice.name, "status", "Overdue")
        finally:
            _as(former)
        return invoice.name

    def _overdue_count(self) -> int:
        """How many overdue invoices the reader may see."""
        return context_api._count_readable("Sales Invoice", [["status", "=", "Overdue"]])

    # -- the names ----------------------------------------------------------

    def test_the_hint_names_the_documents_it_counted(self):
        """The names are the documents the count was made of.

        The reader is told how many invoices are overdue and is shown
        some of them: the customer they recognise at a glance, and the
        series they can look up.
        """
        customer = self._customer("Albanna Context Named")
        invoice = self._overdue_invoice(customer)

        result = context_api.nudge_for_page("Sales Invoice")

        named = {document["name"]: document for document in result["documents"]}
        assert invoice in named, "the hint counted an invoice it did not name"
        assert named[invoice]["title"] == customer
        assert result["more"] == max(0, self._overdue_count() - len(result["documents"]))

    def test_the_hint_names_three_documents_at_most(self):
        """Three names, and a count of the ones behind them.

        The panel is a hint: a list of forty names is not a hint.  So the
        names stop at three, and the reader is told how many are behind
        them rather than being shown a wall.
        """
        for index in range(5):
            self._overdue_invoice(self._customer(f"Albanna Context Many {index}"))

        result = context_api.nudge_for_page("Sales Invoice")

        assert len(result["documents"]) == 3
        assert result["more"] == self._overdue_count() - 3
        assert result["more"] >= 2

    def test_the_names_are_the_readers_own_rows(self):
        """A name the reader may not see is a leak.

        The account may read one customer, and this invoice belongs to
        another.  The count does not see it either — the count and the
        names come from the same query — so the hint says nothing about
        it and shows no sign of it.
        """
        mine = self._customer("Albanna Context Mine")
        theirs = self._customer("Albanna Context Theirs")
        my_invoice = self._overdue_invoice(mine)
        their_invoice = self._overdue_invoice(theirs)

        permission = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": self.reader,
                "allow": "Customer",
                "for_value": mine,
                "apply_to_all_doctypes": 1,
            }
        )
        permission.flags.ignore_permissions = True
        permission.insert()

        result = context_api.nudge_for_page("Sales Invoice")

        names = [document["name"] for document in result["documents"]]
        assert my_invoice in names
        assert their_invoice not in names
        assert result["more"] == max(0, self._overdue_count() - len(result["documents"]))

    def test_a_document_with_no_title_is_named_by_its_own_name(self):
        """The title is sent as the site holds it.

        An invoice whose customer has no title carries no title, and the
        server does not invent one: the panel falls back to the
        document's own name, which is what the reader would see in the
        list anyway.
        """
        customer = self._customer("Albanna Context Untitled")
        invoice = self._overdue_invoice(customer)
        frappe.db.set_value("Sales Invoice", invoice, "title", "")

        result = context_api.nudge_for_page("Sales Invoice")

        named = {document["name"]: document for document in result["documents"]}
        assert invoice in named
        assert named[invoice]["title"] == ""
        assert named[invoice]["name"] == invoice
