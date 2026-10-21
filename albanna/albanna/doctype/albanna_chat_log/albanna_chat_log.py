"""``Albanna Chat Log`` — one row per turn.

An audit row, not a business record: it exists so that a System Manager can
answer "what did the assistant do, what did it cost, and who asked" without
reading anybody's conversation.  It deliberately holds no question text and
no answer text — only counts, timings and error classes.
"""

from frappe.model.document import Document


class AlbannaChatLog(Document):
    """The record of one chat turn."""
