"""The validation ``list_docs`` applies to its filters and sort.

Pure: no Frappe, no site.  The helpers are exercised directly.
"""

from __future__ import annotations

import pytest

erpnext = pytest.importorskip("albanna.tools.erpnext")


class FakeMeta:
    def __init__(self, fields):
        self.fields = [type("F", (), {"fieldname": f}) for f in fields]


KNOWN = ["name", "status", "modified", "customer"]


def test_a_valid_filter_passes():
    filters = [["status", "=", "Open"]]
    assert erpnext._validate_filters(filters, "X") is None


def test_a_list_value_is_rejected():
    filters = [["status", "=", ["a", "b"]]]
    result = erpnext._validate_filters(filters, "X")
    assert result is not None
    assert "plain string" in result


def test_an_object_value_is_rejected():
    filters = [["status", "=", {"a": 1}]]
    result = erpnext._validate_filters(filters, "X")
    assert result is not None
    assert "plain string" in result


def test_a_two_element_filter_is_rejected():
    filters = [["status", "="]]
    result = erpnext._validate_filters(filters, "X")
    assert result is not None
    assert "three elements" in result


def test_a_four_element_filter_is_rejected():
    filters = [["status", "=", "x", "y"]]
    result = erpnext._validate_filters(filters, "X")
    assert result is not None
    assert "three elements" in result


def test_an_unknown_operator_is_rejected():
    filters = [["status", "contains", "x"]]
    result = erpnext._validate_filters(filters, "X")
    assert result is not None
    assert "Unknown filter operator" in result


def test_a_dict_filter_with_a_non_string_value_is_rejected():
    result = erpnext._validate_filters({"status": 5}, "X")
    assert result is not None
    assert "plain string" in result


def test_a_valid_order_by_passes():
    meta = FakeMeta(KNOWN)
    assert erpnext._validate_order_by(meta, "X", "modified desc") is None


def test_a_bare_fieldname_passes():
    meta = FakeMeta(KNOWN)
    assert erpnext._validate_order_by(meta, "X", "status") is None


def test_a_comma_separated_list_passes():
    meta = FakeMeta(KNOWN)
    assert erpnext._validate_order_by(meta, "X", "status asc, modified desc") is None


def test_an_invented_sort_field_is_rejected():
    meta = FakeMeta(KNOWN)
    result = erpnext._validate_order_by(meta, "X", "nope desc")
    assert result is not None
    assert "Unknown sort field" in result
    assert "closest" in result


def test_an_unknown_direction_is_rejected():
    meta = FakeMeta(KNOWN)
    result = erpnext._validate_order_by(meta, "X", "status sideways")
    assert result is not None
    assert "Unknown sort direction" in result
