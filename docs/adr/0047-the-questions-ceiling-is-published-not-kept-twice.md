# ADR-0047: The question's ceiling is published, not kept twice

Status: **Accepted**
Date: 2026-11-09

## Context

ADR-0043 gave the question a ceiling and noted the gap it left: the
number lived in `submit.mjs` for the browser and in `api/chat.py` for the
door, and nothing held the two together. A composer that let a reader
type more than the door would take was a composer that wasted their time,
and the only way to find out was to read both files.

The app already solved this problem once, for the attachment types. The
browser asks the site what it takes rather than keeping a copy, and
`attachments.mjs` says why: *"a browser that keeps a copy of the server's
list is a browser whose copy goes stale, and a stale list is a browser
that accepts a file the server refuses."*

## Decision

**The site publishes its ceiling through `options()`, and the composer
reads it.**

`submitDecision` takes the ceiling as a parameter, so the rule stays pure
and testable and the number has one home. The module's constant becomes a
fallback for a panel rendered before the site answered — a bound that is
that one rather than no bound at all.

## Alternatives considered

**Keep two copies and add a test that they agree.** Rejected: the test
would have to import both, which means a test that reaches into the
browser's module from the server's suite. It is possible and it is a
test nobody would think to run.

**Make it a setting the operator can raise.** Rejected, for the reason
ADR-0043 gave: it is a bound on what one turn can carry, not an
operator's preference. A setting an operator can raise to a million is
not a bound.

**Publish it and drop the module constant entirely.** Rejected: a panel
rendered before the site answers would then have no bound at all, and
"no bound" is worse than "this bound".

## Consequences

* The number has one home, and the browser reads it rather than
  remembering it.
* `options()` grew a key, and the test asserts it is published and is a
  positive integer.
* The tests cover the site's ceiling being honoured, a question the site
  allows that the default would refuse, and a zero ceiling falling back
  rather than refusing everything.
* The general lesson is the one the attachments module already states:
  a rule the browser keeps a copy of is a rule that goes stale. This was
  the same rule, applied to a number instead of a list.

## See also

* [ADR-0043](0043-a-question-has-a-ceiling-and-the-refusal-names-the-length.md)
  — the ceiling itself, and the gap this closes.
* `albanna/api/widget.py` — `options()`, the publishing point.
* `albanna/public/js/side-chat/submit.mjs` — the pure rule, which now
  takes the ceiling as a parameter.
