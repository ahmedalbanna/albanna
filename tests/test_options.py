"""The operator's extra options for the provider.

The rule under test: the options are the operator's own words, parsed into
the types they mean — and the app's own settings are never overwritten by
a line of JSON typed later.
"""

from __future__ import annotations

from albanna.core.options import merge_options, parse_options


def test_no_options_are_no_options():
    assert parse_options("") == {}
    assert parse_options("   ") == {}
    assert parse_options(None) == {}


def test_the_options_are_read():
    assert parse_options('{"setCacheKey": "abc"}') == {"setCacheKey": "abc"}


def test_a_string_that_spells_a_boolean_is_a_boolean():
    """A provider's own configuration writes "True" where it means the
    boolean, and the SDK that reads it parses it into one."""

    assert parse_options('{"setCacheKey": "True"}') == {"setCacheKey": True}
    assert parse_options('{"setCacheKey": "true"}') == {"setCacheKey": True}
    assert parse_options('{"setCacheKey": "FALSE"}') == {"setCacheKey": False}
    assert parse_options('{"setCacheKey": " false "}') == {"setCacheKey": False}


def test_a_number_is_a_number():
    assert parse_options('{"top_p": 0.7, "n": 3}') == {"top_p": 0.7, "n": 3}


def test_a_string_that_is_not_a_boolean_stays_a_string():
    assert parse_options('{"name": "True Story"}') == {"name": "True Story"}
    assert parse_options('{"name": "yes"}') == {"name": "yes"}


def test_something_that_is_not_json_is_no_options():
    assert parse_options("not json") == {}
    assert parse_options("{oops}") == {}


def test_something_that_is_not_an_object_is_no_options():
    """A list is not a set of options, and a number is not either."""

    assert parse_options('["a", "b"]') == {}
    assert parse_options("42") == {}
    assert parse_options('"a string"') == {}


def test_the_options_are_added_to_the_request():
    payload = {"model": "m", "messages": []}
    merged = merge_options(payload, {"setCacheKey": True})

    assert merged["setCacheKey"] is True
    assert merged["model"] == "m"


def test_the_apps_own_settings_win():
    """The options are *extra*: what the app has a field for was written
    on purpose."""

    payload = {"model": "the-model", "temperature": 0.2}
    merged = merge_options(payload, {"model": "another-model", "temperature": 1.5})

    assert merged["model"] == "the-model"
    assert merged["temperature"] == 0.2


def test_no_options_leave_the_payload_alone():
    payload = {"model": "m"}
    assert merge_options(payload, {}) is payload
