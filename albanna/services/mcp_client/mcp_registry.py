"""In-memory MCP tool registry with search (OpenCode-style)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


@dataclass
class McpTool:
    server: str
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"


@dataclass
class McpServer:
    name: str
    url: str  # streamable HTTP endpoint, or "" for stdio
    command: Optional[str] = None  # stdio command
    enabled: bool = True


class McpRegistry:
    def __init__(self):
        self.servers: dict[str, McpServer] = {}
        self.tools: List[McpTool] = []

    def register_server(self, server: McpServer):
        self.servers[server.name] = server

    def register_tool(self, tool: McpTool):
        # replace if exists
        self.tools = [t for t in self.tools if not (t.server == tool.server and t.name == tool.name)]
        self.tools.append(tool)

    def remove_server_tools(self, server: str):
        self.tools = [t for t in self.tools if t.server != server]

    def search(self, query: str = "", limit: int = 20) -> List[McpTool]:
        q = (query or "").lower().strip()
        if not q:
            return self.tools[:limit]
        out = []
        for t in self.tools:
            hay = f"{t.name} {t.description}".lower()
            if q in hay:
                out.append(t)
                if len(out) >= limit:
                    break
        # fuzzy fallback: token substring
        if not out and q:
            toks = re.split(r"\s+", q)
            for t in self.tools:
                hay = f"{t.name} {t.description}".lower()
                if any(tok in hay for tok in toks):
                    out.append(t)
                    if len(out) >= limit:
                        break
        return out

    def get(self, server: str, name: str) -> Optional[McpTool]:
        for t in self.tools:
            if t.server == server and t.name == name:
                return t
        return None

    def all_tools(self) -> Iterable[McpTool]:
        return list(self.tools)