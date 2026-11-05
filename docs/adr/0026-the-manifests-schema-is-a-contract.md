# ADR-0026: The manifest's schema is a contract, not a description

Status: **Accepted**
Date: 2026-11-05

## Context

Every tool declares a JSON schema. The model reads it, and it is the only
thing the model knows about what a tool accepts. `ErpnextBackend._invoke`
calls the handler with the arguments as they arrived:

```python
return handler(**arguments)
```

No validation of any kind happens in between. The schema was a
*description* — a promise about what the tool would accept, enforced by
nobody.

Two promises were broken at once.

**`list_docs` promised to reject malformed filters.** Its schema says:
*"A condition with a list or an object as its value is rejected."*
`_normalise_filters` passed everything through. Extracting the function and
running it directly:

```
list value   -> [['status', '=', ['a', 'b']]]      # promised rejected; passed through
object value -> [['status', '=', {'a': 1}]]        # promised rejected; passed through
two-element  -> [['status', '=']]                  # minItems: 3; passed through
four-element -> [['status', '=', 'x', 'y']]        # maxItems: 3; passed through
```

A malformed filter reached `frappe.get_list` and either mis-filtered
silently or failed at the database with a message the model could not act
on. `fields` was the only parameter the tool validated itself.

**`run_report` promised to report a missing mandatory filter.** Its schema
says it twice: *"if a filter is missing the tool says which one"* and *"A
missing mandatory filter is reported back with the key to add."* Nothing in
the tool looked at the report's mandatory filters — though
`report_doc.filters` is a Table of Report Filter, each row carrying
`fieldname`, `label`, `mandatory` and `default`. What the model got was
whatever the underlying report threw: helpful for ERPNext's own reports
that check their filters, silent for one that does not.

## Decision

**A tool validates what its schema promises, before it runs.**

`list_docs` gained `_validate_filters` and `_validate_order_by`, wired
through one `_validate_list_docs_inputs` so the three checks read as one
gate rather than three:

* **Filters** — exactly three elements, a string fieldname, an operator
  from the documented set (`=, !=, >, <, >=, <=, like, not like, in, not
  in, is, between`), and a string value. Each refusal names the rule and
  shows the shape, the way `_validate_fields` corrects an invented
  fieldname.
* **Sort** — a bare fieldname, `fieldname asc|desc`, or a comma-separated
  list of those, validated against the DocType's own fields with the same
  close-match correction. A bare direction is refused: a sort needs
  something to sort by.

`run_report` gained `_missing_mandatory_filters`, which reads the report's
own filter rows and refuses with the keys to add — **before** the report
runs, so a wasted execution is not spent finding out.

The operator set is enforced exactly as documented. That is a narrowing:
an operator Frappe would have accepted is now refused. It is the right
trade, because the schema is the contract shown to the model and a tool
that accepts more than it advertises is a tool whose documentation cannot
be trusted — but it is a narrowing, and it is flagged for the owner rather
than assumed.

## Alternatives considered

**Leave it to Frappe, and to the report.** This was the behaviour. Rejected:
the model gets a database error or a silent mis-filter, and neither is
something it can act on. The whole point of `_validate_fields` — which
already existed — is that a correction beats a refusal.

**Validate only the shape, and let any operator through.** Rejected as the
primary rule: the schema names the operators, so an operator outside the
set is exactly the kind of plausible guess the field validator corrects.
It is recorded as the fallback if the owner prefers the narrower gate.

**Validate generically at the backend, from the schema.** Considered and
deferred, not rejected. A JSON-schema validator would enforce `minItems`,
`maxItems` and `type` for free, and would have caught the two- and
four-element cases. It would not have caught the operator set, the
fieldname's existence, or the sort's field — those need the DocType's meta,
which only the tool has. So it is complementary rather than alternative,
and adding it later is additive.

**Let the report's own error carry the message.** Rejected: it works for
the reports that check, which is most of ERPNext's, and fails silently for
the ones that do not. A promise kept by the thing being called is a promise
the caller cannot rely on.

## Consequences

* A malformed filter is refused with the shape to use, before any query
  runs.
* A report missing a mandatory filter is refused with the keys to add,
  before the report executes.
* The sort is validated against real fieldnames, with corrections — the
  same treatment `fields` already had.
* The operator set is now a hard boundary. A model that reaches for
  something outside the twelve is refused rather than silently accommodated.
* The schema can be trusted, which is what makes it worth showing the model
  at all: a contract the code keeps is documentation; a contract it does not
  is a guess with good formatting.

## See also

* [ADR-0005](0005-five-tools.md) — the manifest, and why the tool set is
  fixed by design.
* [ADR-0028](0028-the-permission-check-comes-before-the-hint.md) — the
  ordering rule the report's new check had to learn.
* `albanna/tools/erpnext.py` — `_validate_filters`, `_validate_order_by`,
  `_missing_mandatory_filters`, and the one gate that wires them.
