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


def _is_whitelisted_node(node: ast.FunctionDef) -> bool:
    """Whether this function's own decorators make it reachable."""
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "whitelist"
        ):
            return True
    return False


def _is_whitelisted(module: str, function: str) -> bool:
    """Whether the server's own source makes this function reachable."""
    source = (API / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        return _is_whitelisted_node(node)
    return False


#: The doors an endpoint may sit behind.
#:
#: ``require_chat_access`` is the chat's own: read on ``Albanna
#: Conversation``, shipped as the ``Albanna User`` role.  ``can_use_chat``
#: is the same rule read the other way round, for the one endpoint that
#: answers with a *decision* rather than a refusal — it publishes whether
#: this reader may chat, and hands back no tools and no data when they
#: may not.
#:
#: ``require_system_manager`` is the operator's, and it is narrower than
#: the chat's rather than wider: a System Manager who does not hold the
#: chat role is still refused the chat.  The two endpoints behind it run
#: no turn and read no conversation — one calls the provider to prove it
#: is configured, the other reads the site's own spend.
GATES = frozenset({"require_chat_access", "can_use_chat", "require_system_manager"})


def _endpoints() -> list[tuple[str, str, int, set[str]]]:
    """Every whitelisted endpoint, with the names its body calls."""
    found: list[tuple[str, str, int, set[str]]] = []
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not _is_whitelisted_node(node):
                continue
            called = {
                getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)
                for sub in ast.walk(node)
                if isinstance(sub, ast.Call)
            }
            found.append((path.stem, node.name, node.lineno, called))
    return found


def test_every_endpoint_is_behind_a_door():
    """A gate some endpoints remember and others forget is a gate that fails open.

    FR-7.2 says only a reader who holds the chat's role may use the chat.
    The rule is one function — ``require_chat_access`` — and it is only a
    rule while every door calls it.  An endpoint added tomorrow without
    it would be a road into the chat for every account on the site, and
    nothing else would notice: the function works, the route exists, and
    the reader is never refused.

    So the doors are counted here rather than trusted.  The comment
    above ``require_chat_access`` claims every endpoint calls it, and a
    claim like that is true until somebody adds a function — which is
    the whole reason this file exists.

    Parsed rather than read, because a docstring that mentions the gate
    is not a call to it.
    """
    endpoints = _endpoints()

    assert endpoints, "no endpoint was found — the rule below would pass on nothing"

    ungated = [
        f"{module}.{function} (line {line})"
        for module, function, line, called in endpoints
        if not (called & GATES)
    ]

    assert not ungated, (
        "these endpoints are reachable by any signed-in account and sit behind "
        "no door: " + ", ".join(ungated) + ". Every one of them needs "
        "require_chat_access(), or require_system_manager() if it is the "
        "operator's and not the reader's."
    )


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
