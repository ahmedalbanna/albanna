"""Pure helpers for comparing a document before and after a change.

These are the shapes the approval card and the result envelope speak in:
a mapping of fieldname to ``{"before": ..., "after": ...}``, for the fields
that actually changed.  Kept here, free of Frappe, so they can be tested
without a site.
"""


def values_differ(current, value) -> bool:
    """Whether *value* differs from the document's current value.

    Compared as text, because the model sends text and the document holds
    whatever the framework keeps: a date is a ``date`` in one and a string
    in the other, and "2026-10-21" is the same date either way.  An empty
    value and a missing value are the same thing.
    """
    if current is None or current == "":
        return not (value is None or value == "")
    if value is None or value == "":
        return True
    return str(current) != str(value)


def diff_fields(before, after, requested) -> dict:
    """The fields in *requested* whose value changed between *before* and
    *after*.

    Returns ``{fieldname: {"before": ..., "after": ...}}``.  A field that
    is not in *requested* is never included, even if it changed; and a
    field whose value did not change is never included, even if it was
    requested.  That is what makes the diff a report of *the change the
    reader asked for*, and nothing else.
    """
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    requested = requested if isinstance(requested, (list, tuple, set)) else []
    result = {}
    for field in requested:
        b = before.get(field)
        a = after.get(field)
        if values_differ(b, a):
            result[field] = {"before": b, "after": a}
    return result