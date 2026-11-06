"""The escalate endpoint, and the Issue it hands to a human.

Escalation is the one control in the drawer that leaves the app: it
creates a Frappe Issue, and a person picks the conversation up from
there.  It is also the one control that was shipped broken and stayed
broken.

The decorator that made ``delete_conversation`` reachable became the
decorator of ``escalate_conversation`` when the escalate feature was
added, and the button failed on every click — silently, behind a
sentence about the request.  Nothing caught it, because a test that
calls a function directly does not go through the whitelist: the
function works, and the *route* to it does not exist.  The guard that
catches that class of bug now reads the front-end's calls against the
server's own source (``tests/test_api_surface.py``), but a guard is not
a test — it says the route exists, and says nothing about what the
route does when it is called.

So the endpoint is called here, as a person, on a site with a real
permission engine.  That matters because of what the feature *is*: the
Issue is created as the caller, so that Frappe's own rules apply to it.
A test that ran the hand-off as Administrator would prove nothing about
the thing that matters.

The Issue doctype is ERPNext's, and only the **Support Team** role may
create one.  So the reader here holds that role as well as the chat's
own: without it the insert is refused for a reason that has nothing to
do with what is being tested, and the test would be measuring the
permission matrix rather than the hand-off.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.api.conversations import escalate_conversation
from albanna.services.conversation_service import append_messages, ensure_conversation
from albanna.tests.base import AlbannaTestCase

OWNER = "albanna.test.escalate.owner@albanna.dev"
OTHER = "albanna.test.escalate.other@albanna.dev"


@pytest.mark.integration
class TestEscalation(AlbannaTestCase):
    """A conversation handed to a human, and what the human is handed."""

    def setUp(self):
        super().setUp()
        self.owner = self._make_user(OWNER)
        self.other = self._make_user(OTHER)
        frappe.db.commit()

    def _make_user(self, email: str) -> str:
        """A reader who may chat, and who may raise an Issue.

        The user is made as the administrator: the framework makes the
        session's own settings for a user it creates, so a session left
        as somebody else — a user another test made, and one this
        transaction has already rolled back — fails the insert for a
        reason that has nothing to do with what this test is about.
        """
        if not frappe.db.exists("User", email):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Escalate"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        # ``Support Team`` is ERPNext's own role, and it is the one that
        # may create an Issue.  Without it the hand-off is refused by the
        # framework before the endpoint's own work is even looked at.
        user.add_roles("Support Team", "Albanna User")
        return email

    def _as(self, email: str):
        """Act as *email*, the way a request for that user would."""
        frappe.set_user(email)
        frappe.local.session.user = email
        # The role permissions are cached per request; a fresh identity needs
        # a fresh cache or it reads the previous one's.
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _thread(self, title: str = "") -> str:
        """A conversation with a question and an answer.

        Each test gets its own page, because a conversation is found by
        page: a shared page would mean every test appends to the one
        before it.
        """
        conversation = ensure_conversation(self.owner, f"test|escalate|{self.id()}|")
        frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (conversation,))
        if title:
            frappe.db.set_value("Albanna Conversation", conversation, "title", title)
        append_messages(
            conversation,
            [
                {"role": "user", "content": "How many open orders are there?"},
                {"role": "assistant", "content": "Here are your open orders."},
            ],
        )
        return conversation

    # -- the hand-off ------------------------------------------------------

    def test_a_conversation_escalates_to_an_issue(self):
        """The Issue carries the thread, and the thread is in it.

        The subject is drawn from the conversation's *title* — which is
        not the same thing as the first question, because a reader may
        have renamed the thread — and the description carries both
        messages, so the person picking it up does not have to ask what
        was asked.
        """
        self._as(self.owner)
        conversation = self._thread("Open orders for Acme")

        result = escalate_conversation(conversation=conversation)

        issue = frappe.get_doc("Issue", result["issue"])
        self.assertEqual(issue.subject, "Open orders for Acme")
        self.assertIn("How many open orders are there?", issue.description)
        self.assertIn("Here are your open orders.", issue.description)

    def test_the_issue_is_raised_by_the_caller(self):
        """The Issue is created as the reader, not as the administrator.

        This is the property the endpoint's own docstring claims, and it
        is the one that makes the hand-off worth anything: an Issue
        raised by the person who asked the question is one Frappe's
        permission engine has already judged, and one the support team
        can see because the reader may see it.  An Issue raised as
        Administrator would be a document the reader cannot open and
        cannot be held to.
        """
        self._as(self.owner)
        conversation = self._thread("Open orders for Acme")

        result = escalate_conversation(conversation=conversation)

        issue = frappe.get_doc("Issue", result["issue"])
        self.assertEqual(issue.raised_by, self.owner)
        self.assertNotEqual(issue.raised_by, "Administrator")
        # The framework stamps the document with the session user too, so
        # the two cannot drift apart.
        self.assertEqual(issue.owner, self.owner)

    def test_an_empty_conversation_still_escalates(self):
        """A thread with nothing in it is still a thread.

        The reader pressed the button on a conversation they had not
        asked anything in — perhaps to hand the page over, perhaps by
        mistake.  Refusing it would be a refusal the reader cannot act
        on: there is nothing wrong with the conversation, and the Issue
        is the thing that would say so.
        """
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, f"test|escalate|empty|{self.id()}|")

        result = escalate_conversation(conversation=conversation)

        issue = frappe.get_doc("Issue", result["issue"])
        self.assertTrue(issue.subject, "an Issue with no subject is not a hand-off")
        self.assertIn("Escalated from an Albanna conversation.", issue.description)
        self.assertNotIn("**User:**", issue.description)

    # -- what it refuses ----------------------------------------------------

    def test_another_users_conversation_is_refused(self):
        """A conversation that is not the caller's is not theirs to hand over.

        The rows are read with direct SQL, which consults no permission
        at all, so the check has to be explicit — and it has to happen
        before the Issue is made, because an Issue carrying somebody
        else's conversation is a copy of their words in a document they
        never agreed to.
        """
        conversation = self._thread("Open orders for Acme")
        before = frappe.db.count("Issue")

        self._as(self.other)
        with self.assertRaises(frappe.PermissionError):
            escalate_conversation(conversation=conversation)

        self.assertEqual(
            frappe.db.count("Issue"),
            before,
            "the refusal came after the Issue was created",
        )
