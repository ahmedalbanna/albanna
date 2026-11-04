"""A report the desk would refuse to run, the chat refuses to run too.

The desk refuses a report the caller's roles may not run, a report on a
DocType the caller may not report on, and a report an administrator has
disabled.  A role check that raises has not said yes.
"""

from __future__ import annotations

import json

import pytest

erpnext = pytest.importorskip("albanna.tools.erpnext")


class FakeReport(dict):
    """A Report document, as far as the refusal reads one."""

    def __init__(self, permitted=True, disabled=0, ref_doctype=None):
        super().__init__(disabled=disabled, ref_doctype=ref_doctype)
        self._permitted = permitted

    @property
    def ref_doctype(self):
        return self["ref_doctype"]

    def is_permitted(self):
        if isinstance(self._permitted, Exception):
            raise self._permitted
        return self._permitted


@pytest.fixture(autouse=True)
def report_permission(monkeypatch):
    monkeypatch.setattr(erpnext.frappe, "has_permission", lambda *a, **k: True, raising=False)


def _refusal(report_doc):
    envelope = erpnext._report_refusal(report_doc, "Salary Review")
    return json.loads(envelope) if envelope else None


def test_a_permitted_enabled_report_runs():
    assert _refusal(FakeReport()) is None


def test_a_disabled_report_is_refused():
    refusal = _refusal(FakeReport(disabled=1))

    assert refusal is not None
    assert refusal["status"] == "error"
    assert "disabled" in refusal["message"]


def test_a_role_check_that_raises_is_a_refusal():
    refusal = _refusal(FakeReport(permitted=RuntimeError("roles unreadable")))

    assert refusal is not None
    assert refusal["status"] == "error"
    assert "do not have access" in refusal["message"]


def test_a_role_restricted_report_is_refused():
    refusal = _refusal(FakeReport(permitted=False))

    assert refusal is not None
    assert refusal["status"] == "error"


def test_a_report_on_a_doctype_the_caller_may_not_report_on_is_refused(monkeypatch):
    monkeypatch.setattr(erpnext.frappe, "has_permission", lambda *a, **k: False, raising=False)

    refusal = _refusal(FakeReport(ref_doctype="Salary Slip"))

    assert refusal is not None
    assert refusal["ref_doctype"] == "Salary Slip"
