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

The alternative, one switch for the whole site, made the assistant weaker
than the person in front of it: an operator who wanted one role to write
had to let every account write.
"""

from __future__ import annotations

from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import creatable_doctypes, writable_doctypes


def tool_registry(user: str):
    """The tools this account is offered.

    The operator's disabled_tools list is still applied on top, because it
    is a feature switch rather than a permission one: a site that does not
    want a tool at all is entitled to be without it.
    """
    from albanna.services.settings_service import get_settings

    settings = get_settings()
    registry = TOOL_MANIFEST.without_writes_out_of_reach(
        creatable_doctypes(user),
        writable_doctypes(user),
    )
    return registry.without(settings.disabled_tools)
