"""The fixture the smoke UI suite runs against.

A headless browser drives the real widget on a scratch dev server, and
it needs threads to find when the panel opens — because since the
conversation model changed, opening the panel *is* opening the reader's
most recent thread.  This seeds exactly what the suite asserts on:

*   one user, pinned to English, because the suite reads sentences off
    the screen and a user in the site's default language would answer in
    Arabic and fail the assertion for a reason that has nothing to do
    with the widget;
*   the **main thread** — the most recent one, so the panel opens on it:
    two plain messages, one asked from a page the panel is not on (the
    "Asked from" chip), one assistant turn that wrote a file and still
    carries a live undo entry (the Undo button), and two pending
    questions asked in one turn — one single-choice, one multiple —
    which arrive as one wizard card set;
*   the **long thread**: twenty-nine turns, titled so the drawer item
    can be found by text, long enough that ten messages sit behind the
    fifty-message transcript window — which is what the "Show N earlier
    messages" button and the turn dividers are checked against.

Run it from the bench root:

    bench --site test.localhost execute albanna.tests.ui_seed.seed

It is idempotent: the smoke user's threads and probe files are deleted
first, so every run starts from a known state.  It is *not* a test —
nothing asserts here — and it is not whitelisted, so nothing on the
wire can call it.
"""

from __future__ import annotations

import json

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

#: The title of the long thread, so the drawer item can be found by text.
LONG_TITLE = "SMOKE: a long thread"

#: How many turns the long thread holds.  Twenty-nine turns are
#: fifty-eight messages: eight behind the fifty-message window, which
#: names the count on the "Show earlier messages" button.
LONG_TURNS = 29

#: The single-choice question, and its two options.
SINGLE_QUESTION = "SMOKE: pick a priority."
SINGLE_OPTIONS = [
    {"label": "High", "value": "high"},
    {"label": "Low", "value": "low"},
]

#: The multiple-choice question, and its three options.
MULTI_QUESTION = "SMOKE: pick some colours."
MULTI_OPTIONS = [
    {"label": "Red", "value": "red"},
    {"label": "Blue", "value": "blue"},
    {"label": "Green", "value": "green"},
]

#: The tool summary the undo turn carries, so the suite can find its
#: Undo button by the message it belongs to.
UNDO_SUMMARY = "SMOKE: wrote undo-probe.txt"

#: The probe file's content.  The undo deletes the file, so the content
#: is a marker rather than a value anyone reads back.
UNDO_CONTENT = "SMOKE undo probe — written by the seeder."

#: The answer the undo turn stored beside its tool call.
UNDO_ANSWER = "SMOKE: this turn wrote a file."

#: The chat-log row the two seeded questions hang from.  A question's
#: ``turn`` is a Link to the ledger, so a real row has to exist for the
#: wizard to group the cards by it.


def seed() -> dict:
    """Bring the smoke fixture back to a known state, and describe it."""
    _ensure_user()

    # A clean slate: the panel opens the user's most recent thread, so
    # every thread of theirs except the ones being seeded has to go —
    # or an old run's thread would be the one the suite finds.  The
    # order is the links, reversed: a question names its turn (a log
    # row) and its thread, and a log names its thread, so the questions
    # go before the logs and the logs before the threads.  The probe
    # files go too: an undo from a run that never reached its click
    # leaves one behind otherwise.
    for doctype, filters in (
        ("Albanna Question", {"user": SMOKE_USER}),
        ("Albanna Chat Log", {"user": SMOKE_USER}),
        ("File", {"attached_to_name": SMOKE_USER, "file_name": "smoke-undo-probe.txt"}),
        ("Albanna Conversation", {"user": SMOKE_USER}),
    ):
        for name in frappe.get_all(doctype, filters=filters, pluck="name"):
            frappe.delete_doc(doctype, name, ignore_permissions=True)

    # The long thread first, so the main thread is the more recent one
    # and the panel opens on it.
    long_conversation = _seed_long_thread()
    main_conversation, file_name = _seed_main_thread()
    _seed_questions(main_conversation)

    frappe.db.commit()
    return {
        "main": main_conversation,
        "long": long_conversation,
        "file": file_name,
        "user": SMOKE_USER,
    }


def _seed_long_thread() -> str:
    """Twenty-nine plain turns, titled for the drawer."""
    from albanna.services.conversation_service import append_messages, new_conversation

    rows = []
    for turn in range(1, LONG_TURNS + 1):
        rows.append({"role": "user", "content": f"SMOKE long turn {turn} of {LONG_TURNS}: question"})
        rows.append({"role": "assistant", "content": f"SMOKE long turn {turn} of {LONG_TURNS}: answer"})

    conversation = new_conversation(SMOKE_USER, title=LONG_TITLE)
    append_messages(conversation, rows)
    frappe.db.set_value("Albanna Conversation", conversation, "title", LONG_TITLE)
    return conversation


def _seed_main_thread() -> tuple[str, str]:
    """The thread the panel opens on: chip, undo turn, plain words."""
    from albanna.services.conversation_service import append_messages, new_conversation

    # The file the undo turn claims to have written.  It is a real File
    # row, because the undo performs a real deletion — the check is not
    # "a button appeared", it is "the write was taken back".  Public and
    # attached to the smoke user's own record: the undo runs as that
    # user, with that user's permissions, and the probe carries nothing
    # private.
    probe = frappe.new_doc("File")
    probe.file_name = "smoke-undo-probe.txt"
    probe.attached_to_doctype = "User"
    probe.attached_to_name = SMOKE_USER
    probe.is_private = 0
    probe.content = UNDO_CONTENT
    probe.insert(ignore_permissions=True)

    calls = [
        {
            "name": "write_file",
            "ok": True,
            "summary": UNDO_SUMMARY,
            "undo": {"action": "delete", "doctype": "File", "name": probe.name},
        }
    ]

    conversation = new_conversation(SMOKE_USER)
    append_messages(
        conversation,
        [
            {"role": "user", "content": SEED_QUESTION},
            {"role": "assistant", "content": SEED_ANSWER},
            {"role": "assistant", "content": SEED_ANSWER_CROSS, "page_identity": CROSS_PAGE},
            {
                "role": "assistant",
                "content": UNDO_ANSWER,
                "tool_name": "write_file",
                "round_no": 1,
                "tool_calls": json.dumps(calls),
            },
        ],
    )
    return conversation, probe.name


def _seed_questions(conversation: str) -> None:
    """Two pending questions, asked in one turn, so they make one set.

    The turn is a real ``Albanna Chat Log`` row — the ledger the
    question's ``turn`` field links to — so the wizard groups the two
    cards by it the way it would group questions a real turn asked.
    """
    from albanna.services.questions import ask

    log = frappe.new_doc("Albanna Chat Log")
    log.user = SMOKE_USER
    log.conversation = conversation
    log.status = "ok"
    log.insert(ignore_permissions=True)

    ask(conversation, SMOKE_USER, SINGLE_QUESTION, SINGLE_OPTIONS, turn=log.name)
    ask(
        conversation,
        SMOKE_USER,
        MULTI_QUESTION,
        MULTI_OPTIONS,
        turn=log.name,
        multiple=True,
    )


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
