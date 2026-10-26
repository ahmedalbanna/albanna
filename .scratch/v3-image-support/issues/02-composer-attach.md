# Ticket: Composer accepts one image (paste / drop) with preview

**Blocks:** 03
**Blocked by:** 01

## What

The composer gains an attach button, drag-and-drop, and paste handling for
images. A thumbnail preview with a remove button is shown before sending.
The image is encoded as a base64 data URL and passed to `ask()`.

## Acceptance criteria

- Pasting an image into the composer shows a thumbnail.
- Dropping an image file onto the composer shows a thumbnail.
- The remove button clears the attached image.
- Images over `max_image_size_kb` are rejected with a notice.
- Node test covers thumbnail show/clear.
