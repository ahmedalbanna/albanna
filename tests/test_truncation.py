"""The reason a provider stopped, and what the app does with it.

Each provider names the cut-off its own way — the OpenAI-compatible ones
say "length", Anthropic says "max_tokens" — and the fact is the same, so
the rule is in one place.
"""

from __future__ import annotations

from albanna.providers.base import is_truncated


def test_length_is_a_cut_off():
    assert is_truncated("length") is True


def test_max_tokens_is_a_cut_off():
    """Anthropic's word for the same thing."""

    assert is_truncated("max_tokens") is True


def test_the_reason_is_read_whatever_its_case():
    assert is_truncated("LENGTH") is True
    assert is_truncated(" Max_Tokens ") is True


def test_finishing_is_not_a_cut_off():
    assert is_truncated("stop") is False
    assert is_truncated("end_turn") is False
    assert is_truncated("tool_calls") is False


def test_silence_is_not_a_cut_off():
    """A provider that says nothing about why it stopped is taken to have
    finished: silence is not evidence of a cut."""

    assert is_truncated("") is False
    assert is_truncated(None) is False


def test_a_reason_that_is_not_a_string_is_not_a_cut_off():
    assert is_truncated(42) is False
