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

from dataclasses import dataclass, field
from typing import Any

import frappe

from albanna.core.options import parse_options
from albanna.providers.base import ProviderConfig, default_base_url

#: Where the memoised settings live between calls in one request.
_CACHE_ATTR = "albanna_settings_cache"


@dataclass(frozen=True)
class AppSettings:
    """Everything the chat needs to know about this site."""

    enabled: bool
    provider: ProviderConfig
    fallback: ProviderConfig | None
    widget_position: str
    max_tool_rounds: int
    history_limit: int
    turn_timeout: int
    turns_per_minute: int
    system_prompt: str
    disabled_tools: frozenset[str] = frozenset()
    #: What a million tokens cost, in this site's currency.  Zero means
    #: the cost is not known — see :mod:`albanna.core.cost`.
    price_per_million: float = 0.0
    #: The operator's extra options for the provider — the ones the app
    #: has no field for.  See :mod:`albanna.core.options`.
    extra_options: dict[str, Any] = field(default_factory=dict)


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

    # The two fields that were added last are read through `getattr`, and
    # not directly.  The settings are read on *every* request — the chat
    # gate reads them — so a column that has not been migrated yet would
    # take the whole site down rather than one feature.  A missing
    # optional setting is worth no more than its default.

    kind = str(doc.provider_kind or "openai").strip() or "openai"
    provider = ProviderConfig(
        kind=kind,
        # The provider's own default, when the settings leave it blank.  The
        # check for whether a provider is usable happens before the request
        # is made, so a blank base URL would leave the app with no
        # provider at all — even though the request code would have used
        # the default.
        base_url=str(doc.base_url or "").strip() or default_base_url(kind),
        model=str(doc.model or "").strip(),
        api_key=_password(doc, "api_key"),
        max_tokens=_int(doc.max_tokens, 8192),
        timeout=_int(doc.timeout, 120),
        temperature=_float(doc.temperature, 0.2),
        extra_options=parse_options(getattr(doc, "extra_options", "")),
    )

    fallback: ProviderConfig | None = None
    if doc.fallback_enabled:
        fallback_kind = str(doc.fallback_kind or "openai").strip() or "openai"
        fallback = ProviderConfig(
            kind=fallback_kind,
            base_url=str(doc.fallback_base_url or "").strip() or default_base_url(fallback_kind),
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
        widget_position=str(doc.widget_position or "bottom-right").strip() or "bottom-right",
        max_tool_rounds=max(1, _int(doc.max_tool_rounds, 25)),
        history_limit=max(1, _int(doc.history_limit, 50)),
        turn_timeout=max(10, _int(doc.turn_timeout, 600)),
        turns_per_minute=max(0, _int_allowing_zero(doc.turns_per_minute, 6)),
        system_prompt=str(doc.system_prompt or ""),
        disabled_tools=frozenset(split_names(doc.disabled_tools)),
        # What a million tokens cost the operator, in their own currency.
        # Zero means the cost is not known, and a zero that reads as
        # "free" is a lie the ledger would tell.
        price_per_million=_float(getattr(doc, "price_per_million", 0), 0.0),
        # The operator's extra options: the ones the app has no field
        # for, which are added to the request the provider receives.
        extra_options=parse_options(getattr(doc, "extra_options", "")),
    )


def _password(doc, fieldname: str) -> str:
    """The decrypted secret behind a Password field, or an empty string."""
    try:
        return str(doc.get_password(fieldname, raise_exception=False) or "")
    except Exception:
        return ""


def split_names(value) -> list[str]:
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
