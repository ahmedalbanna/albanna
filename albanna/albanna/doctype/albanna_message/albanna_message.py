"""``Albanna Message`` — one turn of a conversation.

A child table: it has no permissions of its own and is reachable only
through its parent conversation, which is where the privacy rules live.
"""

from frappe.model.document import Document


class AlbannaMessage(Document):
    """One message in a conversation."""
