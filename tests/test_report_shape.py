"""The shapes ``_report_shape`` reads.

Pure: no Frappe, no site.  ``_report_shape`` is the one place that
turns a report's raw result into columns and rows, and it has to cope
with four different shapes because ERPNext's reports do not agree on one.
"""

from __future__ import annotations

import pytest

erpnext = pytest.importorskip("albanna.tools.erpnext")


def test_a_six_tuple_yields_columns_and_rows():
    columns = ["name", "total"]
    rows = [["a", 1], ["b", 2]]
    raw = (columns, rows, "message", None, None, None)
    assert erpnext._report_shape(raw) == (columns, rows)


def test_a_two_tuple_yields_columns_and_rows():
    columns = ["name", "total"]
    rows = [["a", 1]]
    raw = (columns, rows)
    assert erpnext._report_shape(raw) == (columns, rows)


def test_a_dict_with_result_yields_columns_and_rows():
    columns = [{"label": "Name", "fieldname": "name"}]
    rows = [["a"]]
    raw = {"columns": columns, "result": rows}
    cols, got_rows = erpnext._report_shape(raw)
    assert cols == ["Name"]
    assert got_rows == rows


def test_a_dict_with_colnames_and_values():
    raw = {"colnames": ["x"], "values": [["y"]]}
    assert erpnext._report_shape(raw) == (["x"], [["y"]])


def test_a_plain_list_yields_no_columns():
    rows = [{"name": "a"}, {"name": "b"}]
    assert erpnext._report_shape(rows) == ([], rows)


def test_dict_columns_are_normalised_to_labels():
    raw = {"columns": [{"fieldname": "qty"}], "result": []}
    cols, _ = erpnext._report_shape(raw)
    assert cols == ["qty"]
