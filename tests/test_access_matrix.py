"""The chat has one door, and the app ships it.

The gate is a read permission on ``Albanna Conversation``, read through
Frappe's own permission matrix (decision 11).  The *live* matrix belongs
to the operator, who may widen or narrow it; the **shipped** matrix
belongs to the app, and it is what decides who can chat before anybody
has touched anything.

So the shipped matrix is asserted here: one role, and one role only.  A
second row — a ``System Manager`` row, say — reopens the chat to every
account on the site that holds that role, which is a wider door than the
one the owner of the site asked for.

The test reads the DocType's JSON rather than the database on purpose.
The database holds what the last migrate put there; the file holds what
the next migrate will put there.  A gate that only holds until the next
release is not a gate — and a Desk edit of the live matrix is undone by
the next migrate that touches this DocType.
"""

from __future__ import annotations

import json
import pathlib

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
CONVERSATION = (
    APP_ROOT / "albanna" / "doctype" / "albanna_conversation" / "albanna_conversation.json"
)

#: The role the chat ships for.  It is the whole of the shipped gate.
CHAT_ROLE = "Albanna User"


def _permissions() -> list[dict]:
    doc = json.loads(CONVERSATION.read_text(encoding="utf-8"))
    return doc.get("permissions") or []


def test_the_shipped_matrix_names_one_door_and_no_other():
    roles = sorted({row.get("role") for row in _permissions() if row.get("read")})
    assert roles == [CHAT_ROLE], (
        f"the shipped chat gate names {roles}. Every role on that list is a "
        "door into the chat for everybody on the site who holds it, and the "
        f"chat ships with one: {CHAT_ROLE}."
    )


def test_the_chat_row_is_scoped_to_the_owner():
    """The row grants the reader their own history, and nobody else's."""
    rows = [row for row in _permissions() if row.get("role") == CHAT_ROLE]
    assert rows, f"the shipped matrix has no {CHAT_ROLE} row"

    for row in rows:
        assert row.get("if_owner"), (
            f"the {CHAT_ROLE} row is not if_owner, so it would grant read on "
            "everybody's conversations rather than the reader's own."
        )


def test_the_chat_role_is_the_one_the_app_creates():
    """The role the matrix names is the role the installer makes."""
    install = (APP_ROOT / "install.py").read_text(encoding="utf-8")
    assert f'role.role_name = "{CHAT_ROLE}"' in install, (
        f"the installer does not create {CHAT_ROLE}, so a fresh install has "
        "a permission row that names a role which does not exist."
    )
