"""``Albanna Question Option`` — one answer the reader may choose.

A child table: it has no permissions of its own and is reachable only
through its question, which is where the privacy rules live.
"""

from frappe.model.document import Document


class AlbannaQuestionOption(Document):
    """One choice on a question's card."""
