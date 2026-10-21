"""The cost in the ledger is now the site's currency.

The cost column used to hold what the provider reported, in the
provider's own currency, in a column the Desk shows as the site's
currency — a dollar in a riyals ledger.  The column now holds the
site's own figure, priced from the tokens, and the provider's number
has a column of its own.

So the old rows are moved: the number in ``cost`` was the provider's,
and it belongs in ``provider_cost``.  The site's cost of those turns is
not recoverable — the site had no price for them — so it is left at
zero, which says "not known" rather than "free".
"""

import frappe


def execute() -> None:
    if not frappe.db.has_column("Albanna Chat Log", "provider_cost"):
        # The column arrives with the schema; nothing to move yet.
        return

    frappe.db.sql(
        """
        update `tabAlbanna Chat Log`
        set provider_cost = cost, cost = 0
        where ifnull(provider_cost, 0) = 0 and ifnull(cost, 0) != 0
        """
    )
