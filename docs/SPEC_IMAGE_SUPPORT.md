# Spec: Albanna v4 — Attachments in Chat

**Scope:** the file path in the chat: attaching a picture or a PDF to a
question, sending it to a model that can read it, and keeping the file on
the site so that the answer can refer to it and the reader can set it on a
document.

**Primary persona:** a warehouse or quality user who photographs a damaged
item and asks "what is this and what should I do?".

**Hero workflow:** attach a file → question → model describes/analyzes →
answer (possibly with a suggested action) → audit row.

---

## What changed since v3

v3 designed this as **one** image, **ephemeral**: it travelled with the turn
and was never stored.  Both decisions have been overtaken, and the code
followed:

- **Several files.** A reader attaching three pictures means three
  pictures, and a turn that carried two and could not read the second must
  not reach the model carrying the first.
- **The file is stored.** A file has an address that outlives the request
  that created it.  Without one, the answer cannot point at the picture,
  and the reader has to attach the same picture a second time to set it on
  a document — the reader doing the app's work twice.

The change is recorded in `CONTEXT.md` invariant 51 and in the
`CHANGELOG.md`.  This document describes what the code does now.

## Problem Statement

Albanna is text-only. A user who has a photo (a damaged item, a
handwritten note, a printed invoice) cannot ask about it without describing
it in words, which defeats the purpose. The Desk already holds the document
the user is looking at, but the *visual* evidence lives outside it.

## Solution

A contained file path:

1. The composer accepts **several** files — from the picker, from a paste,
   or from a drop — and shows each one as a chip with a remove button.
2. Each file is checked against **the site's own rule** before its bytes
   leave the browser: its type must be one the site attaches, and its size
   must be within the site's ceiling.  The site publishes that rule, so the
   browser refuses exactly what the server refuses.
3. Each accepted file is stored as a **private Frappe File** under
   `Home/Albanna`, and gets an address.
4. The bytes travel with the turn as **data URLs**, because that is what a
   vision-capable provider can read.
5. The stored addresses travel with the turn too, so the turn **reuses** the
   file instead of writing the same bytes a second time.
6. A **later** turn is told the addresses in words, and is never handed one
   as an image part: a stored file's address is a path on this site, and a
   vision provider cannot fetch a path it has no way to reach.
7. The assistant's answer can refer to the file ("the crack is on the
   left panel") and may suggest a Frappe action (e.g. create a Quality
   Inspection), which still goes through the normal approval gate.

## User Stories

1. As a warehouse user, I want to paste a picture into the chat, so that I
   can ask about it without describing it.
2. As a warehouse user, I want to drop a file onto the composer, so that I
   can attach a photo from my desktop.
3. As a warehouse user, I want to pick a file from the browser, so that I
   can attach one the reader has somewhere else.
4. As a warehouse user, I want to see what I attached before sending, so
   that I know which file I am asking about.
5. As a warehouse user, I want to remove an attached file before sending,
   so that I can change my mind.
6. As a warehouse user, I want the assistant to describe what it sees, so
   that I get an answer without typing.
7. As a warehouse user, I want the assistant to suggest a Frappe action
   (e.g. create an Issue), so that the photo becomes a document.
8. As a warehouse user, I want any suggested write to go through the normal
   approval gate, so that a photo never causes an unreviewed change.
9. As a warehouse user, I want to be told at once when a file cannot be
   attached, so that I am not left wondering why the upload did nothing.
10. As an admin, I want attachments off by default, so that sites that do
    not want them (or cannot afford the tokens) are not affected.
11. As an admin, I want a size limit on attached files, so that a 50 MB
    photo cannot be sent.
12. As a sales rep, I want to attach a photo on mobile, so that I can ask in
    the field.
13. As a sales rep, I want the panel to stay usable while a file is
    attached, so that I can still type a question.
14. As an auditor, I want the audit log to record that a file was sent
    (a flag, not the bytes), so that file use is traceable without the log
    holding the file.

## Implementation Decisions

- **Seam 1 (the wire):** the browser sends the files in two fields, each one
  string parameter: `image`, the bytes as data URLs, and `image_urls`, the
  addresses they were stored under.  Both are read by one reader in
  `albanna.core.attachments`, which reads a list, a JSON-encoded list and a
  single bare value as the same thing — a field read four ways is a field
  four ways wrong.
- **Seam 2 (the message format):** `Message` in `albanna.core.messages`
  carries `images`, a list of data URLs.  `to_wire()` emits them in the
  OpenAI vision shape (`content` as a list of `{type: "text"}` and
  `{type: "image_url", image_url: {url: ...}}`) only when present;
  otherwise `content` stays a plain string.
- **Seam 3 (the rule):** one function decides whether a file may be
  attached — its type, and its size against the site's ceiling.  The
  browser is *given* the rule by `options()`, and the write enforces it
  again, so a caller that reaches the write directly cannot fill the disk
  with what it likes.
- **Seam 4 (the storage):** files are stored as private Frappe Files under
  `Home/Albanna`, with a hashed name and the extension the type actually
  means.  The file is the reader's, and the right to put it on a document
  is Frappe's decision, not ours.
- **Seam 5 (the settings):** `Albanna Settings` gains `image_support` (Check,
  default off) and `max_image_size_kb` (Int, default 2048).  The setting is
  named for images because images were the only thing that could be
  attached when it was written; it is the site's only ceiling on a file, so
  it is the one that applies to a PDF too.
- **Seam 6 (the audit):** `Albanna Chat Log` gains `had_image` (Check).  The
  chat service sets it when a file was sent.
- **No new tool.** The file is context, not a tool call.
- **The upload is narrow.** Five types are accepted — PNG, JPEG, WebP, GIF
  and PDF.  Anything else is refused rather than stored under a guessed
  extension, because a broad accept would happily file `image/svg+xml`
  (which executes as HTML) away as a `.bin`.
- **A refusal is a reason, not a sentence.**  The rule returns a code, and
  the sentence lives in one table, so the turn, the upload and the browser
  refuse in the same words.

## Testing Decisions

- **Good tests** test external behaviour: a question with a file produces a
  vision-shaped payload; a question without one produces a plain-string
  payload; a file over the ceiling is refused; a file of a type the site
  does not take is refused; a turn that cannot read one of two files is
  refused outright.
- **Prior art:** `tests/test_tool_manifest.py`, `albanna/tests/test_integration.py`,
  `context.test.mjs`, `markdown.test.mjs`.
- **New tests:**
  - Domain: `Message.to_wire()` emits the vision shape iff `images` is set.
  - Domain: the wire's reader reads a list, a JSON list and a bare value
    the same way, and refuses a field that is neither.
  - Domain: the rule names the reason it refused, and the size ceiling is
    enforced with the type.
  - Domain: the browser's rule is tested under plain node, with no Vue.
  - Site: a turn with an oversized file is refused with a clear error, and
    the write refuses a file the rule refuses.
  - Site: a stored file's address reaches the next turn as words and never
    as an image part.
  - Node: the composer's list is written once, with every file that was
    stored.
- **Not tested:** visual layout, drag-and-drop behaviour, clipboard paste
  (manual review).

## Out of Scope

- File drop → analyze pipeline (importing CSV/Excel into Frappe).
- Image understanding for non-vision providers.
- Storing the file's bytes in the transcript or the audit log — only the
  address and a flag.
- Image generation.
- OCR / structured extraction.

## Further Notes

- The bytes are base64-encoded in the browser and travel in the request.
  For large files this is heavy; the ceiling keeps it bounded, and the
  file itself is already on the site by then.
- `supports_vision` is a property of the *model*, not the endpoint. The
  admin setting is a coarse on/off; per-model detection is later work.
- The audit flag (`had_image`) is the only trace of the file in the log,
  which keeps the log small and holds no reader's picture.
