"""Every method the panel calls must be one the server exposes.

The panel calls the server by name — ``albanna.api.conversations.list_conversations``
— and Frappe refuses a method that is not whitelisted.  The refusal is
correct and the panel handles it: the reader is told the request could not
be completed.

But a button that always fails is a button that is always broken, and the
reader cannot tell it from a server that is busy.  The delete-conversation
button in the drawer was exactly that: the decorator that belonged to
``delete_conversation`` became the decorator of ``escalate_conversation``
when the escalate feature was added, and the button has failed on every
click since — silently, behind a sentence about the request.

Nothing caught it, because a test that calls the function directly does
not go through the whitelist: the function works, and the *route* to it
does not exist.  So the rule is asserted here instead — the panel's calls
are read out of the front-end, and each one is checked against the
server's own source for the decorator that makes it reachable.
"""

from __future__ import annotations

import ast
import pathlib
import re

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
FRONT_END = APP_ROOT / "public" / "js"
API = APP_ROOT / "api"

#: A method path the panel calls, as it is written in the front-end.
CALL = re.compile(r"""["'](albanna\.api\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)["']""")


def _called_methods() -> set[str]:
    """Every server method the front-end names."""
    found: set[str] = set()
    for path in list(FRONT_END.rglob("*.vue")) + list(FRONT_END.rglob("*.mjs")):
        found.update(CALL.findall(path.read_text(encoding="utf-8")))
    return found


def _is_whitelisted(module: str, function: str) -> bool:
    """Whether the server's own source makes this function reachable."""
    source = (API / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "whitelist"
            ):
                return True
    return False


def test_the_panel_calls_methods_the_server_exposes():
    called = _called_methods()

    assert called, "the front-end names no server method — the rule below would pass on nothing"

    unreachable = sorted(
        path for path in called if not _is_whitelisted(path.split(".")[-2], path.split(".")[-1])
    )

    assert not unreachable, (
        "the panel calls these methods, and the server does not expose them: "
        + ", ".join(unreachable)
    )
