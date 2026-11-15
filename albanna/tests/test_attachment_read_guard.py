"""The read-back of a turn's attachments is permission-checked.

The rule under test (NFR-SEC10): a turn's bytes are read where they are
stored — ``load_attached_files`` — and a stored file the turn's user may
not read is skipped, not handed to the model.  The check is made
explicitly, because ``frappe.get_doc`` runs *no* permission check: a
crafted request that named another user's private file URL would
otherwise have carried that file's bytes to the model.

The same file is readable by its owner, so the rule cuts one way and
the cut is the right one.
"""

from __future__ import annotations

import frappe

from albanna.services.attachments import load_attached_files
from albanna.tests.base import AlbannaTestCase

OTHER = "albanna.reachback@albanna.dev"


class TestReadingAttachmentsBack(AlbannaTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A user is made as the administrator, for the same reason the
        # escalate tests give: the framework makes the session's own
        # settings for a user it creates.
        if not frappe.db.exists("User", OTHER):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = OTHER
                user.first_name = "Albanna"
                user.last_name = "Attachment"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)

    def setUp(self):
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            saved = frappe.utils.file_manager.save_file(
                "albanna-pinning.txt",
                "the owner's words",
                "User",
                "Administrator",
                is_private=1,
                folder="Home",
            )
        finally:
            frappe.set_user(former)
        self.url = saved.file_url
        self.name = saved.name
        self.addCleanup(self._discard)

    def _discard(self):
        frappe.set_user("Administrator")
        frappe.delete_doc("File", self.name, force=True, ignore_permissions=True)

    def test_the_owner_may_have_their_own_file_read_back(self):
        frappe.set_user("Administrator")
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

        data_urls, texts = load_attached_files([self.url])

        self.assertTrue(data_urls[0].startswith("data:text/plain;base64,"))
        self.assertEqual(texts, ["the owner's words"])

    def test_another_user_cannot_have_the_file_read_into_a_turn(self):
        frappe.set_user(OTHER)
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

        data_urls, texts = load_attached_files([self.url])

        self.assertEqual(data_urls, [""])
        self.assertEqual(texts, [""])
