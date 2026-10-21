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

from albanna.providers.anthropic import AnthropicProvider
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
from albanna.providers.ollama import OllamaProvider
from albanna.providers.openai import OpenAIProvider

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
