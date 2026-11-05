# ADR-0036: No tool is handed SQL

Status: **Accepted**
Date: 2026-11-06

## Context

The requirement is a negative one: the system shall not provide raw SQL access.
It was already true, and it was true for reasons worth recording rather than
assuming.

**No tool accepts SQL.** The twelve tools are typed operations with
`additionalProperties: False` schemas. None of them takes a query.

**The one path that runs SQL is not the model's.** `run_report` executes Query
Reports, whose SQL lives in the Report document — written by an administrator,
never by the model. The model chooses *which* report and supplies *filter
values*.

**Frappe guards that path twice.** `check_safe_sql_query` whitelists only
`select`, `explain`, and (on MariaDB) `with`, and throws a `PermissionError`
otherwise — so a report that is not a read cannot be run at all. And the filters
are passed as bound parameters: `frappe.db.sql(self.query, filters)`, not
interpolated.

**The app's own SQL is parameterised.** The f-string interpolations are all
constants — a `where` built from literals, `placeholders` built from repeated
`%s`, a module-level doctype name.

So the property held. What did not hold was anything that kept it holding. A
future tool that added a `query` parameter would have passed every existing
test, and the manifest tests check schema/implementation drift, the write
surface and the authorisation rights — none of them about this.

## Decision

**The rule is written where it is checked, and checked where it is read.**

`albanna/tests/test_tool_manifest.py` gained a guard that walks the manifest and
fails on any tool declaring a SQL-shaped parameter — `sql`, `query`,
`statement`. And `core/tools.py` gained a comment beside the manifest recording
the rule and the three reasons it holds, so the next person adding a tool reads
it before they write it.

Both, because neither is sufficient alone. The test catches the obvious case — a
parameter literally named `query` — and a tool could execute SQL through a
parameter called `filters`. The comment carries the rule; the test catches the
careless version of breaking it.

A second, smaller thing was closed in the same pass: `permissions.py`
interpolated `ptype` into SQL as a column name. It was safe because all three
callers passed literals, and nothing enforced that. It now has an allowlist of
the seven permission types, so a future caller passing something else gets an
empty answer rather than an injection.

## Alternatives considered

**Rely on Frappe's `check_safe_sql_query` alone.** Rejected as the *only*
mechanism: it guards the report path, and it is the framework's to change. A
future Frappe that widened the whitelist would widen this app's exposure without
this app noticing.

**Ban `run_report` on Query Reports.** Rejected: it would remove a useful
capability — the reports that answer "what are my receivables" are Query Reports
— to close a hole that is already closed twice.

**Scan the source for `frappe.db.sql` calls.** Rejected: it cannot tell a
parameterised call from an interpolated one, and this app has both shapes. A scan
that flags the safe ones is a scan somebody disables.

**Leave `ptype` alone, with a comment.** Rejected in favour of the allowlist: a
comment is read by whoever is already thinking about the function, and the
allowlist is read by everybody. The cost is one set membership test on a path
that already does a database query.

## Consequences

* A tool that declares a SQL-shaped parameter fails the suite, with the tool
  named.
* The rule is stated twice — in the test that enforces it and the comment that
  explains it — and the comment is the one that survives a contributor who has
  not read the test.
* `ptype` can no longer reach the SQL as anything but one of seven known
  permission types.
* The property was already true; this ADR is what makes it stay true, which is
  the third instance of the same pattern in this review (ADR-0030 for reads,
  ADR-0034 for writes, this for the surface).

## See also

* [ADR-0030](0030-the-read-guard-walks-the-manifest.md) and
  [ADR-0034](0034-the-write-guard-walks-the-manifest.md) — the other two guards
  that read what ships rather than a list somebody maintains.
* `albanna/tests/test_tool_manifest.py` — the guard.
* `albanna/core/tools.py` — the comment beside the manifest, which is where a
  contributor adding a tool will actually see the rule.
