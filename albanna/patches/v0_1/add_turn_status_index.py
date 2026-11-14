"""The ledger's hot read, indexed — as its own patch, not an addition.

The unfinished-turn read (every ask and every refresh fallback) filters
``Albanna Chat Log`` by user, status and the thirty-day window.  At a
million ledger rows it cost **10.1 s per ask**; a bare ``user`` index
still scanned a heavy user's own million rows for a running turn; the
composite ``(user, status, creation)`` reads the same query in
**0.9 ms** (ADR-0101, S4).

Why a separate patch: patches run **once** per site.  The index was
measured *after* ``add_lookup_indexes`` had already executed on
production, and an entry appended to an executed patch's list is never
reached — the first production migrate after the measurement proved it,
the table left with only its PRIMARY and ``creation`` indexes.  A patch
of its own is the migration vehicle for every site, old and new; on a
fresh site ``frappe.db.add_index`` makes it a no-op the index already
exists.
"""

import frappe


def execute() -> None:
    try:
        frappe.db.add_index("Albanna Chat Log", ["user", "status", "creation"])
    except Exception:
        # A site whose table was already hand-indexed, or a storage
        # engine that does not index, must not fail the migration over a
        # performance nicety.
        frappe.log_error(
            title="Could not index Albanna Chat Log (user, status, creation)",
            message=frappe.get_traceback(),
        )
