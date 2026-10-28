"""Minimal MCP client (streamable HTTP, JSON-RPC 2.0)."""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import requests


class McpHttpClient:
    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 60):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._id = 0

    def _rpc(self, method: str, params: Optional[dict] = None) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        r = requests.post(self.url, json=payload, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result")

    def initialize(self) -> dict:
        return self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "albanna", "version": "0.1"},
        })

    def list_tools(self) -> List[dict]:
        res = self._rpc("tools/list")
        return (res or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> Any:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})