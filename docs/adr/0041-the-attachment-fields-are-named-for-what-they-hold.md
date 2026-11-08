# ADR-0041: The attachment fields are named for what they hold

Status: **Accepted**
Date: 2026-11-08

## Context

`image_url` held the addresses of stored Frappe Files from the day PDFs
were accepted, and `had_image` recorded in the audit row that a question
"had an image" when it had a PDF. Three names said one thing about a
field that held another.

The app's own vocabulary everywhere else already said "attachment" —
`store_attached_file`, `check_attachments`, `attachable_names`,
`attachment_note`, `unstored_note`, `read_attachment_list`. The field
names were the only place that still said "image".

The owner's decision was to make the name general, covering multimedia
and documents. That is the right instinct, and it is right for a reason
deeper than breadth: the name was already a lie, and a lie in a schema is
a lie every future reader is told.

## Decision

**The fields are renamed to match the vocabulary the app already uses.**

| Before | After |
|---|---|
| `TurnRequest.images` | `attachments` |
| `TurnRequest.image_urls` | `attachment_urls` |
| `Message.images` | `attachments` |
| `tabAlbanna Message.image_url` | `attachment_urls` |
| `tabAlbanna Chat Log.had_image` | `had_attachment` |
| `Albanna Settings.image_support` | `attachment_support` |
| `Albanna Settings.max_image_size_kb` | `max_attachment_size_kb` |
| notice `image_dropped` | `attachment_dropped` |

Two shapes, because Frappe stores the two differently. A normal
DocType's fields are columns, and `frappe.db.rename_column` moves the
column and its data in one `ALTER TABLE ... CHANGE COLUMN`. A Single
DocType's fields are rows in `tabSingles` keyed by (doctype, field), so
there is no column to rename — the row's key moves.

**`supports_vision` stays.** It is the provider's capability flag and it
is genuinely about vision today. It becomes `supports_media` when audio
and video actually land; renaming a capability that does not exist yet is
renaming for a future that may not arrive.

**The wire dialect's `image_url` part type also stays.** That is the
provider's vocabulary, not this app's, and `to_wire` says so in a
docstring so the next reader does not "fix" it.

## Alternatives considered

**Rename only the Python and JS, leave the DB columns.** Rejected: the
DocType JSON is the schema, and it is the thing a future contributor
reads in Desk. Leaving it means the lie persists in the most visible
place, and the migrate is one patch with a supported helper.

**`file_urls` instead of `attachment_urls`.** Rejected, narrowly. Frappe's
File doctype has a `file_url` field, so it would align with the
framework. But one word for one concept, distinguished by what it holds,
is clearer than two words for two halves — and the app already speaks
"attachment" in six other places.

**Wait and rename with the scope broadening.** Rejected: the lie exists
today, and the rename is independent of what types get added later.
`attachments`/`attachment_urls` is correct whether the list holds five
types or fifty.

## Consequences

* A reader of the schema is no longer told a PDF is an image.
* The rename touched four columns across three DocTypes, ~90 references
  across 17 files, and the API contract — so the browser and the server
  deploy together, which is how the app deploys anyway.
* The bulk pass got two things wrong and the review caught them: it
  reached ERPNext's own `image` field on Contact documents in the test
  data, and it turned `image/*` MIME types into `attachments/*`, which
  would have made the type check refuse every file the site accepts.
  Both are the same lesson — a rename wide enough to be worth doing is
  wide enough to reach a word that means something else.
* The patch's first attempt failed in `_move_single` and the failure
  rolled back the column renames without undoing the schema sync, leaving
  the site with both columns and the data in the old one. It now copies
  across and drops the old column.
* Something outside the session later rewrote the patch's f-strings as
  string concatenation, with a comment saying the SQL was built "without
  an f-string so the scanner sees no interpolation". That is evading a
  tool rather than fixing a problem — the identifiers were module
  constants either way, and the app already ships f-string SQL with an
  interpolated identifier in `permissions.py`. Reverted, with a comment
  recording that the identifiers are constants.

## See also

* [ADR-0042](0042-the-truncation-flag-is-stored-not-inferred.md) — the
  other column this pass added, in the same migrate.
* `albanna/patches/v0_1/rename_attachment_fields.py` — the patch, and the
  comment that says why the identifiers are safe.
* `albanna/core/messages.py` — `to_wire`, whose docstring records that the
  wire dialect's name is the provider's.
