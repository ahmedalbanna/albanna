# ADR-0046: The operator set stays exactly as documented

Status: **Accepted**
Date: 2026-11-08

## Context

FR-3.1's validator enforces an operator set of exactly twelve: `=`, `!=`,
`>`, `<`, `>=`, `<=`, `like`, `not like`, `in`, `not in`, `is`,
`between`. The manifest's schema documents the same twelve, in the same
words. The two are in step.

Frappe accepts more. The NestedSet hierarchy operators — `descendants
of`, `not descendants of`, `descendants of (inclusive)`, `ancestors of`,
`not ancestors of` — and `timespan`. Those are refused.

The FR-3 record flagged this as a narrowing awaiting the owner's
confirmation: *"Enforcing the operator set exactly as documented refuses
an operator Frappe would have accepted. That is the right trade — the
schema is the contract shown to the model — but it is a narrowing."*

## Decision

**The twelve stay, exactly as documented.**

The schema is the contract shown to the model. A validator that accepts
more than the schema documents is a schema that lies — and a model that
learned an operator from a refusal it was given has learned something the
schema never promised, which is the same drift in the other direction.

The narrowing is small and the capability is recoverable. A model that
wants a subtree can ask for the tree explicitly; a model that wants "last
30 days" can compute a date and use `>=`. Neither is a dead end, and both
are answered by a sentence the model can act on.

## Alternatives considered

**Shape-only — accept anything Frappe accepts, refuse only malformed
shapes.** Rejected: it is more capable and it makes the schema
under-document what the tool does. The model would reach operators the
schema never named, and the next reader of the schema would be wrong
about the tool's reach.

**Strict, plus the hierarchy operators and `timespan` added to the
schema.** Rejected, but it is the right way to add capability if
capability is wanted. The cost is real: five more operators, each with
its own value shape — `timespan` takes "last 30 days", not a date — and
`descendants of` on a non-tree DocType is a runtime error from Frappe
rather than a clean refusal. The app would be taking on explaining five
more things to the model, and each has a failure mode the twelve do not.

**Widen to whatever Frappe allows, and document it all.** Rejected: the
documentation would be a list of Frappe's operators rather than a
contract, and a contract that is a copy of somebody else's implementation
is not a contract.

## Consequences

* The validator and the schema stay in step, and the drift between them
  is testable.
* A model asking for `descendants of` gets a refusal naming the operator
  set, and can achieve the same thing another way.
* If the hierarchy operators are ever wanted, this ADR names the shape:
  add them to the schema *and* the validator together, and accept the
  cost of explaining their value shapes.
* The general principle is the one ADR-0026 recorded for the read side: a
  schema is a contract, and a validator that enforces more or less than
  the contract is a contract that lies in one direction or the other.

## See also

* [ADR-0026](0026-the-manifests-schema-is-a-contract.md) — the sibling
  decision on the read side.
* `albanna/tools/erpnext.py` — `_VALID_FILTER_OPS`, and
  `_validate_filters`, which enforces it.
* `albanna/core/tools.py` — the schema that documents the same twelve.
* `docs/FR-3_READING.md` — the record that flagged this as awaiting
  confirmation.
