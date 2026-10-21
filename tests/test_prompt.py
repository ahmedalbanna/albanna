"""The system prompt, and the untrusted block.

The rule that matters here: page context is data.  It arrives from the
browser, so it is attacker-controlled, and a document whose title is an
instruction must not be read as one.  These cases pin the framing.
"""

from __future__ import annotations

from albanna.core.prompt import (
    UNTRUSTED_FOOTER,
    UNTRUSTED_HEADER,
    PromptContext,
    build_page_context,
    build_system_prompt,
)
from albanna.core.tools import TOOL_MANIFEST


def test_the_prompt_names_the_tools():
    prompt = build_system_prompt(TOOL_MANIFEST.enabled())
    for spec in TOOL_MANIFEST.enabled():
        assert spec.name in prompt


def test_the_prompt_states_the_site_and_the_company():
    prompt = build_system_prompt([], PromptContext(site="albanna.localhost", company="albanna"))
    assert "albanna.localhost" in prompt
    assert "albanna" in prompt


def test_a_custom_prompt_replaces_the_default():
    prompt = build_system_prompt([], base_prompt="Only answer in French.")
    assert "Only answer in French." in prompt


def test_the_page_context_is_framed_as_data():
    context = build_page_context(doctype="Sales Invoice", name="SINV-0001", title="Acme")
    prompt = build_system_prompt([], PromptContext(page_context=context))
    assert UNTRUSTED_HEADER in prompt
    assert UNTRUSTED_FOOTER in prompt
    assert "Sales Invoice" in prompt


def test_the_framing_says_the_context_is_not_an_instruction():
    prompt = build_system_prompt([], PromptContext(page_context="DocType: Item"))
    assert "not an instruction" in prompt


def test_the_page_context_is_clipped():
    context = build_page_context(selection="x" * 5000)
    assert len(context) < 3000


def test_a_selection_is_clipped_to_five_hundred_characters():
    context = build_page_context(selection="y" * 5000)
    assert "y" * 500 in context
    assert "y" * 501 not in context


def test_no_page_context_means_no_block():
    prompt = build_system_prompt([], PromptContext(page_context=""))
    assert UNTRUSTED_HEADER not in prompt


def test_the_context_is_bounded_even_when_every_field_is_present():
    context = build_page_context(
        view="list",
        doctype="Sales Invoice",
        name="SINV-0001",
        title="Acme",
        filters="status = Open",
        selection="a" * 5000,
        recent_questions="b" * 5000,
    )
    assert len(context) <= 2000
