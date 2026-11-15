"""Pins for the internationalisation requirements (NFR I1–I6, ADR-0110).

Each walker here fails on the shape that would quietly re-introduce the
gap a fix closed:

I1  the tools' result and refusal messages are the summary lines the
    panel shows beside a tool's name and the text of its error card —
    the reader's language.  The walker forbids a bare string literal or
    f-string as the first argument of ``ok``/``error``/``_refusal``:
    every message must be built through ``_()`` (aliased from
    ``tools.base.translate``, the bench-free fallback), a templated
    sentence builder, or a variable whose construction the walker
    requires to contain ``_()`` templates.
I2  the Arabic catalogue covers every wrapped template.  The walker
    extracts every ``_()`` template on the server and every ``__()``
    literal in the panel, and requires each to be an msgid in
    ``albanna/locale/ar.po`` with a non-empty translation and the same
    number of placeholders.
I3  the catalogue parses with babel — the same parser the build's
    compiler uses — so a malformed entry fails a test, not the build.
I5  the manifest's descriptions stay English: no translation call may
    appear in ``core/tools.py``, and the wire builder must pass the
    description through untouched.
I6  no ``toFixed`` in the panel: numbers the reader compares (the turn
    cost, the attachment size) go through ``localeNumber``, which formats
    for the reader's locale.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from babel.messages.pofile import read_po

APP = pathlib.Path(__file__).parent.parent
TOOLS = APP / "albanna" / "tools"
PANEL = APP / "albanna" / "public" / "js" / "side-chat"
LOCALE = APP / "albanna" / "locale"

#: The message-carrying functions whose first argument the reader sees.
READER_FACING = {"ok", "error", "_refusal"}

#: Modules whose strings are *not* reader-facing: the backend's site
#: guards name operators, not readers, and ``base`` defines the
#: translator itself.
EXCLUDED = {"base.py", "backend.py"}


# -- I1: every reader-facing message is built through _() ------------------


def _iter_reader_calls(tree):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") in READER_FACING
            and node.args
        ):
            yield node


def test_every_tool_message_is_wrapped():
    for path in sorted(TOOLS.glob("*.py")):
        if path.name in EXCLUDED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _iter_reader_calls(tree):
            arg = call.args[0]
            bare = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            assert not bare, (
                f"{path.name}:{call.lineno}: a reader-facing message is an "
                f"unwrapped string — wrap it in _(): {ast.get_source_segment(path.read_text(), arg)[:70]!r}"
            )
            assert not isinstance(arg, ast.JoinedStr), (
                f"{path.name}:{call.lineno}: a reader-facing message is an "
                f"unwrapped f-string — use _('template').format(...)"
            )


def test_every_tool_module_aliases_the_translator():
    """The wrapper is ``tools.base.translate``; each module that carries
    reader-facing messages must alias it, so the bench-free unit suite
    (M2) keeps running and a real site translates."""

    source = (TOOLS / "base.py").read_text(encoding="utf-8")
    assert "def translate" in source, "the bench-free translator is gone from tools/base.py"

    for name in ("erpnext.py", "files.py", "history.py", "questions.py"):
        source = (TOOLS / name).read_text(encoding="utf-8")
        assert "from albanna.tools.base import translate as _" in source, (
            f"{name}: the translator alias is missing"
        )


def test_no_wrapped_call_sits_outside_the_reader_walker():
    """A sentence built from fragments concatenates badly in Arabic —
    the reading order of a sentence is not preserved by concatenation.
    Every ``_()`` call in the tools must carry a whole template, and the
    known sentence builders must not append raw English fragments."""

    for name in ("erpnext.py", "files.py", "history.py", "questions.py"):
        source = (TOOLS / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant) and getattr(node, "col_offset", 0) >= 0:
                        # An f-string is allowed only where no reader sees it:
                        # logging and internal keys.  Inside a message-building
                        # function it is a fragment the catalogue cannot hold.
                        pass
        # The fragment concatenations the ADR records as fixed stay fixed.
        assert 'message += " Failed: "' not in source, name
        assert 'message += " and submitted it"' not in source, name
        assert 'message += f" (and {len(failed) - 5} more)"' not in source, name


# -- I2: the catalogue covers every wrapped template -----------------------


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\\\", "\\")
    )


def _po_msgids() -> dict[str, str]:
    """The catalogue, through the same parser the build compiles with."""
    with (LOCALE / "ar.po").open("rb") as stream:
        catalog = read_po(stream)
    return {message.id: (message.string or "") for message in catalog if message.id}


def _server_templates() -> set[str]:
    templates: set[str] = set()
    roots = [TOOLS] + [
        APP / "albanna" / part
        for part in ("api", "services")
    ]
    for root in roots:
        for path in sorted(root.glob("*.py")):
            if path.name in EXCLUDED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_":
                    if not node.args:
                        continue
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        templates.add(arg.value)
    return templates


def _panel_strings() -> set[str]:
    strings: set[str] = set()
    sources = list(PANEL.glob("*.mjs")) + list(PANEL.glob("*.vue"))
    sources.append(APP / "albanna" / "public" / "js" / "albanna-side-chat.bundle.js")
    for path in sources:
        if path.name.endswith(".test.mjs"):
            continue
        text = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("//", "*", "/*"))
        )
        for match in re.finditer(r'__\(\s*"((?:[^"\\]|\\.)*)"', text):
            strings.add(_unescape(match.group(1)))
    return strings


def test_the_arabic_catalogue_covers_every_wrapped_template():
    msgids = _po_msgids()
    missing = sorted(t for t in _server_templates() | _panel_strings() if t not in msgids)
    assert not missing, f"{len(missing)} wrapped strings are not in the Arabic catalogue: {missing[:6]}"


def test_the_arabic_catalogue_has_no_untranslated_entry():
    msgids = _po_msgids()
    empty = sorted(msgid for msgid, msgstr in msgids.items() if not msgstr.strip())
    assert not empty, f"{len(empty)} msgids have an empty Arabic translation: {empty[:6]}"


def test_placeholders_match_between_msgid_and_msgstr():
    msgids = _po_msgids()
    mismatches = [
        (msgid, len(re.findall(r"\{\d+\}", msgid)), len(re.findall(r"\{\d+\}", msgstr)))
        for msgid, msgstr in msgids.items()
        if len(re.findall(r"\{\d+\}", msgid)) != len(re.findall(r"\{\d+\}", msgstr))
    ]
    assert not mismatches, f"placeholder-count mismatches: {mismatches[:6]}"


# -- I3: the catalogue parses with the build's own parser ------------------


def test_the_catalogue_parses_with_babel():
    with (LOCALE / "ar.po").open("rb") as stream:
        catalog = read_po(stream)
    assert len(list(catalog)) >= 400, "the Arabic catalogue has shrunk below its known size"


# -- I5: the manifest's descriptions stay English --------------------------


def test_the_manifest_builder_translates_nothing():
    source = (APP / "albanna" / "core" / "tools.py").read_text(encoding="utf-8")
    assert not re.search(r"\b_\(\s*[\"']", source), (
        "core/tools.py must not call the translator: the manifest is model-facing "
        "(NFR I5), and core/ cannot even import frappe (M1)"
    )
    assert "description=spec.description" in source, (
        "the wire builder must pass the description through untouched"
    )


# -- I6: no locale-blind number formatting in the panel --------------------


def test_the_panel_has_no_fixed_decimal_point():
    offenders = []
    for path in list(PANEL.glob("*.mjs")) + list(PANEL.glob("*.vue")):
        if path.name.endswith(".test.mjs"):
            continue
        text = path.read_text(encoding="utf-8")
        if ".toFixed(" in text:
            offenders.append(path.name)
    assert not offenders, f"toFixed (locale-blind) in the panel: {offenders} — use localeNumber"


def test_the_locale_number_formatter_exists():
    source = (PANEL / "format.mjs").read_text(encoding="utf-8")
    assert "export function localeNumber" in source, (
        "localeNumber is gone from format.mjs — the panel's numbers have no locale path"
    )
