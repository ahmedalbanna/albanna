# Ticket: "Explain this error" button on Frappe error dialogs

**Blocks:** none
**Blocked by:** none

## What

Add a global script (pattern: `albanna-form-button.js`) that hooks Frappe's
error dialog rendering and adds an "Ask Albanna" button. The button opens the
panel with the error text + doctype pre-filled as the first question.

## Acceptance criteria

- Button appears on any Frappe error dialog when chat access holds.
- Button is absent when chat access is denied.
- Clicking it opens the panel and submits the error text as the question.
- Error text and doctype are passed as context (not as a saved conversation).
- Translation: "Explain this error", "Ask Albanna about this error".

## Notes

- Reuse `window.albannaSideChat.open()`.
- Hook `frappe.msgprint` / error dialog rendering, not `cur_frm`.
