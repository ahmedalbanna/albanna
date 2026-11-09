# ADR-0057: Every door into the chat is counted, not trusted

Status: **Accepted**
Date: 2026-11-09

## Context

FR-7.2: only users holding the `Albanna User` role may use the chat.

The rule is one function — `require_chat_access` — and it is only a rule
while every door calls it. Its own docstring said so: *"every endpoint
that carries a user's own data calls this first."* That sentence was
accurate, and it was the only thing holding the property.

An AST walk over all 23 whitelisted endpoints found 21 calling
`require_chat_access` and two calling `require_system_manager` — the
operator's doors, which run no turn and read no conversation. So the
claim was true. It was also unenforced: an endpoint added tomorrow
without a door would be a road into the chat for every account on the
site, and nothing else would notice. The function would work, the route
would exist, and the reader would never be refused.

The existing test in that file checked the opposite direction — whether
the panel's calls are whitelisted. It asked whether a route exists, not
whether the route is guarded.

## Decision

**Count the doors in a test, and accept either of the two gates.**

`tests/test_api_surface.py` parses every whitelisted endpoint in
`albanna/api/` and asserts each calls one of `require_chat_access`,
`can_use_chat`, or `require_system_manager`. The three are named with
the reason each is acceptable: the chat's own door; the same rule read
the other way round, for the one endpoint that answers with a decision
rather than a refusal; and the operator's, which is narrower than the
chat's rather than wider.

Parsed rather than read, because a docstring that mentions the gate is
not a call to it.

## Alternatives considered

**Rely on the docstring's claim.** Rejected: it is the thing that was
wrong, in the sense that matters — not false, but unheld.

**Check only that the endpoints the panel calls are gated.** Rejected:
that is the set the front-end knows about. An endpoint added for a
future feature, or for an operator, is exactly the one that would be
missed.

**Refactor so the gate cannot be forgotten — a decorator, say.**
Rejected for now, and recorded rather than hidden: it is the real fix
and it is a larger change than this pass. The test holds the property
in the meantime, and it would catch the decorator being applied to the
wrong function too.

## Consequences

* A new endpoint without a door fails the suite, and the failure names
  the file, the function and the line.
* The test fails with an ungated endpoint added.
* FR-7.2's *letter* still deviates from the implementation, and
  deliberately: the app's rule is "read on `Albanna Conversation`",
  which an operator may widen through the matrix, plus a per-user
  policy override. That is ADR-0008's decision, in the site owner's own
  words, and it is recorded in the FR-7 record rather than changed
  here.
* The general lesson is ADR-0055's second variant: a comment that
  claims coverage is not coverage, and the claim is usually accurate
  right up until somebody adds a function.

## See also

* [ADR-0008](0008-frappe-decides-permissions.md) — the matrix is the
  rule, and the app keeps no second list.
* [ADR-0014](0014-a-reader-who-may-not-chat-gets-no-widget.md) — the
  widget does not render for a reader who may not chat, and the gate
  that enforces is on the endpoints rather than on the widget.
* `tests/test_api_surface.py` — the door count, beside the existing
  check that the panel's calls are whitelisted.
