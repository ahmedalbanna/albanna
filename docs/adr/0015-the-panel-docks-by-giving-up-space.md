# ADR-0015: The panel docks by giving up the Desk's space

Status: **Accepted**
Date: 2026-11-05

## Context

A side panel in a working application has two shapes, and the choice
between them is the choice between two different products.

It can **float** — a card over the page, dismissed by clicking away,
positioned by the application.  That is the shape of a help widget, a
chat bubble, a toast.  It is the shape of most side chats, and it is
what the app ships when an operator asks for it.

Or it can **dock** — a column of the layout, beside the content, with the
content giving up the space rather than being covered.  That is the shape
of an email client's reading pane, a diff view, an IDE's terminal.

The app's whole claim is that the assistant answers *about the record the
reader is looking at*, and that the reader keeps working on that record
while the answer arrives.  A floating panel covers the record at the
moment the answer is most wanted.  A docked panel puts the answer beside
the record and leaves both readable.

So the dock is the default, and the question this ADR answers is how a
Dock page is made to give up space it does not know it is giving up.

## Decision

**The dock is a margin on `<body>`, on the same logical side as the
panel, written against the panel's live width.**

```css
body.albanna-side-chat-docked-inline-end {
	margin-inline-end: calc(var(--albanna-panel-width) + 16px);
}
```

Four things about that rule are load-bearing, and each was verified
rather than assumed.

**It is a margin, not a padding.**  Frappe's reset ships
`body { padding: 0 !important }`, which beats any non-important
declaration whatever its specificity.  A padding-based dock silently
does nothing.

**A margin on `<body>` really does move the whole Desk.**  This was
checked against the framework's own stylesheets rather than taken from
the comment that claimed it: the navbar declares no `position` and is
therefore in flow; `.standard-sidebar`, which `.desk-sidebar` extends,
declares no `position` either and is in flow on desktop; and the sidebar
only becomes `position: fixed` at ≤991px — which is exactly the
breakpoint where this app switches docking off.  Had the navbar been
fixed, the dock would have moved the content and left the navbar
overlapping the panel, and nothing in the app's own tests would have
said so.

**The side is logical, not physical.**  `margin-inline-end`, not
`margin-right`.  The build's RTL pass mirrors every `left` and `right` in
a stylesheet, so a physical rule written for a left-to-right interface
comes out on the wrong side in a right-to-left one.  A logical property
is left alone by that pass and resolved by the browser, which is the only
thing that knows the direction.

**The margin tracks the panel's width.**  Both read
`--albanna-panel-width`, which the launcher writes to the document as the
reader drags the resize handle.  A wider panel takes more of the Desk,
live, without a second rule to keep in sync.

The class is toggled from exactly one place — `setDock` — so it cannot
drift out of sync with the panel's own visibility.

## Alternatives considered

**A floating overlay as the default.**  Rejected: it covers the record at
the moment the answer is about it, which is the one moment the app
exists for.  Floating is not removed — it is an opt-in position for
helpdesk deployments, and `docs/ROADMAP.md` §4 records that making it the
default would undo the core value proposition.

**A padding on `<body>`.**  Rejected by Frappe's own reset, as above.

**Move the Desk's content container instead of the body.**  Rejected:
the Desk's layout is the framework's, and a rule that reaches into it
breaks the next time the framework rearranges.  A margin on `<body>` is
the outermost thing the app owns.

**A CSS grid or flex re-flow of the whole Desk.**  Rejected: it would
require the app to own the Desk's layout, which is a much larger claim
than a side panel should make.

**Dock only on wide screens and float everywhere else.**  This is what
the app does, and it is recorded here as a consequence rather than an
alternative: below 991px the margin is zeroed and the panel becomes a
fixed overlay, because a column the Desk cannot spare is not a column.
On a phone the panel is a full-screen sheet with a close button.

## Consequences

* While the panel is open the Desk is narrower by the panel's width plus
  a 16px gutter, and the reader keeps reading the record beside the
  answer.  That is the product.
* **A Frappe modal can sit behind the panel.**  `#albanna-side-chat` is
  `z-index: 2147483000`, and a Frappe modal is viewport-centred fixed
  positioning, which a body margin does not move.  On a narrower viewport
  a modal's right edge extends past the panel's left edge and the panel
  paints over it.  Accepted, deliberately: the panel staying reachable
  while a dialog is open is the point of the dock, and the overlap needs
  a modal open on a screen narrow enough that the Desk was already
  cramped.
* **The Desk content ends flush against the panel's border.**  The margin
  is `panel + 16px` and the panel is inset 16px from the viewport edge,
  so the gap between them is zero.  Not covering, but no breathing room
  either.  Accepted; a gutter would have to come out of the Desk's width
  a second time.
* The dock is off below 991px, where the panel covers the Desk, and the
  resize handle is hidden there and in floating mode.  FR-1.2 and FR-1.3
  are scoped by this.
* The dock's correctness depends on the framework's navbar and sidebar
  staying in flow.  Nothing in the app's suite asserts that, because
  nothing in the app's suite can see a page — which is the same gap the
  live-run findings in `docs/ROADMAP.md` §8 exist to describe.

## See also

* [ADR-0013](0013-the-front-ends-rules-are-scanned.md) — the logical-side
  rule this dock depends on, and the scan that now enforces it.
* `docs/FR-1_DESK_PANEL.md` — FR-1.2, the requirement this decides, and
  the trade-offs it accepts.
