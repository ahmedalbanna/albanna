"""The site's configuration, read once per request.

Two things are read here that nothing else should read directly: the
``Albanna Settings`` Single, and the provider configuration built from it.

The API key is the awkward part.  A ``Password`` field holds its value in
two places — the ciphertext in ``__Auth`` and a mask in the column — and
only the first is the secret.  Reading the column gives the mask; reading
the secret means going through ``get_password``, which decrypts.  The
decryption is not free, so the settings are memoised for the life of the
request, and the secret is never written anywhere that is not the settings
document and the audit trail that records the *provider*, never the key.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe

from albanna.providers.base import ProviderConfig

#: Where the memoised settings live between calls in one request.
_CACHE_ATTR = "albanna_settings_cache"


@dataclass(frozen=True)
class AppSettings:
    """Everything the chat needs to know about this site."""

    enabled: bool
    provider: ProviderConfig
    fallback: ProviderConfig | None
    chat_roles: frozenset[str]
    widget_roles: frozenset[str]
    widget_enabled: bool
    widget_position: str
    max_tool_rounds: int
    history_limit: int
    turn_timeout: int
    turns_per_minute: int
    allow_writes: bool
    system_prompt: str
    disabled_tools: frozenset[str]


def get_settings(refresh: bool = False) -> AppSettings:
    """The site's settings, memoised for this request."""
    if not refresh:
        cached = getattr(frappe.local, _CACHE_ATTR, None)
        if cached is not None:
            return cached

    settings = _build()
    setattr(frappe.local, _CACHE_ATTR, settings)
    return settings


def _build() -> AppSettings:
    doc = frappe.get_single("Albanna Settings")

    provider = ProviderConfig(
        kind=str(doc.provider_kind or "openai").strip() or "openai",
        base_url=str(doc.base_url or "").strip(),
        model=str(doc.model or "").strip(),
        api_key=_password(doc, "api_key"),
        max_tokens=_int(doc.max_tokens, 8192),
        timeout=_int(doc.timeout, 120),
        temperature=_float(doc.temperature, 0.2),
    )

    fallback: ProviderConfig | None = None
    if doc.fallback_enabled:
        fallback = ProviderConfig(
            kind=str(doc.fallback_kind or "openai").strip() or "openai",
            base_url=str(doc.fallback_base_url or "").strip(),
            model=str(doc.fallback_model or "").strip(),
            api_key=_password(doc, "fallback_api_key"),
            max_tokens=_int(doc.max_tokens, 8192),
            timeout=_int(doc.timeout, 120),
            temperature=_float(doc.temperature, 0.2),
        )

    return AppSettings(
        enabled=bool(doc.enabled),
        provider=provider,
        fallback=fallback,
        chat_roles=frozenset(_split(doc.chat_roles)),
        widget_roles=frozenset(_split(doc.widget_roles)),
        widget_enabled=bool(doc.widget_enabled),
        widget_position=str(doc.widget_position or "bottom-right").strip() or "bottom-right",
        max_tool_rounds=max(1, _int(doc.max_tool_rounds, 25)),
        history_limit=max(1, _int(doc.history_limit, 50)),
        turn_timeout=max(10, _int(doc.turn_timeout, 600)),
        turns_per_minute=max(0, _int_allowing_zero(doc.turns_per_minute, 6)),
        allow_writes=bool(doc.allow_writes),
        system_prompt=str(doc.system_prompt or ""),
        disabled_tools=frozenset(_split(doc.disabled_tools)),
    )


def _password(doc, fieldname: str) -> str:
    """The decrypted secret behind a Password field, or an empty string."""
    try:
        return str(doc.get_password(fieldname, raise_exception=False) or "")
    except Exception:
        return ""


def _split(value) -> list[str]:
    """Split a multi-value setting into names.

    Newlines and commas both work, because operators paste both.
    """
    if not value:
        return []
    text = str(value)
    for separator in ("\n", ","):
        text = text.replace(separator, "\n")
    return [part.strip() for part in text.split("\n") if part.strip()]


def _int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _int_allowing_zero(value, default: int) -> int:
    """An int where zero is a meaningful value rather than "unset".

    Frappe writes a literal ``0`` for a new Int field, so a reader that
    treats zero as "no value" cannot tell "the operator set it to zero" from
    "nobody has touched it".  For a limit, zero means *no limit*, so it has
    to survive.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
