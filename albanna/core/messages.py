"""The canonical message format for a chat turn.

One dialect, one direction.  Every provider adapter translates *from* this
format into its own wire format and translates *back* before anything else
sees the result.  No foreign shape ever reaches the caller, the stored
history, or the next provider in a fallback chain.

Why OpenAI's shape is the canonical one
----------------------------------------
The canonical format is the OpenAI chat-completions shape:

    {"role": "system",    "content": "..."}
    {"role": "user",      "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [...]}
    {"role": "tool",      "tool_call_id": "call_x", "content": "..."}

Two properties decided it, and both are about *not losing information when
the provider changes*:

1.  **Tool calls carry an id.**  A tool result is paired with the assistant
    turn that asked for it by that id.  Ollama's native format has no id and
    matches a result to its call by *tool name* — which silently misroutes
    the moment a turn calls the same tool twice, and that is not an exotic
    turn: "list the customers, then list the suppliers" is two calls with
    different names but "show me SO-0001 and its items" is one tool called
    twice.  A canonical format without ids cannot represent that turn
    faithfully.

2.  **Arguments are carried as a mapping, not a string.**  Every provider
    wants a different encoding (OpenAI wants a JSON *string*, Ollama and
    Anthropic want an *object*), so the encoding is the adapter's job.  The
    canonical form holds the parsed mapping, and an unparseable argument
    string is a provider-side error rather than a silent empty call.

The rule that follows from this, and that the rest of the app obeys: the
provider adapter is the *only* place that knows a wire format exists.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]

#: The only tool-call type this app speaks.
TOOL_CALL_TYPE = "function"


def new_tool_call_id() -> str:
    """A fresh tool-call id.

    The prefix makes an id recognisable in a log line, and the hex body is
    long enough that two calls in the same turn cannot collide.
    """
    return f"call_{uuid.uuid4().hex[:24]}"


@dataclass(frozen=True)
class ToolCall:
    """A model request to run one tool."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        """The OpenAI-shaped wire form.

        ``arguments`` is a JSON *string* on this dialect, which is why the
        canonical form keeps a mapping and the wire form does the encoding.
        """
        return {
            "id": self.id,
            "type": TOOL_CALL_TYPE,
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, default=str),
            },
        }

    @classmethod
    def from_wire(cls, raw: Any) -> ToolCall:
        """Parse the OpenAI-shaped wire form.

        ``arguments`` arrives as a JSON string from OpenAI-compatible
        endpoints and as a mapping from some others.  Both are accepted; an
        unparseable string yields empty arguments, because a tool call with
        no arguments is a recoverable situation (the model retries) whereas
        raising here kills the whole turn.
        """
        if not isinstance(raw, dict):
            return cls(id=new_tool_call_id(), name="", arguments={})

        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(function.get("name") or raw.get("name") or "")
        arguments = function.get("arguments", raw.get("arguments"))

        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments.strip() else {}
            except (json.JSONDecodeError, ValueError):
                parsed = {}
        elif isinstance(arguments, dict):
            parsed = arguments
        else:
            parsed = {}

        return cls(
            id=str(raw.get("id") or new_tool_call_id()),
            name=name,
            arguments=parsed if isinstance(parsed, dict) else {},
        )


@dataclass(frozen=True)
class Message:
    """One turn in the conversation."""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""
    #: An optional image, as a base64 data URL.  Carried only on the
    #: user's question; the assistant's answer is text.  None means "no
    #: image", which is the common case and keeps the wire shape plain.
    image: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """The OpenAI-shaped wire form."""
        if self.image:
            content: Any = []
            if self.content:
                content.append({"type": "text", "text": self.content})
            content.append({"type": "image_url", "image_url": {"url": self.image}})
        else:
            content = self.content
        payload: dict[str, Any] = {"role": self.role, "content": content}
        if self.tool_calls:
            payload["tool_calls"] = [call.to_wire() for call in self.tool_calls]
        if self.role == "tool":
            payload["tool_call_id"] = self.tool_call_id
        return payload

    @classmethod
    def from_wire(cls, raw: Any) -> Message:
        """Parse the OpenAI-shaped wire form."""
        if not isinstance(raw, dict):
            return cls(role="user", content="")

        role = raw.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            role = "user"

        content = raw.get("content")
        image: str | None = None
        if content is None:
            content = ""
        elif isinstance(content, list):
            # Vision shape: a list of {type: "text"} and
            # {type: "image_url"} parts.  Reassemble into text + image.
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    text_parts.append(str(part.get("text") or ""))
                elif ptype == "image_url":
                    url = part.get("image_url")
                    if isinstance(url, dict):
                        url = url.get("url")
                    if isinstance(url, str) and url:
                        image = url
            content = "\n".join(text_parts)
        elif not isinstance(content, str):
            content = json.dumps(content, default=str)

        calls = raw.get("tool_calls")
        tool_calls: tuple[ToolCall, ...] = ()
        if isinstance(calls, list):
            tool_calls = tuple(ToolCall.from_wire(call) for call in calls)

        return cls(
            role=role,  # type: ignore[arg-type]
            content=content,
            tool_calls=tool_calls,
            tool_call_id=str(raw.get("tool_call_id") or ""),
            image=image,
        )


def system(text: str) -> Message:
    return Message(role="system", content=text)


def user(text: str, image: str | None = None) -> Message:
    return Message(role="user", content=text, image=image)


def assistant(text: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> Message:
    return Message(role="assistant", content=text, tool_calls=tool_calls)


def tool_result(call_id: str, content: str) -> Message:
    """The result of one tool call, paired with the call that asked for it."""
    return Message(role="tool", content=content, tool_call_id=call_id)


def to_wire(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialise a conversation for a provider."""
    return [message.to_wire() for message in messages]


def from_wire(messages: list[Any]) -> list[Message]:
    """Parse a conversation produced by a provider."""
    return [Message.from_wire(message) for message in messages]


def sanitize(messages: list[Message]) -> list[Message]:
    """Drop the messages that carry no information.

    A provider rejects an empty assistant turn and an empty user turn, and a
    trailing tool result whose call is gone is a protocol error.  This is the
    one place those are removed, so every provider sees the same history.

    It also repairs the two shapes that break a strict provider: consecutive
    turns with the same role are merged, and a tool result with no matching
    call in the history is dropped.
    """
    known_call_ids = {
        call.id for message in messages for call in message.tool_calls if call.id
    }

    kept: list[Message] = []
    for message in messages:
        if message.role == "tool":
            if message.tool_call_id and message.tool_call_id not in known_call_ids:
                continue
            if not message.content:
                continue
        elif message.role == "assistant":
            if not message.content and not message.tool_calls:
                continue
        else:
            if not message.content:
                continue

        if kept and kept[-1].role == message.role and message.role in ("user", "system"):
            kept[-1] = Message(
                role=message.role,
                content=f"{kept[-1].content}\n\n{message.content}",
                image=kept[-1].image or message.image,
            )
            continue

        kept.append(message)

    return kept


def as_plain_history(messages: list[Message]) -> list[Message]:
    """History reduced to what a later turn needs to know.

    A stored turn may carry the tool calls that produced it.  Replaying them
    to the model would mean replaying the tool results too — the wire
    protocol requires a result for every call — and that is a lot of
    history to carry for something the assistant's own answer already
    says.  So the calls are dropped and the answer is kept.

    This applies to *history only*.  Inside the turn that is running, the
    tool calls and their results are part of the conversation and are sent
    as they are.
    """
    return [
        Message(role=message.role, content=message.content, image=message.image)
        if message.role == "assistant"
        else message
        for message in messages
    ]
