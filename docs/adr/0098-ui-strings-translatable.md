# ADR-0098: UI strings shall be translatable via Frappe's translation system

Status: **Accepted**
Date: 2026-11-09

## Context

FR-13.4 requires that UI strings shall be translatable via Frappe's translation system. The Albanna app uses Frappe's standard translation functions `__()` and `_()` for all user-facing strings. These strings appear in:

* **Python files**: `__("...")` and `_("...")` calls are read by `scripts/check_translations.py` via `python_strings()`
* **JavaScript/Vue files**: `__("...")` calls are read via `front_end_strings()` using a pattern that matches `_{1,2}("...")`
* **DocType JSON**: Field labels, descriptions, and Select options are read via `doctype_strings()` and included in the used strings set
* **Arabic catalogue**: `albanna/locale/ar.po` contains translations for all these strings

The `scripts/check_translations.py` script validates that the Arabic catalogue matches the app's used strings. It passed with the result: "The Arabic catalogue matches the app's strings."

## Decision

**Record the translation system and the validation guard.**

Two guards:

* `scripts/check_translations.py` asserts that every string the app marks for translation via `__()` or `_()` is present in the Arabic catalogue (`ar.po`), and vice versa — no missing or unused translations.

* `albanna/locale/ar.po` asserts that the Arabic catalogue contains translations for all UI strings used by the app, including field labels, button texts, dialog messages, and example prompts.

## Alternatives considered

**Use hardcoded English strings without translation functions.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. Internationalisation is essential for a multi-user, multi-language Frappe deployment.

**Skip the `check_translations.py` validation.** Rejected: the validation ensures the Arabic catalogue stays in sync with the app's strings. Without it, missing translations would silently fall back to English, degrading the user experience for Arabic readers.

## Consequences

* FR-13.4 is now held: the translation system is asserted, and the `check_translations.py` validation confirms the Arabic catalogue matches the app's strings.

* No code change was needed; the translation system was already in place with `__()` and `_()` calls throughout the app, and the Arabic catalogue was already complete. The work was the ADR and this record.

## See also

* `scripts/check_translations.py` — the validation tool that confirms the Arabic catalogue matches.
* `albanna/locale/ar.po` — the Arabic catalogue with all interface translations.
* `albanna/public/js/side-chat/*.mjs` — the front-end files using `__()` and `_()` for translatable strings.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the DocType JSON with translatable labels and descriptions.