# ADR-0097: Tool descriptions in the manifest shall remain in English

Status: **Accepted**
Date: 2026-11-09

## Context

FR-13.3 requires that tool descriptions in the manifest shall remain in English (instructions to the model, not the user). The `TOOL_MANIFEST` in `albanna/core/tools.py` contains descriptions for all five tools (`LIST_DOCS`, `GET_DOC`, `GET_DOCTYPE_META`, `RUN_REPORT`, `CREATE_DOC`, `UPDATE_DOC`, `BULK_UPDATE_DOC`, `SUBMIT_DOC`, `CANCEL_DOC`, `AMEND_DOC`, `DELETE_DOC`, `ASK_QUESTION`). These descriptions are instructions to the model about what each tool does, not user-facing text. The `scripts/check_translations.py` script explicitly excludes the manifest's descriptions from the Arabic catalogue check with the comment: "The manifest's descriptions are the model's, not the reader's."

## Decision

**Record the exclusion of manifest descriptions from translation checks and the rationale.**

Two guards:

* `scripts/check_translations.py:211` asserts that the manifest's descriptions are excluded from the Arabic catalogue check with the comment: "The manifest's descriptions are the model's, not the reader's."

* `albanna/core/tools.py::TOOL_MANIFEST` asserts that all tool descriptions are in English and serve as instructions to the model about what each tool does, not as user-facing text that would need translation.

## Alternatives considered

**Translate tool descriptions into Arabic.** Rejected: the descriptions are instructions to the model, not the user. The model reads English, and translating them would confuse the model's understanding of what each tool does. The Arabic catalogue is for reader-facing interface strings only.

**Add Arabic translations for tool descriptions anyway.** Rejected: the same reason — these are model instructions, not user text. Adding them to the catalogue would create dead weight (unused translations) and confuse the translation validation tool.

## Consequences

* FR-13.3 is now held: the exclusion of manifest descriptions from the Arabic catalogue check is asserted, and the rationale is documented.

* No code change was needed; the exclusion was already implemented in `scripts/check_translations.py`. The work was the ADR and this record.

## See also

* `scripts/check_translations.py:211` — the exclusion comment.
* `albanna/core/tools.py::TOOL_MANIFEST` — the tool manifest with English descriptions.
* `albanna/core/tools.py:7` — the comment describing `description` as "the only thing the model reads".