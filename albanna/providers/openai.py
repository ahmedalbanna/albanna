"""The OpenAI-compatible adapter.

One adapter for every endpoint that speaks OpenAI's chat-completions API:
OpenRouter, OpenAI itself, Groq, vLLM, LM Studio, Together, and the rest.
They really are the same API — the differences are the base URL and the
model id — so covering them with one adapter is not a shortcut, it is the
accurate description of the landscape.

The canonical message format (:mod:`albanna.core.messages`) *is* this
dialect, so the translation in this adapter is nearly free.  The one thing
that is not free is the argument encoding: on the wire a tool call's
arguments are a JSON *string*, and the canonical form holds a mapping.  The
adapter encodes on the way out and decodes on the way in, and nothing
downstream ever sees the string.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import requests

from albanna.core.errors import (
    ProviderBudgetExceeded,
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnreachable,
)
from albanna.core.messages import Message, ToolCall
from albanna.core.options import merge_options
from albanna.core.tools import ToolSpec
from albanna.providers.base import (
    Completion,
    ProviderConfig,
    StreamDelta,
    StreamDone,
    Usage,
    is_truncated,
)
from albanna.providers.http import post

logger = logging.getLogger(__name__)

#: The default endpoint, used when the settings leave the base URL blank.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: HTTP statuses that mean "try again in a moment" rather than "this request
#: is wrong".  Everything else — 400, 401, 403, 404 — is the same on every
#: retry.
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: The shape of a provider's "you asked for too much" refusal.
#:
#: OpenRouter's is: "You requested up to 4096 tokens, but can only afford
#: 3543."  The number after "afford" is what the key can pay for, and it is
#: the number the request should be made again with.
_AFFORDABLE = re.compile(r"can only afford\s+(\d+)", re.IGNORECASE)


def _affordable_tokens(detail: str) -> int | None:
    """The token ceiling a provider says it could afford, if it says one."""
    match = _AFFORDABLE.search(detail or "")
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return value if value > 0 else None


class OpenAIProvider:
    """Talks to any OpenAI-compatible ``/chat/completions`` endpoint."""

    #: The endpoint used when the settings leave the base URL
    #: blank.  It is here, and not only in the request code, because the
    #: settings have to know it too: a provider with no base URL is a
    #: provider the app will not call.
    default_base_url = DEFAULT_BASE_URL

    kind = "openai"

    def complete(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Completion:
        payload = self._payload(config, messages, tools, stream=False)
        data = self._post(config, payload)

        choice = self._first_choice(data, config)
        message = self._parse_message(choice.get("message"))
        return Completion(
            message=message,
            provider=config.kind,
            model=str(data.get("model") or config.model),
            usage=self._parse_usage(data.get("usage")),
            truncated=is_truncated(choice.get("finish_reason")),
        )

    def stream(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Iterator[StreamDelta | StreamDone]:
        payload = self._payload(config, messages, tools, stream=True)
        response = self._open_stream(config, payload)

        try:
            chunks: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            model = config.model
            usage: Usage | None = None
            truncated = False

            for event in self._read_events(response):
                model = str(event.get("model") or model)

                # The reason comes with the chunk that ends the answer,
                # and it is the only thing that says whether the answer
                # was finished or cut off.
                for choice in event.get("choices") or []:
                    if is_truncated(choice.get("finish_reason")):
                        truncated = True

                # The final chunk carries the usage, but only when the request
                # asked for it.  Without this the ledger records a turn that
                # cost nothing, which is worse than no ledger at all.
                chunk_usage = self._parse_usage(event.get("usage"))
                if chunk_usage is not None:
                    usage = chunk_usage

                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        chunks.append(text)
                        yield StreamDelta(text=text)
                    for call in delta.get("tool_calls") or []:
                        self._merge_tool_call(tool_calls, call)

            calls = tuple(
                ToolCall.from_wire({"id": data.get("id"), "function": data.get("function") or {}})
                for _, data in sorted(tool_calls.items())
                if (data.get("function") or {}).get("name")
            )
            content = "".join(chunks)
            message = Message(role="assistant", content=content, tool_calls=calls)

            if usage is None:
                usage = self._estimate_usage(messages, content)

            yield StreamDone(
                completion=Completion(
                    message=message,
                    provider=config.kind,
                    model=model,
                    usage=usage,
                    truncated=truncated,
                )
            )
        finally:
            # The connection belongs to the pool only once the
            # response is closed.  A streamed response that is
            # not closed holds its socket, and the next call
            # opens another one — and the reader may walk away
            # at any moment, so the closing cannot be left to a
            # generator that nobody collects.
            response.close()

    def _open_stream(self, config: ProviderConfig, payload: dict[str, Any]) -> requests.Response:
        """Open the streaming request, mapping transport failures to errors."""
        try:
            response = post(
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
        # carries no charset.  The bytes on the wire are UTF-8, so an em
        # dash arrives as three Latin-1 characters.  Saying so explicitly
        # is the difference between "—" and "â€”".
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
            if body == "[DONE]":
                return
            try:
                event = json.loads(body)
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
        if config.supports_vision:
            wire_messages = [message.to_wire() for message in messages]
        else:
            # The model cannot see images: drop them so the request is
            # valid, and the chat service reports the drop to the reader.
            wire_messages = [
                Message(
                    role=m.role,
                    content=m.content,
                    tool_calls=m.tool_calls,
                    tool_call_id=m.tool_call_id,
                ).to_wire()
                for m in messages
            ]
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": wire_messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if stream:
            payload["stream"] = True
            # Ask for the usage in the final chunk.  Without it a streamed
            # turn costs nothing in the ledger, which is a number nobody can
            # check and everybody believes.
            payload["stream_options"] = {"include_usage": True}
        if tools and config.supports_tools:
            payload["tools"] = [spec.to_wire() for spec in tools]

        # The operator's extra options — the ones the app has no field
        # for — go in the body, where the provider reads them.  The app's
        # own keys win, so they cannot be overwritten from here.
        return merge_options(payload, config.extra_options)

    def _url(self, config: ProviderConfig) -> str:
        base = (config.base_url or DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/chat/completions"

    def _headers(self, config: ProviderConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        return headers

    # -- response handling ------------------------------------------------

    def _post(self, config: ProviderConfig, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = post(
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

        # The same ISO-8859-1 default applies to a JSON body served without
        # a charset.
        response.encoding = "utf-8"

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
        # The body is read before anything says how to decode it, and
        # `requests` decodes a response with no charset as ISO-8859-1.  A
        # provider that answers in anything else — a Chinese error, an
        # em dash — arrives as mojibake, and this message is what the
        # reader is shown.  Saying so explicitly is the difference between
        # an error and a puzzle.
        response.encoding = "utf-8"
        detail = ""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or "")
            elif error:
                detail = str(error)
        except ValueError:
            detail = (response.text or "")[:300]

        message = f"{config.label} returned HTTP {response.status_code}: {detail}".strip()
        transient = response.status_code in TRANSIENT_STATUSES

        if response.status_code == 402:
            affordable = _affordable_tokens(detail)
            if affordable:
                return ProviderBudgetExceeded(
                    message,
                    provider=config.label,
                    status=response.status_code,
                    affordable_tokens=affordable,
                )

        return ProviderRejected(
            message,
            provider=config.label,
            status=response.status_code,
            transient=transient,
        )

    def _first_choice(self, data: dict[str, Any], config: ProviderConfig) -> dict[str, Any]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError(f"{config.label} returned no choices.", provider=config.label)
        first = choices[0]
        return first if isinstance(first, dict) else {}

    def _parse_message(self, raw: Any) -> Message:
        if not isinstance(raw, dict):
            return Message(role="assistant", content="")
        message = Message.from_wire(raw)
        return Message(
            role="assistant",
            content=message.content,
            tool_calls=message.tool_calls,
        )

    def _parse_usage(self, raw: Any) -> Usage | None:
        if not isinstance(raw, dict):
            return None
        return Usage(
            input_tokens=int(raw.get("prompt_tokens") or 0),
            output_tokens=int(raw.get("completion_tokens") or 0),
            cost=float(raw.get("cost") or 0.0),
        )

    @staticmethod
    def _estimate_usage(messages: list[Message], content: str) -> Usage:
        """A rough token count, for a provider that did not report one.

        Four characters per token is the usual rule of thumb for English
        prose and JSON.  It is an estimate and the ledger says so, but a
        zero would be a lie, and a rough number is the truth that is
        approximately right.
        """
        prompt_chars = sum(len(message.content) for message in messages)
        return Usage(
            input_tokens=max(1, prompt_chars // 4),
            output_tokens=max(1, len(content) // 4),
            estimated=True,
        )

    @staticmethod
    def _merge_tool_call(store: dict[int, dict[str, Any]], call: Any) -> None:
        """Accumulate one streamed tool-call fragment.

        A streamed tool call arrives in pieces: the name in the first chunk,
        the arguments in one or more later chunks.  The pieces are keyed by
        the ``index`` the provider sends, not by the id, because the id only
        arrives with the first piece and a provider may reorder them.
        """
        if not isinstance(call, dict):
            return
        index = call.get("index")
        if index is None:
            index = len(store)
        entry = store.setdefault(int(index), {"id": "", "function": {"name": "", "arguments": ""}})

        if call.get("id"):
            entry["id"] = str(call["id"])
        function = call.get("function")
        if isinstance(function, dict):
            if function.get("name"):
                entry["function"]["name"] = function["name"]
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                entry["function"]["arguments"] += arguments
