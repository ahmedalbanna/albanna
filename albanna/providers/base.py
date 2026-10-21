"""The provider port and its value types.

This module defines what a model provider *is* to the rest of the app: a
pair of methods, ``complete`` and ``stream``, plus the configuration that
says which endpoint and which model to talk to.

Nothing here performs I/O.  The adapters in this package do; this module
defines the shape they must have, so the chat service can be written against
the shape and tested against a stub.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from albanna.core.messages import Message
from albanna.core.secrets import mask_secret
from albanna.core.tools import ToolSpec

#: The provider kinds this app knows.
OPENAI = "openai"
OLLAMA = "ollama"
ANTHROPIC = "anthropic"

PROVIDER_KINDS = (OPENAI, OLLAMA, ANTHROPIC)

#: The stop reasons that mean the answer was cut off rather than
#: finished.
#:
#: Each provider names it its own way: the OpenAI-compatible ones say
#: "length", Anthropic says "max_tokens".  The fact is the same, so the
#: rule is in one place.
TRUNCATED_REASONS = frozenset({"length", "max_tokens"})


def is_truncated(reason: Any) -> bool:
    """True when the provider stopped because the answer hit the ceiling.

    @param reason: the provider's stop reason
    @returns: whether the answer was cut off
    """
    return str(reason or "").strip().lower() in TRUNCATED_REASONS


@dataclass(frozen=True)
class ProviderConfig:
    """One model endpoint."""

    kind: str
    base_url: str
    model: str
    api_key: str = ""
    max_tokens: int = 4096
    timeout: int = 120
    temperature: float = 0.2
    supports_tools: bool = True
    #: The operator's extra options — the ones the app has no field for.
    #: They are added to the request body; see :mod:`albanna.core.options`.
    extra_options: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """The configuration, with the key hidden.

        The configuration is printed by more than one thing — a
        traceback, a ``bench execute``, a log line, a test failure — and
        the key is in it.  So the representation is written by hand, and
        it says only *that* there is a key.
        """
        return (
            f"ProviderConfig(kind={self.kind!r}, base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key={mask_secret(self.api_key)!r}, "
            f"max_tokens={self.max_tokens!r}, timeout={self.timeout!r}, "
            f"temperature={self.temperature!r}, supports_tools={self.supports_tools!r}, "
            f"extra_options={self.extra_options!r})"
        )

    @property
    def usable(self) -> bool:
        """True when this endpoint has enough configuration to be called."""
        return bool(self.base_url.strip() and self.model.strip() and self.kind in PROVIDER_KINDS)

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.model}"


@dataclass(frozen=True)
class LLMConfig:
    """A primary provider and an optional fallback."""

    primary: ProviderConfig
    fallback: ProviderConfig | None = None
    retries: int = 1

    def chain(self) -> list[ProviderConfig]:
        """The providers to try, in order."""
        providers = [self.primary]
        if self.fallback is not None and self.fallback.usable:
            providers.append(self.fallback)
        return [provider for provider in providers if provider.usable]


@dataclass(frozen=True)
class Usage:
    """What one model call cost."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    #: True when the token counts are an estimate rather than a number the
    #: provider reported.  The ledger says so, because a number that looks
    #: measured but is not is worse than no number.
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class Completion:
    """One model answer, in the canonical shape."""

    message: Message
    provider: str
    model: str
    usage: Usage | None = None
    fell_back: bool = False
    #: True when the provider stopped because the answer hit the token
    #: ceiling, rather than because it was finished.
    #:
    #: The difference matters to the reader: an answer that was cut off
    #: is not wrong, but it is not *complete*, and an answer that looks
    #: complete and is not is worse than one that says it was cut.
    truncated: bool = False


@dataclass(frozen=True)
class StreamDelta:
    """A fragment of the answer, as it arrives."""

    text: str


@dataclass(frozen=True)
class StreamDone:
    """The terminal event of a stream: the assembled answer."""

    completion: Completion


StreamEvent = StreamDelta | StreamDone


@runtime_checkable
class ChatProvider(Protocol):
    """What the chat service needs from a model provider."""

    kind: str

    def complete(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Completion:
        """Run one completion and return the assembled answer."""
        ...

    def stream(
        self,
        config: ProviderConfig,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> Iterator[StreamEvent]:
        """Run one completion, yielding deltas and then a terminal event."""
        ...


def default_base_url(kind: str) -> str:
    """The endpoint a provider kind uses when the settings leave it blank.

    The settings have to know it, because a provider with no base URL is
    not one the app will call: the check for whether a provider is usable
    happens before the request is made, and the request is where the
    default would have been applied.  A deployment that followed the
    instructions — a key and a model, and nothing else — would have had
    no provider at all.
    """
    kind = (kind or "").strip().lower()
    if kind == OPENAI:
        from albanna.providers.openai import OpenAIProvider

        return OpenAIProvider.default_base_url
    if kind == OLLAMA:
        from albanna.providers.ollama import OllamaProvider

        return OllamaProvider.default_base_url
    if kind == ANTHROPIC:
        from albanna.providers.anthropic import AnthropicProvider

        return AnthropicProvider.default_base_url
    return ""


def build_provider(kind: str) -> ChatProvider:
    """The adapter for a provider kind.

    Imported lazily so that a site which only ever talks to one vendor does
    not pay for the other two adapters' imports.
    """
    kind = (kind or "").strip().lower()
    if kind == OPENAI:
        from albanna.providers.openai import OpenAIProvider

        return OpenAIProvider()
    if kind == OLLAMA:
        from albanna.providers.ollama import OllamaProvider

        return OllamaProvider()
    if kind == ANTHROPIC:
        from albanna.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"Unknown provider kind: {kind!r}. Known kinds: {', '.join(PROVIDER_KINDS)}.")
