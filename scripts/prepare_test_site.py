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
  provided;
* one submitted Sales Invoice, because two of the suite's tests read
  one and skip themselves when the site has none;
* one field on Customer that the form will not let a person change,
  because the suite's test for that refusal needs one to refuse;
* a provider key that is not a real key, because the suite's test for
  the key's redaction needs a key to redact.

Every step is skipped when the site already has what it needs, so the
script is safe to run against a site twice, and against a site that
already carries ERPNext's demo data.  Nothing it writes overwrites
what is already there: a site with a real provider key keeps it.

    cd /path/to/frappe-bench && ./env/bin/python apps/albanna/scripts/prepare_test_site.py --site test_site

Why the invoice and the read-only field are made *here* rather than in
the tests: the suite deliberately does not submit an invoice of its own
— the submission runs whatever hooks the site's apps put on it, and a
test that depends on the app set is a test that breaks when the app set
changes — and it deliberately does not depend on ERPNext's field
layout, which is ERPNext's business and may change.  A gate that skips
the tests it cannot set up is a gate that quietly stops testing them,
so the site is prepared instead and the tests run.
"""

from __future__ import annotations

import argparse
import os
import sys

import frappe


def _read_only_probe_name() -> str:
    """The name of the read-only probe field, from the suite itself."""
    from albanna.tests.base import READ_ONLY_PROBE

    return READ_ONLY_PROBE


COUNTRY = "United States"
CURRENCY = "USD"
COMPANY_NAME = "Albanna Test Company"
COMPANY_ABBR = "ATC"
ITEM_CODE = "Albanna Test Item"
CUSTOMER_NAME = "Albanna Test Customer"

#: The field the read-only test refuses to write.  It is a custom field
#: so that the test does not depend on ERPNext's Customer layout, which
#: is ERPNext's business and may change under the suite.  The name
#: comes from the suite itself, so the two cannot drift apart.
READ_ONLY_PROBE = _read_only_probe_name()

#: A provider key that is not a real key.  The redaction test needs a
#: key to redact; it never calls the provider, and a real key has no
#: business being written to a site by a preparation script.
NOT_A_REAL_KEY = "sk-albanna-site-preparation-not-a-real-key"


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


def report_customer_meta(label: str) -> None:
    """Say what the site's Customer looks like.

    The read-only test reads the Customer's fields, so what they are
    decides whether that test runs.  A site that says it has no
    read-only field is saying something about the site, and it should
    say it out loud — a gate that quietly stops testing a thing is
    worse than a gate that fails.

    The label says *when* the report was taken, because the two
    reports are not the same: a site that has just had ERPNext
    installed has a cached Customer meta from before ERPNext's fields
    were synced, and the cache is not invalidated by the sync.  So the
    first report may show a Customer with no fields at all — which is
    a stale cache, not a site — and the second, taken after the cache
    is cleared, shows the real one.
    """
    meta = frappe.get_meta("Customer")
    read_only = [df.fieldname for df in meta.fields if getattr(df, "read_only", 0)]
    _say(
        f"the customer has {len(meta.fields)} fields, {len(read_only)} of them read-only ({label})"
    )
    if read_only:
        _say(f"the read-only fields are: {', '.join(read_only)}")


def clear_customer_meta_cache() -> None:
    """Throw away the site's cached Customer meta.

    A fresh site has one stale entry: the Customer meta as it was
    before ERPNext synced its fields.  The framework caches a doctype's
    meta when the doctype is created and does not invalidate that entry
    when the fields arrive, so a read that happens before the cache is
    cleared sees a Customer with no fields — and the read-only test,
    which reads the Customer's fields, skips itself and says so.

    That is what happened in the CI, and it was the whole of the skip:
    the site's Customer was fine, and the cache was not.
    """
    frappe.clear_cache(doctype="Customer")


def ensure_read_only_probe() -> None:
    """A field on Customer that the form will not let a person change.

    The suite has a test for the app's refusal to write a read-only
    field — the chat must not be a way around a field the form locks.
    The test needs one to refuse.  ERPNext's Customer has five, but
    that is ERPNext's layout: a test that depends on it skips itself
    the day ERPNext moves them, and a skipped test is a test that
    quietly stopped testing anything.  So the site is given a field
    whose only job is to be read-only.
    """
    if frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": READ_ONLY_PROBE}):
        _say("the read-only probe is already there")
        return

    field = frappe.new_doc("Custom Field")
    field.dt = "Customer"
    field.fieldname = READ_ONLY_PROBE
    field.label = "Albanna Read Only Probe"
    field.fieldtype = "Data"
    field.read_only = 1
    field.insert(ignore_permissions=True)
    _say("the read-only probe is in place")


def ensure_submitted_invoice(company: str, customer: str, item: str) -> None:
    """One submitted Sales Invoice, so the tests that read one do not skip.

    The suite reads a submitted invoice; it does not submit one, because
    the submission runs whatever hooks the site's apps put on it.  Here
    the invoice is made by the site's preparation, and the tests read
    it.
    """
    if frappe.db.exists("Sales Invoice", {"docstatus": 1}):
        _say("a submitted sales invoice is already there")
        return

    currency = frappe.db.get_value("Company", company, "default_currency") or CURRENCY
    price_list = (
        frappe.db.get_single_value("Selling Settings", "selling_price_list")
        or frappe.db.get_value("Price List", {"selling": 1}, "name")
        or "Standard Selling"
    )

    invoice = frappe.new_doc("Sales Invoice")
    invoice.company = company
    invoice.currency = currency
    invoice.customer = customer
    invoice.selling_price_list = price_list
    invoice.append("items", {"item_code": item, "qty": 1, "rate": 10})
    invoice.insert(ignore_permissions=True)
    invoice.submit()
    _say(f"the sales invoice {invoice.name} is submitted")


def ensure_provider_key() -> None:
    """A provider key for the redaction test to redact.

    The test checks that a key the provider quotes in its refusal never
    reaches the chat log.  It needs a key to quote, and it never calls
    the provider — so a key that is not a real key is enough, and a
    real key has no business being written here.  A site that already
    has a key keeps it.
    """
    from frappe.utils.password import get_decrypted_password

    existing = get_decrypted_password(
        "Albanna Settings", "Albanna Settings", "api_key", raise_exception=False
    )
    if existing:
        _say("the site already has a provider key")
        return

    from frappe.utils.password import set_encrypted_password

    set_encrypted_password("Albanna Settings", "Albanna Settings", NOT_A_REAL_KEY, "api_key")
    _say("a provider key that is not a real key is in place")


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
        item = ensure_item()
        customer = ensure_customer()
        report_customer_meta("before the probe")
        ensure_read_only_probe()
        clear_customer_meta_cache()
        report_customer_meta("after the probe and a cache clear")
        ensure_submitted_invoice(company, customer, item)
        ensure_provider_key()
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
