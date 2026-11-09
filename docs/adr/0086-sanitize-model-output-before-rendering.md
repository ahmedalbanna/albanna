# ADR-0086: Sanitize model output before rendering (escape first, build markup second)

Status: **Accepted**
Date: 2026-11-09

## Context

FR-11.3 requires that the system not expose API keys in logs, error messages, or the UI (except to System Managers in settings). A related and equally important concern is that model output must be sanitized before rendering — the markdown renderer in `albanna/public/js/side-chat/markdown.js` already follows the correct pattern: the text is **escaped first**, and only then are this module's own tags inserted. Nothing the model or the site says can therefore introduce markup — there is nothing left in the string that could be markup.

## Decision

**Record the escaping pattern and the three-line guarantee.**

Two guards:

* `albanna/public/js/side-chat/markdown.js` asserts that the text is **escaped first** via `escapeHtml()` before any markdown-to-HTML conversion. The five HTML special characters (`&`, `<`, `>`, `"`, `'`) are replaced with their entity equivalents, so any model-written `<script>`, `<img onerror=...>`, or other markup tags are rendered as plain text.

* `albanna/public/js/side-chat/markdown.js::renderMarkdown()` asserts the three-line guarantee: (1) `escapeHtml(text)` is called on the raw model output; (2) the escaped text is then processed into HTML blocks/inline/links; (3) the result is safe to use with `v-html`, because all markup has been neutralized.

* `albanna/tests/markdown.test.mjs` asserts that `escapeHtml("<b>&'\"</b>")` produces `"<b>&'"</b>"` — the entire original string is escaped, not just the "dangerous" characters.

## Alternatives considered

**Use a client-side sanitizer like DOMPurify.** Rejected: DOMPurify is a large dependency and the current approach — escaping the five HTML special characters — is sufficient because the markdown renderer only produces a known subset of tags (bold, italic, headings, lists, tables, code). Any model-written tag is escaped before it ever reaches the DOM.

**Skip escaping for performance.** Rejected: the escaping is a fixed string of five `replace()` calls — the performance cost is negligible compared to the security guarantee.

## Consequences

* FR-11.4 is now held: the escaping pattern, the three-line guarantee, and the test assertion are each asserted.

* No code change was needed; the sanitization was already implemented. The work was the ADR and this record.

## See also

* `albanna/public/js/side-chat/markdown.js::escapeHtml` — the five-character escape.
* `albanna/public/js/side-chat/markdown.js::renderMarkdown` — the three-line guarantee.
* `albanna/public/js/side-chat/markdown.test.mjs` — the test assertion.
* `albanna/core/secrets.py::mask_secret` — the secret-masking counterpart.