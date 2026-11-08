# ADR-0043: A question has a ceiling, and the refusal names the length

Status: **Accepted**
Date: 2026-11-08

## Context

There was no cap on the question anywhere: not in the composer's rule,
not at the endpoint, not on the stored question.

The two neighbouring fields are capped — the conversation title at 120,
the recent-questions list at 300 — and both are *display* fields. The
question is the primary input, and it is the one place a reader
legitimately pastes something long: a stack trace, a list of invoice
numbers, a query.

## Decision

**4000 characters, enforced at both doors, with the length named in the
refusal.**

Roughly a thousand tokens: room for one stack trace, and small enough
that a runaway paste cannot quietly eat the turn's whole context.

**Enforced twice.** The composer enforces it so the reader is told before
they send; the endpoint enforces it because the composer is one client
and the endpoint is the door. A door that trusts the browser is a door
only honest callers use. Both doors — the synchronous `ask` and the
streaming `ask_stream` — because a refusal only one of them makes is a
refusal a caller routes around by asking for a stream.

**The refusal names the length.** A reader told only "too long" cannot
tell how much to cut, and a refusal the reader cannot act on is a refusal
they work around by asking a worse question.

**The composer shows the count near the ceiling, not always.** A counter
on every question is noise; a counter that appears when it matters is
what stops the refusal being a surprise. It turns the danger colour when
the question is over, so the reader who pasted too much sees it before
pressing Enter rather than after.

**The length is the trimmed length.** An indent is not part of the
question, and a reader who pasted with one should not be charged for it.

## Alternatives considered

**2000 characters.** This was the first recommendation, and it was
changed on checking what the question actually carries. A pasted stack
trace runs 1,500–3,000 characters, so 2000 would refuse a legitimate
paste — and a cap that refuses legitimate input is a cap that gets worked
around by pasting less and asking worse questions.

**No cap.** Rejected: the question is the one unbounded field in the
system, and it is the one that flows into the provider's context, the
cache entry and the database row.

**A setting the operator can raise.** Rejected: it is a bound on what one
turn can carry, not an operator's preference. A setting an operator can
raise to a million is not a bound.

**Silent truncation.** Rejected: it loses the reader's words. The app's
rule throughout is that a refusal the reader cannot act on is a refusal
that fails — and a truncation they cannot see is worse than one they can.

**Enforce only in the composer.** Rejected: see above. The browser is one
client.

## Consequences

* A question over 4000 characters is refused at both doors, with its
  length and the limit.
* The reader sees the count climb near the ceiling, so the refusal is
  never a surprise.
* The RTL guard caught a `margin-left` in the new style and it is now
  `margin-inline-start`: the build's RTL pass mirrors every left and
  right, so a physical rule lands on the wrong side in an Arabic sheet.
* The number is a constant in `api/chat.py` and in `submit.mjs`, and the
  two must agree. Nothing enforces that they do — which is the one gap in
  this decision, and it is recorded rather than papered over.

## See also

* `albanna/public/js/side-chat/submit.mjs` — the pure rule, and the
  comment that says why 4000 and not 2000.
* `albanna/api/chat.py` — `_question_refusal`, the door.
* `albanna/public/js/side-chat/Composer.vue` — the counter and the
  refusal the reader sees.
