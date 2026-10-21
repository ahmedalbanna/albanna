"""The HTTP interface.

Four endpoints, and every one of them gates before it does anything else.
The gate is not decoration: an endpoint that carries a user's own chat
history must not be reachable by someone who may not chat, and a gate that
some endpoints remember and others forget is a gate that fails open.
"""

from albanna.api.chat import ask, ask_stream, status
from albanna.api.widget import options

__all__ = ["ask", "ask_stream", "options", "status"]
