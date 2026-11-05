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


# -- the permission check comes first --------------------------------------


class RefusingReport(FakeReport):
    """A report the caller may not run, which also needs a filter.

    Both facts are true at once, and only one of them may be said: the
    mandatory filters are the report's own shape, and the shape of a thing
    the reader cannot reach is the same knowledge the DocType catalogue
    withholds.
    """

    def __init__(self, filters):
        super().__init__(filters)
        self.ref_doctype = "Salary Slip"

    def is_permitted(self):
        return False

    def get(self, key, default=None):
        return getattr(self, key, default)


def test_a_refused_report_is_not_told_which_filters_it_takes(monkeypatch):
    """The refusal names the permission, never the report's shape."""
    report = RefusingReport([FakeFilter("company", mandatory=1)])

    # The report resolves, the caller may not run it, and it needs a
    # filter.  The answer must be the refusal.
    monkeypatch.setattr(erpnext, "_resolve_report", lambda name, filters: (report, {}))
    monkeypatch.setattr(erpnext, "_report_refusal", lambda doc, name: "refused")

    answer = erpnext.run_report("Salary Register", filters={})

    assert answer == "refused", (
        "a reader who may not run a report was told which filters it takes before being refused"
    )


def test_a_permitted_report_is_still_told_its_missing_filters(monkeypatch):
    """The ordering must not cost the reader who *can* run it the hint."""
    report = FakeReport([FakeFilter("company", mandatory=1)])
    report.ref_doctype = "Sales Order"

    monkeypatch.setattr(erpnext, "_resolve_report", lambda name, filters: (report, {}))
    monkeypatch.setattr(erpnext, "_report_refusal", lambda doc, name: None)

    answer = erpnext.run_report("Sales Register", filters={})

    assert "company" in answer, (
        "the permission check ran first and swallowed the missing-filter hint "
        "for a reader who may run the report"
    )
