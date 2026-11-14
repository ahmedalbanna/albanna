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

from albanna.services.settings_service import get_settings

#: How many rows a breakdown shows.  A breakdown that lists everything
#: is a list, and the point of a breakdown is the top of it.
BREAKDOWN_LIMIT = 5

#: The table the ledger is written to.
LOG_DOCTYPE = "Albanna Chat Log"


def usage_summary() -> dict[str, Any]:
    """Month-to-date usage: the totals, and where they went.

    The totals are the month's, not all time: a number that grows for
    ever is a number nobody reads twice.

    The month is aggregated **in the database**, not row by row in
    Python.  A ledger of a million rows makes a read-every-row month
    summary a multi-second query, and the summary is opened by an
    operator who asked one question.  The grouped read returns one row
    per (provider, model, user, status) — a handful — so the query's
    cost tracks the *aggregation* the site did this month, and a large
    ledger costs no more than a small one of the same month shape.
    """
    start = _month_start()

    groups = frappe.db.sql(
        """
        select provider, model, `user`, status,
               count(*) as turns,
               sum(coalesce(input_tokens, 0) + coalesce(output_tokens, 0)) as tokens,
               sum(coalesce(cost, 0)) as cost,
               sum(coalesce(provider_cost, 0)) as provider_cost,
               sum(case when coalesce(cost, 0) = 0
                         and coalesce(input_tokens, 0) + coalesce(output_tokens, 0) > 0
                        then 1 else 0 end) as uncosted,
               max(coalesce(estimated, 0)) as estimated,
               sum(case when status = 'error' then 1 else 0 end) as errors
        from `tabAlbanna Chat Log`
        where creation >= %s
          and status not in ('running', 'interrupted')
        group by provider, model, `user`, status
        """,
        (start,),
        as_dict=True,
    )

    tokens = sum(_as_int(g.get("tokens")) for g in groups)
    # The site's own figure: the cost in the site's currency.
    cost = sum(_as_float(g.get("cost")) for g in groups)
    # The provider's own figure, in the provider's own currency.  It is
    # beside the site's and never mixed with it.
    provider_cost = sum(_as_float(g.get("provider_cost")) for g in groups)
    errors = sum(_as_int(g.get("errors")) for g in groups)
    turns = sum(_as_int(g.get("turns")) for g in groups)
    uncosted = sum(_as_int(g.get("uncosted")) for g in groups)

    return {
        "status": "ok",
        "month": start.strftime("%Y-%m"),
        "turns": turns,
        "tokens": tokens,
        "cost": round(cost, 4),
        "provider_cost": round(provider_cost, 8),
        # The price the site prices a turn with, so that a total of zero
        # can be read as "no price was set" rather than "it was free".
        "priced": any(_as_float(g.get("cost")) for g in groups),
        # True when any of the token counts is an estimate rather than a
        # number the provider reported.
        "estimated": any(_as_int(g.get("estimated")) for g in groups),
        # The turns whose cost is not known.
        "uncosted_turns": uncosted,
        "errors": errors,
        # The operator's optional monthly budget, and whether this month
        # has reached it.  A blank budget means "no limit set".
        "budget": get_settings().monthly_budget,
        "budget_exceeded": (
            get_settings().monthly_budget > 0 and cost >= get_settings().monthly_budget
        ),
        "by_model": _breakdown(groups, "model"),
        "by_user": _breakdown(groups, "user"),
    }


def _breakdown(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """The top of a breakdown: what it was, and what it cost.

    The rows are the aggregated groups, so each carries a ``turns``
    count and pre-summed tokens and cost.  Ordered by what it cost,
    because that is what the operator is looking for: the model that is
    expensive, the user that is using it.
    """
    totals: dict[str, dict[str, Any]] = {}

    for row in rows:
        name = str(row.get(field) or "") or "(unknown)"
        entry = totals.setdefault(name, {"name": name, "turns": 0, "tokens": 0, "cost": 0.0})
        entry["turns"] += _as_int(row.get("turns"))
        entry["tokens"] += _as_int(row.get("tokens"))
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
