"""The attachment fields are named for what they hold, not for one type.

``image_url`` held the addresses of stored Frappe Files from the day
PDFs were accepted, and ``had_image`` recorded in the audit row that a
question "had an image" when it had a PDF.  The names said one thing
about a field that held another, and the app's own vocabulary
everywhere else — ``store_attached_file``, ``check_attachments``,
``attachment_note`` — already said "attachment".

So the fields are renamed to match, and the data moves with them.

Two shapes, because Frappe stores the two differently:

* a normal DocType's fields are columns on its own table, and
  ``frappe.db.rename_column`` moves the column and its data in one
  ``ALTER TABLE ... CHANGE COLUMN``;
* a Single DocType's fields are rows in ``tabSingles`` keyed by
  (doctype, field), so there is no column to rename — the row's key
  moves.

Both are guarded, so the patch is safe on a site that never had the
old names (a fresh install) and safe to re-run.
"""

import frappe

#: (doctype, old fieldname, new fieldname, is the new column a number).
#:
#: The last one decides what "still empty" means when the data is copied
#: across: a Check column is empty at zero and a text column is empty at
#: null or the empty string.  One test for both would compare a string
#: to a number, and MariaDB answers that by coercing the string — so
#: ``'abc' = 0`` comes back true and a real value reads as empty.
COLUMNS = (
    ("Albanna Message", "image_url", "attachment_urls", False),
    ("Albanna Chat Log", "had_image", "had_attachment", True),
)

#: (doctype, old fieldname, new fieldname) for the Single, whose values
#: are rows in ``tabSingles`` rather than columns.
SINGLES = (
    ("Albanna Settings", "image_support", "attachment_support"),
    ("Albanna Settings", "max_image_size_kb", "max_attachment_size_kb"),
)


def execute() -> None:
    for doctype, old, new, numeric in COLUMNS:
        _rename_column(doctype, old, new, numeric)

    for doctype, old, new in SINGLES:
        _move_single(doctype, old, new)


def _rename_column(doctype: str, old: str, new: str, numeric: bool) -> None:
    """Rename a column, keeping its data, when the old column is there."""
    if not frappe.db.has_column(doctype, old):
        # Either a fresh install that never had the old name, or a site
        # this patch has already run on.  Both are fine.
        return

    if frappe.db.has_column(doctype, new):
        # The schema sync added the new name before this patch could
        # rename into it — the state a failed first attempt leaves
        # behind, because the sync runs after the patch and a rollback
        # undoes the rename without undoing the sync.  So the newcomer
        # is there and empty, and the column with the data still has the
        # old name.
        #
        # Move the data across, then drop the old column: two columns
        # for one field is a schema nobody can read, and Frappe's sync
        # does not drop a column the DocType no longer names.
        _copy_across(doctype, old, new, numeric)
        frappe.db.sql_ddl(f"alter table `tab{doctype}` drop column `{old}`")
        return

    frappe.db.rename_column(doctype, old, new)


def _copy_across(doctype: str, old: str, new: str, numeric: bool) -> None:
    """Fill the new column from the old one, where the new one is empty.

    Only the empty rows are filled.  The app already writes the new
    name, so a row written between the sync and this patch holds a real
    value that must not be overwritten with the old column's null.
    """
    if numeric:
        where = f"`{new}` = 0 and `{old}` = 1"
    else:
        where = f"ifnull(`{new}`, '') = '' and ifnull(`{old}`, '') != ''"

    frappe.db.sql(f"update `tab{doctype}` set `{new}` = `{old}` where {where}")


def _move_single(doctype: str, old: str, new: str) -> None:
    """Move a Single's stored value from one fieldname to another.

    ``tabSingles`` is not a DocType, so the ORM cannot be pointed at it:
    ``frappe.db.exists`` and ``get_value`` build a query against a meta
    that does not exist and fail on a column the table never had.  Raw
    SQL, and only raw SQL.
    """
    held = frappe.db.sql(
        "select `value` from `tabSingles` where `doctype` = %s and `field` = %s",
        (doctype, old),
    )
    if not held:
        # Nothing was ever stored under the old name — a fresh install,
        # or a site this patch has already run on.
        return

    already = frappe.db.sql(
        "select 1 from `tabSingles` where `doctype` = %s and `field` = %s",
        (doctype, new),
    )
    if already:
        return

    frappe.db.sql(
        "update `tabSingles` set `field` = %s where `doctype` = %s and `field` = %s",
        (new, doctype, old),
    )
