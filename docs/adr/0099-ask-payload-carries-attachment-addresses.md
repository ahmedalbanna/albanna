# ADR-0099: The ask payload carries attachment addresses, not bytes

Status: **Accepted**
Date: 2026-11-12

## Context

NFR-P1 requires that the endpoint for submitting a question returns a
stream ID within 500 ms. Measured end to end on test.localhost, a plain
question submits in 40–90 ms — but a question carrying an attachment at
the site's 2 MB ceiling took 360–520 ms, and a no-op endpoint handed the
same 2.8 MB body costs ~390 ms under `bench serve` (more under
gunicorn). The framework's body read and parse alone consumed the
budget; no amount of app-side work could close it.

The cause was that the browser uploaded every file *first* — the
composer's upload endpoint stores each one as a private Frappe File —
and then sent the same bytes again inline, as data URLs, in the ask
payload. The bytes crossed the wire twice, and the queue's turn marker
held a second copy in Redis. The regenerate path (FR-6.11) already
carried addresses only, and for the same reason it could not show a
stored picture to the model: nothing read the files back.

## Decision

**The ask payload carries addresses only.** The widget's
`turnAttachments()` returns `attachmentUrls` and nothing else; the
attachment object drops its `dataUrl` field (the bytes were read only to
be uploaded); `runTurn()` no longer sends an `attachments` field.

On the server, `_store_attachments()` gains a fourth return value — the
data URLs the model is given — and when the request carries no bytes it
reads the stored files back with `load_attached_files()` (by URL, via
`File.get_content()`, the type read from the stored name's extension).
The picture parts come from where the files are stored, so a regenerate
turn now shows the model the same pictures a first turn would have. A
file that cannot be read back falls to the row's carried
`attachment_texts`, which remains the record of a document that has
gone.

The endpoint still accepts the `attachments` bytes field — the wire is
read by one parser, and a caller that carries bytes is still answered.

## Alternatives considered

**Hybrid: images keep bytes, documents go URL-only.** Rejected: a 2 MB
image still rode the 500 ms line, and the split left two shapes for one
idea.

**Document the boundary; accept that attachments ride the line.**
Rejected: the double-carry was real waste — the bytes were paid for on
the wire, in the marker, and in browser memory for the panel's whole
life — and fixing it also fixed regenerate-not-seeing-pictures.

## Consequences

* A submission at any attachment size carries a body of tens of bytes;
  the endpoint lands at ~30–100 ms end to end.
* The stored files are read in the job, off the request path.
* `readable_attachments()` now filters the read-back data URLs; the
  vision/no-vision drop checks addresses as well as bytes.

## See also

* `albanna/public/js/side-chat/attachments.mjs` — `turnAttachments`, the
  wire shape.
* `albanna/services/attachments.py` — `load_attached_files`, the
  read-back.
* `albanna/services/chat_service.py` — `_store_attachments`, the fourth
  return value.
* CONTEXT.md invariant 93.
