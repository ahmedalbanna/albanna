"""Which site is this?

One function, one answer, and every call site uses it.

The reason this needs to exist at all: the ``erpnext_mcp`` tool functions
resolve their site through ``get_site()``, which reads ``FRAPPE_SITE`` and
then ``sites/currentsite.txt`` — and on this bench that file names the
*production* site.  ``get_site()`` does prefer ``frappe.local.site`` when
the Frappe context is initialised, which covers a web request, but it does
not cover a worker thread whose ``frappe.local`` is fresh.

So the site is resolved once, here, from the request — never from the
environment — and the tool adapter asserts it before every call.  A
mismatch is an error, not a redirect.
"""

from __future__ import annotations

import frappe


def current_site() -> str:
    """The site this request is bound to.

    Raises rather than guessing.  A fallback to ``currentsite.txt`` here
    would reintroduce exactly the bug this module exists to prevent: a
    request for one site silently reading and writing another.
    """
    site = str(getattr(frappe.local, "site", "") or "").strip()
    if not site:
        raise RuntimeError(
            "No site is bound to this request. "
            "A background job must be enqueued with an explicit site."
        )
    return site


def default_company() -> str:
    """The company the site is working in, if there is one.

    Used to tell the model which company it is looking at, so that an
    answer about "the sales" is about *this* company's sales.
    """
    try:
        companies = frappe.get_all("Company", pluck="name", limit=1)
    except Exception:
        return ""
    return companies[0] if companies else ""


def default_currency(company: str = "") -> str:
    """The currency the site's documents are in.

    Told to the model, because a document's currency has to match its
    company's and the model is the one who fills the field in.  A site whose
    company is in one currency and whose global default is in another will
    refuse the document the model writes, and the error it gives
    ("Party Account … currency (YER) and document currency (USD) should be
    same") is not something a model can act on.
    """
    try:
        if not company:
            company = default_company()
        if not company:
            return ""
        currency = frappe.db.get_value("Company", company, "default_currency")
    except Exception:
        return ""
    return str(currency or "")
