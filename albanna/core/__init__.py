"""The core domain.

Everything in this package is free of Frappe: no ``import frappe``, no
database, no cache, no session.  That is a deliberate constraint, not an
accident of layering — the interesting half of a chat app (what a tool is,
who may call it, what a turn looks like, how a provider's answer is shaped)
is exactly the half that is hard to test once a site is involved.

The rule that keeps it true: ``core/`` imports from the standard library and
from nothing else in this app — not Frappe, not ``providers/``, not
``tools/``.  A pull request that adds ``import frappe`` to this package is a
pull request that made the domain untestable, and it should be rejected on
that ground alone.

The dependency arrow points one way, downwards:

    api/  ->  services/  ->  {providers/, tools/}  ->  core/

``providers/`` and ``tools/`` both depend on ``core/`` for the message and
tool types they speak in; neither depends on the other, and neither depends
on ``services/``.

``core/`` also never imports ``erpnext_mcp``.  The tool *implementations*
live behind the :mod:`albanna.tools` port, and the tool *manifest* — the
names, descriptions, schemas, tiers and role requirements the model sees —
lives here, in plain data.  The two are checked against each other by a
test, so neither can drift from the other without the suite going red.
"""
