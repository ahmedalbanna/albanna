"""Check that the Arabic catalogue covers the strings the app actually uses.

Run it from the app root:

    python scripts/check_translations.py

It reports two kinds of drift:

*   a string the code uses that the catalogue does not translate — the
    interface falls back to English for it, silently;
*   a translation the catalogue carries for a string the code no longer
    uses — dead weight, and a sign that a message was reworded without the
    catalogue being told.

Python files are read with :mod:`ast`, so a message written as an implicit
concatenation is seen as the single string the model will translate.  The
front-end files are read with a pattern, because their strings are always
on one line.

The tool descriptions in the manifest are deliberately *not* checked: they
are instructions to the model, not to the person, and they stay in English
because that is what the model reads best.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

APP = pathlib.Path(__file__).resolve().parents[1]
LOCALE = APP / "albanna" / "locale"

#: ``__("...")`` and ``_("...")`` in the front-end files.  The two ways a
#: string is marked for translation.
CALL = re.compile(r"""\b_{1,2}\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*[,)]""")


def unquote(literal: str) -> str:
    """The value of a quoted literal, with its escapes resolved."""
    body = literal[1:-1]
    body = body.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), body)


def python_strings(path: pathlib.Path) -> set[str]:
    """The translatable strings in a Python file.

    Read with :mod:`ast` rather than a pattern, so that a message written
    as an implicit concatenation is seen whole — which is how it is
    translated and how it is displayed.
    """
    found: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return found

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            # `frappe._("...")` — the same call, written out.
            name = func.attr
        else:
            continue
        if name not in ("_", "__"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)

    return found


def front_end_strings(path: pathlib.Path) -> set[str]:
    """The translatable strings in a JavaScript or Vue file."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return set()
    return {unquote(match.group(1)) for match in CALL.finditer(text)}


def catalogue_entries(po_path: pathlib.Path) -> set[str]:
    """The msgids in a ``.po`` file."""
    if not po_path.exists():
        return set()
    entries: set[str] = set()
    for line in po_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("msgid "):
            entries.add(unquote(line[6:].strip()))
    entries.discard("")
    return entries


def main() -> int:
    used = used_strings()
    catalogued = catalogue_entries(LOCALE / "ar.po")

    missing = sorted(used - catalogued)
    unused = sorted(catalogued - used)

    if missing:
        print(f"{len(missing)} string(s) used by the app but not translated:")
        for text in missing:
            print(f"  - {text}")

    if unused:
        print(f"\n{len(unused)} translation(s) for strings the app no longer uses:")
        for text in unused:
            print(f"  - {text}")

    if not missing and not unused:
        print("The Arabic catalogue matches the app's strings.")

    return 1 if missing else 0


def used_strings() -> set[str]:
    """Every string the app marks for translation."""
    used: set[str] = set()

    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts or "scripts" in path.parts:
            # The maintenance scripts are not part of the app's interface.
            continue
        used |= python_strings(path)

    for pattern in ("*.vue", "*.mjs", "*.js"):
        for path in APP.rglob(pattern):
            if "public/dist" in str(path):
                continue
            if path.name.endswith(".bundle.js"):
                # A build entry: imports and comments, no interface.
                continue
            used |= front_end_strings(path)

    # The manifest's descriptions are the model's, not the reader's.
    used -= set(catalogue_entries(APP / "albanna" / "core" / "tools.py"))

    return used


if __name__ == "__main__":
    sys.exit(main())
