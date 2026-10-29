"""Prepare a fresh site for the site suite.

The site suite reads a Company, an Item and a Customer, and it finds
the customer's group through the customer.  A site that has just had
ERPNext installed has none of those: ERPNext's setup wizard makes them
when an operator goes through it, and its demo setup clones the first
company it finds — so on a fresh site there is nothing to clone and the
demo setup fails before it makes anything.

So this makes the smallest set the suite needs, using ERPNext's own
operations where they exist:

* the standard masters — item groups, customer groups, units of
  measure, the warehouse type — from the setup wizard's fixtures;
* a company with a chart of accounts, and the fiscal year the year
  belongs to;
* the price lists, and the defaults that name the company and its
  currency, from the setup wizard's defaults;
* one item and one customer, which the demo data would otherwise have
  provided.

Every step is skipped when the site already has what it needs, so the
script is safe to run against a site twice, and against a site that
already carries ERPNext's demo data.

    cd /path/to/frappe-bench && ./env/bin/python apps/albanna/scripts/prepare_test_site.py --site test_site

What the site suite does *not* get from this script: a submitted
Sales Invoice.  Two of its tests need one and skip themselves when
there is none.  On a site that carries ERPNext's demo data — the test
site, and production — they run.
"""

from __future__ import annotations

import argparse
import os
import sys

import frappe

COUNTRY = "United States"
CURRENCY = "USD"
COMPANY_NAME = "Albanna Test Company"
COMPANY_ABBR = "ATC"
ITEM_CODE = "Albanna Test Item"
CUSTOMER_NAME = "Albanna Test Customer"


def _say(message: str) -> None:
    print(f"prepare_test_site: {message}", flush=True)


def ensure_standard_masters() -> None:
    """The masters ERPNext's setup wizard makes for an operator."""
    if frappe.db.exists("Warehouse Type", "Transit"):
        _say("the standard masters are already there")
        return

    from erpnext.setup.setup_wizard.operations import install_fixtures

    install_fixtures.install(COUNTRY)
    _say("the standard masters are in place")


def ensure_company() -> str:
    """A company with a chart of accounts, and the fiscal year it is in."""
    companies = frappe.get_all("Company", pluck="name", limit=1)
    if companies:
        _say(f"the company {companies[0]} is already there")
        return companies[0]

    from erpnext.setup.setup_wizard.operations.company_setup import (
        create_fiscal_year_and_company,
    )

    year = frappe.utils.getdate().year
    create_fiscal_year_and_company(
        {
            "company_name": COMPANY_NAME,
            "company_abbr": COMPANY_ABBR,
            "currency": CURRENCY,
            "country": COUNTRY,
            "fy_start_date": f"{year}-01-01",
            "fy_end_date": f"{year}-12-31",
        }
    )
    company = frappe.get_all("Company", pluck="name", limit=1)[0]
    _say(f"the company {company} is in place")
    return company


def ensure_defaults(company: str) -> None:
    """The price lists, and the defaults that name the company.

    A Sales Invoice needs a price list.  ERPNext fills it in from the
    selling settings, and the selling settings take it from the first
    price list that is created — so the site needs ERPNext's own price
    lists, made by ERPNext's own operation, and the global defaults that
    say which company and currency the site trades in.
    """
    if frappe.db.exists("Price List", "Standard Selling"):
        _say("the price lists are already there")
        return

    from erpnext.setup.setup_wizard.operations import install_fixtures

    currency = frappe.db.get_value("Company", company, "default_currency") or CURRENCY
    install_fixtures.install_defaults(
        frappe._dict(
            {
                "company_name": company,
                "company_abbr": COMPANY_ABBR,
                "currency": currency,
                "country": COUNTRY,
            }
        )
    )
    _say("the price lists and the defaults are in place")


def ensure_item() -> str:
    """One item, so the suite has something to read and to sell.

    A *service*, not a stock item: a stock item has to be shipped from a
    warehouse, and the suite's documents name an item and nothing else.
    That is what the site the suite usually runs against gives it — the
    item it reads there is a service — and this is the same thing.
    """
    if frappe.db.exists("Item", ITEM_CODE):
        _say(f"the item {ITEM_CODE} is already there")
        return ITEM_CODE

    group = (
        "Services"
        if frappe.db.exists("Item Group", "Services")
        else frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"
    )
    item = frappe.new_doc("Item")
    item.item_code = ITEM_CODE
    item.item_name = ITEM_CODE
    item.item_group = group
    item.stock_uom = "Nos"
    item.is_stock_item = 0
    item.insert(ignore_permissions=True)
    _say(f"the item {item.name} is in place")
    return item.name


def ensure_customer() -> str:
    """One customer, so the suite has a customer group to find."""
    if frappe.db.exists("Customer", CUSTOMER_NAME):
        _say(f"the customer {CUSTOMER_NAME} is already there")
        return CUSTOMER_NAME

    group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
    customer = frappe.new_doc("Customer")
    customer.customer_name = CUSTOMER_NAME
    customer.customer_type = "Company"
    customer.customer_group = group
    customer.insert(ignore_permissions=True)
    _say(f"the customer {customer.name} is in place")
    return customer.name


def _sites_path(explicit: str = "") -> str:
    """Where the sites live.

    Frappe looks for a site under the *current directory* by default, so
    a script run from anywhere but the bench's ``sites`` folder needs to
    say where they are.  The bench's own convention is used first: the
    ``FRAPPE_SITES_PATH`` environment variable, then a ``sites``
    directory beside the working directory.
    """
    if explicit:
        return explicit
    from_env = os.environ.get("FRAPPE_SITES_PATH")
    if from_env:
        return from_env
    beside = os.path.join(os.getcwd(), "sites")
    if os.path.isdir(beside):
        return beside
    return "."


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a site for the site suite.")
    parser.add_argument("--site", default=os.environ.get("FRAPPE_SITE", ""))
    parser.add_argument("--sites-path", default="")
    args = parser.parse_args()

    if not args.site:
        print("Which site? Pass --site, or set FRAPPE_SITE.", file=sys.stderr)
        return 2

    # Frappe writes a site's logs *beside* the site, relative to the
    # working directory, and reads the site's configuration from there
    # too — so the working directory is the sites folder, which is where
    # the bench itself runs from.
    sites_path = _sites_path(args.sites_path)
    os.chdir(sites_path)
    frappe.init(site=args.site, sites_path=".")
    frappe.connect()
    try:
        ensure_standard_masters()
        company = ensure_company()
        ensure_defaults(company)
        ensure_item()
        ensure_customer()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
