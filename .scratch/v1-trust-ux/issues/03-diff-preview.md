# Ticket: Diff preview for update_doc in the approval card

**Blocks:** none
**Blocked by:** 02 (optional; can ship independently)

## What

`update_doc` returns a before/after diff of the changed fields; the approval
card renders it before the reader confirms. Diff shape:
`{ fieldname: { before, after } }` for each changed field, only fields in
the user's `data` argument.

## Acceptance criteria

- Diff contains exactly the changed fields with old/new values.
- A refused write returns no diff.
- Child-table fields show nested changes.
- Diff is readable on a phone (stacks old → new).
- Approval card renders the diff above the countdown.

## Notes

- Compute diff in the `update_doc` adapter (before/after `doc.save()`).
- Carry via the `confirm` event (new `diff` field or extend `preview`).
- Add a site test: `update_doc` returns a diff containing the changed field;
  a refused write returns no diff.
- Add a domain test for a pure `diffFields(before, after, requested)`.
