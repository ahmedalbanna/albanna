"""``Albanna Conversation`` — one chat thread.

The owner is forced from the session on insert.  The doctype grants ``All``
read/write — without that grant a user who is allowed to chat could not
reach the conversation endpoints at all — and the permission hooks in
``hooks.py`` are what narrow ``All`` back down to "the owner, and a System
Manager".  The two are edited together; changing one without the other
widens or breaks the other.
"""

import frappe
from frappe.model.document import Document


class AlbannaConversation(Document):
    """A thread of questions and answers."""

    def before_insert(self):
        from albanna.services.conversation_service import PLACEHOLDER_TITLE

        if not self.user:
            self.user = frappe.session.user
        if not self.title:
            self.title = PLACEHOLDER_TITLE

    def validate(self):
        # The owner is not editable.  A conversation that could be handed to
        # another user would be a conversation whose history that user can
        # read, and the permission hooks key off this field.
        if not self.is_new() and self.get_doc_before_save() and self.get_doc_before_save().user != self.user:
            frappe.throw(
                frappe._("A conversation's owner cannot be changed."),
                frappe.PermissionError,
            )
