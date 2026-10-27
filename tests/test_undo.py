"""What a turn's undo may do, and when there is nothing left to undo.

These are the rules the whole feature reads, and they are pure: no
database, no site.  Two readers have to agree about them — the transcript
that offers the button and the undo that carries it out — so they live in
one module and are tested here.

The rule the app follows is narrow: **the tool decides what its own undo
may be.**  The stored entry says what to do; the tool says what was done
— and only the tool can be trusted about that.

The bug this test exists for: the transcript recorded a document's name
out of the tool's envelope, and every tool names the document it touched
— so a **read** was recorded as a creation.  The undo of a turn that read
a document and changed it reverted the change correctly and then deleted
the document, because the read's entry said "delete".  The reader pressed
undo to take back a change, and the ticket was gone.
"""

from __future__ import annotations

from albanna.core.undo import is_undoable, spend


def test_a_creation_may_be_undone_by_deleting_it():
    call = {
        "name": "create_doc",
        "undo": {"action": "delete", "doctype": "Issue", "name": "ISS-2026-00003"},
    }

    assert is_undoable(call) is True


def test_a_read_may_not_be_undone_by_deleting_what_it_read():
    """The bug: a read recorded as a creation."""
    call = {
        "name": "get_doc",
        "undo": {"action": "delete", "doctype": "Issue", "name": "ISS-2026-00003"},
    }

    assert is_undoable(call) is False


def test_a_change_may_be_undone_by_writing_the_old_values_back():
    call = {
        "name": "update_doc",
        "undo": {
            "action": "update",
            "doctype": "Issue",
            "name": "ISS-2026-00003",
            "data": {"priority": "Medium"},
        },
    }

    assert is_undoable(call) is True


def test_a_bulk_change_may_be_undone_too():
    call = {
        "name": "bulk_update_doc",
        "undo": {
            "action": "update",
            "doctype": "Issue",
            "name": "ISS-2026-00003",
            "data": {"priority": "Medium"},
        },
    }

    assert is_undoable(call) is True


def test_a_change_without_the_old_values_may_not_be_undone():
    """There is nothing to write back, so there is nothing to undo."""
    call = {
        "name": "update_doc",
        "undo": {"action": "update", "doctype": "Issue", "name": "ISS-2026-00003", "data": {}},
    }

    assert is_undoable(call) is False


def test_a_submission_may_be_undone_by_cancelling_it():
    call = {
        "name": "submit_doc",
        "undo": {"action": "cancel", "doctype": "Sales Invoice", "name": "SINV-0001"},
    }

    assert is_undoable(call) is True


def test_a_delete_may_not_be_undone_by_anything():
    call = {
        "name": "delete_doc",
        "undo": {"action": "delete", "doctype": "Issue", "name": "ISS-2026-00003"},
    }

    assert is_undoable(call) is False


def test_a_cancel_may_not_be_undone_by_anything():
    call = {
        "name": "cancel_doc",
        "undo": {"action": "cancel", "doctype": "Sales Invoice", "name": "SINV-0001"},
    }

    assert is_undoable(call) is False


def test_a_call_without_an_entry_is_not_undoable():
    assert is_undoable({"name": "get_doc", "ok": True}) is False
    assert is_undoable({"name": "get_doc", "undo": None}) is False
    assert is_undoable({"name": "get_doc", "undo": "delete"}) is False


def test_an_entry_without_a_document_is_not_undoable():
    call = {"name": "create_doc", "undo": {"action": "delete", "doctype": "Issue"}}

    assert is_undoable(call) is False


def test_spending_an_entry_takes_it_out_of_the_stored_calls():
    """The undo that has been carried out is not offered again."""
    calls = [
        {"name": "get_doc", "undo": {"action": "delete", "doctype": "Issue", "name": "ISS-1"}},
        {
            "name": "update_doc",
            "undo": {
                "action": "update",
                "doctype": "Issue",
                "name": "ISS-2",
                "data": {"priority": "Medium"},
            },
        },
    ]

    remaining = spend(calls, [{"action": "reverted", "doctype": "Issue", "name": "ISS-2"}])

    assert remaining[0] == calls[0], "the read's entry is not the undo's business"
    assert "undo" not in remaining[1]
    assert remaining[1]["name"] == "update_doc", "the call itself is still kept"


def test_spending_nothing_changes_nothing():
    calls = [{"name": "create_doc", "undo": {"action": "delete", "doctype": "Issue", "name": "I"}}]

    assert spend(calls, []) == calls
