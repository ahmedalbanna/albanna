# Spec: Albanna v3 — Image Support in Chat

**Scope:** the smallest useful slice of "file/image" from the roadmap ideas:
pasting or dropping an image into the composer, sending it to a vision-capable
model, and showing the answer. No file-drop/analyze pipeline, no storage of the
image in the transcript.

**Primary persona:** a warehouse or quality user who photographs a damaged
item and asks "what is this and what should I do?".

**Hero workflow:** paste/drop image → question → model describes/analyzes →
answer (possibly with a suggested action) → audit row.

---

## Problem Statement

Albanna today is text-only. A user who has a photo (a damaged item, a
handwritten note, a printed invoice) cannot ask about it without describing
it in words, which defeats the purpose. The Desk already holds the document
the user is looking at, but the *visual* evidence lives outside it.

## Solution

A minimal, contained image path:

1. The composer accepts one image (paste or drop) and shows a thumbnail
   preview with a remove button.
2. The image is encoded as a base64 data URL and sent with the question.
3. Only providers that support vision (OpenAI-compatible endpoints, and
   only when the model is vision-capable) send it; others fall back to
   text-only with a clear notice.
4. The image is **ephemeral** — it travels with the turn and is never
   stored in `Albanna Message` or the audit log. Only the question text and
   the answer are stored.
5. The assistant's answer can reference the image ("the crack is on the
   left panel") and may suggest a Frappe action (e.g. create a Quality
   Inspection), which still goes through the normal approval gate.

## User Stories

1. As a warehouse user, I want to paste an image into the chat, so that I
   can ask about it without describing it.
2. As a warehouse user, I want to drop an image file onto the composer, so
   that I can attach a photo from my desktop.
3. As a warehouse user, I want a thumbnail preview before sending, so that I
   know which image I am asking about.
4. As a warehouse user, I want to remove the attached image before sending,
   so that I can change my mind.
5. As a warehouse user, I want the assistant to describe what it sees, so
   that I get an answer without typing.
6. As a warehouse user, I want the assistant to suggest a Frappe action
   (e.g. create an Issue), so that the photo becomes a document.
7. As a warehouse user, I want any suggested write to go through the normal
   approval gate, so that a photo never causes an unreviewed change.
8. As a warehouse user, I want a clear notice when my provider or model does
   not support images, so that I am not left wondering why the image was
   ignored.
9. As a warehouse user, I want the image to not be stored, so that the
   transcript stays small and private.
10. As an admin, I want image support to be off by default, so that sites
    that do not want it (or cannot afford the tokens) are not affected.
11. As an admin, I want a size limit on attached images, so that a 50 MB
    photo cannot be sent.
12. As a sales rep, I want to attach a photo on mobile, so that I can ask in
    the field.
13. As a sales rep, I want the panel to stay usable while an image is
    attached, so that I can still type a question.
14. As an auditor, I want the audit log to record that an image was sent
    (a flag, not the image), so that image use is traceable without storing
    the image.

## Implementation Decisions

- **Seam 1 (message format):** `Message` in `albanna.core.messages` gains an
  optional `image` field (a base64 data URL, or None). `to_wire()` emits it in
  the OpenAI vision shape (`content` as a list of `{type: "text"}` and
  `{type: "image_url", image_url: {url: ...}}`) only when present; otherwise
  `content` stays a plain string. Anthropic and Ollama adapters ignore the
  field (text-only) for v3.
- **Seam 2 (turn request):** `TurnRequest` gains an optional `image` field.
  The endpoint accepts it; the chat service passes it to the `Message` it
  builds for the user's question. The image is never persisted by
  `append_messages` (the stored row holds text only).
- **Seam 3 (provider):** only `OpenAIProvider` honours `image`. It checks a
  `supports_vision` flag on `ProviderConfig` (default False, set True for
  known vision models or by an admin setting). When False, the adapter drops
  the image and the chat service adds a notice.
- **Seam 4 (settings):** `Albanna Settings` gains `image_support` (Check,
  default off) and `max_image_size_kb` (Int, default 2048). The widget
  options endpoint reports `image_support`.
- **Seam 5 (audit):** `Albanna Chat Log` gains `had_image` (Check). The chat
  service sets it when an image was sent.
- **No new tool.** The image is context, not a tool call.
- **Size limit:** enforced in the composer (client) and re-checked on the
  server (reject images over `max_image_size_kb`).
- **One image per question** for v3. Multiple images are v4.

## Testing Decisions

- **Good tests** test external behaviour: a question with an image produces a
  vision-shaped payload; a question without an image produces a plain-string
  payload; a non-vision provider drops the image and the turn reports it;
  an oversized image is rejected.
- **Prior art:** `tests/test_tool_manifest.py`, `albanna/tests/test_integration.py`,
  `context.test.mjs`, `markdown.test.mjs`.
- **New tests:**
  - Domain: `Message.to_wire()` emits vision shape iff `image` is set.
  - Domain: `OpenAIProvider._payload` includes the image content array iff
    the message has an image and `supports_vision` is True.
  - Site: a turn with an oversized image is refused with a clear error.
  - Node: the composer shows a thumbnail when an image is attached and
    clears it on remove.
- **Not tested:** visual layout, drag-and-drop behaviour, clipboard paste
  (manual review).

## Out of Scope

- File drop → analyze pipeline (importing CSV/Excel into Frappe).
- Image understanding for non-vision providers.
- Storing the image in the transcript or audit log (only a flag).
- Multiple images per question.
- Image generation.
- OCR / structured extraction.

## Further Notes

- The image is base64-encoded in the browser and sent in the JSON body. For
  large images this is heavy; the size limit keeps it bounded. A future
  version can upload to a Frappe File and pass a URL.
- `supports_vision` is a property of the *model*, not the endpoint. The
  admin setting is a coarse on/off; per-model detection is v4.
- The audit flag (`had_image`) is the only trace of the image, which keeps
  the audit log small and avoids storing user photos.
