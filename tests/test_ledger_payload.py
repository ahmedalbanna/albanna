"""The ledger's payload is merged, not overwritten.

The row that records a turn is written by three writers: the worker as
the turn runs, the endpoint that takes the reader's decision, and the
worker again when the turn ends.  What must not happen is one of them
overwriting another's fact — and the fact that matters most is the
reader's answer, because an answer that is lost is an answer nobody
hears about.

So the merge is a rule about data, and a rule about data is proved
here, without a site and without a database: what a merge does to two
lists is the whole of it.

The names are private because the public face of the module is the
ledger's reads and writes.  A test may look at the innards; a caller
may not.
"""

from __future__ import annotations

from albanna.services.audit_rows import _append_calls, _merge_approvals


def test_a_decision_updates_the_approval_it_belongs_to():
    """The answer goes into the record it answers, not beside it.

    A second record for the same request would leave the row with an
    approval that says nothing and a decision that belongs to nothing —
    and the panel, which reads the approval, would name nothing.
    """
    merged = _merge_approvals(
        [{"request_id": "req-1", "tool": "update_doc", "doctype": "Customer"}],
        [{"request_id": "req-1", "decision": "approve"}],
    )

    assert merged == [
        {
            "request_id": "req-1",
            "tool": "update_doc",
            "doctype": "Customer",
            "decision": "approve",
        }
    ]


def test_an_approval_for_another_request_is_a_record_of_its_own():
    """Two writes in one turn are two approvals.

    Merging them into one would mean the first write's answer being
    read as the second write's.
    """
    merged = _merge_approvals(
        [{"request_id": "req-1", "tool": "update_doc"}],
        [{"request_id": "req-2", "tool": "create_doc"}],
    )

    assert [record["request_id"] for record in merged] == ["req-1", "req-2"]


def test_a_record_without_a_request_id_is_not_kept():
    """A record nobody can answer is a record nobody reads.

    The reader's answer is bound to a request, so an approval without
    one can never be marked as answered — and a row that holds it says
    "something was asked" without saying what.
    """
    merged = _merge_approvals([], [{"tool": "update_doc", "decision": "approve"}])

    assert merged == []


def test_the_same_call_is_not_recorded_twice():
    """A call recorded twice is one call in the ledger's eyes.

    The row's list grows as the turn runs, and a turn that is retried
    must not make the row say it did the same thing twice.
    """
    call = {
        "name": "update_doc",
        "ok": True,
        "write": True,
        "documents": [{"doctype": "Customer", "name": "CUST-0001"}],
    }

    calls = _append_calls([call], [dict(call)])

    assert len(calls) == 1


def test_a_call_is_added_to_the_ones_the_row_already_holds():
    """The row's list grows; it is not replaced.

    The list is what a turn that dies mid-way leaves behind, so the
    calls that came before the last one have to still be there.
    """
    first = {
        "name": "update_doc",
        "ok": True,
        "documents": [{"doctype": "Customer", "name": "CUST-0001"}],
    }
    second = {
        "name": "update_doc",
        "ok": True,
        "documents": [{"doctype": "Customer", "name": "CUST-0002"}],
    }

    calls = _append_calls([first], [second])

    assert [call["documents"][0]["name"] for call in calls] == ["CUST-0001", "CUST-0002"]
