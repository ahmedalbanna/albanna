"""The fixture the smoke UI suite runs against.

A headless browser drives the real widget on a scratch dev server, and it
needs a thread to find when the panel opens — because since the
conversation model changed, opening the panel *is* opening the reader's
most recent thread.  This seeds exactly that: one user, one thread, three
messages — two plain and one asked from a page the panel is not on, which
is what the "Asked from" chip is for.

Run it from the bench root:

    bench --site test.localhost execute albanna.tests.ui_seed.seed

It is idempotent: the smoke user's threads are deleted first, so every
run starts from a known state.  It is *not* a test — nothing asserts
here — and it is not whitelisted, so nothing on the wire can call it.
"""

from __future__ import annotations

import frappe

#: The user the smoke suite logs in as.
SMOKE_USER = "albanna.smoke@albanna.dev"

#: The password the suite logs in with.  Test-only, on a test site.
SMOKE_PASSWORD = "albanna-smoke-pass"

#: The page identity one message carries, so the suite can assert the
#: chip appears for a message asked from somewhere the panel is not.
CROSS_PAGE = "form|Item|SMOKE-PROBE"

#: The question text the suite asserts is on screen after the panel opens.
SEED_QUESTION = "SMOKE: how many open sales orders are there?"

#: The answer text beside it.
SEED_ANSWER = "SMOKE: two are open."

#: The answer that carries the cross-page identity.
SEED_ANSWER_CROSS = "SMOKE: this one was asked from an Item."


def seed() -> dict:
    """Bring the smoke fixture back to a known state, and describe it."""
    _ensure_user()

    # A clean slate: the panel opens the user's most recent thread, so
    # every thread of theirs except the one being seeded has to go —
    # or an old run's thread would be the one the suite finds.
    for name in frappe.get_all(
        "Albanna Conversation", filters={"user": SMOKE_USER}, pluck="name"
    ):
        frappe.delete_doc("Albanna Conversation", name, ignore_permissions=True)

    from albanna.services.conversation_service import append_messages, new_conversation

    conversation = new_conversation(SMOKE_USER)
    append_messages(
        conversation,
        [
            {"role": "user", "content": SEED_QUESTION},
            {"role": "assistant", "content": SEED_ANSWER},
            {"role": "assistant", "content": SEED_ANSWER_CROSS, "page_identity": CROSS_PAGE},
        ],
    )
    frappe.db.commit()
    return {"conversation": conversation, "user": SMOKE_USER}


def _ensure_user() -> None:
    """The smoke user, with the roles the widget asks for and English.

    The interface language is pinned to English because the suite reads
    sentences off the screen — "Asked from Item" — and a user whose
    language is the site's default would answer in Arabic and fail the
    assertion for a reason that has nothing to do with the widget.
    """
    if not frappe.db.exists("User", SMOKE_USER):
        user = frappe.new_doc("User")
        user.email = SMOKE_USER
        user.first_name = "Albanna"
        user.last_name = "Smoke"
        user.language = "en"
        user.flags.ignore_permissions = True
        user.insert(ignore_permissions=True)

    user = frappe.get_doc("User", SMOKE_USER)
    user.language = "en"
    existing_roles = {role.role for role in user.roles or []}
    for role in ("Desk User", "Albanna User"):
        if role not in existing_roles:
            user.append("roles", {"role": role})
    user.flags.ignore_permissions = True
    user.save(ignore_permissions=True)

    from frappe.utils.password import update_password

    update_password(SMOKE_USER, SMOKE_PASSWORD)
