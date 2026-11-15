"""Pins for the deployment requirements (NFR D1–D7, ADR-0111).

The walkers hold the shapes the D-series read and fixed:

D2  the model provider is the app's one outbound surface.  Any HTTP
    client outside ``albanna/providers/`` is a service the deployment
    requirement did not declare.
D3  no license machinery: the app must run without a license server or
    gateway, so the tokens that would carry one have no way in.
D4  schema changes flow through Frappe's migration system.  DDL is
    allowed only inside ``albanna/patches/`` — the migration system's
    own extension point — and only through the framework's helpers.
D5  the turn's job runs on a queue a stock bench serves workers for.
    A custom queue name is a turn parked in Redis forever.
D7  the app extends Frappe only through the framework's own extension
    points.  Overriding core classes or methods is a fork, not an app.
"""

from __future__ import annotations

import ast
import pathlib
import re

APP = pathlib.Path(__file__).parent.parent
PACKAGE = APP / "albanna"
PATCHES = PACKAGE / "patches"
PROVIDERS = PACKAGE / "providers"

HTTP_CLIENT_IMPORTS = re.compile(
    r"^\s*(import (requests|httpx|urllib|http\.client|socket)|from (requests|httpx|urllib|http\.client|socket)\b)",
    re.MULTILINE,
)
HTTP_CLIENT_CALLS = re.compile(
    r"\b(urlopen|requests\.(get|post|put|delete|head|request)|httpx\.(get|post))\b"
)
DDL_TOKENS = re.compile(
    r"\bsql_ddl\b|\bALTER\s+TABLE\b|\bCREATE\s+TABLE\b|\bDROP\s+TABLE\b|\bCHANGE\s+COLUMN\b|\badd_index\b",
    re.IGNORECASE,
)
LICENSE_TOKENS = re.compile(
    r"\bentitlement\b|\blicence\b(?!_server)|license[_-]server|license[_-]portal|8466",
    re.IGNORECASE,
)


def _python_files():
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        yield path


# -- D2: one outbound surface, the model provider --------------------------


def test_no_http_clients_outside_the_providers():
    offenders = []
    for path in _python_files():
        if PROVIDERS in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if HTTP_CLIENT_IMPORTS.search(text) or HTTP_CLIENT_CALLS.search(text):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, (
        f"an HTTP client outside providers/ is an undeclared external "
        f"service (NFR D2): {offenders}"
    )


# -- D3: no license server or gateway -------------------------------------


def test_no_license_machinery():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if LICENSE_TOKENS.search(text):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, (
        f"license machinery has no way into this app (NFR D3): {offenders}"
    )


# -- D4: DDL only inside the migration system -----------------------------


def test_no_ddl_outside_the_patches():
    offenders = []
    for path in _python_files():
        if PATCHES in path.parents:
            continue
        if DDL_TOKENS.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP)))
    assert not offenders, (
        f"schema changes belong in patches (NFR D4): {offenders}"
    )


def test_the_patches_run_through_the_migration_system():
    patches_txt = (PACKAGE / "patches.txt").read_text(encoding="utf-8")
    named = [
        line.strip()
        for line in patches_txt.splitlines()
        if line.strip() and not line.startswith(("#", "["))
    ]
    for name in named:
        module_path = APP.joinpath(*name.split(".")).with_suffix(".py")
        assert module_path.exists(), f"patch {name} names a module that does not exist"


# -- D5: the turn's job runs on a stock queue -----------------------------


def test_the_turn_job_queue_is_not_a_string_literal():
    chat = ast.parse((PACKAGE / "api" / "chat.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(chat)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", "") == "enqueue"
            or getattr(node.func, "attr", "") == "enqueue"
        )
    ]
    assert calls, "the enqueue call is gone from api/chat.py — the walker is blind"
    for node in calls:
        keywords = {kw.arg: kw.value for kw in node.keywords}
        if "queue" not in keywords:
            continue
        literal = isinstance(keywords["queue"], ast.Constant)
        assert not literal, (
            "the turn's queue is hard-coded — it must come from the "
            "settings so a site can pick a stock queue its workers "
            "actually serve (NFR D5)"
        )


def test_the_settings_honour_only_standard_queue_names():
    from albanna.services.settings_service import STANDARD_QUEUES, _queue

    assert STANDARD_QUEUES == ("short", "default", "long")
    assert _queue("long") == "long"
    assert _queue("") == "short"
    assert _queue("chat") == "short", "a custom queue name must fall back, not park the job"
    assert _queue("Short") == "short"


# -- D7: extension points, not overrides ---------------------------------


def test_the_hooks_override_no_core_behaviour():
    hooks = (PACKAGE / "hooks.py").read_text(encoding="utf-8")
    forbidden = (
        "override_doctype_class",
        "override_whitelisted_methods",
        "override_email_content",
        "extend_bootinfo_override",
    )
    present = [name for name in forbidden if name in hooks]
    assert not present, f"hooking core behaviour is a fork, not an app (NFR D7): {present}"


def test_no_monkey_patching_of_the_framework():
    """``setattr(frappe.local, ...)`` is the per-request memo idiom —
    request-scoped state, not a change to the framework.  Anything else
    that writes an attribute through frappe is a core edit."""
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and node.args
            ):
                target = ast.get_source_segment(text, node.args[0]) or ""
                if "frappe" in target and "frappe.local" not in target:
                    offenders.append(f"{path.name}:{node.lineno}: {target}")
    assert not offenders, f"setattr on frappe is a core edit (NFR D7): {offenders}"
