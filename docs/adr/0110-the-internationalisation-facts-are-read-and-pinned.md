# ADR-0110: The internationalisation facts are read and pinned

Date: 2026-11-15 · Status: accepted · The eighth NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107), M- (ADR-0108)
and C-series (ADR-0109); answers the NFR-I1–I6 questions raised
against the app's translation surface.

## What the reading found

Five of the six held — two of them by mechanisms worth recording, one
by a hair that turned out to be complete — and two were exposed: the
tools' message layer, and two locale-blind numbers in the panel.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| I1 | all UI strings translatable via `_()` | **the tool layer was exposed, fixed** | the panel was already whole: 141 strings, every one through `__` — the `.mjs` modules carry a local `__` that delegates to `globalThis.__` (Frappe's desk translator, present because the panel is mounted inside the Desk) with a `{0}`-substitution fallback for the node tests.  The server api/ and services/ were already whole: `_()` with `{0}` placeholders, and `refusal_sentence` (attachments) is a designed translation seam.  **Exposed: the tool layer.**  The ~93 message templates across `tools/erpnext.py`, `files.py`, `questions.py`, `history.py` — the summary line shown beside every tool's name and the text of every error card — were bare English f-strings, and several messages were *concatenated fragments* (`message += " Failed: "`), which no translation catalogue can hold and Arabic reading order cannot survive.  All wrapped: `_('template {0}').format(...)`, the four sentence builders rewritten as complete templated sentences |
| I2 | Arabic complete | **the catalogue was exposed, fixed** | the catalogue itself was complete — 433 entries, zero empty msgstr, zero fuzzy, covering every wrapped panel and server string (verified by extraction and diff, not by trust) — but the ~93 unwrapped tool templates could not be in any catalogue.  107 entries added (the wrapping also turned concatenations into single templates, changing the count and the shape); Arabic written by hand, placeholder counts matching, code identifiers (`limit`, `offset`, `asc`) kept Latin so the reader can match them to the manifest and the Desk.  Babel now parses 543 entries, zero untranslated |
| I3 | catalogue compiled to .mo at build time | holds | it is Frappe's own build that does it: `bench build --app albanna` → `compile_translations(app)` (frappe/commands/utils.py) → `albanna/locale/ar.po` → `sites/assets/locale/ar/LC_MESSAGES/albanna.mo` (babel `write_mo`).  No app-side build step is needed or wanted — the app's locale directory follows Frappe v16's gettext layout, and the compiler is the framework's |
| I4 | new translations live after clear-cache, no restart | holds | the runtime reads the .mo from disk inside `get_translations_from_apps`, cached per language in redis (`frappe.cache.hget(MERGED_TRANSLATION_KEY, lang, generator=...)`); the app holds no translation cache of its own (no module-level dict, no process-local copy — M1's import walker keeps core/ free of even the ability to build one).  Verified live end-to-end: build → `bench clear-cache` → probe reads `Found {0} {1}` → `عُثر على {0} {1}`, no restart |
| I5 | tool descriptions stay English | holds | the manifest's descriptions are plain `str` fields passed untouched into `to_wire()`'s dict; `core/tools.py` cannot import frappe (M1's walker forbids it), so a translation call cannot even compile there.  The split is deliberate and now pinned: the *model-facing* surface (descriptions) stays English, the *reader-facing* surface (tool-labels.mjs, the summary lines) is translated |
| I6 | date/number/currency follow the reader's locale | **two number surfaces were exposed, fixed** | dates and times were already whole: `currentLocale()` reads the document language the Desk sets, `Intl.RelativeTimeFormat` and `Intl.DateTimeFormat` with a per-locale formatter cache.  **Exposed:** the turn-cost line (`Number(message.cost).toFixed(4)`) and the attachment chip (`(file.size/1024).toFixed(1) KB`) — `toFixed` pins the decimal point and Western digits.  Fixed with `localeNumber()` in format.mjs: `Intl.NumberFormat` for the reader's locale, formatters cached per locale + digit budget, identity fallback when Intl refuses.  Currency is *not* formatted as money deliberately: the cost is a usage figure the site's currency only loosely names, and dressing it as a currency amount would claim a precision the price table does not have |

## The two decisions worth keeping

**The translator alias lives in `tools/base.py`, not in Frappe.**
Frappe's `_()` cannot run without a bench — `frappe.local` has no site,
no cache, and the unit suite (M2) runs without either.  The alias
(`from albanna.tools.base import translate as _`) returns the text
itself when no site is up and Frappe's `_()` when one is.  The tools
stay bench-free-testable, the reading stays honest, and the pin
asserts the alias is present in every tool module.

**The backend's site guards stay English.**  The two strings in
`tools/backend.py`'s `_assert_site` ("no site was resolved for this
call") and `_explain_missing_doctype`'s closest-names sentence name
*operators and the model*, not the reader: a site mismatch is a
deployment fault, the closest-names hint is a model hint in the
model's language, and the reader-facing part of both — the tool's
summary line and the error card — is already translated by the wrap.
The pin's `EXCLUDED` set records the boundary.

## What is pinned

`tests/test_internationalisation_pins.py`, ten walkers, five of them
red-checked live (unwrapped a refusal — the I1 walker failed; blanked
and dropped a catalogue entry — the I2 walkers failed; re-added a
`toFixed` — the I6 walker failed; wrapped a manifest description — the
I5 walker failed):

- I1: no bare string literal or f-string as the first argument of
  `ok`/`error`/`_refusal` in the tools; the `translate as _` alias
  present in every tool module; the fragment concatenations
  (`message += " Failed: "`, …) have no way back.
- I2: every `_()` template on the server and every `__()` literal in
  the panel is an msgid in the Arabic catalogue (babel-parsed), no
  empty translation, placeholder counts matching between msgid and
  msgstr.
- I3: the catalogue parses with babel — the same parser the build's
  compiler uses — and stays above its known size.
- I5: no translation call in `core/tools.py`; `description` passes
  through `to_wire()` untouched.
- I6: no `toFixed` in the panel; `localeNumber` exists in format.mjs.

## The trade-offs, named

- The tool messages are *the reader's* lines, so they went through the
  translator — but they are also what the model reads when it
  interprets a tool result.  A translated message is still a complete,
  structured sentence, and the model answers in the reader's language
  anyway; the data payload beside the message is unchanged, and the
  tests assert the envelope's shape, not its English words.
- Arabic translations were written in one pass by the same hand that
  wrote the English; a reviewer who reads Arabic should treat the
  catalogue as a draft worth a native pass, not as finished work.
- The catalogue-coverage pin means every new `_()` or `__()` string
  fails the suite until it enters the Arabic catalogue — the same
  friction the SEC and compat walkers impose, on purpose.
