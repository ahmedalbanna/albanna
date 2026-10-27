"""What a turn's undo may do, and when there is nothing left to undo.

Undo is the one feature in the app that *removes* something the assistant
did, so its rules live in one place and both sides of the feature read
them: the endpoint that performs the undo and the transcript that offers
it.  A rule that lives in two places is a rule that will be true in one of
them.

**The tool decides what its own undo may be.**  The stored entry says what
to do; the tool says what was done — and only the tool can be trusted
about that.  An entry that says "delete" for a *read* is a bug in the
entry, and an undo that obeyed it would delete a document the turn had
only looked at.  The reader pressed undo to take back a change, and a
ticket was gone.

So the rule is narrow, and it is the same rule everywhere:

*   ``create_doc`` may be undone by deleting the document;
*   ``update_doc`` and ``bulk_update_doc`` by writing the old values back;
*   ``submit_doc`` by cancelling;
*   nothing else may be undone at all.

A cancel is not an undo, an amend is not an undo, and a delete cannot be
taken back by anything this app offers — so the reader is not offered a
button that cannot be honest.

**An undo is spent once it has been used.**  The entry is taken out of the
stored tool calls when it has been carried out, so a turn is offered for
undo only while there is still something to take back.  A button that
stays after the undo says "you can take this back" about a change that has
already been taken back, and the reader is left clicking a button that
does nothing.

Nothing here touches the database: these are the rules, and the rules are
what the transcript, the live panel and the undo itself all have to agree
about.
"""

from __future__ import annotations

from typing import Any

#: The tool that may be undone by each action.
#:
#: The mapping is the rule; a stored entry that asks for an action its own
#: tool does not allow is refused.
UNDO_BY_ACTION: dict[str, tuple[str, ...]] = {
    "delete": ("create_doc",),
    "update": ("update_doc", "bulk_update_doc"),
    "cancel": ("submit_doc",),
}


def entry(call: Any) -> dict[str, Any] | None:
    """The undo entry of a stored tool call, if it has one."""
    if not isinstance(call, dict):
        return None
    undo = call.get("undo")
    return undo if isinstance(undo, dict) else None


def is_undoable(call: Any) -> bool:
    """Whether this stored tool call may still be undone.

    The same question the undo asks, asked the same way: the entry says
    what it wants, the tool says whether it may have it.
    """
    undo = entry(call)
    if not undo:
        return False

    action = str(undo.get("action") or "").strip()
    allowed = UNDO_BY_ACTION.get(action)
    if not allowed:
        return False

    tool = str(call.get("name") or "").strip()
    if tool not in allowed:
        return False

    doctype = str(undo.get("doctype") or "").strip()
    name = str(undo.get("name") or "").strip()
    if not doctype or not name:
        return False

    if action == "update":
        data = undo.get("data")
        return isinstance(data, dict) and bool(data)

    return True


def spend(calls: list[Any], spent: list[dict[str, Any]]) -> list[Any]:
    """The stored calls with the undo entries of *spent* taken out.

    *spent* is the list of entries the undo carried out.  An entry that
    was carried out is spent: the change it would take back has been
    taken back, and offering it again would offer a second undo of the
    same change.
    """
    if not spent:
        return calls

    keys = {
        (str(item.get("doctype") or "").strip(), str(item.get("name") or "").strip())
        for item in spent
    }

    remaining: list[Any] = []
    for call in calls:
        undo = entry(call)
        if not undo:
            remaining.append(call)
            continue
        key = (
            str(undo.get("doctype") or "").strip(),
            str(undo.get("name") or "").strip(),
        )
        if key in keys:
            call = {k: v for k, v in call.items() if k != "undo"}
        remaining.append(call)
    return remaining
