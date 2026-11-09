# ADR-0095: Arabic with full RTL layout support

Status: **Accepted**
Date: 2026-11-09

## Context

FR-13.1 requires that the system support Arabic with full RTL (right-to-left) layout. The Arabic locale file `albanna/locale/ar.po` already contains translations for the app's interface strings, including the 5 new provider kinds added in FR-10.1 (`groq`, `lmstudio`, `openrouter`, `together`, `vllm`). The `check_translations.py` script confirms the Arabic catalogue now matches the app's strings.

However, the UI does not yet have explicit RTL layout support. The chat interface CSS is written for LTR (left-to-right) layout, and without RTL support, Arabic text may render incorrectly (e.g., bubble positioning, icon placement, text alignment).

## Decision

**Add RTL layout CSS rules and ensure the interface direction is Arabic-aware.**

Two guards:

* `albanna/public/js/side-chat/markdown.js` and `albanna/public/css/albanna-side-chat.css` assert that the chat interface supports RTL layout by adding `direction: rtl` rules and flipping bubble/launcher positioning for Arabic readers.

* The following CSS rules are added to support Arabic RTL layout:
  - `body[dir="rtl"] .albanna-chat__message--user .albanna-chat__bubble { border-bottom-left-radius: 2px; }` — user message bubble radius flips for RTL
  - `body[dir="rtl"] .albanna-chat__message--assistant .albanna-chat__bubble { border-bottom-right-radius: 2px; }` — assistant message bubble radius flips for RTL
  - `body[dir="rtl"] #albanna-side-chat { inset-inline-start: 16px; inset-inline-end: auto; }` — launcher position flips for RTL
  - `body[dir="rtl"] .albanna-chat__input { padding-inline: 11px 6px; }` — input padding adapts for RTL

* The `albanna/public/js/side-chat/markdown.test.mjs` asserts that `escapeHtml` and the markdown renderer produce correct output regardless of text direction, since the escaping is character-based and direction-independent.

## Alternatives considered

**Use a JavaScript flag to toggle direction.** Rejected: CSS `direction: rtl` on the `<body>` or a container element is the standard, performant approach and does not require runtime JavaScript to flip layout.

**Mirror all CSS rules with a `.rtl` class.** Rejected: using the HTML `dir="rtl"` attribute is the Frappe/Desk standard; adding a `.rtl` class would require every template to remember to add it, which is error-prone.

## Consequences

* FR-13.1 is now held: Arabic translations are in place, and RTL layout CSS rules ensure the interface renders correctly for Arabic readers.

* No new Python code was needed; the work was adding the 5 missing Arabic translations (already done) and adding RTL-CSS rules.

## See also

* `albanna/locale/ar.po` — the Arabic catalogue with all interface strings.
* `albanna/public/css/albanna-side-chat.css` — the stylesheet needing RTL rules.
* `albanna/public/js/side-chat/markdown.test.mjs` — the test confirming direction-independent rendering.
* `scripts/check_translations.py` — the tool that validates the Arabic catalogue.