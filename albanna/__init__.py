"""Albanna — an ERPNext side chat, in one Frappe app.

This app is the *combination* of two projects that used to meet over the
network:

  ``erpnext_mcp``
      the tool layer — ~500 ERPNext operations implemented as plain Python
      functions decorated with ``@with_frappe``, each returning a JSON
      envelope.

  ``erpnext_mcp_connector``
      the chat layer — a floating side-chat widget, a provider abstraction for
      Ollama / OpenAI-compatible / Anthropic models, and a tool-calling loop.

Albanna does not run either of them as a service. It imports the tool
functions and calls them in-process, inside the Frappe request that the chat
widget already opened. That removes the MCP HTTP server, the gateway, the
per-user API keys, the licence check and the Redis job registry — and it
replaces them with one thing the network topology could not give us: the tool
call runs in the *same* Frappe session as the person who asked for it, so the
tools see that person's real roles, permissions and user permissions.

The cost of that choice is stated plainly in ``core/authority.py``: the
backend's role gate is gone, and Albanna owns the "who may call what"
decision itself. Everything else in the architecture exists to keep that
decision in one place.

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

__version__ = "0.1.0"
