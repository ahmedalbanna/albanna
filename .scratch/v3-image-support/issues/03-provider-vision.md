# Ticket: OpenAI provider sends image in vision format

**Blocks:** none
**Blocked by:** 01, 02

## What

`OpenAIProvider` honours `Message.image` when `supports_vision` is True,
emitting the vision content array. When False, the image is dropped and the
chat service adds a "images not supported by this model" notice. `Albanna
Settings` gains `image_support` (Check, default off) and `max_image_size_kb`
(Int, default 2048). The widget options endpoint reports `image_support`.
`Albanna Chat Log` gains `had_image` (Check).

## Acceptance criteria

- A turn with an image produces a vision-shaped payload (domain test).
- A turn with an image and a non-vision provider drops the image and
  reports it.
- An oversized image is refused with a clear error (site test).
- Audit log records `had_image` when an image was sent.
