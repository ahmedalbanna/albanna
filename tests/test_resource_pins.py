"""Pins for the resource efficiency requirements (NFR RE1–RE5, ADR-0114).

The walkers hold the shapes the RE-series read, measured and fixed:

RE1 the app costs a worker its own modules and nothing more at boot;
    the provider HTTP stack (``requests`` and its tree, some nine
    megabytes) loads with the first turn, not with the import.
RE2 the app opens no database connections of its own — every read is
    the request-scoped ``frappe.db`` and every cache touch the
    framework's pooled ``frappe.cache()``.
RE3 a turn's marker and its parked answer live one hour by default,
    the operator can say so, and the turn's own clock is the floor.
RE4 the history the model reads is bounded by the configured limit,
    default 50, and both consumers read the setting.
RE5 the status poll reads the cache while the turn runs; the database
    is asked once, at the terminal lost verdict, never per poll — and
    the realtime publish is the primary delivery.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

APP = pathlib.Path(__file__).parent.parent
PACKAGE = APP / "albanna"

PROVIDERS_INIT = PACKAGE / "providers" / "__init__.py"
SETTINGS_SERVICE = PACKAGE / "services" / "settings_service.py"
CHAT_API = PACKAGE / "api" / "chat.py"
CHAT_JOB = PACKAGE / "services" / "chat_job.py"
SETTINGS_JSON = (
    PACKAGE / "albanna" / "doctype" / "albanna_settings" / "albanna_settings.json"
)

OWN_DB_CLIENTS = re.compile(
    r"\bpymysql\b|\bmysql\.connector\b|\bcreate_engine\b"
    r"|\bfrappe\.db\.get_connection\b|\bsqlite3\b|\bpsycopg\b"
)


def _source(path: pathlib.Path) -> str:
    return path.read_text()


def _tree(path: pathlib.Path) -> ast.AST:
    return ast.parse(_source(path))


# -- RE1: the provider HTTP stack loads with the first turn -----------------


def test_providers_package_imports_no_adapter_at_boot():
    tree = _tree(PROVIDERS_INIT)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            "albanna.providers."
        ) and node.module != "albanna.providers.base":
            offenders.append(node.module)
        if isinstance(node, ast.ImportFrom) and node.module in (
            "anthropic",
            "ollama",
            "openai",
        ):
            offenders.append(node.module)
    assert not offenders, (
        f"{offenders} imported by the providers package itself — every"
        " worker that imports anything under albanna.providers would pay"
        " for the adapters' HTTP stack at boot.  The concrete classes"
        " resolve through module __getattr__ on first use."
    )
    assert "__getattr__" in _source(PROVIDERS_INIT)


def test_importing_the_base_loads_no_http_stack():
    # A real import, in a fresh interpreter: frappe's baseline carries
    # no requests, so a base import that loads it is the regression
    # the walker above guards against — held behaviourally, not only
    # by shape.
    code = (
        "import frappe, albanna.providers.base, albanna.services.settings_service,"
        " albanna.services.chat_service, sys;"
        " assert 'requests' not in sys.modules, 'requests loaded at boot'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(APP.parent.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


# -- RE2: no database connections of the app's own --------------------------


def test_no_own_database_clients():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        if OWN_DB_CLIENTS.search(path.read_text()):
            offenders.append(path.relative_to(APP))
    assert not offenders, (
        f"{[str(o) for o in offenders]} open database connections of their"
        " own — every read goes through the request-scoped frappe.db, and"
        " the framework owns the pool."
    )


# -- RE3: the parked answer lives an hour by default, configurable ----------


def test_the_ttl_is_a_setting_with_the_hour_default():
    import json

    doctype = json.loads(_source(SETTINGS_JSON))
    fields = {f["fieldname"]: f for f in doctype["fields"]}
    ttl = fields.get("turn_cache_ttl_seconds")
    assert ttl is not None, "the operator has no knob for the cache span"
    assert ttl.get("default") == "3600"
    assert "turn_cache_ttl_seconds" in doctype.get("field_order", [])
    source = _source(SETTINGS_SERVICE)
    assert "_int(doc.turn_cache_ttl_seconds, 3600)" in source


def test_the_ttl_floor_is_the_turns_own_clock():
    source = _source(CHAT_API)
    function = source[source.index("def turn_cache_ttl_seconds") :]
    assert "max(configured," in function, (
        "the configured span must never be honoured below the turn's own"
        " clock — a marker that dies under a live turn has status declare"
        " the turn lost while it is still working."
    )
    # The lost-turn deadline is a different number and stays on the
    # turn's clock, not the cache span.
    deadline = source[source.index("def _turn_deadline") :]
    assert "job_budget_seconds(turn, wait) + STALE_GRACE_SECONDS" in deadline


def test_every_marker_write_uses_the_ttl():
    api = _source(CHAT_API)
    assert "expires_in_sec=ttl" in api, "the initial marker write"
    job = _source(CHAT_JOB)
    writes = job.count("expires_in_sec=turn_cache_ttl_seconds(get_settings())")
    assert writes == 2, (
        f"the job renews the marker at {writes} places, expected 2 — the"
        " heartbeat's first renewal and the mirror's."
    )


# -- RE4: the history bound is the configured limit, default 50 -------------


def test_history_default_is_fifty_and_consumers_read_it():
    source = _source(SETTINGS_SERVICE)
    assert "_int(doc.history_limit, 50)" in source
    chat_service = _source(PACKAGE / "services" / "chat_service.py")
    assert "conversation, settings.history_limit" in chat_service, (
        "the turn's history read must carry the configured limit"
    )
    history = _source(PACKAGE / "tools" / "history.py")
    assert "get_settings().history_limit" in history, (
        "the prompt window must read the same setting"
    )


def test_history_read_is_bounded_in_the_database():
    source = _source(PACKAGE / "services" / "conversation_service.py")
    function = source[source.index("def load_messages") :]
    assert "limit %s" in function, (
        "the history query must be bounded in the database, not in memory"
    )


# -- RE5: the running status asks the cache, never the database -------------


def test_status_running_path_touches_no_database():
    tree = _tree(CHAT_API)
    function = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "status":
            function = node
    assert function is not None
    offenders = []
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and node.attr in (
            "sql",
            "get_value",
            "get_all",
            "get_doc",
            "exists",
            "delete",
            "set_value",
        ):
            # frappe.db.anything and frappe.get_doc are both Attribute
            # nodes; a cache read is not.
            value = node.value
            names = set()
            while isinstance(value, ast.Attribute):
                names.add(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                names.add(value.id)
            if "db" in names or "frappe" in names and node.attr == "get_doc":
                offenders.append(node.attr)
    assert not offenders, (
        f"status touches {offenders} — the running path must read only the"
        " cache; the database is asked once, at the lost verdict, and"
        " that call belongs to _lost_turn."
    )


def test_the_realtime_publish_is_the_delivery():
    source = _source(CHAT_JOB)
    assert "publish_realtime" in source, (
        "the socket is the primary delivery; a chat with no realtime path"
        " is a chat that polls the cache for everything."
    )
    turn = _source(APP / "albanna" / "public" / "js" / "side-chat" / "turn.mjs")
    assert "albanna.api.chat.status" in turn, (
        "the polling fallback must name the cache-backed endpoint"
    )
