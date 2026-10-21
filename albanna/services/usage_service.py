"""What the chat has cost, and who spent it.

Every turn writes a row: the model, the tokens, the cost, the duration,
whether it worked.  A ledger is a list of rows, and an operator does not
want a list of rows — they want the month's total, and they want to know
which model and which user it went to.

So this is the read side of the ledger.  Read-only, and it says what it
does not know: a turn whose cost the provider did not report is a turn
whose cost is **not known**, and a ledger that shows a zero for it is
saying something the operator would believe.

The cost is the provider's own — its currency, its own reckoning — and
not the site's.  A provider that bills in dollars and a site that keeps
its books in riyals are two currencies, and the ledger records the
number the provider sent because that is the number there is.
"""

from __future__ import annotations

from typing import Any

import frappe

#: How many rows a breakdown shows.  A breakdown that lists everything
#: is a list, and the point of a breakdown is the top of it.
BREAKDOWN_LIMIT = 5

#: The table the ledger is written to.
LOG_DOCTYPE = "Albanna Chat Log"


def usage_summary() -> dict[str, Any]:
    """Month-to-date usage: the totals, and where they went.

    The totals are the month's, not all time: a number that grows for
    ever is a number nobody reads twice.
    """
    start = _month_start()

    rows = frappe.db.sql(
        f"""
        select provider, model, `user`, status,
               input_tokens, output_tokens, cost, estimated, duration_ms
        from `tab{LOG_DOCTYPE}`
        where creation >= %s
        """,
        (start,),
        as_dict=True,
    )

    tokens = sum(_as_int(row.get("input_tokens")) + _as_int(row.get("output_tokens")) for row in rows)
    cost = sum(_as_float(row.get("cost")) for row in rows)
    errors = sum(1 for row in rows if row.get("status") == "error")

    # A cost of zero with tokens recorded is a cost the provider did not
    # report, and the operator is told so rather than shown a number
    # that reads like "free".
    uncosted = sum(
        1
        for row in rows
        if _as_float(row.get("cost")) == 0
        and (_as_int(row.get("input_tokens")) + _as_int(row.get("output_tokens"))) > 0
    )

    return {
        "status": "ok",
        "month": start.strftime("%Y-%m"),
        "turns": len(rows),
        "tokens": tokens,
        "cost": round(cost, 4),
        # True when any of the token counts is an estimate rather than a
        # number the provider reported.
        "estimated": any(_as_int(row.get("estimated")) for row in rows),
        # The turns whose cost is not known.
        "uncosted_turns": uncosted,
        "errors": errors,
        "by_model": _breakdown(rows, "model"),
        "by_user": _breakdown(rows, "user"),
    }


def _breakdown(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """The top of a breakdown: what it was, and what it cost.

    Ordered by what it cost, because that is what the operator is
    looking for: the model that is expensive, the user that is using it.
    """
    totals: dict[str, dict[str, Any]] = {}

    for row in rows:
        name = str(row.get(field) or "") or "(unknown)"
        entry = totals.setdefault(name, {"name": name, "turns": 0, "tokens": 0, "cost": 0.0})
        entry["turns"] += 1
        entry["tokens"] += _as_int(row.get("input_tokens")) + _as_int(row.get("output_tokens"))
        entry["cost"] += _as_float(row.get("cost"))

    ordered = sorted(totals.values(), key=lambda entry: entry["cost"], reverse=True)
    for entry in ordered:
        entry["cost"] = round(entry["cost"], 4)
    return ordered[:BREAKDOWN_LIMIT]


def _month_start() -> Any:
    """The first of this month, at the start of the day."""
    from datetime import datetime

    import frappe.utils

    today = frappe.utils.nowdate()
    return datetime.strptime(f"{today[:7]}-01", "%Y-%m-%d")


def _as_int(value: Any) -> int:
    """An integer, or zero."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    """A number, or zero."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
