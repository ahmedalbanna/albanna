"""The attachments' text is stored, so a reloaded thread still has it.

A turn that carried a PDF read its text and put it in the note, and the
model answered about the document.  Then the reader reloaded the thread
and asked a follow-up — and the history knew a file had been attached and
nothing about what was in it, because the note is rebuilt from stored
URLs alone.

That was honest and useless.  The text is now stored on the message row,
parallel to the URLs, and replayed when the history is loaded.

The column arrives with the schema sync, so there is nothing to move: a
row written before it existed carries no text, and the note says nothing
about readability — which is the correct answer for a row nobody looked
at.
"""

import frappe


def execute() -> None:
    if frappe.db.has_column("Albanna Message", "attachment_texts"):
        return

    # The sync adds it; this is the guard that makes the patch safe to
    # re-run on a site where it has already run.
    frappe.db.add_column("Albanna Message", "attachment_texts", "Long Text")
