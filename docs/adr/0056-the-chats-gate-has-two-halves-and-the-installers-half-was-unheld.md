# ADR-0056: The chat's gate has two halves, and the installer's half was unheld

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7.1: chat access is off by default for all users.

The gate is read permission on `Albanna Conversation`, shipped as the
`Albanna User` role and nothing else. That half was already held —
`tests/test_access_matrix.py` asserts the shipped matrix names exactly
one role, that the row is `if_owner`, and that the installer creates the
role the matrix names.

The other half was not. The installer creates the role and grants it to
no one, and nothing asserted that. An `add_roles` anywhere in the install
path would flip the default for every account on the site, and every
other test would still pass — they each build their own user with
explicit roles, so not one of them reads what the installer handed out.
`after_migrate` is in that path too, and a grant there would re-open the
chat on every migrate rather than only on install.

## Decision

**Assert the installer hands the role to nobody, by parsing it rather
than searching it.**

The test walks `install.py`'s AST for a call to `add_roles`. Parsed
rather than searched as text, because a comment that mentions
`add_roles` is not a grant and a string that contains it is not a call.

## Alternatives considered

**Assert it behaviourally, by installing the app on a scratch site.**
Rejected: it needs a site, it is slow, and it proves the installer's
behaviour on *that* site rather than the installer's *code* — which is
what ships.

**Leave it, on the grounds that nobody would add a grant to an
installer.** Rejected: that is the argument for every unguarded silent
default. "Grant the chat to everybody on install" is a plausible edit
that reads like a kindness.

**Move the role creation out of the installer entirely.** Rejected: a
fresh install never runs the patches, so the role has to be made
somewhere that always runs. The installer is that place.

## Consequences

* The shipped default is held on both sides — the matrix that names the
  door, and the installer that decides who holds it.
* The test fails with the defect reintroduced, and names the line.
* The general lesson is ADR-0055's first variant: a rule held on one
  side is a rule that is half-held, and the unheld half is the one
  nobody thinks to look at because the held half is right there.

## See also

* [ADR-0008](0008-frappe-decides-permissions.md) — Frappe decides
  permissions, and the app keeps no second list.
* `tests/test_access_matrix.py` — the shipped matrix, asserted against
  the JSON rather than the database.
* `albanna/install.py` — `_ensure_role`, which creates the role and
  grants it to nobody.
