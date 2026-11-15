# ADR-0107: The panel's accessibility facts are read and pinned

Date: 2026-11-15 · Status: accepted · The fifth NFR batch, after the
S-, R-, SEC- (ADR-0105) and U-series (ADR-0106); answers the NFR-A1–A6
questions raised against the panel.

## The requirement, and what "verified" means here

Six accessibility requirements were named for the side chat.  Each was
read against the panel's source before it was believed; two did not
hold and are what this ADR changes.  The other four were already
designed in, several deliberately — and the reading says so in the
words the design used, so the next reader does not "fix" a decision
they did not know was one.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| A1 | ARIA labels and roles | holds | the panel is `role="complementary"` with a label — deliberately *not* `dialog`; the resize handle is `role="separator"` with a label and a tab stop; the launcher carries `aria-expanded` and `aria-controls`; every icon-only button is labelled; the text buttons' accessible names *are* their visible text; both inputs are labelled, the composer via `aria-describedby` to the Enter/Shift+Enter hint |
| A2 | new messages announced via live regions | holds, deliberately shaped | the transcript is `role="log"` with `aria-live="off"` — a token-streaming answer in a live region re-announces itself whole, again and again.  The *outcome* is announced once, in a `role="status" aria-live="polite"` region ("Answer ready." / "The answer was cut off."); errors are `role="alert"`; approval cards are `role="alertdialog" aria-live="assertive"` |
| A3 | prefers-reduced-motion stops all animation | **was gapped, fixed** | see below |
| A4 | follows prefers-color-scheme when the Desk theme is not explicit | holds | the Desk's `User.desk_theme` has an `Automatic` option; when set, Frappe resolves it through `prefers-color-scheme` and a live `change` listener re-resolves when the OS flips.  The panel keys on `[data-theme="dark"]`, which the Desk always sets — it follows whatever the Desk decided, OS-driven when the Desk is Automatic |
| A5 | focus trapped when open | **was exposed, fixed** | see below |
| A6 | closable via Escape | holds | Escape closes the panel; inside the rename and edit fields it first cancels those; the launcher is a real button, reachable by Tab, Enter and Space |

## The exposure: the keyboard and the moving parts

**The trap, and what the panel is.**  The bundle's comment once said
the panel is "a column of the Desk, not a dialog over it" and declined
`role="dialog"` on that ground — and for the *docked* column that
reasoning is right: the Desk beside the panel is active content, and a
trap there would strand the keyboard user out of the Desk the answer
is about.  But the panel is not always a column.  It is an overlay
when the position is `floating`, and whenever the viewport is past the
991px breakpoint, where the stylesheet itself turns the dock off and
the panel covers the Desk.  In an overlay, Tab walking out lands in
content the reader cannot see the panel leaving — how a keyboard
reader gets lost.

So the trap now asks what the panel currently *is*, and holds the
focus only when the panel is *over* the Desk.  The decision logic and
the focus cycle live in a pure module (`focus-trap.mjs`, thirteen node
tests: overlay arithmetic, the stops a disabled or hidden button is
not, the wrap at both ends, the empty panel's refusal); the wiring
joins the panel's existing keydown handler beside Escape and
Ctrl/Cmd+K.  What already held — focus into the composer on open,
focus back to the launcher on close — was left as it was.

**Reduced motion's scope.**  The reduce block stopped the spinner and
killed every transition inside the Vue subtree — but scoped to
`.albanna-chat *`.  The launcher's hover lift and the resize handle's
fade live outside that subtree and kept moving after the reader asked
the browser to stop.  The block reaches the widget's root now
(`#albanna-side-chat` and all inside it); the entry animations were
already gated behind `prefers-reduced-motion: no-preference` and stay.

## What the walking tests mean

`tests/test_usability_pins.py` gained a walker for the reduce block's
scope: no reduced-motion rule may again stop at the Vue subtree while
the launcher moves.  It joins the U-series' contrast, touch and focus
walkers in the same file, and the focus trap's thirteen node tests
hold its own arithmetic in `focus-trap.test.mjs`.

## Consequences

- A keyboard reader using the panel as an overlay stays inside it
  until they choose to leave; a keyboard reader using it as a column
  keeps the Desk.
- A reader who asked the browser for less motion gets less motion
  from every part of the widget.
- A future reader who wants the panel to be `role="dialog"` will find
  the reasoning spelled out in the bundle, the trap conditional, and
  the tests that hold both.
