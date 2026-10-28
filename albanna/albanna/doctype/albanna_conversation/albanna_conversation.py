"""``Albanna Conversation`` — one chat thread.

The owner is forced from the session on insert.

The doctype grants read and write to two roles, and no more: ``System
Manager`` outright, and ``Albanna User`` for the rows the account owns
(``if_owner``).  The hooks in ``hooks.py`` are the other half of that:
``permission_query_conditions`` narrows the *list views* to the owner's
rows, and ``has_permission`` answers the *document* question the same
way.  The permission rows and the hooks are edited together; changing
one without the other widens or breaks the other.
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
