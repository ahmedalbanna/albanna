"""Pins for the observability requirements (NFR O1–O5, ADR-0112).

O1  the turn's log lines carry the identifiers a grep can join against
    the ledger: every ``logger.exception``/``logger.error`` call in the
    turn paths (``services/chat_job.py``, ``services/chat_service.py``)
    has at least one format argument.  A bare message is the shape
    "Chat turn failed" had — true, and useless.
O2  the turn-summary line exists and carries the metadata (provider,
    model, status, tokens, duration); the provider adapters log no
    content-bearing variable — the question and the answer reach no log.
O3  the health endpoint is whitelisted with ``allow_guest``, its
    response carries only the allowlisted keys, and it degrades rather
    than raising; the behaviour is tested with the probes mocked, so a
    monitor gets a readable body even when the site is half-broken.
O5  the ledger's status field is standard-filterable and carries the
    full vocabulary; the usage summary counts the errors.
"""

from __future__ import annotations

import ast
import pathlib
import re
from unittest import mock

APP = pathlib.Path(__file__).parent.parent
PACKAGE = APP / "albanna"

CONTENT_VARIABLES = re.compile(
    r"\b(payload|data|message|content|reply|question|answer|prompt|body|transcript)\b"
)


def _log_calls(path: pathlib.Path) -> list[tuple[int, ast.Call]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("exception", "error", "warning", "info", "debug")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            calls.append((node.lineno, node))
    return calls


# -- O1: the turn's error lines carry identifiers --------------------------


def test_the_turn_paths_log_with_context():
    for name in ("chat_job.py", "chat_service.py"):
        path = PACKAGE / "services" / name
        for lineno, call in _log_calls(path):
            if not call.args:
                continue
            fmt = call.args[0]
            if not (isinstance(fmt, ast.Constant) and isinstance(fmt.value, str)):
                continue
            if call.func.attr in ("exception", "error"):
                assert len(call.args) > 1, (
                    f"{name}:{lineno}: an error line with no identifiers "
                    f"— a grep cannot join it against the ledger (NFR O1): "
                    f"{fmt.value[:60]!r}"
                )


# -- O2: the metadata line, and no content in any log ---------------------


def test_the_turn_summary_line_exists():
    source = (PACKAGE / "services" / "chat_service.py").read_text(encoding="utf-8")
    assert "chat turn: user=%s provider=%s model=%s status=%s" in source, (
        "the turn-summary line is gone from chat_service.py — provider "
        "request/response metadata reaches no log (NFR O2)"
    )


def test_the_providers_log_no_content():
    offenders = []
    for path in sorted((PACKAGE / "providers").glob("*.py")):
        for lineno, call in _log_calls(path):
            for arg in call.args[1:] if call.args else []:
                segment = ast.get_source_segment(path.read_text(encoding="utf-8"), arg) or ""
                if CONTENT_VARIABLES.search(segment):
                    offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        f"a log call in the providers passes a content-bearing variable "
        f"(NFR O2): {offenders}"
    )


def test_the_turn_paths_log_no_content():
    offenders = []
    for name in ("chat_job.py", "chat_service.py"):
        path = PACKAGE / "services" / name
        source = path.read_text(encoding="utf-8")
        for lineno, call in _log_calls(path):
            for arg in call.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    continue
                segment = ast.get_source_segment(source, arg) or ""
                if CONTENT_VARIABLES.search(segment):
                    offenders.append(f"{name}:{lineno}: {segment[:40]}")
    assert not offenders, (
        f"a log call in the turn paths passes a content-bearing variable "
        f"(NFR O2): {offenders}"
    )


# -- O3: the health endpoint ----------------------------------------------


def test_the_health_endpoint_is_a_guest_door():
    source = (PACKAGE / "api" / "health.py").read_text(encoding="utf-8")
    assert "@frappe.whitelist(allow_guest=True)" in source, (
        "the health endpoint is not guest-callable — a monitor without a "
        "session cannot read it (NFR O3)"
    )


def test_the_health_response_keys_are_allowlisted():
    source = (PACKAGE / "api" / "health.py").read_text(encoding="utf-8")
    match = re.search(r'ALLOWED_KEYS = \(([^)]*)\)', source)
    assert match, "ALLOWED_KEYS is gone from health.py"
    allowed = {part.strip().strip('"\'') for part in match.group(1).split(",") if part.strip()}
    assert allowed == {"status", "checks", "version", "chat"}, allowed


def test_the_health_check_degrades_and_tells_the_truth():
    from albanna.api import health

    # Both probes broken: degraded, every check false, still readable.
    with mock.patch.object(health, "_db_probe", side_effect=RuntimeError("db down")), mock.patch.object(
        health, "_cache_probe", side_effect=RuntimeError("redis down")
    ), mock.patch.object(health, "_chat_ready", return_value=False):
        body = health._health()

    assert set(body) <= set(health.ALLOWED_KEYS), body.keys()
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": False, "cache": False}
    assert body["chat"] is False

    # Both probes healthy: ok, and the version is the app's own.
    with mock.patch.object(health, "_db_probe", return_value=None), mock.patch.object(
        health, "_cache_probe", return_value=None
    ), mock.patch.object(health, "_chat_ready", return_value=True):
        body = health._health()

    assert body["status"] == "ok"
    assert body["checks"] == {"database": True, "cache": True}
    assert body["chat"] is True
    assert isinstance(body["version"], str) and body["version"]


# -- O5: the ledger distinguishes the outcomes -----------------------------


def test_the_status_field_is_filterable_with_the_full_vocabulary():
    import json

    doctype = json.loads(
        (PACKAGE / "albanna" / "doctype" / "albanna_chat_log" / "albanna_chat_log.json").read_text()
    )
    status = next(f for f in doctype["fields"] if f["fieldname"] == "status")
    assert status.get("in_standard_filter"), (
        "the ledger's status is not filterable — the operator cannot ask "
        "for the failed turns (NFR O5)"
    )
    for word in ("ok", "error", "interrupted", "capped", "truncated", "denied"):
        assert word in status["options"].split("\n"), word


def test_the_usage_summary_counts_errors():
    source = (PACKAGE / "services" / "usage_service.py").read_text(encoding="utf-8")
    assert "status = 'error'" in source, (
        "the usage summary no longer counts the failed turns (NFR O5)"
    )
