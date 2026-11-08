# ADR-0050: A PDF's text reaches the model, and its bytes do not

Status: **Accepted**
Date: 2026-11-09

## Context

A PDF's bytes travel to the provider as an `image_url` part, and no
provider parses one. The app worked around this with a caveat sentence:
*"A PDF's contents could not be read; only its address is available, so do
not describe what it says."*

So the model was honest, and the reader attached a document and got an
answer that could not see it. A reader who attached a contract and got an
answer that ignored it was answered about a document nobody read.

The cost was not only honesty. The site's own ceiling is 2048 KB, and a
two-megabyte PDF is the better part of a million tokens of base64 — a
turn that fails, or a turn that costs a fortune, for a part nothing reads.

## Decision

**A PDF's text is extracted and travels with the turn; its bytes are
dropped from the provider payload.**

`pypdf` is a dependency of Frappe itself, so it is on every bench this
app runs on and nothing new is installed for this. The text is read from
the data URL the browser already sent, so there is no file to open and no
path to resolve.

**The text is bounded at 12000 characters.** The bound is on what the
*model* is given, because that is what costs tokens and what fills the
context — and a document whose first pages say what it is worth more than
one whose last pages do.

**Every failure is the same answer: empty.** A malformed PDF, an
encrypted one, a library that changed its shape — all of them mean "no
text", and none of them is worth failing a turn over. A scanned document
is pictures of words, and no library reads those without OCR; the model is
told so rather than left to guess, which is the same "say what it could
not read" property the app ships for refused reads.

**`None` and an empty entry mean different things**, and the difference is
the whole point. `None` — nobody looked; the history is rebuilt from
stored URLs alone and does not know whether a PDF's text was readable, so
it says nothing. `""` — somebody looked and there was nothing to get, and
the model is told.

## Alternatives considered

**Refuse PDFs at the door.** Rejected: it loses a real capability. The
note already tells the model it may use a stored file's URL as a
document's field value, so a reader can attach a PDF to a Sales Invoice
as its file. Refusing PDFs would take that away to close a hole that is
now closed properly.

**Add a parsing pipeline for office formats too.** Rejected: DOCX and
XLSX need their own libraries, and the app's posture is to do one thing
honestly rather than five things hopefully. PDF is the type the site
already accepts and the one readers actually attach.

**Keep sending the bytes as well as the text.** Rejected: it is the
million tokens for nothing. The text is what the model can use.

**Send the text as a separate message part rather than in the note.**
Rejected: the note is where the page context goes, and the attachment's
description belongs with the attachment's address. A second channel
would be a second place to keep in step.

**Store the extracted text on the message row so the history can replay
it.** Rejected for now: it needs another column and another migrate, and
the history saying nothing is honest. It is the natural next step if a
reader reloads a thread and finds the model has forgotten the document.

## Consequences

* A reader who attaches a PDF gets an answer about the document.
* A PDF's bytes no longer reach the provider, so a large attachment
  cannot blow the context.
* A scanned PDF is described as unreadable, in the turn that attached it
  and nowhere else.
* The history claims nothing about a PDF it never looked at — which is
  the bug this got wrong on the first attempt, and the one the review
  caught: `load_messages` rebuilds the note from stored URLs alone, so
  the new "could not be read" sentence fired for every PDF in every
  thread's history.
* The test that would have caught the original gap fails with the
  extraction removed.
* The general lesson: a sentence that is true in one context and false in
another is a sentence that needs to know which context it is in. The
note now does.

## See also

* [ADR-0041](0041-the-attachment-fields-are-named-for-what-they-hold.md) —
  the rename that made "attachment" the app's word for this.
* `albanna/core/attachments.py` — `pdf_text`, `readable_attachments`, and
  the ceiling.
* `albanna/core/messages.py` — `attachment_note`, and the `None` versus
  `""` distinction.
* `docs/FR-2_ASKING.md` — the record that flagged this as blocked.
