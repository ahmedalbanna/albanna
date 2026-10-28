"""Albanna — an ERPNext side chat, in one Frappe app.

A docked panel in the Desk that answers questions about the site's data and
acts on it when asked.

The app is the *combination* of two projects that used to meet over the
network:

  ``erpnext_mcp``
      the tool layer — ~500 ERPNext operations implemented as plain Python
      functions, each returning a JSON envelope.

  ``erpnext_mcp_connector``
      the chat layer — a floating side-chat widget, a provider abstraction for
      Ollama / OpenAI-compatible / Anthropic models, and a tool-calling loop.

Neither runs as a service here.  The tools are called *in-process*, inside
the Frappe request that the chat widget already opened, so the call runs in
the *same* Frappe session as the person who asked for it and the tools see
that person's real roles, permissions and user permissions.  The chat layer
is the connector's, re-expressed on top of a much smaller surface.

The five tools this app uses were first taken from the ``erpnext-mcp``
project.  They are now implemented in the app (``tools/erpnext.py``), because
``erpnext-mcp`` on PyPI is a *different* project — an earlier release by
another author — so the version this app needs could never be installed by a
site that was not handed it by hand.  An app that cannot be installed is
not an app.

The cost of calling the tools in-process is stated plainly in
``core/authority.py``: the backend's role gate is gone, and Albanna owns the
"who may call what" decision itself.  Everything else in the architecture
exists to keep that decision in one place.

Layers, and the dependency rule between them:

    api/          whitelisted endpoints          (interface)
    services/     the chat turn, persistence      (application)
    core/         tools, authority, messages      (domain — no Frappe)
    providers/    LLM adapters                    (ports)
    tools/        tool execution adapters         (ports)

``core/`` and ``providers/`` import nothing from Frappe and nothing from the
layers above them. That is what makes the interesting half of this app
testable on a machine with no bench, no site and no network.
"""

__version__ = "0.2.1"
