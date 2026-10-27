"""The global Desk includes must resolve, and the files they name must exist.

Frappe resolves an ``app_include_js`` or ``app_include_css`` entry to a
hashed, content-addressed URL only when the name contains ``.bundle.``
(``frappe.utils.jinja_globals.bundled_asset``).  An entry without it is
passed through untouched and requested from the site root — where the file
does not exist.

The failure is invisible in every way that matters: the request 404s, the
browser logs a console error, the page renders perfectly, and the feature
is simply not there.  The "Ask Albanna" button on a form and the "Ask
Albanna" button on an error dialog were both missing on every page of
every site for exactly this reason, and nothing caught it, because a test
that reads ``hooks.py`` cannot see a 404.

So the rule is asserted here instead: every global include carries
``.bundle.``, and every one of them names a file that exists in the app's
``public`` folder.
"""

from __future__ import annotations

import ast
import pathlib

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
HOOKS = APP_ROOT / "hooks.py"


def _hook(name: str) -> list[str]:
    """The value of a module-level hook, read without importing Frappe."""
    tree = ast.parse(HOOKS.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = ast.literal_eval(node.value)
                return [value] if isinstance(value, str) else list(value)
    raise AssertionError(f"hooks.py does not define {name}")


def test_every_global_script_include_is_a_bundle():
    for entry in _hook("app_include_js"):
        assert ".bundle." in entry, (
            f"{entry!r} carries no '.bundle.', so Frappe requests it from the "
            "site root and it 404s. Name it '*.bundle.js' and Frappe resolves "
            "it to a hashed asset URL."
        )


def test_every_global_style_include_is_a_bundle():
    for entry in _hook("app_include_css"):
        assert ".bundle." in entry, (
            f"{entry!r} carries no '.bundle.', so Frappe serves it from a URL "
            "that never changes under a one-year max-age, pinning every "
            "returning user to the first stylesheet they loaded."
        )


def test_every_global_include_names_a_file_that_exists():
    for entry in _hook("app_include_js") + _hook("app_include_css"):
        source = APP_ROOT / "public" / "js" / entry
        if not source.exists():
            source = APP_ROOT / "public" / "css" / entry
        assert source.exists(), f"{entry!r} is included globally but does not exist."
