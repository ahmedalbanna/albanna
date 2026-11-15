# ADR-0106: The panel's usability facts are read and pinned

Date: 2026-11-15 · Status: accepted · The fourth NFR batch, after the
S-series (ADR-0101), the R-series (ADR-0102) and the SEC-series
(ADR-0105); answers the NFR-U1–U10 questions raised against the panel.

## The requirement, and what "verified" means here

Ten usability requirements were named for the side chat.  Each one was
read against the panel's source and stylesheet before it was believed;
where the fact lives in the stylesheet it was then pinned by a walker
over the same file.  Eight of the ten already held.  Two did not, and
they are what this ADR changes — along with one gap that was polish
rather than exposure.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| U1 | first question within 30 s | holds | the launcher is on the page at load; the bundle URL comes from `frappe.boot.assets_json`, already cached; opening focuses the composer; the access decision arrives with the page. Nothing between "open" and "send" but typing |
| U2 | fully keyboard-operable | holds | Escape closes the panel and cancels edit/rename; Enter sends and stops while running; Ctrl/Cmd+K focuses the composer; arrow keys (and Home/End) drive the resize handle; every interactive element is a real `<button type="button">` with an aria-label — no click-only divs |
| U3 | visible focus indicators | was leaning on the browser; fixed | the launcher, resize handle, send and confirm buttons had explicit `:focus-visible` rings, and the four `outline: none`s were each paired with a replacement — but the quiet buttons (copy, remove, retry, header icons, attach, chips, drawer actions) had no rule at all and fell to whatever the browser draws. The focus-visible group rule draws them in the panel's own accent now. Pinned |
| U4 | WCAG 2.1 AA contrast | **was exposed, fixed** | see below |
| U5 | usable at 1024px | holds | the default 400px panel with `max-width: calc(100vw - 32px)`; below 991px it floats full-height; below 640px it becomes a full-screen sheet |
| U6 | errors human-readable | holds | `errors.mjs` unwraps all three refusal shapes and reduces a traceback to its last line without the exception class; server refusals are sentences, and the access-denied card names the missing role and what to ask for |
| U7 | empty state suggests page questions | holds | `examples.mjs` picks the set from the page — form, list, report, generic; `nudge.mjs` names the documents behind a count; both pinned by node tests |
| U8 | async feedback | holds | the pending turn is a `role="status"` line with a spinner and activity text; send becomes stop while running; disabled states styled; the inflight tracker recovers a turn across navigation |
| U9 | no layout shift on open/close | holds | floating (the default) is `position: fixed` — nothing joins the flow, no body class, no scrollbar change. Docked mode moves the Desk *by design* (side-by-side, one `setDock` writer, symmetric on close): a documented product choice, not shift by accident |
| U10 | 44×44px touch targets | **was exposed, fixed** | see below |

## The exposure: muted ink, and fingers at 1024px

**Contrast.** `--albanna-muted` read the Desk's `--text-light` —
gray-600, `#7c7c7c` on a light theme.  Computed against the palette the
panel actually paints with, that is **4.17:1** on white and **3.76:1**
on the bubble the reader's own messages sit on — both under the 4.5:1
the words have to meet, in some forty call sites: subtitles,
placeholders, timestamps, source labels, attachment chip sizes.  The
dark theme passed only because the Desk's dark `--text-light` is
gray-300.  The fix is one variable: the muted ink reads
`--text-muted` now — gray-700 (`#525252`) light, 6.4:1 and 7.0:1;
gray-400 dark, 10.6:1 — and the pair is pinned.

**Touch targets.** A "larger tap targets" block existed, but it was
gated on `max-width: 991px` — a screen width, not an input — so the
1024-pixel tablet that U5 explicitly names got nothing, and it set
`min-height` only: a 44-pixel-high button twenty pixels wide is a
button the finger misses as surely.  The new `@media (pointer:
coarse)` block says what is actually meant — *the reader's input is a
finger* — and lifts **both** sides of every interactive element in the
panel to 44px, whatever the screen.  The width-gated block stays.

## What the walking tests mean

`tests/test_usability_pins.py` reads the same stylesheet the U-a
reading did and holds three facts the way the SEC walkers hold theirs:
the eight colour pairs the panel paints meet their WCAG floors in both
themes (the Desk's own palette values are read, not invented), the
`pointer: coarse` block covers every interactive element with both
44px minimums, and the focus-visible group rule covers every quiet
button.  A colour tuned by eye, a control added outside the touch
block, a button that loses its ring — each now fails a suite rather
than a reader.

## Consequences

- The panel's words are readable at AA in both themes, including the
  muted words — which are the *labels*, and so the ones a first-time
  reader leans on.
- A touch user at any screen width, including the 1024px tablet, gets
  finger-sized targets everywhere in the panel.
- The keyboard reach is drawn by the panel's own design system, not
  guessed by the browser.
- The remaining eight requirements are held by their existing node and
  site tests plus the structural facts recorded in the table; a
  regression in any of them fails a suite rather than a reading.
