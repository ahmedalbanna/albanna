# Ticket: "Sources" line under answers

**Blocks:** none
**Blocked by:** none

## What

Render a "Sources" line under each assistant answer listing the documents the
tools actually read (already stored as `message.documents` / `tool.documents`).
Each source is a link using the existing document-link logic.

## Acceptance criteria

- One link per document actually read.
- No line when no documents were read.
- Links open the document (existing `openDocumentFrom` behaviour).
- Survives page reload (data comes from stored tool calls).
- Translation: "Sources".

## Notes

- Pure frontend. No backend, no schema change.
- Add a node test mirroring `context.test.mjs`.
