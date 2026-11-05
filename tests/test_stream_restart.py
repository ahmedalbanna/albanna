"""A stream that restarts must say so, or the reader reads two answers.

A turn's model call is retried, and it falls back to the next provider in
the chain.  Both restart the *same* round, and both start streaming from
the beginning again.  The client accumulates every token it is given, so
without a signal it would hold the tail of the failed attempt followed by
a whole second answer — one confident-looking reply made of two.

The accumulation is right across *rounds*: a round's preamble and the
next round's answer are one continuous answer.  That is what makes this
subtle, and it is why the signal has to come from the server, which is
the only party that knows a round restarted.

Every case here stubs the provider, so the suite runs with no key, no
network and no site.
"""

from __future__ import annotations

import pytest

from albanna.core.errors import ProviderError
from albanna.core.messages import assistant, user
from albanna.providers.base import (
    Completion,
    LLMConfig,
    ProviderConfig,
    StreamDelta,
    StreamDone,
)
from albanna.services.chat_service import ChatService

CONFIG = ProviderConfig(
    kind="openai",
    base_url="https://example.test/api/v1",
    model="test-model",
    api_key="sk-test",
)


def _completion(text: str) -> Completion:
    return Completion(
        message=assistant(text),
        provider="test",
        model="test-model",
    )


class FlakyProvider:
    """Streams some tokens, then dies — once, then works.

    The first call is the failure the reader would otherwise see
    concatenated; the second is the answer that replaces it.
    """

    def __init__(self, tokens_before_failure: int = 3):
        self.calls = 0
        self.tokens_before_failure = tokens_before_failure

    def stream(self, config, messages, tools):
        self.calls += 1
        if self.calls == 1:
            for index in range(self.tokens_before_failure):
                yield StreamDelta(text=f"stale{index} ")
            raise ProviderError("the connection dropped mid-stream", transient=True)
        for token in ("the ", "whole ", "answer"):
            yield StreamDelta(text=token)
        yield StreamDone(completion=_completion("the whole answer"))

    def complete(self, config, messages, tools):
        return _completion("the whole answer")


@pytest.fixture
def service(monkeypatch):
    def fake_build(kind):
        return FlakyProvider()

    monkeypatch.setattr("albanna.services.chat_service.build_provider", fake_build)
    return ChatService()


def _events(service) -> list[dict]:
    """Run one streamed model call and collect everything it emitted."""
    seen: list[dict] = []
    service._complete(
        LLMConfig(primary=CONFIG, retries=1),
        [user("hello")],
        [],
        seen.append,
        stream=True,
    )
    return seen


def test_a_restarted_stream_announces_itself(service):
    """The reader is told the round restarted, before the new tokens arrive."""
    events = _events(service)

    resets = [index for index, event in enumerate(events) if event.get("event") == "reset"]
    assert resets, (
        "a stream that restarted after tokens had gone out emitted no 'reset', "
        "so the client keeps the stale tail and appends the new answer to it"
    )


def test_the_reset_comes_before_the_replacement_tokens(service):
    """A reset that arrived after the new tokens would be too late to matter."""
    events = _events(service)

    first_reset = next(index for index, event in enumerate(events) if event.get("event") == "reset")
    tokens_after = [
        event["text"] for event in events[first_reset + 1 :] if event.get("event") == "token"
    ]
    assert tokens_after, "no tokens followed the reset"
    assert all(not text.startswith("stale") for text in tokens_after), (
        "a token from the failed attempt arrived after the reset, so the client "
        "would still be holding text the new stream is replacing"
    )


def test_the_stale_tokens_were_emitted_before_the_reset(service):
    """The reset is only needed because something was already sent.

    If nothing had gone out there would be nothing to drop, and a reset
    emitted anyway would be noise the client has to ignore.
    """
    events = _events(service)

    first_reset = next(index for index, event in enumerate(events) if event.get("event") == "reset")
    tokens_before = [
        event["text"] for event in events[:first_reset] if event.get("event") == "token"
    ]
    assert tokens_before, "the reset was emitted before any token, which is not a restart"


def test_a_stream_that_never_failed_emits_no_reset(monkeypatch):
    """The ordinary turn is untouched: one stream, no reset, no noise."""
    import albanna.services.chat_service as chat_service_module

    class CleanProvider(FlakyProvider):
        def stream(self, config, messages, tools):
            self.calls += 1
            for token in ("the ", "whole ", "answer"):
                yield StreamDelta(text=token)
            yield StreamDone(completion=_completion("the whole answer"))

    monkeypatch.setattr(chat_service_module, "build_provider", lambda kind: CleanProvider())

    seen: list[dict] = []
    ChatService()._complete(
        LLMConfig(primary=CONFIG, retries=1),
        [user("hello")],
        [],
        seen.append,
        stream=True,
    )

    assert not [event for event in seen if event.get("event") == "reset"], (
        "a stream that never restarted emitted a reset"
    )
