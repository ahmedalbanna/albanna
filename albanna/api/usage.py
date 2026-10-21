"""The chat's usage: what it cost, and where it went.

The ledger is written by every turn, and it is a ledger: a list of rows
that nobody wants to read.  The operator wants the month's total, and
they want to know which model and which user it went to.

This is the read side of that ledger, and it is the operator's: a
System Manager, and nobody else.  A reader who may use the chat has no
business knowing what the site spends on it.
"""

from __future__ import annotations

from typing import Any

import frappe

from albanna.permissions import require_system_manager


@frappe.whitelist()
def summary() -> dict[str, Any]:
    """Month-to-date usage: the totals, and the breakdowns.

    Read-only, and it says what it does not know: the turns whose cost
    the provider did not report are counted apart, so a total of zero
    is never mistaken for a month that cost nothing.
    """
    require_system_manager()

    from albanna.services.usage_service import usage_summary

    return usage_summary()
