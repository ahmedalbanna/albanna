"""The provider adapters.

Every case here stubs the network, so the suite runs with no key, no
provider and no connectivity.  What is being tested is the translation: the
canonical message format in, a provider's wire format out, and a provider's
wire format back into the canonical one.
"""

from __future__ import annotations

import pytest

from albanna.core.errors import (
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnreachable,
)
from albanna.core.messages import Message, ToolCall, assistant, system, tool_result, user
from albanna.core.tools import TOOL_MANIFEST
from albanna.providers.anthropic import AnthropicProvider
from albanna.providers.base import LLMConfig, ProviderConfig, build_provider
from albanna.providers.ollama import OllamaProvider
from albanna.providers.openai import OpenAIProvider

OPENAI_CONFIG = ProviderConfig(
    kind="openai",
    base_url="https://example.test/api/v1",
    model="test-model",
    api_key="sk-test",
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", lines=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self._lines = lines or []
        # `requests` sets this on a real response; the fake needs it too, so
        # that the code under test has something to set.
        self.encoding = None
        # Whether the provider closed it — a streamed response that is not
        # closed holds its connection.
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def close(self):
        """A real response releases its connection when it is closed."""
        self.closed = True


@pytest.fixture
def tools():
    return TOOL_MANIFEST.enabled()


def test_an_error_body_is_decoded_as_utf_8(tools, monkeypatch):
    """A provider that answers in anything but Latin-1 is not mojibake.

    The error is what the reader is shown, and a Chinese error message
    that arrives as "Ã¤Â¸Â­..." is a puzzle rather than an error.
    """
    from albanna.providers.openai import OpenAIProvider

    class Failing(FakeResponse):
        def json(self):
            raise ValueError("not json")

        @property
        def text(self):
            # The body must not be read before the encoding is set: the
            # bytes on the wire would have been decoded as Latin-1.
            assert self.encoding == "utf-8", self.encoding
            return self._text

        @text.setter
        def text(self, value):
            self._text = value

    response = Failing(status_code=500, text="服务自动下线，模型不可用")
    captured = {}
    provider = OpenAIProvider()

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    with pytest.raises(Exception) as caught:
        provider.complete(OPENAI_CONFIG, [user("hello")], tools)

    assert response.encoding == "utf-8"
    assert "服务自动下线" in str(caught.value)


# -- OpenAI ---------------------------------------------------------------


def test_the_openai_payload_is_the_canonical_format(tools, monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        captured.update({"url": url, "headers": headers, "payload": json})
        return FakeResponse(
            payload={"choices": [{"message": {"role": "assistant", "content": "hi"}}], "model": "m"}
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    OpenAIProvider().complete(
        OPENAI_CONFIG,
        [system("s"), user("u"), assistant("a"), tool_result("call_1", "r")],
        tools,
    )

    assert captured["url"] == "https://example.test/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    payload = captured["payload"]
    assert [m["role"] for m in payload["messages"]] == ["system", "user", "assistant", "tool"]
    assert payload["tools"][0]["function"]["name"] == "list_docs"
    assert payload["tools"][0]["function"]["parameters"]["additionalProperties"] is False


def test_the_openai_response_is_parsed_into_the_canonical_format(monkeypatch):
    def fake_post(*args, **kwargs):
        return FakeResponse(
            payload={
                "model": "m-1",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_7",
                                    "type": "function",
                                    "function": {
                                        "name": "list_docs",
                                        "arguments": '{"doctype": "Item"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "cost": 0.001},
            }
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    completion = OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], [])
    assert completion.message.tool_calls[0].name == "list_docs"
    assert completion.message.tool_calls[0].arguments == {"doctype": "Item"}
    assert completion.usage.input_tokens == 12
    assert completion.usage.cost == pytest.approx(0.001)


def test_a_rate_limit_is_transient_and_a_refused_key_is_not(monkeypatch):
    def rate_limited(*args, **kwargs):
        return FakeResponse(payload={"error": {"message": "slow down"}}, status_code=429)

    monkeypatch.setattr("albanna.providers.openai.post", rate_limited)
    with pytest.raises(ProviderRejected) as caught:
        OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], [])
    assert caught.value.transient is True
    assert caught.value.status == 429

    def refused(*args, **kwargs):
        return FakeResponse(payload={"error": {"message": "no key"}}, status_code=401)

    monkeypatch.setattr("albanna.providers.openai.post", refused)
    with pytest.raises(ProviderRejected) as caught:
        OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], [])
    assert caught.value.transient is False


def test_a_timeout_is_a_timeout_and_an_unreachable_host_is_not_a_timeout(monkeypatch):
    import requests

    def timed_out(*args, **kwargs):
        raise requests.exceptions.Timeout("too slow")

    monkeypatch.setattr("albanna.providers.openai.post", timed_out)
    with pytest.raises(ProviderTimeout):
        OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], [])

    def refused(*args, **kwargs):
        raise requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr("albanna.providers.openai.post", refused)
    with pytest.raises(ProviderUnreachable):
        OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], [])


def test_the_openai_stream_assembles_a_tool_call(monkeypatch):
    lines = [
        'data: {"model":"m","choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"list_docs","arguments":"{\\"doct"}}]}}]}',
        'data: {"model":"m","choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ype\\": \\"Item\\"}"}}]}}]}',
        'data: {"model":"m","choices":[{"delta":{"content":"done"}}]}',
        'data: {"model":"m","choices":[],"usage":{"prompt_tokens":31,"completion_tokens":7,"cost":0.0004}}',
        "data: [DONE]",
    ]

    def fake_post(*args, **kwargs):
        return FakeResponse(lines=lines)

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    events = list(OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], []))
    deltas = [event for event in events if hasattr(event, "text")]
    assert "".join(delta.text for delta in deltas) == "done"

    final = events[-1]
    assert final.completion.message.tool_calls[0].name == "list_docs"
    assert final.completion.message.tool_calls[0].arguments == {"doctype": "Item"}
    # The usage from the final chunk must survive into the completion: a
    # streamed turn that records no tokens records no cost either.
    assert final.completion.usage.input_tokens == 31
    assert final.completion.usage.output_tokens == 7
    assert final.completion.usage.estimated is False


def test_a_stream_without_usage_is_estimated_rather_than_recorded_as_zero(monkeypatch):
    lines = [
        'data: {"model":"m","choices":[{"delta":{"content":"done"}}]}',
        "data: [DONE]",
    ]

    def fake_post(*args, **kwargs):
        return FakeResponse(lines=lines)

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    events = list(OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], []))
    usage = events[-1].completion.usage
    assert usage.estimated is True
    assert usage.input_tokens > 0
    assert usage.output_tokens > 0


# -- Anthropic ------------------------------------------------------------


def test_the_anthropic_system_prompt_is_a_top_level_parameter():
    provider = AnthropicProvider()

    system_text, turns = provider._split_system([system("be helpful"), user("u")])
    assert system_text == "be helpful"
    assert turns[0]["role"] == "user"


def test_the_anthropic_tool_results_share_one_user_turn():
    provider = AnthropicProvider()
    calls = (
        ToolCall(id="call_1", name="list_docs", arguments={}),
        ToolCall(id="call_2", name="get_doc", arguments={}),
    )
    _, turns = provider._split_system(
        [
            user("u"),
            assistant("working", calls),
            tool_result("call_1", "one"),
            tool_result("call_2", "two"),
        ]
    )
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    blocks = turns[-1]["content"]
    assert [block["type"] for block in blocks] == ["tool_result", "tool_result"]
    assert blocks[0]["tool_use_id"] == "call_1"


def test_the_anthropic_tools_use_input_schema():
    provider = AnthropicProvider()
    config = ProviderConfig(kind="anthropic", base_url="https://api.anthropic.test", model="m")
    payload = provider._payload(config, [user("u")], TOOL_MANIFEST.enabled(), stream=False)
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    assert "parameters" not in payload["tools"][0]
    assert payload["max_tokens"] == config.max_tokens


# -- Ollama ---------------------------------------------------------------


def test_the_ollama_tool_arguments_are_an_object():
    provider = OllamaProvider()
    config = ProviderConfig(kind="ollama", base_url="http://127.0.0.1:11434", model="m")
    payload = provider._payload(config, [user("u")], TOOL_MANIFEST.enabled(), stream=False)
    tool = payload["tools"][0]
    assert tool["function"]["name"] == "list_docs"
    assert tool["function"]["parameters"]["type"] == "object"


# -- the registry ---------------------------------------------------------


def test_the_provider_registry_knows_its_kinds():
    assert build_provider("openai").kind == "openai"
    assert build_provider("ollama").kind == "ollama"
    assert build_provider("anthropic").kind == "anthropic"
    with pytest.raises(ValueError):
        build_provider("nope")


def test_the_fallback_chain_only_includes_usable_providers():
    usable = ProviderConfig(kind="openai", base_url="https://x", model="m")
    unusable = ProviderConfig(kind="openai", base_url="", model="")

    config = LLMConfig(primary=usable, fallback=unusable)
    assert config.chain() == [usable]

    config = LLMConfig(primary=unusable, fallback=usable)
    assert config.chain() == [usable]

    config = LLMConfig(primary=unusable, fallback=unusable)
    assert config.chain() == []


def test_a_streamed_response_is_closed(monkeypatch):
    """A connection belongs to the pool only once the response is closed.

    A streamed response that is not closed holds its socket, and the next
    call to the provider opens another one — which would undo the point
    of the shared session.
    """
    lines = [
        'data: {"model":"m","choices":[{"delta":{"content":"done"}}]}',
        "data: [DONE]",
    ]
    response = FakeResponse(lines=lines)

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    list(OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], []))

    assert response.closed, "the streamed response must be closed"


def test_a_stream_the_reader_walks_away_from_is_closed(monkeypatch):
    """The reader may stop reading — the turn is aborted, the provider
    misbehaves — and the socket must not be left open for it."""
    lines = [
        'data: {"model":"m","choices":[{"delta":{"content":"one"}}]}',
        'data: {"model":"m","choices":[{"delta":{"content":"two"}}]}',
    ]
    response = FakeResponse(lines=lines)

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    stream = OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], [])
    next(stream)
    stream.close()

    assert response.closed, "a response nobody reads to the end must still be closed"


def test_the_operators_extra_options_go_in_the_request(tools, monkeypatch):
    """Options the app has no field for are added to the body, where the
    provider reads them — a cache key, a vendor's own flag."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        captured.update({"payload": json})
        return FakeResponse(
            payload={"choices": [{"message": {"role": "assistant", "content": "hi"}}], "model": "m"}
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/api/v1",
        model="test-model",
        api_key="sk-test",
        extra_options={"setCacheKey": True},
    )

    OpenAIProvider().complete(config, [user("u")], tools)

    assert captured["payload"]["setCacheKey"] is True


def test_the_apps_own_settings_are_not_overwritten_by_the_options(tools, monkeypatch):
    """The options are *extra*: what the app has a field for was written
    on purpose."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        captured.update({"payload": json})
        return FakeResponse(
            payload={"choices": [{"message": {"role": "assistant", "content": "hi"}}], "model": "m"}
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/api/v1",
        model="test-model",
        api_key="sk-test",
        temperature=0.2,
        extra_options={"model": "another-model", "temperature": 1.5},
    )

    OpenAIProvider().complete(config, [user("u")], tools)

    payload = captured["payload"]
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0.2


def test_an_answer_cut_off_at_the_ceiling_says_so(tools, monkeypatch):
    """A provider that stops because the answer hit the token ceiling
    says so, and the reason is read."""
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        captured.update({"payload": json})
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "a long answer"},
                        "finish_reason": "length",
                    }
                ],
                "model": "m",
            }
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    completion = OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], tools)

    assert completion.truncated is True
    assert completion.message.content == "a long answer"


def test_an_answer_that_was_finished_is_not_truncated(tools, monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        return FakeResponse(
            payload={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "a whole answer"},
                        "finish_reason": "stop",
                    }
                ],
                "model": "m",
            }
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    completion = OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], tools)

    assert completion.truncated is False


def test_a_stream_cut_off_at_the_ceiling_says_so(monkeypatch):
    lines = [
        'data: {"model":"m","choices":[{"delta":{"content":"half an ans"}}]}',
        'data: {"model":"m","choices":[{"delta":{},"finish_reason":"length"}]}',
        "data: [DONE]",
    ]
    response = FakeResponse(lines=lines)

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    events = list(OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], []))

    assert events[-1].completion.truncated is True


def test_a_finished_stream_is_not_truncated(monkeypatch):
    lines = [
        'data: {"model":"m","choices":[{"delta":{"content":"the whole"}}]}',
        'data: {"model":"m","choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    response = FakeResponse(lines=lines)

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    events = list(OpenAIProvider().stream(OPENAI_CONFIG, [user("u")], []))

    assert events[-1].completion.truncated is False


def test_a_provider_with_no_reason_at_all_is_not_truncated(tools, monkeypatch):
    """Some providers say nothing about why they stopped.  Silence is not
    a cut-off: the answer is taken to be finished."""

    def fake_post(url, headers=None, json=None, timeout=None, stream=False):
        return FakeResponse(
            payload={
                "choices": [{"message": {"role": "assistant", "content": "an answer"}}],
                "model": "m",
            }
        )

    monkeypatch.setattr("albanna.providers.openai.post", fake_post)

    completion = OpenAIProvider().complete(OPENAI_CONFIG, [user("u")], tools)

    assert completion.truncated is False
