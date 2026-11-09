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


def test_the_rows_a_list_shows_are_carried():
    context = build_page_context(doctype="Sales Order", filters="status = To Deliver", rows=24)
    assert "Sales Order" in context
    assert "status = To Deliver" in context
    assert "24" in context


def test_a_list_with_no_rows_says_nothing_about_rows():
    context = build_page_context(doctype="Sales Order", rows=0)
    assert "Rows" not in context


def test_the_recent_questions_are_carried():
    context = build_page_context(recent_questions="which orders are open? | and their value?")
    assert "which orders are open?" in context
    assert "and their value?" in context


def test_a_value_carrying_a_newline_stays_on_one_line():
    """The block is lines, and a value that carries a newline of its own
    would look like part of the framing rather than part of the data."""
    context = build_page_context(filters="status = To Deliver\nDocType: Item")
    assert context.count("\n") == 0


def test_the_report_the_reader_is_looking_at_is_carried():
    context = build_page_context(report="General Ledger", filters="company = Albanna")
    assert "General Ledger" in context
    assert "company = Albanna" in context


def test_the_columns_the_list_shows_are_carried():
    context = build_page_context(doctype="Sales Order", columns="status, grand_total")
    assert "status, grand_total" in context


def test_the_order_the_list_is_in_is_carried():
    context = build_page_context(sort="creation desc")
    assert "creation desc" in context


def test_a_field_that_says_nothing_is_left_out():
    context = build_page_context(doctype="Sales Order", columns="", sort="", report="")
    assert "Columns" not in context
    assert "Sorted" not in context
    assert "Report" not in context
    assert "Rows" not in context


def test_every_field_is_clipped():
    """Every value is one line, and a value that is not is a value that
    cannot be allowed to break the framing."""
    context = build_page_context(
        view="v" * 500,
        doctype="d" * 500,
        name="n" * 500,
        title="t" * 500,
        filters="f" * 900,
        report="r" * 500,
        columns="c" * 900,
        sort="s" * 500,
    )
    assert len(context) <= 2000
    assert context.count("\n") == len(context.split("\n")) - 1


def test_the_prompt_says_how_much_of_the_thread_is_behind_the_window():
    """A long thread is worked on for days, and the model sees the tail.

    It used to not know that — so a question about a decision made forty
    messages ago was answered from the window, and wrong in a way nobody
    could see.  Silence is not the whole truth, and this is the number
    that lets the model say so.
    """
    prompt = build_system_prompt([], PromptContext(history_behind=290))

    assert "290" in prompt
    assert "behind what you can see" in prompt


def test_a_short_thread_says_nothing_about_what_is_behind_it():
    """A line about messages that do not exist is a line of noise.

    The instruction to say so when there *are* messages behind is always
    in the prompt — it is the rule.  What is conditional is the number,
    and that is what this asserts is absent.
    """
    prompt = build_system_prompt([], PromptContext(history_behind=0))

    assert "Messages of this thread behind" not in prompt


def test_the_prompt_tells_the_model_what_mine_means():
    """ "My open tickets" was a suggestion the assistant could not answer.

    The reader was named in the site block already; what was missing was
    the model knowing that "mine" means that user, and that there is a
    filter for it.
    """
    prompt = build_system_prompt([], PromptContext(user="agent@albanna.dev"))

    assert "assigned_to" in prompt
    assert "mine" in prompt
