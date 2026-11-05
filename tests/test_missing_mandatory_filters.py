"""``_missing_mandatory_filters`` reports the keys a report needs.

Pure: no Frappe, no site.
"""

from __future__ import annotations

import pytest

erpnext = pytest.importorskip("albanna.tools.erpnext")


class FakeFilter:
    def __init__(self, fieldname, mandatory=0, default=None):
        self.fieldname = fieldname
        self.mandatory = mandatory
        self.default = default

    def get(self, key, default=None):
        return getattr(self, key, default)


class FakeReport:
    def __init__(self, filters):
        self.filters = filters


def test_a_mandatory_filter_without_a_default_is_missing():
    report = FakeReport([FakeFilter("company", mandatory=1)])
    assert erpnext._missing_mandatory_filters(report, {}) == ["company"]


def test_a_mandatory_filter_with_a_default_is_not_missing():
    report = FakeReport([FakeFilter("company", mandatory=1, default="Acme")])
    assert erpnext._missing_mandatory_filters(report, {}) == []


def test_a_supplied_mandatory_filter_is_not_missing():
    report = FakeReport([FakeFilter("company", mandatory=1)])
    assert erpnext._missing_mandatory_filters(report, {"company": "Acme"}) == []


def test_an_optional_filter_is_not_required():
    report = FakeReport([FakeFilter("from_date", mandatory=0)])
    assert erpnext._missing_mandatory_filters(report, {}) == []

    # dict-style rows (Frappe child docs expose .get)
    class DictRow(dict):
        pass

    report = FakeReport([DictRow(fieldname="x", mandatory=1)])
    assert erpnext._missing_mandatory_filters(report, {}) == ["x"]
