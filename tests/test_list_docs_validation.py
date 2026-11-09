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


# -- the child tables a create carries -------------------------------------


class FakeTableField:
    def __init__(self, fieldname, options):
        self.fieldname = fieldname
        self.fieldtype = "Table"
        self.options = options


class FakeDataField:
    def __init__(self, fieldname):
        self.fieldname = fieldname
        self.fieldtype = "Data"
        self.options = ""


def _meta_with(fields):
    return type("M", (), {"fields": fields})()


def test_a_fieldname_invented_in_a_child_row_is_refused():
    meta = _meta_with([FakeTableField("items", "Sales Invoice Item")])
    child = _meta_with([FakeDataField("qty"), FakeDataField("rate")])

    original = erpnext._meta
    erpnext._meta = lambda doctype: child if doctype == "Sales Invoice Item" else original(doctype)
    try:
        result = erpnext._child_table_refusal(
            meta, "Sales Invoice", {"items": [{"qty": 1, "quntity": 2}]}
        )
    finally:
        erpnext._meta = original

    assert result is not None
    assert "quntity" in result
    assert "qty" in result
    assert "Sales Invoice Item" in result


def test_a_fieldname_invented_two_levels_down_is_refused():
    """A child table's rows can carry table fields of their own, and a row
    inside one of those is the same silent drop one level further down."""
    meta = _meta_with([FakeTableField("items", "Sales Invoice Item")])
    child = _meta_with([FakeDataField("qty"), FakeTableField("serials", "Serial No Row")])
    grandchild = _meta_with([FakeDataField("serial_no")])

    def fake_meta(doctype):
        if doctype == "Sales Invoice Item":
            return child
        if doctype == "Serial No Row":
            return grandchild
        return original(doctype)

    original = erpnext._meta
    erpnext._meta = fake_meta
    try:
        result = erpnext._child_table_refusal(
            meta,
            "Sales Invoice",
            {"items": [{"qty": 1, "serials": [{"serial_no": "A1", "serail": "A2"}]}]},
        )
    finally:
        erpnext._meta = original

    assert result is not None
    assert "serail" in result
    assert "serial_no" in result
    assert "Serial No Row" in result


def test_a_well_formed_nested_row_is_allowed():
    """The check refuses invented fieldnames, not child tables."""
    meta = _meta_with([FakeTableField("items", "Sales Invoice Item")])
    child = _meta_with([FakeDataField("qty"), FakeTableField("serials", "Serial No Row")])
    grandchild = _meta_with([FakeDataField("serial_no")])

    original = erpnext._meta
    erpnext._meta = lambda doctype: {
        "Sales Invoice Item": child,
        "Serial No Row": grandchild,
    }.get(doctype, original(doctype))
    try:
        result = erpnext._child_table_refusal(
            meta,
            "Sales Invoice",
            {"items": [{"qty": 1, "serials": [{"serial_no": "A1"}]}]},
        )
    finally:
        erpnext._meta = original

    assert result is None


def test_the_recursion_is_bounded():
    """A DocType can name itself as its own child, and a check without a
    bound is a check that never returns."""
    meta = _meta_with([FakeTableField("items", "Sales Invoice Item")])
    child = _meta_with([FakeTableField("items", "Sales Invoice Item")])

    original = erpnext._meta
    erpnext._meta = lambda doctype: child if doctype == "Sales Invoice Item" else original(doctype)
    try:
        # A row that nests itself, deeper than the bound.
        row = {"items": [{"items": [{"items": [{"items": [{"qty": 1}]}]}]}]}
        result = erpnext._child_table_refusal(meta, "Sales Invoice", row)
    finally:
        erpnext._meta = original

    assert result is None, "the recursion ran away"
