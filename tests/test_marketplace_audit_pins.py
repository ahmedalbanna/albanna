"""Pins for the marketplace audit findings (SRC-albanna-001, Semgrep).

Two rule families were reported against the tools, 30 findings, and
both are held out here:

*   ``frappe-format-string-injection`` — an exception object passed to
    ``.format()`` on a translated string.  An exception's str() is a
    sentence written by whatever library raised it; formatted straight
    into a translated template it is also a string the reader sees,
    built from material nobody proofread.  Every such argument is now
    ``str(exc)`` before it enters the template.
*   ``frappe-sql-format-injection`` — a ``.format()`` or f-string in a
    Frappe SQL call.  The history reader's queries interpolated a
    where-clause built from constants, which is not injectable — but
    the shape is the one the rule exists for, so the clause is spelled
    out in each query and the queries are parameterized all the way
    down.
"""

from __future__ import annotations

import ast
import pathlib

PACKAGE = pathlib.Path(__file__).parent.parent / "albanna"

EXC_NAMES = {"exc", "e", "error"}


def _trees():
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts or path.name.startswith("test_"):
            continue
        if "patches" in path.parts:
            # The patches carry their own reasoned exemptions (nosemgrep
            # where an identifier cannot travel as a parameter), and the
            # migration discipline already holds that directory.
            continue
        yield path, ast.parse(path.read_text())


def _is_db_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in {"sql", "sql_ddl", "sql_multiset"}
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "db"
    )



def test_no_exception_object_is_formatted_into_a_template():
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(
                node.func, ast.Attribute
            ) and node.func.attr == "format":
                args = list(node.args) + [kw.value for kw in node.keywords]
                for arg in args:
                    if isinstance(arg, ast.Name) and arg.id in EXC_NAMES:
                        offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert not offenders, (
        f"{offenders} pass an exception object straight into .format() —"
        " wrap it in str() first: the exception's own str() is text"
        " nobody proofread, and the template is what the reader sees."
    )


def test_no_fstring_or_format_inside_a_sql_call():
    offenders = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_db_call(node):
                for arg in node.args:
                    if isinstance(arg, ast.JoinedStr):
                        offenders.append(
                            f"{path.relative_to(PACKAGE)}:{node.lineno} f-string"
                        )
                    if isinstance(arg, ast.Call) and isinstance(
                        arg.func, ast.Attribute
                    ) and arg.func.attr == "format":
                        offenders.append(
                            f"{path.relative_to(PACKAGE)}:{node.lineno} .format()"
                        )
    assert not offenders, (
        f"{offenders} build SQL by formatting — the queries must be"
        " spelled out and parameterized: values travel as %s parameters,"
        " and only identifiers (which are module constants) may appear"
        " in the text, never caller-supplied anything."
    )
