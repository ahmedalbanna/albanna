"""The fallback, as the chain actually walks it.

The pure cases live with the providers (``tests/test_providers.py`` pins
transient against refused); these need a site and a *real* endpoint,
because the claim — the fallback is attempted before an error is
returned — is about the walk in ``ChatService._complete``, the retry
between attempts, and the aggregation of every provider's failure into
one error the reader can be given.

A dead port is a provider that refuses the connection; a tiny local HTTP
server speaking the OpenAI protocol's server-sent events is the
fallback.  Both live on loopback; nothing leaves the host.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from albanna.core.errors import AllProvidersFailed
from albanna.core.messages import Message, user
from albanna.providers.base import LLMConfig, ProviderConfig
from albanna.services.chat_service import ChatService
from albanna.tests.base import AlbannaTestCase

#: A port nothing on this host listens on.  The connection is refused at
#: once, which is what an unreachable provider looks like.
DEAD_PORT = "http://127.0.0.1:59997/v1"

MOCK_PORT = 18411
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"
MOCK_MODEL = "mock-fallback"

def _sse(model: str, content: str) -> bytes:
    """One text chunk, one final chunk that ends the stream cleanly, and
    the usage on the final chunk so the completion is a whole one."""
    return (
        b'data: {"model": "%s", "choices": [{"delta": {"content": '
        b'"%s"}, "finish_reason": null}]}\n\n'
        b'data: {"model": "%s", "choices": [{"delta": {}, '
        b'"finish_reason": "stop"}], "usage": {"prompt_tokens": 10, '
        b'"completion_tokens": 4}}\n\n'
        b"data: [DONE]\n\n"
    ) % (model.encode(), content.encode(), model.encode())


_SSE = _sse(MOCK_MODEL, "The fallback answered.")


class _MockOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server's name
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(_SSE)))
        self.end_headers()
        self.wfile.write(_SSE)

    def log_message(self, *args) -> None:
        pass


def _config(fallback: ProviderConfig | None = None) -> LLMConfig:
    return LLMConfig(
        primary=ProviderConfig(
            kind="openai", base_url=DEAD_PORT, model="dead-model", timeout=5
        ),
        fallback=fallback,
        retries=1,
    )


class TestTheFallback(AlbannaTestCase):
    @classmethod
    def setUpClass(cls):
        cls._server = HTTPServer(("127.0.0.1", MOCK_PORT), _MockOpenAIHandler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()

    def test_the_fallback_answers_when_the_primary_is_unreachable(self):
        config = _config(
            ProviderConfig(
                kind="openai", base_url=MOCK_BASE, model=MOCK_MODEL, timeout=5
            )
        )

        completion = ChatService()._complete(
            config, [user("hello")], [], lambda event: None, stream=True
        )

        assert completion.provider == "openai"
        assert completion.model == MOCK_MODEL
        assert "The fallback answered." in completion.message.content
        assert completion.usage.input_tokens == 10
        assert completion.usage.output_tokens == 4

    def test_the_error_names_every_provider_tried(self):
        """Both providers dead: the error carries both labels, so the
        operator reading the ledger sees the whole chain's verdict."""

        config = _config(
            ProviderConfig(
                kind="openai", base_url=DEAD_PORT, model="also-dead", timeout=5
            )
        )

        try:
            ChatService()._complete(
                config, [user("hello")], [], lambda event: None, stream=True
            )
        except AllProvidersFailed as exc:
            message = str(exc)
        else:
            message = ""

        assert "dead-model" in message
        assert "also-dead" in message

    def test_the_chain_walks_the_fallback_only_when_the_primary_fails(self):
        """A working primary is answered by the primary; the fallback is
        never contacted.  The mock counts its requests."""

        seen = []
        counting_sse = _sse("primary-mock", "The primary answered.")
        handler = self._server.RequestHandlerClass

        class _Counting(handler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                seen.append(1)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(counting_sse)))
                self.end_headers()
                self.wfile.write(counting_sse)

        server = HTTPServer(("127.0.0.1", MOCK_PORT + 1), _Counting)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = LLMConfig(
                primary=ProviderConfig(
                    kind="openai", base_url=f"http://127.0.0.1:{MOCK_PORT + 1}/v1",
                    model="primary-mock", timeout=5,
                ),
                fallback=ProviderConfig(
                    kind="openai", base_url=DEAD_PORT, model="never-asked", timeout=5
                ),
                retries=1,
            )
            completion = ChatService()._complete(
                config, [Message(role="user", content="hello")], [], lambda e: None, stream=True
            )
        finally:
            server.shutdown()
            server.server_close()

        assert completion.model == "primary-mock"
        assert seen == [1], "the fallback was contacted although the primary answered"
