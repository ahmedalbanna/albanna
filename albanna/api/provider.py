"""Testing the configured provider.

An operator who has mistyped a base URL finds that out at the first
question, in front of a user, rather than at the moment they press
"Test".  This endpoint is the difference between those two.

The call it makes is the smallest one that means anything: one message, no
tools, and the smallest number of tokens a provider will accept.  It costs
nothing worth counting and it proves the three things that are wrong in
practice — the base URL, the model id, and the key.
"""

from __future__ import annotations

import time

import frappe
from frappe import _

from albanna.permissions import require_system_manager
from albanna.core.messages import user
from albanna.providers.base import ProviderConfig, build_provider, default_base_url

#: What the model is asked.  It has to be short enough that a provider
#: with a token budget will not refuse it, and specific enough that the
#: answer proves the model answered rather than the endpoint echoing.
PROBE = "Reply with the single word: ok"

#: The most of the answer that is shown.  A model that ignores the
#: instruction and writes an essay is still a model that answered.
REPLY_LIMIT = 200


@frappe.whitelist()
def test_provider(
    kind: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 0,
) -> dict:
    """Call the provider and report what happened.

    The form's own values are used where they are given, so a provider
    can be tested *before* it is saved.  An argument that was not given
    at all falls back to the saved value; an argument that was given and
    is empty is empty — an operator who has cleared the model means it.

    The key is the exception: an unchanged password field arrives
    masked, and a masked key is not a key — so the saved one is used
    instead.

    What comes back is the model that answered and how long it took, or
    the reason it did not.
    """
    require_system_manager()

    settings = _saved_settings()
    key = _usable_key(api_key, settings.api_key)

    config = ProviderConfig(
        kind=(settings.kind if kind is None else kind).strip(),
        base_url=(settings.base_url if base_url is None else base_url).strip(),
        model=(settings.model if model is None else model).strip(),
        api_key=key,
        max_tokens=settings.max_tokens,
        # The form sends a number as a string, and `requests` refuses a
        # timeout that is not a number.
        timeout=_seconds(timeout, settings.timeout),
        temperature=0.0,
        # The operator's extra options travel with the test, so that the
        # test is the request the app would really send — an option that
        # the provider refuses has to be found by the button and not by
        # the reader.
        extra_options=settings.extra_options,
    )

    if not config.kind:
        frappe.throw(_("Choose a provider."))
    if not config.model:
        frappe.throw(_("The provider needs a model id."))
    if not config.base_url:
        config = ProviderConfig(
            kind=config.kind,
            base_url=default_base_url(config.kind),
            model=config.model,
            api_key=config.api_key,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            temperature=config.temperature,
        )
    if not config.base_url:
        frappe.throw(_("The provider needs a base URL."))

    try:
        provider = build_provider(config.kind)
    except ValueError as exc:
        frappe.throw(_("The provider is not one this app knows: {0}").format(str(exc)))

    started = time.monotonic()
    try:
        completion = provider.complete(config, [user(PROBE)], [])
    except Exception as exc:  # noqa: BLE001 - the point is to report it
        return {
            "status": "error",
            "error": _redact(f"{type(exc).__name__}: {exc}", key),
        }
    elapsed = round(time.monotonic() - started, 2)

    return {
        "status": "ok",
        "provider": completion.provider,
        "model": completion.model,
        "reply": (completion.message.content or "")[:REPLY_LIMIT],
        "seconds": elapsed,
        "base_url": config.base_url,
    }


def _seconds(passed, saved: int) -> int:
    """A timeout in seconds, from the form or from the settings.

    A number in a form arrives as a string, and ``requests`` refuses a
    timeout that is not a number — with a message about the *connect*
    timeout, which is nowhere near the thing that was wrong.
    """
    try:
        return int(passed) if passed else int(saved)
    except (TypeError, ValueError):
        return int(saved)


def _saved_settings():
    """The provider as it is saved, as a plain object."""
    from albanna.services.settings_service import get_settings

    provider = get_settings().provider
    return provider


def _usable_key(passed: str, saved: str) -> str:
    """The key to use: the one passed, unless it is a mask.

    An unchanged password field arrives as a row of asterisks.  A row of
    asterisks is not a key, and sending it would produce an
    authentication error that looks like a wrong key.
    """
    text = str(passed or "").strip()
    if not text or set(text) == {"*"}:
        return str(saved or "").strip()
    return text


def _redact(text: str, key: str) -> str:
    """The message, with the key taken out of it.

    A provider's error should not carry the key, but one that echoes the
    request would, and this message goes into the settings page.
    """
    message = str(text or "")
    if key and key in message:
        message = message.replace(key, "***")
    return message
