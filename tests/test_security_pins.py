"""The security posture, pinned at the source.

The SEC-series NFRs are mostly facts about *code* — a field's type, a
decorator's argument, a function that must never be called.  Such a fact
is only a fact while the source stays the way it was read, and a test
that walks the source keeps it so without needing the framework: a
harness that reads the same files the reading did.

The rules:

- the settings' API keys are ``Password`` fields, not ``Data`` — the
  ciphertext lives in the ``__Auth`` table and the column holds only a
  mask (SEC1);
- no whitelisted endpoint admits a guest — anonymous access is nowhere
  (SEC3);
- the audit log carries no question or answer text (SEC9);
- model output is never executed — no ``eval``, no ``exec``, no dynamic
  import outside the tests (SEC11);
- the panel speaks realtime through ``frappe.realtime`` and opens no
  socket of its own (SEC12).
"""

from __future__ import annotations

import ast
import pathlib
import re

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
API = APP_ROOT / "api"
DOCTYPES = APP_ROOT / "albanna" / "doctype"
PANEL = APP_ROOT / "public" / "js"
SERVICES = APP_ROOT


def _whitelisted_endpoints() -> list[tuple[pathlib.Path, ast.FunctionDef]]:
    """Every function in ``albanna/api`` that carries the whitelist decorator."""
    found: list[tuple[pathlib.Path, ast.FunctionDef]] = []
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "whitelist"
                ):
                    found.append((path, node))
    return found


def test_the_settings_keys_are_password_fields():
    """An API key that reads as a Data field reads as a key (SEC1)."""
    import json

    spec = DOCTYPES / "albanna_settings" / "albanna_settings.json"
    fields = json.loads(spec.read_text(encoding="utf-8"))["fields"]
    password_fields = {
        f["fieldname"]: f["fieldtype"]
        for f in fields
        if "key" in f["fieldname"] or "password" in f["fieldname"]
    }
    self_keys = {name: kind for name, kind in password_fields.items() if "key" in name}
    assert self_keys, "the settings hold no key fields at all"
    assert set(self_keys.values()) == {"Password"}, self_keys


def test_no_endpoint_admits_a_guest():
    """A whitelisted door that lets a guest in is anonymous access (SEC3).

    The one exception is named, not silent: the health check (NFR O3)
    must answer a monitor that holds no session, and its response is
    booleans, a status word and the app version — nothing the site has
    not already published.  See ADR-0112 and the ALLOWED_KEYS walker in
    test_observability_pins.py, which holds the response to exactly that.
    """
    allowed = {"health.py"}
    guests: list[str] = []
    for path, node in _whitelisted_endpoints():
        for decorator in node.decorator_list:
            for argument in getattr(decorator, "keywords", []):
                if argument.arg == "allow_guest":
                    truthy = ast.literal_eval(argument.value)
                    if truthy:
                        if path.name in allowed:
                            continue
                        guests.append(f"{path.name}:{node.name}")
    assert guests == [], f"endpoints behind an open door: {guests}"


def test_the_audit_log_carries_no_transcript():
    """The row may say *what happened*; it may not say *what was said* (SEC9)."""
    spec = DOCTYPES / "albanna_chat_log" / "albanna_chat_log.json"
    import json

    fields = json.loads(spec.read_text(encoding="utf-8"))["fields"]
    names = {f["fieldname"] for f in fields}
    forbidden = names & {"question", "answer", "prompt", "reply", "transcript", "messages"}
    assert forbidden == set(), f"the audit log holds reader words: {forbidden}"


def test_no_code_execution_in_shipped_python():
    """A refusal that runs the model's text is the end of privilege (SEC11).

    ``eval``, ``exec``, ``compile`` and ``__import__`` are banned outright.
    ``importlib.import_module`` is allowed: it can only load a module that
    is already importable on the app's path, so it is module *discovery*
    (the tool handlers and the provider adapters register themselves this
    way), never the execution of content the model produced.
    """
    banned = re.compile(r"(?<!re\.)\b(compile|eval|exec)\s*\(")
    imports = re.compile(r"\b__import__\s*\(")
    offenders: list[str] = []
    for path in SERVICES.rglob("*.py"):
        parts = path.relative_to(SERVICES).parts
        if parts and parts[0] in ("tests",):
            continue
        if "__pycache__" in parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped in ('"""', "'''"):
                continue
            if banned.search(line) or imports.search(line):
                offenders.append(f"{path.name}:{line_number}: {stripped}")
    assert offenders == [], offenders


def test_no_code_execution_in_shipped_panel():
    """``Function()`` and ``eval()`` in the panel are the same door (SEC11)."""
    banned = re.compile(r"\bnew\s+Function\s*\(|\beval\s*\(")
    offenders: list[str] = []
    for path in PANEL.rglob("*.mjs"):
        if path.name.endswith(".test.mjs"):
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "/*", "*")):
                continue
            if banned.search(line):
                offenders.append(f"{path.name}:{line_number}: {stripped}")
    assert offenders == [], offenders


def test_the_panel_opens_no_socket_of_its_own():
    """A socket that skips the framework skips the origin check (SEC12)."""
    banned = re.compile(r"\bnew\s+WebSocket\b|\bio\s*\(\s*[\"'({]|\bsocket\.io\b")
    offenders: list[str] = []
    for path in PANEL.rglob("*.mjs"):
        if path.name.endswith(".test.mjs"):
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "/*", "*")):
                continue
            if banned.search(line):
                offenders.append(f"{path.name}:{line_number}: {stripped}")
    assert offenders == [], offenders
