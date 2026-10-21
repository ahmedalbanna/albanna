# ADR-0004: The site is asserted, never guessed

Status: **Accepted**
Date: 2026-10-21

## Context

A tool that resolves its site from the environment — `FRAPPE_SITE`, then
`sites/currentsite.txt` — can be pointed at the *production* site while the
request is for another one.  On this bench that file names
**`frappe.localhost` — the production site.**

The framework prefers `frappe.local.site` when the Frappe context is
initialised, which covers a web request.  It does **not** cover a worker
thread, whose `frappe.local` is fresh.

So the failure mode is specific and quiet: a tool called from a request for
`albanna.localhost`, in a thread without a Frappe context, resolves to
`frappe.localhost` and reads and writes the **production database** — with
the production site's data, in the production site's schema, while the user
is looking at a different site entirely.

There is also a subtler variant of the same thing inside the Frappe context
itself: the framework re-initialises the context when the site it resolves
to is not the site already bound.  A mismatch there tears down the
request's own context and rebuilds it on the wrong site.

## Decision

**The site is resolved once, from the request, and asserted before every
tool call.**

* `albanna/site_context.py` is the only place the site is decided.  It
  reads `frappe.local.site` and **raises** if there is none — it never falls
  back to the environment or to `currentsite.txt`.  A worker that has not
  initialised a site is a bug, and it is reported as one.
* `albanna/tools/backend.py` compares the Frappe context's site with
  the one the request was resolved for, before every call, and refuses on a
  mismatch.  The check is cheap, it runs on every call, and it fails closed.
* A background job is enqueued with its site, and Frappe's own worker
  machinery initialises that site before the job body runs.

## Consequences

* A tool can never run against a site other than the one the request is
  for.  The check is a single `!=` on a string, and it is the difference
  between a demo site and a production incident.
* The site's name travels with the request, rather than being inferred from
  the environment at the point of use.  That is the whole point: the
  environment is a *default*, and a default that points at production is
  exactly the thing that must not be consulted mid-request.
* The check is in one place, so it cannot be forgotten on a new tool.  A
  new adapter gets it by being an adapter.
