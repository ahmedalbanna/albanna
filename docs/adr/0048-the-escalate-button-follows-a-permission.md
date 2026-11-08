# ADR-0048: The escalate button follows a permission

Status: **Accepted**
Date: 2026-11-09

## Context

The escalate button was shown whenever a conversation was open, and only
a reader who may create an Issue can escalate — so most readers were
offered a button that answered with a generic refusal.

FR-6.10 recorded this as blocked, on the grounds that hiding it behind a
permission check is *"a product decision about who may escalate"*.

It is not. The question "who may escalate" already has an answer in the
system: whoever Frappe lets create an Issue. The endpoint creates the
Issue as the caller, so the framework's own permission engine is the
rule. What was missing was not a decision but the check that reads it.

## Decision

**The site publishes whether this reader may escalate, and the button is
drawn for them.**

`options()` reads `can_create("Issue")` — the same checker the authority
layer uses for every write tool — and the panel hides the button when it
is false.

## Alternatives considered

**Leave it, and let the refusal teach the reader.** Rejected: a button
that cannot work is worse than no button, because it looks like the
assistant is broken rather than like the reader lacks a permission. The
reader learns nothing about *which* permission, and the app's whole
posture is that a refusal names the way forward.

**Hide it behind a new role.** Rejected: that would be a second answer to
a question the framework already answers, and the two would drift.

**Show it disabled with an explanation.** Rejected: a disabled button
with a tooltip is more machinery than the problem needs, and the reader
who cannot escalate does not need to be told what they are missing —
they need to not be offered it.

**Check the permission in the endpoint only.** Rejected: that is what it
did. The endpoint refused correctly; the button was the lie.

## Consequences

* A reader who may not escalate is not offered the button.
* The answer is the framework's own, read at the same place the authority
  layer reads every other permission — so it cannot drift from the rule
  that actually governs the write.
* `options()` grew a key, and the test asserts it is published and is a
  boolean.
* The general lesson: a "product decision" that turns out to be a
  permission check nobody wrote is not a product decision. The question
  to ask is not "who should be allowed?" but "who *is* allowed, and does
  the interface know?"

## See also

* `albanna/api/widget.py` — `options()`, and the `can_create("Issue")`
  read.
* `albanna/public/js/side-chat/SideChatApp.vue` — `canEscalate`, and the
  button's `v-if`.
* `docs/FR-6_CONVERSATIONS.md` — the record that flagged this as
  awaiting a decision.
