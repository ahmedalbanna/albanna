"""Provider adapters: the LLM side of the app.

Each adapter speaks one vendor's wire format and nothing else.  The shape it
speaks in is the canonical one defined in :mod:`albanna.core.messages`; the
adapter's whole job is translating in and out of that shape, and the
canonical shape is what every caller sees.

Three adapters ship:

``openai``
    Any OpenAI-compatible ``/chat/completions`` endpoint — OpenRouter,
    OpenAI itself, Groq, vLLM, LM Studio, Together.  One adapter covers all
    of them, because they genuinely are the same API; only the base URL and
    the model id differ.

``ollama``
    Ollama's native ``/api/chat``.  Useful for a local model and for
    anything that wants the Ollama-specific extras.

``anthropic``
    Anthropic's native ``/messages``.  Kept because its tool-use quality is
    the best of the three, and because a fallback chain that only ever spans
    one vendor is not a fallback chain.

The adapters deliberately do not retry, and do not fall back.  A provider
that fails is a fact, and the decision about what to do with that fact —
retry, fall back, give up — belongs to the chat service, which is the only
thing that knows the shape of a turn.  What the adapters *do* provide is a
precise classification of the failure, so the service can tell a timeout
(which is worth retrying) from a rejected key (which is not).
"""

from typing import Any

from albanna.providers.base import (
    ChatProvider,
    Completion,
    LLMConfig,
    ProviderConfig,
    StreamDelta,
    StreamDone,
    Usage,
    build_provider,
)

#: The concrete adapters, by the class name this package exports them
#: under.  They are **not** imported here: every one of them pulls in
#: ``providers.http`` and with it ``requests`` — some nine megabytes of
#: the adapter's HTTP stack — and a worker that imports anything under
#: ``albanna.providers`` would pay for all three whether it talks to
#: any of them or not.  ``settings_service`` imports ``base``, so the
#: eager import would put the HTTP stack in every worker at boot.
#: The classes resolve on first attribute use instead, and
#: ``build_provider`` still imports only the kind the turn actually
#: speaks to.
_ADAPTERS: dict[str, str] = {
    "AnthropicProvider": "anthropic",
    "OllamaProvider": "ollama",
    "OpenAIProvider": "openai",
}

__all__ = [
    "AnthropicProvider",
    "ChatProvider",
    "Completion",
    "LLMConfig",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderConfig",
    "StreamDelta",
    "StreamDone",
    "Usage",
    "build_provider",
]


def __getattr__(name: str) -> Any:
    """The concrete adapters, imported the first time they are asked for."""
    module = _ADAPTERS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))
