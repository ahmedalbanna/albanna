# Ticket: Canonical message format gains an optional image

**Blocks:** 02, 03
**Blocked by:** none

## What

`Message` in `albanna.core.messages` gains an optional `image` field (a
base64 data URL, or None). `to_wire()` emits the OpenAI vision shape
(`content` as a list of `{type: "text"}` and `{type: "image_url"}`) only
when `image` is set; otherwise `content` stays a plain string.

## Acceptance criteria

- `Message.to_wire()` returns vision shape iff `image` is set.
- Existing callers (no image) are unaffected (plain string).
- Anthropic/Ollama adapters ignore the field (text-only).
- Domain test covers both shapes.

## Notes

- Keep `image` out of the stored transcript (`append_messages` stores
  text only).
