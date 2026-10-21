# ADR-0001: The ERPNext tools run in-process

Status: **Accepted**
Date: 2026-10-21

## Context

Albanna needs ERPNext tools.  They exist in the `erpnext-mcp` project, which
publishes ~500 of them over MCP: an HTTP server, a licence check, an
API-key authentication layer, a role gate, and a Redis-backed job registry.

The `albanna.localhost` site — the one this app is built for — is **not on
that project's licence allow-list**.  The backend answers `license
site_mismatch` for it.

Three ways to give Albanna the tools:

1. Run the MCP server as a service and talk to it over HTTP.
2. Run the MCP server in-process inside Frappe.
3. Call the tool functions directly, without the server at all.

## Decision

**Call the tool functions directly.**  `albanna/tools/erpnext_mcp.py` imports
them from `erpnext_mcp.tools.*` and calls them in the Frappe request that
opened the chat.

The server is never imported, so its licence gate, its HTTP transport, its
FastMCP dependency, its Redis client and its role gate are all simply never
loaded.

## Consequences

**Gained**

* One deployable unit.  No service to run, no port, no gateway, no licence
  server, no per-user API key, no Redis job registry.
* The tool call runs in the *same Frappe session* as the person who asked
  for it, so the tools see that person's roles, permissions and User
  Permissions.  This is not a convenience — it is the whole reason the
  approach is attractive.  Over HTTP, the backend had to be told who the
  caller was, via an API key, and the mapping was the trust boundary.
* Latency.  A tool call is a function call, not a request to another
  process.

**Lost**

* The backend's role gate.  The decision "who may call what" was made at the
  backend's edge, and calling the functions directly removes it.  Albanna
  therefore **owns that decision itself**, in `core/authority.py`.  This is
  not a detail to be tidied up later; it is the main design work of the
  app, and it is tested as such.
* The backend's write-permission default.  The tool functions bypass
  Frappe's permission engine by default, because the backend used to be the
  authority.  The adapter switches that off — see
  [ADR-0002](0002-authority-and-permissions.md).
* The backend's multi-site routing.  Albanna is single-site per process,
  which is what Frappe is.

**Kept**

The port.  `tools/base.py` defines `ToolBackend`, and the in-process
implementation is one adapter behind it.  A second implementation that
speaks MCP over HTTP would satisfy the same port, and the chat service, the
authority layer and the manifest would not change by a line.  The decision
reversible; the *sequencing* is what makes it reversible is not.

## Alternatives rejected

**Run the MCP server as a service.**  Rejected: the licence gate excludes
the target site, the operational surface is large, and the trust boundary
it provides — mapping an HTTP API key to a Frappe user — is one Albanna
already has for free, because the caller is a Frappe session.
