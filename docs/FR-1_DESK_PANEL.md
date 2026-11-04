# FR-1 — The Desk panel

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the seven functional requirements FR-1.1 … FR-1.7, which
describe the side chat as a thing that lives in the Desk rather than
beside it — present on every page, docked into the layout, resizable,
reachable from a launcher, themed with the Desk, and aware of the page it
sits on.

---

## FR-1.1 — The panel is present on every Desk page

**Requirement.** A reader who may chat sees the side chat on every Desk
page: the launcher that opens it and the panel it opens into.  A reader
who may not chat sees nothing at all.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/hooks.py:46-52` — `app_include_js` lists the launcher
  (`albanna-side-chat.bundle.js`) alongside the form and error-dialog
  buttons; `app_include_css` lists the stylesheet.
- `albanna/public/js/albanna-side-chat.bundle.js` — `boot()` asks the
  server (`albanna.api.widget.options`) whether the widget should render
  and returns early when `config.visible !== true`, after publishing the
  answer so the other bundles do not wait for a decision already made.
- `albanna/api/widget.py` — `options()` is the gate; the docstring there
  records why a reader without chat access gets no widget at all.

**Gaps found.** None in this pass.  The earlier failure mode — an entry
without `.bundle.` 404ing silently on every page — is now guarded by
`tests/test_hooks.py`, which asserts both that every entry carries
`.bundle.` and that each names a file that exists.

**Deliberate exclusions.** Gated visibility; print view.

---

## FR-1.2 — The panel docks into the Desk layout

**Requirement.** In docked mode the panel is a column of the Desk, not an
overlay: the Desk gives up the space and the reader keeps reading the
record beside the answer.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/public/js/albanna-side-chat.bundle.js:232-246` — `DOCK_CLASS`
  maps the logical side to `albanna-side-chat-docked-inline-end` /
  `albanna-side-chat-docked-inline-start`, toggled from the single
  `setDock` call so it cannot drift from the panel's visibility.
- `albanna/public/js/albanna-side-chat.bundle.js:328-342` — `setDock`
  adds and removes the class on `<body>`, because a margin there is the
  only thing that moves the whole Desk (Frappe's reset ships
  `body { padding: 0 !important }`).
- `albanna/public/css/albanna-side-chat.bundle.css` — the docked margin
  is written against `--albanna-panel-width`, so a wider panel takes more
  of the Desk.

**Gaps found.** None in this pass.

**Deliberate exclusions.** Tablet ≤ 991 px and phone ≤ 640 px; floating
mode.

**Accepted trade-offs.** A Frappe modal centred in the viewport can sit
behind the panel on a narrower screen, because `#albanna-side-chat` is
`z-index: 2147483000` and a body margin does not move a fixed modal.
The panel staying reachable is the point of the dock, so this is
accepted.  The Desk content ends flush against the panel's border (margin
is `panel + 16 px`, panel inset 16 px) — zero gap, also accepted.

---

## FR-1.3 — The panel's width is resizable and remembered

**Requirement.** The reader can drag the panel wider or narrower within a
sensible range, and the width survives a reload on the same browser.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/public/js/side-chat/launcher.mjs` — `clampWidth`,
  `readStoredWidth`, `MIN_WIDTH` (320), `MAX_WIDTH` (720),
  `KEYBOARD_STEP` (24), `DEFAULT_WIDTH` (400), `WIDTH_KEY`
  (`albanna.side-chat.width`).  The handle is a splitter moved with the
  arrow keys, Home and End.
- `albanna/public/js/albanna-side-chat.bundle.js:250-260` — `setWidth`
  clamps, writes the CSS variable, updates the ARIA values, and persists
  to `localStorage` inside a try/catch.
- `albanna/public/js/albanna-side-chat.bundle.js:272` — `setWidth(readStoredWidth(window.localStorage))`
  restores on boot.

**Gaps found and fixed.** The read path was unguarded: `currentWidth()`
called `localStorage.getItem` with no try/catch, and it ran from `boot()`
with no guard around it, so a browser that throws on touching
`localStorage` lost the widget on every page while the form button still
rendered and opened nothing.  The read is now `readStoredWidth`, which
returns the default 400 when the read throws, and is covered by a
regression test in `launcher.test.mjs`.

**Deliberate exclusions.** Tablet ≤ 991 px and phone ≤ 640 px (docking
and the resize handle are switched off); floating mode (fixed 400 px);
width persistence is per-browser, per-origin.

---

## FR-1.4 — A launcher opens the panel

**Requirement.** A button on the page opens and closes the panel; it is
hidden while the panel is open, because the close button lives in the
panel header.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/public/js/albanna-side-chat.bundle.js:195-210` — the launcher
  button is created with `aria-label`, `aria-expanded`, `aria-controls`,
  and the launcher SVG.
- `albanna/public/js/albanna-side-chat.bundle.js:344-360` — `setOpen`
  toggles `launcher.hidden = open`, so the launcher disappears while the
  panel is open.
- `albanna/hooks.py:46-52` — the launcher bundle is a global include.

**Gaps found.** None in this pass.  The launcher's registration is now
asserted by `tests/test_hooks.py::test_the_launcher_is_registered_globally`,
because an empty include list passed every existing test.

**Deliberate exclusions.** Gated visibility; print view; the launcher is
hidden while the panel is open.

---

## FR-1.5 — The panel is logical, not physical

**Requirement.** Everything inside the panel is expressed in logical
properties, so the same stylesheet serves both reading directions and the
build's RTL pass has nothing to mirror.

**Status.** Shipped.

**Evidence.**
- `albanna/public/css/albanna-side-chat.bundle.css` — the stylesheet is
  written in `padding-inline-*`, `margin-inline-*`, `inset-inline-*`,
  `text-align: start` throughout; the one remaining physical property
  (`padding-left: 4px` on `.albanna-chat__attach-notice`) was corrected
  to `padding-inline-start: 4px` in this pass.
- `tests/test_front_end_rules.py::test_no_physical_direction_property` —
  scans every file under `public/` and fails on any `left:` / `right:` /
  `margin-left` / `padding-right` / `border-left` / `float: left|right` /
  `text-align: left|right`.

**Gaps found and fixed.** One physical property survived the earlier
conversion: `.albanna-chat__attach-notice { padding-left: 4px; }`.  It
rendered correctly only because rtlcss flipped it at build time, so its
correctness came from the build step rather than the browser.  Corrected.

---

## FR-1.6 — The panel inherits the Desk theme

**Requirement.** Every filled state in the panel follows the theme: the
accent token in light, the grey in dark, with the matching ink.  No
state is permanently one colour.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/public/css/albanna-side-chat.bundle.css:78-95` — the
  `[data-theme="dark"]` block redefines the `--albanna-*` tokens, and
  the duplicate `--albanna-bubble` declaration that sat on adjacent lines
  was removed in this pass.
- `albanna/public/css/albanna-side-chat.bundle.css:1769-1774` —
  `.albanna-chat__question-option.is-selected` now uses
  `--albanna-accent` and `--albanna-on-accent`, matching every other
  filled state, instead of the undefined `--albanna-primary` with a
  hardcoded white ink.
- `tests/test_front_end_rules.py::test_every_albanna_token_is_declared` —
  would have caught the undefined token; it now scans every file under
  `public/`.

**Gaps found and fixed.** `.albanna-chat__question-option.is-selected`
referenced `--albanna-primary`, which is declared nowhere in the app, so
its background was permanently the hardcoded fallback blue with hardcoded
white ink — the only filled state that did not follow the theme.  Fixed
to use `--albanna-accent` / `--albanna-on-accent`.

---

## FR-1.7 — The empty state names the page and offers relevant questions

**Requirement.** When the panel has nothing to answer yet, it says what it
is asking about (the document, the list, or the report) and offers
questions that fit that page.  Only a page with nothing to anchor on falls
back to generic questions.

**Status.** Shipped, with the exclusions in §Deliberate exclusions.

**Evidence.**
- `albanna/public/js/side-chat/SideChatApp.vue` — `pageContext` now names
  a form (`Asking about {0} {1}`), a list (`Asking about the {0} list`)
  and a report (`Asking about the {0} report`), and returns `""` only
  when there is genuinely no page to name.
- `albanna/public/js/side-chat/examples.mjs` — `examplesFor(context, count, party)`
  is the pure function behind the `examples` computed, covering the Issue
  form, a generic form with a document, a new document with and without a
  party, the Issue list, an empty list, a generic list, a report, and the
  generic fallback.
- `albanna/public/js/side-chat/examples.test.mjs` — covers every branch.

**Gaps found and fixed.**
- The context line only appeared on a form, because `pageContext` was
  derived from `openDocument`, which is null unless the context carries
  both a doctype and a name.  Lists and reports now name themselves.
- The generic fallback was still sales-shaped (`Which Sales Orders are
  still open?`, `What is the total value of open orders?`) after the
  persona was re-cut to a support agent.  It is now support-shaped
  (`How many open Issues are there?`, `Which Issues are still open?`,
  `How many customers are there?`), with no "my" anywhere, because the
  assistant has no way to know who "my" is.
- The suggestion logic lived inside `SideChatApp.vue` as an eight-branch
  pure function with no test, against the file's own rule that pure logic
  belongs in the `.mjs` modules.  It moved to `examplesFor` in
  `examples.mjs`.

**Deliberate exclusions.** None specific to this requirement.

---

## Deliberate exclusions (shared)

These are stated once here; every requirement above references the ones
that apply to it rather than repeating them.

- **Gated visibility.** The panel and the launcher exist only when
  `settings.enabled && can_use_chat()`.  A reader without chat access gets
  nothing on any page.  Deliberate; documented in `albanna/api/widget.py`'s
  docstring and the launcher's header.  (FR-1.1, FR-1.4)
- **Print view.** `/printview` is a separate Jinja page with no
  `app_include_js`, so there is no panel and no launcher there.  Recorded
  as out of scope: it is a print rendering, not a working page, and the
  panel's value is sitting beside the record being worked on.
  (FR-1.1, FR-1.4)
- **Tablet ≤ 991 px and phone ≤ 640 px.** Docking is switched off and the
  panel covers the Desk; the resize handle is hidden.  Deliberate,
  documented in the stylesheet.  (FR-1.2, FR-1.3)
- **Floating mode (opt-in).** Covers by design, no body margin, fixed
  400 px width.  (FR-1.2, FR-1.3)
- **The launcher is hidden while the panel is open.** The close button is
  in the panel header.  (FR-1.4)
- **Width persistence is per-browser, per-origin.** It survives restarts
  on the same machine and profile; it does not follow the user to another
  device.  (FR-1.3)

## Accepted trade-offs

Each with the reason.

- A Frappe modal centred in the viewport can sit behind the panel on a
  narrower screen (`#albanna-side-chat` is `z-index: 2147483000` and a
  body margin does not move a fixed modal).  Accepted: the panel staying
  reachable is the point of the dock.
- The Desk content ends flush against the panel's border (margin is
  `panel + 16 px`, panel inset 16 px) — zero gap.  Accepted.

---

## Pointer

`docs/ROADMAP.md` §0 lists the Desk panel as shipped; this document is
the evidence behind that line.
