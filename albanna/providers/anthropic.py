"""The Anthropic adapter — the native ``/messages`` API.

Kept because Anthropic's tool use is the best of the three providers, and
because a fallback chain that only spans one vendor is not a fallback chain.
It is also the dialect that differs most from the canonical format, which is
exactly why having it is useful: the canonical format was not designed
around one vendor's API.

The differences, all handled here and nowhere else:

*   The system prompt is a **top-level parameter**, not a message.
*   Tool schemas are ``input_schema``, not ``parameters``.
*   A tool call is a ``tool_use`` content block carrying an **id** and an
    ``input`` object.
*   A tool result is a ``tool_result`` block inside a **user** turn, and
    several results belong in the *same* user turn.

The last one is the fiddly part, and it is why this adapter builds the
message list rather than mapping it one-to-one.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import requests

from albanna.core.errors import (
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnreachable,
)
from albanna.core.messages import Message, ToolCall
from albanna.core.tools import ToolSpec
from albanna.providers.base import (
    Completion,
    ProviderConfig,
    StreamDelta,
    StreamDone,
    Usage,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class AnthropicProvider:
    """Talks to Anthropic's native messages endpoint."""

    kind = "anthropic"

    def complete(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Completion:
        payload = self._payload(config, messages, tools, stream=False)
        data = self._post(config, payload)
        return Completion(
            message=self._parse_message(data.get("content")),
            provider=config.kind,
            model=str(data.get("model") or config.model),
            usage=self._parse_usage(data.get("usage")),
        )

    def stream(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Iterator[StreamDelta | StreamDone]:
        payload = self._payload(config, messages, tools, stream=True)
        response = self._open_stream(config, payload)

        chunks: list[str] = []
        partial_calls: dict[int, dict[str, Any]] = {}
        usage: Usage | None = None
        model = config.model

        for event in self._read_events(response):
            kind = event.get("type")
            if kind == "message_start":
                model, usage = self._on_message_start(event, model, usage)
            elif kind == "content_block_start":
                self._on_block_start(event, partial_calls)
            elif kind == "content_block_delta":
                text = self._on_block_delta(event, partial_calls)
                if text:
                    chunks.append(text)
                    yield StreamDelta(text=text)
            elif kind == "message_delta":
                usage = self._parse_usage(event.get("usage")) or usage

        calls = self._build_calls(partial_calls)
        content = "".join(chunks)
        message = Message(role="assistant", content=content, tool_calls=calls)

        yield StreamDone(
            completion=Completion(
                message=message,
                provider=config.kind,
                model=model,
                usage=usage,
            )
        )

    # -- the stream, in pieces -------------------------------------------

    def _open_stream(self, config: ProviderConfig, payload: dict[str, Any]) -> requests.Response:
        """Open the streaming request, mapping transport failures to errors."""
        try:
            response = requests.post(
                self._url(config),
                headers=self._headers(config),
                json=payload,
                timeout=config.timeout,
                stream=True,
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderTimeout(f"{config.label} timed out.", provider=config.label) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderUnreachable(
                f"{config.label} could not be reached: {exc}", provider=config.label
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, config)

        # `requests` decodes a `text/event-stream` response as ISO-8859-1,
        # because that is what the `text/*` rule gives when the header
        # carries no charset.  The bytes on the wire are UTF-8.
        response.encoding = "utf-8"
        return response

    @staticmethod
    def _read_events(response: requests.Response) -> Iterator[dict[str, Any]]:
        """Parse the server-sent events of a streaming response."""
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if not body:
                continue
            try:
                event = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(event, dict):
                yield event

    @staticmethod
    def _on_message_start(
        event: dict[str, Any], model: str, usage: Usage | None
    ) -> tuple[str, Usage | None]:
        message = event.get("message") or {}
        return str(message.get("model") or model), AnthropicProvider._parse_usage(
            message.get("usage")
        ) or usage

    @staticmethod
    def _on_block_start(event: dict[str, Any], partial_calls: dict[int, dict[str, Any]]) -> None:
        block = event.get("content_block") or {}
        if block.get("type") != "tool_use":
            return
        index = int(event.get("index") or 0)
        partial_calls[index] = {
            "id": str(block.get("id") or ""),
            "name": str(block.get("name") or ""),
            "input": "",
        }

    @staticmethod
    def _on_block_delta(event: dict[str, Any], partial_calls: dict[int, dict[str, Any]]) -> str:
        """Return the text of one delta, and accumulate any tool-call JSON."""
        delta = event.get("delta") or {}

        partial = delta.get("partial_json")
        index = int(event.get("index") or 0)
        if isinstance(partial, str) and index in partial_calls:
            partial_calls[index]["input"] += partial

        text = delta.get("text")
        return text if isinstance(text, str) else ""

    @staticmethod
    def _build_calls(partial_calls: dict[int, dict[str, Any]]) -> tuple[ToolCall, ...]:
        calls: list[ToolCall] = []
        for index in sorted(partial_calls):
            entry = partial_calls[index]
            if not entry["name"]:
                continue
            try:
                arguments = json.loads(entry["input"]) if entry["input"].strip() else {}
            except (json.JSONDecodeError, ValueError):
                arguments = {}
            calls.append(
                ToolCall(
                    id=entry["id"] or f"call_{index}",
                    name=entry["name"],
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        return tuple(calls)

    # -- request building -------------------------------------------------

    def _payload(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
        stream: bool,
    ) -> dict[str, Any]:
        system_text, turns = self._split_system(messages)
        payload: dict[str, Any] = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "messages": turns,
        }
        if system_text:
            payload["system"] = system_text
        if stream:
            payload["stream"] = True
        if tools and config.supports_tools:
            payload["tools"] = [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": {
                        **spec.parameters,
                        "additionalProperties": False,
                    },
                }
                for spec in tools
            ]
        return payload

    def _split_system(self, messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        """Split the system prompt out and build Anthropic's turn list."""
        system_text = "\n\n".join(
            message.content for message in messages if message.role == "system" and message.content.strip()
        )

        turns: list[dict[str, Any]] = []
        pending_results: list[dict[str, Any]] = []

        for message in messages:
            if message.role == "system":
                continue

            if message.role == "tool":
                pending_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                    }
                )
                continue

            if pending_results:
                turns.append({"role": "user", "content": list(pending_results)})
                pending_results = []

            turn = self._turn_for(message)
            if turn is not None:
                turns.append(turn)

        if pending_results:
            turns.append({"role": "user", "content": list(pending_results)})

        # Anthropic requires the conversation to open with a user turn.  A
        # history whose first turn is an assistant one is a history this app
        # cannot produce, but a provider that rejects it would fail the turn
        # rather than the history, so the leading turns are dropped here.
        while turns and turns[0]["role"] != "user":
            turns.pop(0)

        return system_text, turns

    @staticmethod
    def _turn_for(message: Message) -> dict[str, Any] | None:
        """One canonical message as one Anthropic turn.

        ``None`` for a turn with nothing in it: Anthropic rejects an empty
        content array, and an assistant turn with neither text nor a tool
        call carries nothing worth sending.
        """
        if message.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            return {"role": "assistant", "content": blocks} if blocks else None

        return {"role": "user", "content": [{"type": "text", "text": message.content}]}

    def _url(self, config: ProviderConfig) -> str:
        base = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/v1/messages"

    def _headers(self, config: ProviderConfig) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": API_VERSION,
        }
        if config.api_key:
            headers["x-api-key"] = config.api_key
        return headers

    # -- response handling ------------------------------------------------

    def _post(self, config: ProviderConfig, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                self._url(config),
                headers=self._headers(config),
                json=payload,
                timeout=config.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise ProviderTimeout(f"{config.label} timed out.", provider=config.label) from exc
        except requests.exceptions.RequestException as exc:
            raise ProviderUnreachable(
                f"{config.label} could not be reached: {exc}", provider=config.label
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response, config)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"{config.label} returned a response that is not JSON.", provider=config.label
            ) from exc

        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ProviderRejected(
                f"{config.label} refused the request: {message}", provider=config.label
            )

        return data if isinstance(data, dict) else {}

    def _http_error(self, response: requests.Response, config: ProviderConfig) -> ProviderError:
        detail = ""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
        except ValueError:
            detail = (response.text or "")[:300]

        return ProviderRejected(
            f"{config.label} returned HTTP {response.status_code}: {detail}".strip(),
            provider=config.label,
            status=response.status_code,
            transient=response.status_code in (408, 429, 500, 502, 503, 504),
        )

    def _parse_message(self, raw: Any) -> Message:
        if not isinstance(raw, list):
            return Message(role="assistant", content="")

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in raw:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text_parts.append(str(block.get("text") or ""))
            elif kind == "tool_use":
                arguments = block.get("input")
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )

        return Message(
            role="assistant",
            content="".join(text_parts),
            tool_calls=tuple(calls),
        )

    def _parse_usage(self, raw: Any) -> Usage | None:
        if not isinstance(raw, dict):
            return None
        input_tokens = int(raw.get("input_tokens") or 0)
        output_tokens = int(raw.get("output_tokens") or 0)
        if not input_tokens and not output_tokens:
            return None
        return Usage(input_tokens=input_tokens, output_tokens=output_tokens)
