"""The operator's list of tools to hide from the assistant.

The rule under test: the list is read the way an operator writes it, and
a name that is not a tool is a name that hides nothing.

That second half is the reason this file exists.  A typo in the settings
used to be ignored: the list was split, whatever it held was switched
off, and ``createe_doc`` disabled exactly nothing while looking exactly
like ``create_doc`` had been disabled.  The one setting whose job is to
narrow what the assistant may do failed silently, in the direction of
more power rather than less.
"""

from __future__ import annotations

from albanna.core.tools import TOOL_MANIFEST, parse_tool_names, unknown_tool_names


def test_nothing_is_nothing():
    assert parse_tool_names("") == ()
    assert parse_tool_names("   ") == ()
    assert parse_tool_names(None) == ()


def test_a_comma_separated_list_is_a_list():
    assert parse_tool_names("create_doc, delete_doc") == ("create_doc", "delete_doc")


def test_a_line_per_tool_is_a_list():
    assert parse_tool_names("create_doc\ndelete_doc\nrun_report") == (
        "create_doc",
        "delete_doc",
        "run_report",
    )


def test_the_two_separators_are_the_same_separator():
    """One way to write a list, not two ways that read differently."""

    assert parse_tool_names("create_doc, delete_doc") == parse_tool_names("create_doc\ndelete_doc")


def test_a_name_written_twice_is_kept_once():
    assert parse_tool_names("delete_doc, delete_doc") == ("delete_doc",)


def test_a_blank_entry_is_not_a_name():
    assert parse_tool_names("delete_doc,, ,\n") == ("delete_doc",)


def test_whitespace_separates_nothing():
    """``a b`` is one entry, and one entry that matches no tool.

    Reading two tools out of one line the operator thought was a list of
    two is the same silence as a typo — and worse, because the list would
    look as though it had been understood.
    """

    assert parse_tool_names("create_doc delete_doc") == ("create_doc delete_doc",)


def test_every_tool_the_manifest_knows_is_a_name_that_works():
    """The manifest is the list the description in the form carries."""

    names = ", ".join(TOOL_MANIFEST.names())
    assert unknown_tool_names(names) == ()


def test_a_name_that_is_not_a_tool_is_unknown():
    assert unknown_tool_names("create_doc, createe_doc") == ("createe_doc",)


def test_an_unknown_name_keeps_its_position_in_the_complaint():
    """The error the operator reads names the entries to fix, in order."""

    assert unknown_tool_names("nope, create_doc, alsonope") == ("nope", "alsonope")


def test_nothing_unknown_when_there_is_nothing_to_hide():
    assert unknown_tool_names("") == ()
    assert unknown_tool_names(None) == ()
