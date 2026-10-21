"""Scheduled jobs.

One job: prune the chat log.

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


def prune_chat_logs() -> None:
    """Delete chat log rows older than the retention window."""
    try:
        cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -LOG_RETENTION_DAYS)
        frappe.db.delete("Albanna Chat Log", {"creation": ("<", cutoff)})
    except Exception:
        logger.exception("Could not prune the chat logs")
