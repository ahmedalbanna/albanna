"""Pins for the maintainability facts (NFR M-series, ADR-0108).

These are walkers, not feature tests: they read the source the way a
reviewer would, and fail when a fact the roadmap relies on stops being
true.

*   M1 — ``albanna.core`` imports nothing from Frappe or from the app's
    outer layers.  The domain is the part every other layer reaches for;
    if it reaches back, the layering is fiction.
*   M2 — the unit tests import no Frappe.  A suite that needs a site is
    a suite that cannot run on a laptop, and the domain tests especially
    must not.
*   M3 — the tool backend derives its bindings.  A declared table is a
    third place a new tool must be registered; the marker must be the
    only pairing.
*   M4 — ``providers/base.py`` names no adapter.  The adapters declare
    themselves; a dispatch written by hand in the base module is a
    second place a new provider must be registered.
*   M6 — every whitelisted API endpoint carries a docstring.  The API is
    the app's public face; an undocumented endpoint is undocumented API.
"""

from __future__ import annotations

import ast
import pathlib
import re

import albanna.tools.backend as tool_backend
from albanna.providers.base import build_provider, provider_kinds

APP = pathlib.Path(__file__).resolve().parent.parent
CORE = APP / "albanna" / "core"
API = APP / "albanna" / "api"
TESTS = APP / "tests"

#: The layers a core module may not reach into.  ``albanna.core`` itself
#: is the only ``albanna`` package it may import from.
FORBIDDEN_CORE_TARGETS = {
    "frappe",
    "albanna.api",
    "albanna.services",
    "albanna.tools",
    "albanna.providers",
    "albanna.permissions",
    "albanna.install",
    "albanna.privacy",
}


def _imports(tree: ast.AST) -> list[str]:
    """Every module an ``import``/``from`` statement in *tree* names."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_core_imports_nothing_from_frappe_or_the_outer_layers():
    """M1: the domain is the innermost layer, and it stays there."""
    offenders: list[str] = []
    for path in sorted(CORE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _imports(tree):
            root = name.split(".")[0]
            target = name if name.startswith("albanna.") else root
            if target == "albanna.core" or name == "albanna":
                continue
            if target in FORBIDDEN_CORE_TARGETS or any(
                target.startswith(f"{layer}.") for layer in FORBIDDEN_CORE_TARGETS
            ):
                offenders.append(f"{path.name}: {name}")
    assert offenders == [], offenders


def _unguarded_imports(tree: ast.AST) -> list[str]:
    """Every module an unguarded ``import``/``from`` statement names.

    A try/except-wrapped import is the suite's deliberate way to read a
    framework constant while still running without Frappe, so a guarded
    import is not an offence.
    """
    names: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Try):
            return
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return names


def test_the_unit_tests_import_no_frappe():
    """M2: a bare ``pytest tests/`` must never need a site."""
    offenders: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _unguarded_imports(tree):
            if name == "frappe" or name.startswith("frappe."):
                offenders.append(f"{path.name}: {name}")
    assert offenders == [], offenders


def test_the_tool_backend_declares_no_binding_table():
    """M3: the marker is the pairing; a declared table is a third place."""
    assert not hasattr(tool_backend, "_BOUND_TOOLS")
    source = pathlib.Path(tool_backend.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.search(r'"(list_docs|get_doc|read_file|ask_question)":', stripped), stripped


def test_providers_base_names_no_adapter():
    """M4: the adapters declare themselves; the base dispatches nothing."""
    source = (APP / "albanna" / "providers" / "base.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        assert not re.search(r"\b(OpenAIProvider|OllamaProvider|AnthropicProvider)\b", stripped), stripped


def test_every_provider_kind_builds():
    """M4: the registry the package declares is the registry that builds."""
    kinds = provider_kinds()
    assert {"openai", "ollama", "anthropic"} <= set(kinds)
    assert "groq" in kinds, "the OpenAI-compatible aliases must be registered"
    for kind in kinds:
        assert build_provider(kind).kind in kinds


def test_every_whitelisted_endpoint_has_a_docstring():
    """M6: the API is documented where the API is defined."""
    offenders: list[str] = []
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            whitelisted = any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "whitelist"
                for decorator in node.decorator_list
            )
            if whitelisted and not ast.get_docstring(node):
                offenders.append(f"{path.name}:{node.lineno}: {node.name}")
    assert offenders == [], offenders
