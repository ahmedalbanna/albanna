"""Domain tests for the pure diff helper."""

from albanna.core.diff import diff_fields, values_differ


def test_values_differ_treats_empty_and_missing_as_equal():
    assert not values_differ(None, "")
    assert not values_differ("", None)
    assert not values_differ("x", "x")


def test_values_differ_detects_a_real_change():
    assert values_differ("a", "b")
    assert values_differ(None, "x")
    assert values_differ("x", None)


def test_diff_fields_reports_only_changed_requested_fields():
    before = {"name": "Acme", "phone": "111", "untouched": "x"}
    after = {"name": "Acme", "phone": "222", "untouched": "x"}
    diff = diff_fields(before, after, ["phone", "untouched", "missing"])
    assert diff == {"phone": {"before": "111", "after": "222"}}
    assert "name" not in diff
    assert "missing" not in diff


def test_diff_fields_is_empty_when_nothing_changed():
    before = {"phone": "111"}
    after = {"phone": "111"}
    assert diff_fields(before, after, ["phone"]) == {}


def test_diff_fields_handles_non_dict_inputs():
    assert diff_fields(None, {"a": 1}, ["a"]) == {"a": {"before": None, "after": 1}}
    assert diff_fields({"a": 1}, None, ["a"]) == {"a": {"before": 1, "after": None}}
    assert diff_fields("nope", "nope", ["a"]) == {}
