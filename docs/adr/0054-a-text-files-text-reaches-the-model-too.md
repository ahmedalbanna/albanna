# ADR-0054: A text file's text reaches the model too

Status: **Accepted**
Date: 2026-11-09

## Context

ADR-0050 gave a PDF's text to the model, because a PDF's bytes are not a
picture and no provider reads them as an image part.

The same is true of every other non-image type, and the site accepted
none of them. A reader who wanted to ask about a CSV of the month's
orders, a JSON payload, or a note they were sent had no way to attach it
— and if they had, the only thing the model could be given was the file's
address.

## Decision

**Four text types are accepted, and their text travels with the turn the
same way a PDF's does.**

`text/plain`, `text/csv`, `text/markdown`, `application/json`. They are
the types a reader actually attaches and the ones whose text is the whole
of their content.

**`readable_attachments` keeps only the image types.** That is the rule
stated the right way round: an image goes to the provider as a picture,
everything else goes as text read here. The old form asked "is this a
PDF?", which was the same answer for the wrong reason.

**A text file is decoded UTF-8 first, and Latin-1 after it.** UTF-8
because that is what a browser writes; Latin-1 because a CSV exported
from a spreadsheet on an Arabic Windows install is Windows-1256, and
UTF-8 turns it into mojibake rather than failing.

**The unreadable sentence is the attachment's, not the PDF's.** "Could
not be read as text" covers a scanned PDF and bytes that are not text
alike; a sentence that named one type would be wrong about the other.

## Alternatives considered

**Accept office formats too.** Rejected: reading a `.docx` needs a
library this bench does not have, and the app's posture is to do one
thing honestly rather than five things hopefully. PDF was already
accepted and is what readers attach; the text types are the natural
completion rather than a new frontier.

**Accept any type and refuse the dangerous ones.** Rejected: the list is
an allowlist for a reason — `image/svg+xml` executes as HTML and
`text/html` is a page, not a file. An allowlist that grows by exception
is a denylist with extra steps.

**Send the text as a separate message part rather than in the note.**
Rejected: the note is where the page context goes, and the attachment's
description belongs with the attachment's address. A second channel
would be a second place to keep in step.

**Sniff the type from the bytes rather than trusting the header.**
Rejected: the header is the same claim `check_attachment` already
validated against the site's list, so it is the one thing about a data
URL this app trusts. A second opinion would be a second rule.

## Consequences

* A reader can attach a CSV, a JSON payload, a Markdown note or a plain
  text file, and the model is given its contents.
* The bytes of every non-image attachment stay out of the provider
  payload, so a large file cannot blow the context.
* The refusal sentence that names the attachable types now names nine,
  and the list is the site's own rather than a copy in the sentence.
* The general lesson is ADR-0050's, one type wider: the question is never
  "is this a PDF?" but "can a provider read this as a picture?" — and
  everything that answers no travels as text.

## See also

* [ADR-0050](0050-a-pdfs-text-reaches-the-model-and-its-bytes-do-not.md)
  — the PDF half, and the rule this generalises.
* [ADR-0053](0053-an-attachments-text-is-stored-so-a-reloaded-thread-still-has-it.md)
  — the stored half, which covers these types too.
* `albanna/core/attachments.py` — `ATTACHABLE_TYPES`,
  `IMAGE_MIME_TYPES`, `attachment_text`, and `readable_attachments`.
