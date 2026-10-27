"""The tool set one turn is allowed to use.

One function, because two callers need the same answer and a second copy
would be a second truth: the chat service builds the set it runs the turn
with, and the widget builds the set it tells the browser about.  They are
the same set, and they are computed the same way.

Frappe decides, and it decides per account.  A write tool appears when the
caller holds the right it needs somewhere on the site -- a person who may
create a ToDo is offered create_doc, and a person who may change a Customer
is offered update_doc -- and it does not appear when they do not, so the
model is never told about a tool it cannot use.
"""

from __future__ import annotations

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import (
    amendable_doctypes,
    cancellable_doctypes,
    creatable_doctypes,
    deletable_doctypes,
    submittable_doctypes,
    writable_doctypes,
)
from albanna.services.settings_service import get_settings


def tool_registry(user: str):
    """The tools this account is offered.

    Frappe decides: a write tool appears when the caller holds the right
    it needs somewhere on the site, and not otherwise.  The operator may
    also hide tools by name (the settings' "disabled tools" list) — a
    tool hidden there is hidden from everyone, regardless of role.

    There is no site-wide switch that can disagree with the permission
    matrix; the disabled list only ever narrows it.
    """
    base = TOOL_MANIFEST.without_writes_out_of_reach(
        creatable_doctypes(user),
        writable_doctypes(user),
        submittable_doctypes(user),
        cancellable_doctypes(user),
        amendable_doctypes(user),
        deletable_doctypes(user),
    )
    disabled = set(get_settings().disabled_tools or ())
    if not disabled:
        return base
    return base.without(disabled)
