"""Pins for the data integrity requirements (NFR DI1–DI5, ADR-0113).

The walkers hold the shapes the DI-series read, and the one fix they
brought:

DI1 the messages' order is the `idx` the writer allocated, and the
    allocation is serialised — two appends racing one thread must not
    walk away with the same index.
DI2 the ledger's cost is one pure function of tokens and price,
    deterministic by construction, called at write time and never
    recomputed for display.
DI3 deleting a conversation unlinks the ledger rather than deleting it —
    the ledger is the operator's record, and DI4 makes its rows
    append-only.
DI4 the audit trail is append-only where it matters: the desk may read
    it but not write or delete it, the retention prune is the only
    delete path, and a merged update never drops what the row already
    held.
DI5 a message's attachment references are held at both ends: rows gone
    release the files that only they named, and a file gone stops being
    named by any row.
"""

from __future__ import annotations

import ast
import json
import pathlib

APP = pathlib.Path(__file__).parent.parent
PACKAGE = APP / "albanna"

CONVERSATION_SERVICE = PACKAGE / "services" / "conversation_service.py"
ATTACHMENTS_SERVICE = PACKAGE / "services" / "attachments.py"
TASKS = PACKAGE / "tasks.py"
HOOKS = PACKAGE / "hooks.py"
CHAT_LOG_JSON = (
    PACKAGE / "albanna" / "doctype" / "albanna_chat_log" / "albanna_chat_log.json"
)


def _source(path: pathlib.Path) -> str:
    return path.read_text()


def _tree(path: pathlib.Path) -> ast.AST:
    return ast.parse(_source(path))


# -- DI1: the sequence is allocated under a lock ---------------------------


def test_index_allocation_takes_the_parent_row_lock():
    source = _source(CONVERSATION_SERVICE)
    append = source[source.index("def append_messages") : source.index("def _next_index")]
    assert "for update" in append, (
        "append_messages must take the conversation row FOR UPDATE before"
        " reading max(idx) — a plain read-then-insert race gives two rows"
        " the same index and no order between them."
    )
    # The locked read is also the existence check: a thread deleted while
    # its turn ran must store nothing, not orphan rows.
    assert "if not locked" in append


def test_next_index_continues_the_sequence():
    source = _source(CONVERSATION_SERVICE)
    next_index = source[source.index("def _next_index") :]
    assert "max(idx)" in next_index
    # Every read that presents history orders by the same index.
    assert source.count("order by idx") >= 3


# -- DI2: one deterministic cost calculation --------------------------------


def test_cost_has_one_calculator():
    # Every cost in the app comes from cost_of_turn.
    uses = [
        path
        for path in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts and "cost_of_turn(" in path.read_text()
    ]
    assert uses == [
        PACKAGE / "core" / "cost.py",
        PACKAGE / "services" / "chat_service.py",
    ], uses


def test_cost_of_turn_is_pure_and_rounded():
    tree = _tree(APP / "albanna" / "core" / "cost.py")
    names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "cost_of_turn" in names
    source = _source(APP / "albanna" / "core" / "cost.py")
    assert "round(" in source, "the ledger's number must be rounded, not raw float noise"
    assert "import frappe" not in source, "the calculation must not depend on a site"


def test_cost_of_turn_is_deterministic():
    import sys

    sys.path.insert(0, str(APP))
    from albanna.core.cost import cost_of_turn

    pairs = [
        (1000, 2000, 0.5),
        (12345, 67890, 1.25),
        (0, 1, 0.0001),
        (999999, 999999, 3.7),
        (0, 0, 1.0),
        (500, 300, 0.0),
    ]
    for tokens_in, tokens_out, price in pairs:
        first = cost_of_turn(tokens_in, tokens_out, price)
        assert first == cost_of_turn(tokens_in, tokens_out, price)
        assert repr(first) == repr(cost_of_turn(tokens_in, tokens_out, price))
    assert cost_of_turn(1_000_000, 0, 2.0) == 2.0
    assert cost_of_turn(0, 500, 0.0) == 0.0


# -- DI3: the ledger is unlinked, not deleted, with its conversation --------


def test_conversation_delete_unlinks_the_ledger():
    source = _source(CONVERSATION_SERVICE)
    delete = source[source.index("def delete_conversation") :]
    assert "update `tabAlbanna Chat Log` set conversation = null" in delete
    assert "delete from `tabAlbanna Chat Log`" not in source


def test_conversation_delete_releases_the_message_files():
    source = _source(CONVERSATION_SERVICE)
    delete = source[source.index("def delete_conversation") :]
    assert "release_message_files" in delete, (
        "a thread's rows gone with nobody following their addresses leaves"
        " the chat's private files on the disk for ever."
    )


# -- DI4: the audit trail is append-only where it matters -------------------


def test_chat_log_grants_no_write_access_to_any_role():
    doctype = json.loads(_source(CHAT_LOG_JSON))
    for perm in doctype.get("permissions", []):
        granted = [key for key in ("write", "create", "delete", "cancel", "amend") if perm.get(key)]
        assert not granted, (
            f"role {perm.get('role')} holds {granted} on Albanna Chat Log —"
            " the ledger's rows are written by the turn, and only by the"
            " turn; the desk must not be able to rewrite them."
        )


def test_retention_prune_is_the_only_chat_log_delete():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        source = path.read_text()
        if "Albanna Chat Log" not in source and "tabAlbanna Chat Log" not in source:
            continue
        lowered = source.lower()
        if (
            'db.delete("albanna chat log"' in lowered
            or "delete from `tabalbanna chat log`" in lowered
        ) and path != TASKS:
            offenders.append(path)
    assert not offenders, (
        f"{[str(o.relative_to(APP)) for o in offenders]} delete ledger rows —"
        " the retention prune in tasks.py is the only delete path the audit"
        " trail has."
    )


def test_a_log_update_merges_what_the_row_already_holds():
    source = _source(PACKAGE / "services" / "chat_service.py")
    log = source[source.index("def _log") :]
    # The approvals were asked for and answered while the turn ran; an
    # update that overwrites `tools` without reading them back drops the
    # record of what was confirmed.
    merge_position = log.index("approvals_of(")
    tools_position = log.index("doc.tools = ")
    assert merge_position < tools_position, (
        "_log must read the row's existing approvals before it overwrites"
        " the tools payload — the record of what was confirmed must never"
        " shrink."
    )


# -- DI5: the attachment references are held both ways ----------------------


def test_released_files_are_the_chat_s_own():
    source = _source(ATTACHMENTS_SERVICE)
    assert "albanna-" in source and "is_private" in source, (
        "the cleanup must recognise the files the chat stored — private,"
        " named albanna-… — and never touch anybody else's File records."
    )


def test_delete_turn_releases_its_files():
    source = _source(CONVERSATION_SERVICE)
    delete = source[source.index("def delete_turn") : source.index("def _url_list")]
    assert "release_message_files" in delete


def test_a_deleted_file_stops_being_named():
    source = _source(ATTACHMENTS_SERVICE)
    hook = source[source.index("def on_file_trash") :]
    assert "attachment_urls" in hook and "attachment_texts" in hook, (
        "the address and the text that travelled beside it must both go —"
        " removing only the address misaligns the parallel lists."
    )
    hooks = _source(HOOKS)
    assert "on_file_trash" in hooks and '"File"' in hooks
