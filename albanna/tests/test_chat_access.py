"""Who may use the chat, and who may not.

These tests need a site, and they are excluded from the default ``pytest``
run by the ``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna

The gate has two layers, and this file holds both.

The **permission matrix** is the rule: read on ``Albanna Conversation``,
shipped as the ``Albanna User`` role.  It is the operator's ordinary way
of granting the chat, and it is the answer for every account that has no
policy row.

The **per-user policy** is the exception to that rule, for one account:
``Off`` refuses a person the matrix would allow, and ``On`` allows a
person the matrix would refuse.  It exists because the matrix is granted
by *role*, and a role cannot say "everyone except this one".

Both layers are read in one place — :func:`albanna.permissions.chat_access`
— so the widget and the API cannot disagree about who may chat.  That is
the property these tests are here to hold: a gate that the panel and the
endpoint read differently is a gate that fails open somewhere.
"""

from __future__ import annotations

import frappe
import pytest
from frappe.tests.utils import FrappeTestCase

from albanna.permissions import can_use_chat, chat_access, require_chat_access
from albanna.user_policy import chat_access_override

#: Holds the shipped ``Albanna User`` role, so the matrix allows the chat.
ALLOWED = "chat-access-allowed@example.com"

#: Holds a role that does not carry the chat, so the matrix refuses it.
PLAIN = "chat-access-plain@example.com"


@pytest.mark.integration
class TestChatAccess(FrappeTestCase):
    """The gate, read three ways: the matrix, the policy, and the widget."""

    def setUp(self):
        super().setUp()
        self.allowed = self._make_user(ALLOWED, "Albanna User")
        self.plain = self._make_user(PLAIN, "Sales User")
        self._clear_policies()

    def tearDown(self):
        self._clear_policies()
        super().tearDown()

    # -- the helpers -------------------------------------------------------

    def _make_user(self, email: str, role: str) -> str:
        """A user with exactly *role* — no more, so the matrix is known."""
        if not frappe.db.exists("User", email):
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "Chat"
            user.last_name = "Access"
            user.flags.ignore_permissions = True
            user.insert()

        # The roles of a user that a previous run left behind are cleared
        # first: what the matrix says has to be what this test set up, not
        # what an earlier run happened to leave.
        frappe.db.delete("Has Role", {"parent": email})

        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role)
        return email

    def _clear_policies(self) -> None:
        """No policy rows survive a test — the matrix is the default."""
        frappe.set_user("Administrator")
        frappe.local.session.user = "Administrator"
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

        for name in frappe.get_all("Albanna User Policy", pluck="name"):
            frappe.delete_doc("Albanna User Policy", name, force=True)
        frappe.db.commit()
        frappe.clear_cache()

    def _set_policy(self, email: str, override: str) -> None:
        """Give *email* a policy row with *override* as its chat access."""
        frappe.set_user("Administrator")
        frappe.local.session.user = "Administrator"
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

        existing = frappe.db.get_value("Albanna User Policy", {"user": email}, "name")
        if existing:
            frappe.delete_doc("Albanna User Policy", existing, force=True)

        doc = frappe.get_doc(
            {
                "doctype": "Albanna User Policy",
                "user": email,
                "chat_access_override": override,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()
        frappe.clear_cache()

    def _as(self, email: str) -> None:
        """Act as *email*, the way a request for that user would."""
        frappe.set_user(email)
        frappe.local.session.user = email
        # The role permissions are cached per request; a fresh identity needs
        # a fresh cache or it reads the previous one's.
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    # -- the matrix --------------------------------------------------------

    def test_the_matrix_grants_the_chat(self):
        """A role that holds read on Albanna Conversation opens the chat."""
        self._as(self.allowed)

        self.assertTrue(can_use_chat())
        allowed, reason = chat_access()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_the_matrix_refuses_the_chat(self):
        """A role that does not hold it does not open the chat."""
        self._as(self.plain)

        self.assertFalse(can_use_chat())
        allowed, reason = chat_access()
        self.assertFalse(allowed)
        self.assertEqual(reason, "permission")

    # -- the policy --------------------------------------------------------

    def test_a_policy_switches_the_chat_off(self):
        """Off outranks the role that would have opened it."""
        self._set_policy(self.allowed, "Off")
        self._as(self.allowed)

        self.assertFalse(can_use_chat())
        allowed, reason = chat_access()
        self.assertFalse(allowed)
        self.assertEqual(reason, "policy")

    def test_a_policy_switches_the_chat_on(self):
        """On opens it for an account the matrix would refuse."""
        self._set_policy(self.plain, "On")
        self._as(self.plain)

        self.assertTrue(can_use_chat())

    def test_a_blank_override_inherits_the_matrix(self):
        """"Site default" is an absence of opinion, not a refusal."""
        self._set_policy(self.plain, "Site default")
        self._as(self.plain)
        self.assertFalse(can_use_chat())

        self._set_policy(self.allowed, "Site default")
        self._as(self.allowed)
        self.assertTrue(can_use_chat())

    def test_a_policy_is_one_account_and_not_another(self):
        """Switching one person off does not touch the people beside them."""
        self._set_policy(self.plain, "Off")
        self._as(self.allowed)

        self.assertTrue(can_use_chat())

    def test_the_reader_reports_the_override(self):
        """The override reads as the word the gate acts on."""
        self.assertEqual(chat_access_override(self.plain), "")

        self._set_policy(self.plain, "Off")
        self.assertEqual(chat_access_override(self.plain), "off")

        self._set_policy(self.plain, "On")
        self.assertEqual(chat_access_override(self.plain), "on")

    # -- the refusal -------------------------------------------------------

    def test_the_refusal_names_the_policy_and_not_the_roles(self):
        """A person switched off by policy is told that, not sent to a role."""
        self._set_policy(self.allowed, "Off")
        self._as(self.allowed)

        with self.assertRaises(frappe.PermissionError) as caught:
            require_chat_access()

        message = str(caught.exception)
        self.assertIn("policy", message.lower())
        self.assertNotIn("Albanna User role", message)

    def test_the_refusal_still_names_the_roles_for_the_matrix(self):
        """Without a policy, the refusal points at the role that opens it."""
        self._as(self.plain)

        with self.assertRaises(frappe.PermissionError) as caught:
            require_chat_access()

        message = str(caught.exception)
        self.assertIn("Albanna Conversation", message)
        self.assertNotIn("policy", message.lower())

    # -- the widget --------------------------------------------------------

    def test_the_widget_is_hidden_from_a_switched_off_account(self):
        """No widget for an account the gate refuses — not a broken one."""
        self._set_policy(self.allowed, "Off")
        self._as(self.allowed)

        from albanna.api.widget import options

        payload = options()
        self.assertFalse(payload["visible"])
        self.assertFalse(payload["chat_access"])
        self.assertEqual(payload["tools"], [])

    def test_the_widget_is_shown_to_an_account_the_policy_allows(self):
        """The widget follows the same gate the endpoints do."""
        self._set_policy(self.plain, "On")
        self._as(self.plain)

        from albanna.api.widget import options

        payload = options()
        self.assertTrue(payload["visible"])
        self.assertTrue(payload["chat_access"])
