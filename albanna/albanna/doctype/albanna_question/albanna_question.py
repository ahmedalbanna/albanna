"""``Albanna Question`` — one question the assistant asked the reader.

The owner is forced from the session on insert, and cannot be changed
afterwards: the question is asked *of* somebody, and a question that
could be handed to another account is a question somebody else answers
by accident.

The answer is likewise final.  The first answer is the answer, because
the reader's choice is one choice, and a second click on a card whose
answer has already been acted on is a click that lands after the fact.
"""

import frappe
from frappe.model.document import Document


class AlbannaQuestion(Document):
    """A question waiting for the reader's answer."""

    def before_insert(self):
        if not self.user:
            self.user = frappe.session.user
        if not self.asked_at:
            self.asked_at = frappe.utils.now()

    def validate(self):
        previous = self.get_doc_before_save() if not self.is_new() else None
        if not previous:
            return

        if previous.user != self.user:
            frappe.throw(
                frappe._("A question's reader cannot be changed."),
                frappe.PermissionError,
            )

        if (
            previous.status == "Answered"
            and self.status == "Answered"
            and previous.answer_value != self.answer_value
        ):
            frappe.throw(
                frappe._("This question has already been answered."),
                frappe.PermissionError,
            )
