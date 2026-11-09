"""The settings form's own gate, written down where it is checked.

The settings hold the provider's key, so who may read them is a security
question and not a convenience one.  The gate is a permission row on
``Albanna Settings`` — System Manager, read and write — and the doctype
is a Single, so the configuration is site-wide rather than per account.

Both of those are true by inspection and unheld by any test, which is
the shape this review keeps finding: a rule that is correct in the code
and unenforced by anything, so that a change to it passes every suite.
"""

from __future__ import annotations

import json
import pathlib

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
SETTINGS = APP_ROOT / "albanna" / "doctype" / "albanna_settings" / "albanna_settings.json"

#: The role that may read and write the settings.  It is the whole of the
#: shipped gate, and it is the role the operator holds.
SETTINGS_ROLE = "System Manager"

#: The fields FR-8.1 names.  The requirement is about configuring the
#: provider, so the fields that carry that configuration are asserted
#: rather than assumed — a field renamed or removed would otherwise be
#: discovered by an operator who opened the form and found it empty.
PROVIDER_FIELDS = (
    "provider_kind",
    "base_url",
    "model",
    "api_key",
    "temperature",
    "max_tokens",
    "timeout",
)


def _doc() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def test_the_shipped_matrix_names_one_door_and_no_other():
    """Only a System Manager may read or write the settings.

    A second row — ``All``, or ``Desk User`` — would hand the API key to
    every account on the site, and nothing else would notice.
    """
    roles = sorted({row.get("role") for row in _doc().get("permissions", []) if row.get("read")})
    assert roles == [SETTINGS_ROLE], (
        f"the shipped settings gate names {roles}. Every role on that list "
        f"may read the provider's key, and the settings ship with one: "
        f"{SETTINGS_ROLE}."
    )

    writers = sorted({row.get("role") for row in _doc().get("permissions", []) if row.get("write")})
    assert writers == [SETTINGS_ROLE], (
        f"the shipped settings gate lets {writers} write. A role that may "
        f"write the settings may change the provider, the key, and the "
        f"budget, and the settings ship with one: {SETTINGS_ROLE}."
    )


def test_the_settings_are_a_single():
    """The configuration is site-wide, not per account.

    A settings document that is not a Single gives every user their own
    copy, and the provider the assistant uses would depend on who opened
    the form.  The settings are a Single, and that is asserted rather
    than assumed.
    """
    assert _doc().get("issingle"), (
        "Albanna Settings is not a Single. The provider configuration "
        "would then be per account rather than site-wide."
    )


def test_the_provider_fields_are_present():
    """The fields FR-8.1 names exist on the form.

    A field renamed or removed would otherwise be discovered by an
    operator who opened the form and found it empty, which is the worst
    moment to learn it.
    """
    fieldnames = {field.get("fieldname") for field in _doc().get("fields", [])}

    missing = [name for name in PROVIDER_FIELDS if name not in fieldnames]
    assert not missing, f"the settings form is missing the provider fields FR-8.1 names: {missing}."
