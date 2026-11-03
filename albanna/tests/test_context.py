"""The live hint on the list page.

The panel opens on a list and says one thing about it: *there is one
overdue invoice — want me to draft reminders?*  It is the only thing the
chat says before the reader has asked anything, so it has to be right in
a way that is hard to get right: the count must be the reader's own
count, the words must be in the reader's language, and the numbers must
be in the sentence at all.

This file holds the first of those three.  The hint is a translated
string with two holes in it, and a translated string is filled *after*
the translation — ``frappe._`` takes a language as its second argument
and never fills a ``{0}`` on its own.  Getting that wrong leaves the
reader looking at ``{0} overdue {1}``, which is what happened.

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
        ``{0} متأخر {1}`` — the same defect in the other language.
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
        assert "Sales Invoice" in message
        assert "{" not in message
        assert "}" not in message
        # The sentence is the Arabic one, not the English one.
        assert message != HINT.format(3, "Sales Invoice")

    def test_no_hint_when_nothing_is_overdue(self):
        """Nothing to say is nothing said."""
        with patch.object(context_api, "_count_readable", return_value=0):
            result = context_api.nudge_for_page("Sales Invoice")

        assert result["message"] == ""

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
