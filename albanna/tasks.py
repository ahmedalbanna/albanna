"""Scheduled jobs.

Two jobs: prune the chat log, and interrupt the rows of turns that died.

The log is an audit trail, not a business record, and it grows by a row per
turn.  Conversations are *not* pruned — a user's chat history is theirs,
and it is deleted when they delete it, not when a timer decides it has
been long enough.
"""

import logging

import frappe

logger = logging.getLogger(__name__)

#: How long a chat log row is kept.
LOG_RETENTION_DAYS = 90

#: How long a turn's row may say 'running' after the turn has stopped
#: being alive.  A turn cannot outlive its own timeout, and the reader
#: hears about a dead turn a little after that; fifteen minutes is
#: generous enough not to mislabel a slow turn, and short enough that a
#: row does not go on saying 'running' for a day.
#:
#: The reaper's *cadence* is tied to this number, and the tie is asserted
#: in ``tests/test_scheduler.py``: a job that runs less often than the
#: window it is meant to close tells the ledger a lie for as long as the
#: gap between its runs.
STALE_AFTER_MINUTES = 15


def prune_chat_logs() -> None:
    """Delete chat log rows older than the retention window."""
    try:
        cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -LOG_RETENTION_DAYS)
        frappe.db.delete("Albanna Chat Log", {"creation": ("<", cutoff)})
    except Exception:
        logger.exception("Could not prune the chat logs")


def interrupt_stale_chat_logs() -> None:
    """Mark audit rows that never finished as 'interrupted'.

    A turn that dies leaves a 'running' row behind.  Those rows are
    truth — they say a turn started and did not end — but after a while
    they are no longer 'running', they are finished by dying, and the
    ledger should say so.  The cutoff is the turn timeout plus a margin,
    so a turn that is merely slow is not mislabelled.
    """
    try:
        cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-STALE_AFTER_MINUTES)
        frappe.db.sql(
            """
            update `tabAlbanna Chat Log`
            set status = 'interrupted'
            where status = 'running' and creation < %s
            """,
            (cutoff,),
        )
        frappe.db.commit()
    except Exception:
        logger.exception("Could not interrupt stale chat logs")
