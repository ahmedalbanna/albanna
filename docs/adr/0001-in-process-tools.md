# ADR-0001: The ERPNext tools are the app's own

Status: **Accepted** (supersedes the first version of this ADR, 2026-10-21)
Date: 2026-10-21

## Context

The app was originally built on top of the ``erpnext-mcp`` project: it
imported that project's tool functions and called them in-process, inside the
Frappe request the chat widget had already opened.

That was the right shape — the tool call ran in the *same* Frappe session as
the person who asked, so the tools saw that person's roles, permissions and
User Permissions — but it could not be published.

``erpnext-mcp`` on PyPI is a **different project**: an earlier release
(0.5.0) by another author, under the MIT licence.  The version this app
needed (3.79) exists only in one private checkout.  So a site that
installed the app from GitHub would have run ``pip install
erpnext-mcp>=3.77``, found 0.5.0 on PyPI, and either failed to install or
installed a codebase with a completely different API.  An app that cannot be
installed is not an app.

## Decision

**Implement the five tools in the app**, in ``albanna/tools/erpnext.py``,
against the framework's own APIs.

They are the small part of that project this app ever used:

| Tool | What it does |
|---|---|
| ``list_docs`` | find documents of one DocType |
| ``get_doc`` | read one document |
| ``get_doctype_meta`` | the field definitions of a DocType |
| ``run_report`` | run an ERPNext report and return its rows |
| ``create_doc`` | create a document |

Each returns the same envelope the chat service already speaks:
``{"status", "message", "data", "hints"}``.

The permissions are the framework's, and they are the *caller's*: a read
goes through ``frappe.get_list`` / ``frappe.get_doc``, and a write goes
through ``doc.insert()``.  Nothing here bypasses the permission engine.

The port is unchanged.  ``albanna/tools/base.py`` defines ``ToolBackend``,
and ``albanna/tools/backend.py`` is its one implementation; a second
implementation that spoke MCP over HTTP would satisfy the same port, and the
chat service, the authority layer and the model-facing manifest would not
change by a line.

## Consequences

**Gained**

*   The app installs anywhere.  Its only dependencies are ``requests`` and
    ``jsonschema``.
*   The app is self-contained and its licence is unambiguous: MIT, its own.
*   The permission model is *stronger* than the one it replaces.  The old
    functions bypassed Frappe's permission engine by default and relied on
    the app to switch that off; these ones never bypass it.
*   The envelopes and the error messages are the app's own, so they can be
    written for the model that reads them.

**Lost**

*   The other ~495 tools.  They were never exposed to the model, so nothing
    was lost in practice — but a future tool that *is* wanted has to be
    written here rather than imported.
*   The upstream's fixes to those tools.  The trade was worth it: a
    dependency that cannot be resolved is worth less than the bug fixes it
    would have brought.

**The cost of the split, and what pays for it**

The manifest and the implementations are in different packages, so they can
drift.  ``tests/test_tool_manifest.py`` checks them against each other: the
schema's properties against the function's parameters, the schema's
required set against the parameters the function cannot do without.  A tool
that is half-finished fails the suite rather than the first user who
reaches for it.
