# ADR-0014: A reader who may not chat gets no widget at all

Status: **Accepted**
Date: 2026-11-05

## Context

The chat is a Frappe permission.  Read on `Albanna Conversation`,
shipped as the `Albanna User` role, with a per-user override for the one
account a role cannot describe.  That gate is the app's answer to *who
may use this*, and it is read in one place —
`albanna.permissions.chat_access` — so the widget and the endpoints
cannot disagree about it.

The question this ADR answers is what the **browser** does with a *no*.

The obvious answer is the one most applications give: render the panel,
grey it out, and put a sentence in it explaining what is missing.  It is
a kind answer.  It is also the wrong one here, for three reasons that
only show up when you ask who reads the sentence.

A reader who may not chat is usually a reader who was never given the
role — an account the operator created for something else.  They did not
go looking for an assistant, would not know what to do with the news
that they lack one, and are served a panel of dead weight on every page
of the Desk for the rest of their employment.  A reader who *was* given
the role and had it taken away is in the same position with sharper
feelings, and the sentence does not help them either: the lever is on
the User form, which is not where they are.

And the sentence is a promise the app cannot keep.  It would have to say
*why* — no role, or a policy row set to Off — and the reason is a
permission fact that Frappe and the operator's role assignment already
explain, in the place an operator would look.  A second copy of that
fact, in a panel, goes stale the moment the operator changes the first
one.

## Decision

**The widget does not render for a reader who may not chat.**

`albanna.api.widget.options` answers `visible = settings.enabled and
can_use_chat()`, and the launcher returns early when the answer is not
`true`.  No panel, no launcher, no empty state, nothing on any page.

Two details make that safe rather than merely terse:

* **The answer is published before the early return.**  `publishAccess`
  runs whether or not the widget renders, because "no widget" is an
  answer too, and the bundles that wait for one must not wait for a
  decision that has already been made.
* **The gate that matters is on the endpoints that run a turn.**  The
  widget's visibility is a courtesy; `require_chat_access` on the turn
  itself is the enforcement.  A reader who cannot see the panel cannot
  ask a question through it, and a reader who finds another road to the
  endpoint is refused there.

The same decision governs the other two entry points.  The "Ask
Albanna" button on a form and the "Explain this error" button on an
error dialog wait for the same published answer, so a reader who may not
chat is not offered a button that opens nothing.  That was a real defect
once — every reader was given the button on every form, and for a reader
who may not chat it opened nothing at all — and it was fixed by giving
the question one home rather than by giving the button a second opinion.

## Alternatives considered

**Render a disabled panel with an explanatory sentence.**  Rejected for
the reasons above: it puts weight on every page for a reader who did not
ask for it, and it duplicates a permission fact that already has a home
and an owner.

**Render the panel and refuse the first question.**  Rejected: it is the
same dead weight with an extra click before the refusal, and the refusal
would arrive in a panel the reader had already opened and typed into.

**Show the launcher but not the panel.**  Rejected: a launcher that opens
nothing is the defect this app already had with the form button, and it
is worse here because the launcher is on *every* page.

**Let the operator choose.**  Considered and rejected as a setting
nobody should have to make.  The app's design rule is that a feature
which is not used is clutter; a toggle that chooses between two kinds of
clutter is not a kindness.

## Consequences

* FR-1.1 and FR-1.4 — the panel on every page, the launcher on every
  page — are scoped by this decision.  They mean *every page a reader
  who may chat can reach*, and the requirements document says so rather
  than leaving a reader to discover it.
* A reader who may not chat sees a Desk identical to the one they had
  before the app was installed.  That is the intended outcome, not a
  degradation.
* The visibility answer is one function deep, so the widget, the form
  button and the error button cannot disagree about who may chat.  The
  property is held by `albanna/tests/test_chat_access.py`, which reads
  the gate three ways — the matrix, the policy, and the widget.
* Turning the chat off for one account is an operator action with a
  visible, immediate and complete effect: the widget disappears.  It was
  proved on production by switching the Administrator's own chat off and
  watching the widget go.

## See also

* [ADR-0008](0008-frappe-decides-permissions.md) — Frappe decides
  permissions, and the app does not add a second rule to undo it.
* [ADR-0002](0002-authority-and-permissions.md) — a write the reader has
  not approved does not run; the same shape of rule, applied to who may
  speak at all.
* `docs/FR-1_DESK_PANEL.md` — the requirements this decision scopes.
