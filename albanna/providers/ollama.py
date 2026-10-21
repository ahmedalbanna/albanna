"""The Ollama adapter — Ollama's native ``/api/chat``.

Kept because Ollama is how a site runs a model on its own hardware, and
because its native API is the one this app's canonical format was *not*
copied from, which makes it a useful check that the translation layer is
real and not a formality.

Two differences from the canonical format, both handled here and nowhere
else:

*   Ollama's tool-call arguments are an **object**, not a JSON string.
*   Ollama pairs a tool result with its call by **tool name**, not by id.

The second one is why the canonical format carries ids: this adapter has to
drop them on the way out, and the pairings are reconstructed from the order
of the messages, which Ollama does preserve.
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

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider:
    """Talks to Ollama's native chat endpoint."""
    #: The endpoint used when the settings leave the base URL
    #: blank.  It is here, and not only in the request code, because the
    #: settings have to know it too: a provider with no base URL is a
    #: provider the app will not call.
    default_base_url = DEFAULT_BASE_URL

    kind = "ollama"

    def complete(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Completion:
        payload = self._payload(config, messages, tools, stream=False)
        data = self._post(config, payload)
        return Completion(
            message=self._parse_message(data.get("message")),
            provider=config.kind,
            model=str(data.get("model") or config.model),
            usage=self._parse_usage(data),
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
        calls: list[ToolCall] = []
        model = config.model
        usage: Usage | None = None

        for event in self._read_events(response):
            model = str(event.get("model") or model)
            parsed_usage = self._parse_usage(event)
            if parsed_usage is not None:
                usage = parsed_usage

            message = event.get("message") or {}
            text = message.get("content")
            if isinstance(text, str) and text:
                chunks.append(text)
                yield StreamDelta(text=text)

            for call in message.get("tool_calls") or []:
                parsed = self._parse_tool_call(call)
                if parsed is not None:
                    calls.append(parsed)

        yield StreamDone(
            completion=Completion(
                message=Message(role="assistant", content="".join(chunks), tool_calls=tuple(calls)),
                provider=config.kind,
                model=model,
                usage=usage,
            )
        )

    def _open_stream(self, config: ProviderConfig, payload: dict[str, Any]) -> requests.Response:
        """Open the streaming request, mapping transport failures to errors."""
        try:
            response = requests.post(
                self._url(config),
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
        """Parse the newline-delimited JSON of Ollama's streaming response."""
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(event, dict):
                yield event

    # -- request building -------------------------------------------------

    def _payload(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [self._to_ollama(message) for message in messages],
            "stream": stream,
            "options": {"temperature": config.temperature},
        }
        if stream:
            payload["stream"] = True
        if tools and config.supports_tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": {**spec.parameters, "additionalProperties": False},
                    },
                }
                for spec in tools
            ]
        return payload

    def _to_ollama(self, message: Message) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                }
                for call in message.tool_calls
            ]
        return payload

    def _url(self, config: ProviderConfig) -> str:
        base = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/api/chat"

    # -- response handling ------------------------------------------------

    def _post(self, config: ProviderConfig, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(self._url(config), json=payload, timeout=config.timeout)
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
            raise ProviderRejected(
                f"{config.label} refused the request: {data['error']}", provider=config.label
            )

        return data if isinstance(data, dict) else {}

    def _http_error(self, response: requests.Response, config: ProviderConfig) -> ProviderError:
        # The body is read before anything says how to decode it, and
        # `requests` decodes a response with no charset as ISO-8859-1.  A
        # provider that answers in anything else — a Chinese error, an
        # em dash — arrives as mojibake, and this message is what the
        # reader is shown.  Saying so explicitly is the difference between
        # an error and a puzzle.
        response.encoding = "utf-8"
        detail = (response.text or "")[:300]
        return ProviderRejected(
            f"{config.label} returned HTTP {response.status_code}: {detail}".strip(),
            provider=config.label,
            status=response.status_code,
            transient=response.status_code in (408, 429, 500, 502, 503, 504),
        )

    def _parse_message(self, raw: Any) -> Message:
        if not isinstance(raw, dict):
            return Message(role="assistant", content="")
        calls: list[ToolCall] = []
        for call in raw.get("tool_calls") or []:
            parsed = self._parse_tool_call(call)
            if parsed is not None:
                calls.append(parsed)
        return Message(
            role="assistant",
            content=str(raw.get("content") or ""),
            tool_calls=tuple(calls),
        )

    def _parse_tool_call(self, raw: Any) -> ToolCall | None:
        if not isinstance(raw, dict):
            return None
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            return None
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except (json.JSONDecodeError, ValueError):
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        return ToolCall(id=f"call_{name}_{len(arguments)}", name=name, arguments=arguments)

    def _parse_usage(self, raw: Any) -> Usage | None:
        if not isinstance(raw, dict):
            return None
        prompt = int(raw.get("prompt_eval_count") or 0)
        evaluation = int(raw.get("eval_count") or 0)
        if not prompt and not evaluation:
            return None
        return Usage(input_tokens=prompt, output_tokens=evaluation)
