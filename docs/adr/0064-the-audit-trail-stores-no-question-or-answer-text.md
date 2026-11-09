# ADR-0064: The audit trail stores no question text or answer text

Status: **Accepted**
Date: 2026-11-09

## Context

FR-9.4 requires that the audit trail not store question text or answer text.
The `Albanna Chat Log` doctype's docstring already declares this intent: "An
audit row, not a business record: it exists so a System Manager can answer
'what did the assistant do, what did it cost, and who asked' without reading
anybody's conversation. It deliberately holds no question text and no answer
text — only counts, timings and error classes." The `_log()` method in
`chat_service.py` writes only the declared fields — none of which are question
or answer text. The rule had no ADR.

## Decision

**Hold the negative claim where the doctype is defined, and test it where the
audit is read.**

Two guards:

* `albanna/albanna/doctype/albanna_chat_log/albanna_chat_log.py::docstring`
  asserts the intent: the doctype deliberately holds no question text and no
  answer text — only counts, timings and error classes.

* `albanna/tests/test_integration.py` asserts the read side: the
  `unfinished_turn()`, `unfinished_facts()`, and `approved_not_run()` functions
  in `albanna/services/audit_rows.py` read only the fields that the doctype
  stores — never question text or answer text.

## Alternatives considered

**Trust the docstring, since the fields are fixed.** Rejected: the review's
pattern has consistently found rules that are correct in the code and
unheld by any test. A test that reads the row back makes the negative claim
visible.

**Add a check in `_log()` that rejects question text.** Rejected: the rule is
about what is *not* stored, and the existing fields already exclude it; adding
a check would be defensive duplication.

## Consequences

* FR-9.4 is now held: the audit trail's intent is asserted in the doctype
  docstring, and the readers assert it by reading only the stored fields.
* No code change was needed; the rule was already implemented. The work was
  the tests and this record.

## See also

* [ADR-0062](0062-the-ledger-records-every-turn.md) — the FR-9.1 ADR.
* `albanna/albanna/doctype/albanna_chat_log/albanna_chat_log.py` — the
  doctype docstring.
* `albanna/services/audit_rows.py` — the readers.
* `albanna/tests/test_integration.py` — the read-side tests.