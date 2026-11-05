"""The tool manifest's shape.

A guard that reads what ships: no tool may declare a SQL-shaped parameter,
because the assistant must never be handed a way to run SQL against the
site.  The one path that does run SQL (Query Reports) is
administrator-authored, Frappe-guarded and parameterised, and it is not a
tool parameter.
"""

from __future__ import annotations

from albanna.core.tools import TOOL_MANIFEST

#: Parameter names that would let a model hand the app SQL to run.
SQL_SHAPED = {"sql", "query", "statement"}


def test_no_tool_declares_a_sql_shaped_parameter():
    offenders = []
    for spec in TOOL_MANIFEST.all():
        props = (spec.parameters or {}).get("properties") or {}
        for param in props:
            if param.lower() in SQL_SHAPED:
                offenders.append(f"{spec.name}.{param}")
    assert not offenders, "tool(s) declare a SQL-shaped parameter: " + ", ".join(offenders)
