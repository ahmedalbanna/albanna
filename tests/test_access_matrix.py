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

import ast
import json
import pathlib

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
CONVERSATION = (
    APP_ROOT / "albanna" / "doctype" / "albanna_conversation" / "albanna_conversation.json"
)

#: The role the chat ships for.  It is the whole of the shipped gate.
CHAT_ROLE = "Albanna User"

#: The rights FR-7.3 names on that role.  The row is asserted against
#: this list rather than against a memory of it, because the four are
#: what the requirement asks for and a row that quietly lost one of them
#: would still be ``if_owner`` and would still pass every other test
#: here.
CHAT_RIGHTS = ("read", "write", "create", "delete")


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


def test_the_chat_row_grants_the_four_rights_and_is_one_row():
    """Read, write, create and delete — the four FR-7.3 names.

    The test above holds *whose* rows these are.  This one holds *which*
    rights, and how many rows there are.

    A row that lost its delete would still be ``if_owner`` and would
    still pass every other test in this file: the reader could no longer
    take back a thread they should not have kept, and nothing would say
    so.  The four are asserted against :data:`CHAT_RIGHTS` rather than
    against a memory of the row.

    One row, not two.  Frappe applies *every* matching row, so a second
    row for the same role is a second shape — and the wider of the two is
    the one that governs.  A row added later "for a special case" is how
    a gate that was one door becomes two.
    """
    rows = [row for row in _permissions() if row.get("role") == CHAT_ROLE]

    assert len(rows) == 1, (
        f"the shipped matrix has {len(rows)} {CHAT_ROLE} rows. One row is "
        "one door with one shape; two rows are two shapes, and Frappe "
        "applies both."
    )

    for right in CHAT_RIGHTS:
        assert rows[0].get(right), (
            f"the {CHAT_ROLE} row does not grant {right}. FR-7.3 names all "
            "four, and a reader who cannot delete their own thread cannot "
            "take back a question they should not have asked."
        )

    # The row grants exactly the four rights and nothing that crosses the
    # owner boundary.  ``share`` in particular would let a reader hand
    # their conversation to another user, which is the one right that
    # contradicts the "the chat is the reader's" posture in ADR-0014 and
    # decision 13.  It was granted by Frappe's default and never trimmed;
    # it is trimmed now, and this is what holds it trimmed.
    assert not rows[0].get("share"), (
        f"the {CHAT_ROLE} row grants share. A reader who may share their "
        "conversation hands it to somebody else, and the owner-only model "
        "does not survive that."
    )


def test_the_chat_role_is_the_one_the_app_creates():
    """The role the matrix names is the role the installer makes."""
    install = (APP_ROOT / "install.py").read_text(encoding="utf-8")
    assert f'role.role_name = "{CHAT_ROLE}"' in install, (
        f"the installer does not create {CHAT_ROLE}, so a fresh install has "
        "a permission row that names a role which does not exist."
    )


def test_the_installer_hands_the_chat_to_nobody():
    """The role is made, and it is given to no one.

    This is the other half of "off by default", and it is the half
    nothing held.  The matrix says which role may chat; the installer
    decides who *holds* that role — and the answer the requirement wants
    is "nobody, until an operator says otherwise".

    An ``add_roles`` anywhere in the install path would flip the default
    for every account on the site, and every other test would still pass:
    they each build their own user with explicit roles, so not one of
    them reads what the installer handed out.  ``after_migrate`` is in
    that path too, and a grant there would re-open the chat on every
    migrate rather than only on install.

    Parsed rather than searched for as text, because a comment that
    mentions ``add_roles`` is not a grant and a string that contains it
    is not a call.
    """
    tree = ast.parse((APP_ROOT / "install.py").read_text(encoding="utf-8"))

    granted = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "attr", None) == "add_roles"
            or getattr(node.func, "id", None) == "add_roles"
        )
    ]

    assert not granted, (
        f"the installer grants {CHAT_ROLE} at line(s) {granted}. The chat "
        "ships off for every account on the site; an operator turns it on, "
        "in the permission matrix, for the accounts they choose."
    )
