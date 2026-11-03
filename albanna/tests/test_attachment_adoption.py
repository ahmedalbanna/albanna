"""The document's own copy of an attachment.

The rule under test: an image the chat stored is private and the
uploader's, so it renders in their session and nowhere else.  An image
set on a document is the document's picture, and it has to render for
everyone who may read the document — so the document gets a public copy
of the same bytes, attached to it, exactly as a person uploading through
the form would produce.

The second rule under test is the one the next turn depends on: the
model's view of a conversation must not carry a stored file's address as
an *image*.  The address is a path on this site
(``/private/files/albanna-8f2a1c.png``), and a vision provider cannot
read a path it has no way to fetch — the request is refused, and the
second turn of every conversation with an attachment dies with it.  The
address travels as words instead, which is what it is for.
"""

from __future__ import annotations

import json

import frappe

from albanna.services.chat_service import ChatService
from albanna.services.conversation_service import (
    append_messages,
    ensure_conversation,
    load_messages,
)
from albanna.tests.base import AlbannaTestCase

PNG = "data:image/png;base64,aGVsbG8="  # "hello", which is not a PNG: bytes are enough here


class TestAdoptingAnAttachment(AlbannaTestCase):
    def setUp(self):
        self.url = ChatService()._store_image(PNG, frappe.session.user or "Administrator")
        self.assertTrue(self.url.startswith("/private/files/"))

    def _document(self):
        doc = frappe.get_doc({"doctype": "Contact", "first_name": "Albanna Attachment"})
        doc.insert()
        self.addCleanup(frappe.delete_doc, "Contact", doc.name, force=True, ignore_permissions=True)
        return doc

    def test_the_document_gets_a_public_copy_of_the_file(self):
        from albanna.tools.erpnext import _adopt_attachments

        doc = self._document()
        changes = {"image": self.url}
        _adopt_attachments(doc, changes)

        self.assertTrue(changes["image"].startswith("/files/"))
        owned = frappe.db.get_value(
            "File",
            {
                "attached_to_doctype": "Contact",
                "attached_to_name": doc.name,
                "attached_to_field": "image",
            },
            ["file_url", "is_private"],
            as_dict=True,
        )
        self.assertIsNotNone(owned, "the document has no file of its own")
        self.assertFalse(owned.is_private)
        self.assertEqual(owned.file_url, changes["image"])

    def test_the_chats_own_attachment_is_left_alone(self):
        from albanna.tools.erpnext import _adopt_attachments

        doc = self._document()
        _adopt_attachments(doc, {"image": self.url})

        self.assertTrue(frappe.db.get_value("File", {"file_url": self.url}, "is_private"))

    def test_setting_the_same_image_twice_adds_no_second_row(self):
        """Setting an image the document already owns must not leave a
        second File row behind it."""
        from albanna.tools.erpnext import _adopt_attachments

        doc = self._document()
        first = {"image": self.url}
        _adopt_attachments(doc, first)
        second = {"image": self.url}
        _adopt_attachments(doc, second)

        self.assertEqual(first["image"], second["image"])
        rows = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Contact",
                "attached_to_name": doc.name,
                "attached_to_field": "image",
            },
        )
        self.assertEqual(len(rows), 1)

    def test_a_field_that_is_not_an_attachment_is_left_alone(self):
        from albanna.tools.erpnext import _adopt_attachments

        class _Meta:
            @staticmethod
            def get_field(fieldname):
                return None

        class _Doc:
            meta = _Meta()
            doctype = "Item"
            name = "RM-007"

        changes = {"description": "/files/albanna-abc.png"}
        self.assertEqual(_adopt_attachments(_Doc(), changes), changes)


class TestTheAttachmentInTheNextTurn(AlbannaTestCase):
    """What the model reads when the reader comes back to the thread."""

    def setUp(self):
        self.url = ChatService()._store_image(PNG, frappe.session.user or "Administrator")
        self.assertTrue(self.url.startswith("/private/files/"))
        self.conversation = ensure_conversation(
            frappe.session.user or "Administrator", "", "A thread"
        )
        append_messages(
            self.conversation,
            [
                {
                    "role": "user",
                    "content": "what is this?",
                    "round_no": 0,
                    "image_url": json.dumps([self.url]),
                },
                {"role": "assistant", "content": "A picture.", "round_no": 1},
            ],
        )

    def test_the_stored_address_is_not_an_image_part(self):
        """A path on this site is not a picture the provider can read."""
        messages = load_messages(self.conversation)
        self.assertEqual(messages[0].images, [])

    def test_the_model_is_told_where_the_picture_went(self):
        """The reader does not attach the same picture twice to set it on
        a document: the model is told the address on the turn after."""
        messages = load_messages(self.conversation)
        self.assertIn(self.url, messages[0].content)

    def test_the_reader_still_sees_the_attachment(self):
        """The widget's own view is not the model's, and it keeps the
        address so the reader can see the picture they sent."""
        from albanna.services.conversation_service import load_transcript

        transcript = load_transcript(self.conversation)
        self.assertEqual(transcript[0]["images"], [self.url])
