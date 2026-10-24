# Destructive-approval UX — design

**Status:** design + first implementation (frontend only)
**Scope:** the approval card for `cancel_doc` and `delete_doc` (and, by extension, any future destructive tool).
**Related:** `docs/PRODUCT_UX_REVIEW.md` §3.1, ADR-0007 (the second write), invariant 49 (server owns the deadline).

## Why

The approval rail was built for *writes* — creating or editing a document. The
in-progress lifecycle tools (`submit_doc`, `cancel_doc`, `amend_doc`,
`delete_doc`) make the assistant a lifecycle actor, not just an editor. Two of
those four are destructive:

- `delete_doc` removes the document (Frappe keeps a `Deleted Document`, but
  its `restore()` renames children, so identity is not preserved).
- `cancel_doc` cancels a submitted document and runs its `on_cancel` hooks.

A card that says "Confirm / Cancel" with a generic "Waiting Ns" line does
not carry enough weight for either. The reader must be able to tell, at a
glance, *what* they are about to do and *that it cannot be taken back*.

## Design decisions

1. **Detection is by tool name, not by a new server field.** The confirm
   event already carries `name` (the tool name). The frontend classifies
   `cancel_doc` and `delete_doc` as destructive. No backend change is needed,
   and the classification is a single function (`isDestructiveTool`) that a
   future tool opts into by name.

2. **Danger styling, not a different component.** The card stays a card in
   the transcript (one card per waiting write, threaded). Only the border,
   background, consequence line, and confirm button change colour. No new
   component, no modal — modal fatigue is the enemy.

3. **A consequence line, always present for destructive tools.** One sentence,
   in the theme's danger colour, stating what will happen and that it cannot
   be undone from here. It appears above the countdown, so it is read before
   the reader looks at the clock.

4. **The confirm button is danger-coloured for destructive tools.** The
   cancel button stays neutral. This makes "Confirm" the dangerous action
   visually, which is the correct emphasis.

5. **The countdown and server-owned deadline are unchanged.** Invariant 49
   still holds: the server owns the deadline; the card counts down from the
   same number. Destructive approvals do not get a longer window — the
   operator's `confirm_timeout` applies to all writes.

6. **Expired cards still say what happened.** When the wait runs out, the
   consequence line remains and the countdown becomes "The wait ran out — the
   change was not made." The reader is never left wondering whether a delete
   happened.

## What is implemented now

- `SideChatApp.vue`: `isDestructiveTool()` and `destructiveConsequence()`;
  card class `albanna-chat__confirm--destructive`; consequence paragraph;
  danger button modifier.
- `albanna-side-chat.bundle.css`: the three new rules, using
  `--albanna-danger` with a fallback so they work in both themes.
- `albanna/locale/ar.po`: two new translated strings.

## What is deliberately not implemented

- **No change to button labels.** "Confirm" / "Cancel" stay. Renaming to
  "Delete it" / "Cancel this document" was considered and rejected: it
  multiplies the translation surface and the generic pair is already
  understood once the consequence line is read.
- **No per-tool icons.** An icon would help, but the icon set is not
  standardised in this app; adding a one-off SVG risks drift. Revisit when
  the app adopts a single icon font.
- **No backend change.** The classification lives in the frontend. If a
  future tool is destructive, add its name to `isDestructiveTool()` and
  write its consequence sentence.

## Open follow-ups

- When the lifecycle tools land, add a site-level test that the confirm event
  for `delete_doc` carries `name === "delete_doc"` (so the classification
  fires).
- Consider a stronger confirmation for `delete_doc` specifically: a typed
  confirmation ("type the document name to delete") for the most destructive
  case. Deferred until real usage data shows the single-click card is
  insufficient.
- Dark-mode visual review of the danger colours (part of the broader
  dark-mode regression item in `PRODUCT_UX_REVIEW.md`).
