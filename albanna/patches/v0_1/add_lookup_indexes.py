"""An index for the one question the app asks the database most.

A Frappe table ships with the name's primary key and an index on
``creation``, and nothing else.  That is enough for a doctype that is
listed and read by name, and it is not enough for this one.

``ensure_conversation`` runs on **every** ask — it looks up the user's
conversation for the page they are on, ordering by the page's last
activity.  Without an index that is a full table scan of every
conversation ever opened, and conversations are deliberately never
pruned: a user's history is theirs, and it is deleted when they delete
it.  So the table grows without bound, and the scan with it.

The conversation list (NFR-P10) asks two more questions of these tables.
The drawer's search matches a conversation's *title* — the retrieval's
indexed columns are user, created_on and title.  And the per-thread
totals are read from ``Albanna Chat Log`` by conversation, one query for
the whole page: without an index that is a scan of every turn the site
has ever recorded, per page of the drawer.

``Albanna Message`` is a child table, and Frappe indexes child tables on
their parent — the preview query filters on it.

The patch is idempotent: ``frappe.db.add_index`` checks for the index
before creating it, so a re-run on an already-migrated site is a no-op.
"""

import frappe

#: The lookup the index is for, as ``(doctype, fields, the question it
#: answers)``.  The third element is not read by the code — it is here so
#: that the *reason* an index exists sits next to the code that adds it,
#: rather than in a commit message that ages away.
INDEXES = [
    (
        "Albanna Conversation",
        ["user", "page", "last_activity"],
        "the conversation for this user on this page, the most recent first",
    ),
    (
        "Albanna Conversation",
        ["title"],
        "the drawer's search, which matches a conversation's title",
    ),
    (
        "Albanna Chat Log",
        ["conversation"],
        "the turn totals the drawer shows for each thread on its page",
    ),
]


def execute() -> None:
    for doctype, fields, _why in INDEXES:
        try:
            frappe.db.add_index(doctype, fields)
        except Exception:
            # A site whose table was already hand-indexed, or a storage
            # engine that does not index, must not fail the migration
            # over a performance nicety.
            frappe.log_error(
                title=f"Could not index {doctype}",
                message=frappe.get_traceback(),
            )
