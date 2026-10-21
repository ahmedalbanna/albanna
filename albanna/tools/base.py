"""The tool execution port.

The chat service does not know how a tool is run.  It knows that a tool has
a name, a schema and a tier, and that running it produces a result — a
string of text the model will read, plus a flag saying whether it worked.

That indirection is what makes the app's central decision reversible.  Today
the only implementation is :mod:`albanna.tools.backend`, which calls the
ERPNext tools in :mod:`albanna.tools.erpnext`.  A second implementation that
spoke MCP over HTTP to a remote server would satisfy the same port, and the
chat service, the authority layer and the model-facing manifest would not
change by a line.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from albanna.core.authority import Principal
from albanna.core.tools import ToolSpec


@dataclass(frozen=True)
class ToolContext:
    """Who is calling, and on which site."""

    principal: Principal
    site: str
    request_id: str = ""


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call."""

    ok: bool
    content: str
    data: Any = None
    error: str = ""
    denied: bool = False

    @classmethod
    def success(cls, content: str, data: Any = None) -> ToolResult:
        return cls(ok=True, content=content, data=data)

    @classmethod
    def failure(cls, content: str, error: str, data: Any = None) -> ToolResult:
        return cls(ok=False, content=content, error=error, data=data)

    @classmethod
    def refusal(cls, content: str, error: str) -> ToolResult:
        return cls(ok=False, content=content, error=error, denied=True)


class ToolBackend(Protocol):
    """Runs a tool."""

    def call(
        self,
        spec: ToolSpec,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run one tool and return its result."""
        ...
