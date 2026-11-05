# ADR-0017: Pure logic does not live in a browser bundle

Status: **Accepted**
Date: 2026-11-05

## Context

`SideChatApp.vue` opens with the app's own rule, stated plainly:

> The pure, tested logic is deliberately out of this file; what stays
> here is state, wiring and DOM.

Every concern in the panel follows it.  `approval.mjs` holds the approval
window, `context.mjs` the page's identity, `examples.mjs` the empty
state's questions, `markdown.js` the answer rendering, `window.mjs` the
transcript slice — twenty-odd modules, each pure, each with a
`*.test.mjs` beside it that runs under plain node with no framework and
no DOM.  The component holds state, wiring and DOM, and the tests hold
the logic.

The launcher did not follow it.

`albanna-side-chat.bundle.js` is a browser script: it asks the server
whether the widget should render, puts a launcher button and an empty
panel on the page, and fetches the Vue bundle on the first open.  It also
held the panel's geometry — the width it may be dragged through, how a
stored width is restored, which logical side the panel sits on, which
physical edge the resize handle faces — as four constants and four
functions inside a 400-line file with no tests.

That mattered twice in one pass.

**The geometry was wrong and nothing said so.**  `setWidth` wrapped its
`localStorage.setItem` in a try/catch, with a comment explaining that a
browser which will not remember the width is a browser that will not lose
it either.  `currentWidth` — the *read* — had no such guard, and it ran
from `boot()` with no try/catch around it.  In a browser where touching
`localStorage` throws, the exception escaped `boot()` and the widget
never appeared on any page, while `publishAccess` had already run — so
the "Ask Albanna" button rendered and opened nothing.  The guard was on
the wrong side of the asymmetry: the protected path ran later and mattered
less.

**The bundle is where the linters do not reach.**  `.pre-commit-config.yaml`
excludes `albanna/public/js/*.bundle.js` from prettier and eslint,
because those files are entry points the build flattens and a formatter
that reflows them is a formatter that fights the build.  That exclusion
is correct, and it makes the bundle the one place in the front-end where
untested logic can sit indefinitely without anything noticing.

## Decision

**Pure logic lives in a `.mjs` module beside its test.  A browser bundle
holds wiring.**

`albanna/public/js/side-chat/launcher.mjs` now holds the launcher's
geometry, and nothing else:

* `clampWidth(width)` — clamp to `[MIN_WIDTH, MAX_WIDTH]` and round.
* `readStoredWidth(storage)` — read the persisted width, validate it,
  and **return the default when the read throws**.  The Stage 1 defect is
  now a pure function with a test that fails if the guard is removed.
* `sideFor(position)` — the logical side, from the configured position.
* `pinnedRight(side, isRtl)` — which physical edge the panel is pinned to.
* The constants — `WIDTH_KEY`, `MIN_WIDTH`, `MAX_WIDTH`, `KEYBOARD_STEP`,
  `DEFAULT_WIDTH` — exported from one home rather than declared in the
  bundle and re-derived wherever they are needed.

`launcher.test.mjs` runs under plain node, like its neighbours, and
covers clamping at both bounds and beyond, a stored value that is out of
range or unparseable, a storage whose `getItem` throws, `sideFor` for
every configured position, and `pinnedRight` for all four
side-by-direction combinations.

The bundle imports the module and keeps the wiring.  Its behaviour is
unchanged apart from the guarded read, which is the point of the change.

The same rule was applied to the empty state in the same pass: the
`examples` computed — an eight-branch pure function of
`(context, count, party)` plus a read of `window.cur_frm` — moved out of
`SideChatApp.vue` into `examples.mjs` as `examplesFor`, and
`examples.test.mjs` grew to cover every branch.  Two applications in one
pass is what turned a local convention into a decision worth recording.

## Alternatives considered

**Test the bundle with a DOM stub.**  Rejected: it would need a
hand-rolled `document`, `window.frappe`, `window.localStorage` and a
module loader that copes with the bundle's top-level side effects, and
the result would be a test that breaks whenever the wiring changes for
reasons that have nothing to do with the logic.  Extracting the logic is
less work and tests more.

**Leave the geometry in the bundle and add a comment.**  Rejected: that
is the state this ADR was written to end.  The comment saying the read
needed a guard was already there in spirit — the write had one — and the
read was still unguarded.

**Lift the prettier/eslint exclusion for the bundle.**  Rejected: the
exclusion exists because the build flattens these files, and a formatter
that reflows an entry point is fighting the build.  The answer is not to
lint the bundle harder; it is to have less in it.

**Move the whole launcher into a `.mjs` module.**  Rejected: the launcher
*is* wiring.  It creates DOM, it calls the server, it fetches a bundle on
first open.  What moved out is the part that is not wiring.

## Consequences

* The launcher's geometry is tested, and the defect that took the widget
  down in storage-blocked browsers is now a test that fails if the guard
  is removed.
* The bundle is smaller and holds only what a browser script must hold.
* The rule is now stated in two places — the Vue file's header and this
  ADR — and the second one applies to the launcher, which the first one
  did not.
* A future browser entry point has an obvious home for its pure logic,
  and an obvious reason to use it: the bundle is the one place the
  linters do not reach.
* The constants have one home, so the clamp range and the keyboard step
  cannot drift between the drag handler and the ARIA values.

## See also

* [ADR-0013](0013-the-front-ends-rules-are-scanned.md) — the other rule
  this pass had to enforce in a second place, and the reason the bundle
  is where untested logic could hide.
* [ADR-0016](0016-the-empty-states-questions-follow-the-page.md) — the
  same rule applied to the empty state's suggestions, in the same pass.
* `albanna/public/js/side-chat/` — the twenty-odd modules the rule
  already governed, and the pattern `launcher.mjs` now follows.
