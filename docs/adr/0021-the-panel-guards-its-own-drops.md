# ADR-0021: The panel guards its own drops

Status: **Accepted**
Date: 2026-11-05

## Context

A reader can attach a file by pasting it, dropping it, or choosing it from
the picker.  All three converge on one function, and the rules they follow
are the site's, published rather than copied — a browser that accepts a
file the server would refuse is a reader who waited for an upload that was
going to be refused.

The drop target was one attribute:

```
Composer.vue:496   <div class="albanna-chat__field" @drop="onDrop" @dragover="onDragOver">
```

That was the only drop handling in the entire app.  A grep of the whole
front end for `dragover`, `drop` and `ondrop` returned that one line.

`.albanna-chat__field` is a ~44px strip at the bottom of a 70vh panel.  The
transcript — by far the largest part of the panel — has only `@scroll` and
`@click`.  So a reader who dragged an image toward the panel and released
it over the transcript, the empty state, the header or the nudge got the
browser's default: **navigate the current document to the file**.  In the
Desk SPA that replaces the entire page with the image.  The conversation,
the draft and the reader's place in the Desk are gone.

The miss is likely, not exotic.  The target is roughly five percent of the
panel's area, and "drop it on the panel" is the natural aim.  And the
failure is invisible in testing, because you always drop on the target when
you are testing the feature.

## Decision

**The panel cancels the browser's default for drops that land inside it.
The Desk outside the panel keeps its ordinary behaviour.**

Two listeners on the `<aside>` the launcher creates, both calling
`preventDefault()` — one for `dragover`, one for `drop`.  The guard lives in
the launcher rather than in the composer, for two reasons:

* **The launcher owns the panel element.**  It creates the `<aside>`, so it
  is the natural place for a rule about what may happen inside it.
* **The guard then holds when the Vue bundle fails to load.**  The panel
  shows its boot-error state in that case, and a reader dropping a file on
  an error message should not lose the Desk either.

The composer's own handler is a descendant of the panel, so it runs first
in the bubble order and its work stands; the panel's listener only catches
the drops that miss it.  That ordering is the whole reason the fix is safe,
and it is stated in the comment so that nobody "simplifies" it later by
moving the guard to a capturing listener.

A drop on the Desk *outside* the panel is the browser's ordinary behaviour
and is not the app's business.  The guard covers the panel, not the window.

## Alternatives considered

**A window-level guard.**  Rejected: it would change the behaviour of the
whole Desk, which is not this app's to change.  A reader who drops a file
on a Frappe list view outside the panel gets whatever Frappe gives them,
and that is correct.

**Put the guard in the composer, on a wrapper element.**  Rejected: the
composer unmounts and remounts with the panel's views, and the guard would
have to be re-attached.  The launcher's panel is created once.

**Make the whole panel a drop target that attaches the file.**  Rejected:
it would make dropping on the transcript attach a file to a question the
reader has not asked yet, and it would make the destructive miss
*ambiguous* rather than merely safe.  The composer is where a question is
written; that is where a file belongs.

**Warn the reader instead.**  Rejected as the only measure: a warning after
the navigation is too late, and a warning before it is a dialog nobody
reads.  The guard is the fix; the affordance below is the courtesy.

**Leave it, because the reader can use the picker.**  Rejected: that is the
argument for every unguarded destructive action, and it is wrong each time.
The picker is one of three ways in, and the other two were safe.

## Consequences

* A drop that misses the composer is a no-op instead of a navigation.  The
  reader keeps the Desk, the conversation and the draft.
* The composer's own drop still works, because it runs first.
* The Desk outside the panel is untouched.
* The guard is two `preventDefault()` calls in the launcher, and it holds
  even when the Vue bundle is not there.
* It exposed a second, smaller gap: `onDragOver` called `preventDefault()`
  and nothing else, so the reader had no visible affordance showing where
  the target was.  A `--dragover` class on the field, toggled by a
  `dragenter`/`dragleave` counter, now says so.  The counter rather than a
  boolean, because `dragleave` fires when the pointer crosses a child
  element and a boolean would flicker.

## See also

* [ADR-0013](0013-the-front-ends-rules-are-scanned.md) — the scans that now
  fail on a physical direction property, which the drag-over class had to
  respect.
* `albanna/public/js/albanna-side-chat.bundle.js` — the launcher, which
  owns the panel and now guards it.
* `albanna/public/js/side-chat/Composer.vue` — the three attach paths and
  the one rule they share.
