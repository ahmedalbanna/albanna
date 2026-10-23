"""The secret, and the places it must not reach.

A secret that is printed by accident is a secret that has leaked by
accident, and an accidental leak is not a smaller leak — it is the same
leak, in a place nobody was looking.  These cases pin the rule down: the
key is hidden in every printed form, and it still works.
"""

from __future__ import annotations

from albanna.core.secrets import REDACTED, mask_secret
from albanna.providers.base import ProviderConfig

KEY = "sk-9f3c2a1b8e7d6c5a4b3c2d1e0f9a8b7c"


def test_a_secret_is_masked():
    assert mask_secret(KEY) == REDACTED


def test_no_secret_is_no_secret():
    """An empty secret stays empty: "there is no key" and "there is a key
    and it is hidden" are different facts."""

    assert mask_secret("") == ""
    assert mask_secret(None) == ""
    assert mask_secret("   ") == ""


def test_the_mask_does_not_reveal_the_shape_of_the_secret():
    """A mask that reveals how long the secret is, or how it starts, is a
    mask with holes in it."""

    masked = mask_secret(KEY)

    # Neither end of the secret survives, nor its length.
    assert KEY[:4] not in masked
    assert KEY[-4:] not in masked
    assert str(len(KEY)) not in masked


def test_the_configuration_does_not_print_its_key():
    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/v1",
        model="a-model",
        api_key=KEY,
    )

    assert KEY not in repr(config)
    assert REDACTED in repr(config)


def test_the_configuration_still_holds_its_key():
    """The key is hidden from the *reader* of the representation, not from
    the code that calls the provider."""

    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/v1",
        model="a-model",
        api_key=KEY,
    )

    assert config.api_key == KEY


def test_a_configuration_with_no_key_says_so():
    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/v1",
        model="a-model",
    )

    assert "api_key=''" in repr(config)


def test_the_settings_do_not_print_the_key_either():
    """The settings hold the configuration, so their own representation
    would have printed the key through it."""

    from albanna.services.settings_service import AppSettings

    provider = ProviderConfig(
        kind="openai",
        base_url="https://example.test/v1",
        model="a-model",
        api_key=KEY,
    )
    settings = AppSettings(
        enabled=True,
        provider=provider,
        fallback=None,
        widget_position="bottom-right",
        max_tool_rounds=25,
        history_limit=50,
        turn_timeout=600,
        turns_per_minute=6,
        system_prompt="",
    )

    assert KEY not in repr(settings)


def test_the_two_ends_of_a_chain_do_not_print_the_key():
    """The chain holds the primary and the fallback, and both are
    configurations."""

    from albanna.providers.base import LLMConfig

    config = ProviderConfig(
        kind="openai",
        base_url="https://example.test/v1",
        model="a-model",
        api_key=KEY,
    )
    chain = LLMConfig(primary=config, fallback=config)

    assert KEY not in repr(chain)
