"""Service layer: sync MCP servers into registry, search, dispatch (Frappe-friendly)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .mcp_registry import McpRegistry, McpServer, McpTool
from .mcp_client import McpHttpClient

# Module-level singleton registry (in production, store in frappe cache / redis)
_REGISTRY = McpRegistry()


def get_registry() -> McpRegistry:
    return _REGISTRY


def register_server(name: str, url: str, enabled: bool = True):
    _REGISTRY.register_server(McpServer(name=name, url=url, enabled=enabled))


def sync_server(name: str, url: str, headers: Optional[Dict[str, str]] = None):
    """Fetch tools from an MCP server and populate registry."""
    client = McpHttpClient(url, headers=headers)
    try:
        client.initialize()
    except Exception:
        pass  # some servers skip initialize
    tools = client.list_tools()
    _REGISTRY.remove_server_tools(name)
    for t in tools:
        _REGISTRY.register_tool(McpTool(
            server=name,
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("inputSchema", {}) or {},
        ))
    return len(tools)


def search_tools(query: str = "", limit: int = 20) -> List[dict]:
    out = []
    for t in _REGISTRY.search(query, limit):
        out.append({
            "server": t.server,
            "name": t.name,
            "qualified": t.qualified,
            "description": t.description,
            "input_schema": t.input_schema,
        })
    return out


def dispatch_tool(server: str, name: str, arguments: dict,
                  url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    """Execute a tool on a given MCP server and return raw result."""
    client = McpHttpClient(url, headers=headers)
    return client.call_tool(name, arguments)


# Frappe whitelisted wrappers would go here, e.g.:
# @frappe.whitelist()
# def search_mcp_tools(query="", limit=20):
#     return search_tools(query, limit)
#
# @frappe.whitelist()
# def call_mcp_tool(server, name, arguments):
#     # resolve url from Mcp Server doctype by name
#     ...
#     return dispatch_tool(server, name, json.loads(arguments), url)