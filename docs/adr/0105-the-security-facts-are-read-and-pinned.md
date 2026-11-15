# ADR-0105: The chat's security facts are read and pinned

Date: 2026-11-15 · Status: accepted · The third NFR batch, after the
S-series (ADR-0101) and the R-series (ADR-0102); answers the NFR-SEC1–SEC12
questions raised against the chat.

## The requirement, and what "verified" means here

Twelve security requirements were named for the chat.  For each one the
mechanism was read before it was believed, and a fact that lives in the
source was then pinned by a test that walks the same source — so the
fact cannot drift silently.  Eleven of the twelve already held; one did
not, and it is the one this ADR changes.

| # | Requirement | Verdict | Where the fact lives |
|---|---|---|---|
| SEC1 | API keys encrypted in the DB | holds | both keys are `Password` fieldtype — ciphertext in `__Auth`, a mask in the column. Pinned: `tests/test_security_pins.py` |
| SEC2 | keys never in logs, errors, console, responses | holds | `mask_secret` in the provider's repr; `_without_secrets` redacts both keys from every audit-log error; the settings API returns no key material. Pinned: `tests/test_secrets.py` |
| SEC3 | every endpoint authenticated | holds | 23 whitelisted endpoints, zero `allow_guest`. Pinned: `tests/test_api_surface.py` (the gate walk) + the guest pin in `tests/test_security_pins.py` |
| SEC4 | permissions validated before executing | holds | `require_chat_access()` on every user-data endpoint, `require_system_manager` on the operator's, per-doctype `has_permission` on the context endpoints — all walked by `tests/test_api_surface.py` |
| SEC5 | site context verified before every tool call | holds | `Backend.call` runs `_assert_site` then `_assert_actor` before anything else (`albanna/tools/backend.py`). Pinned: `albanna/tests/test_integration.py` — "a tool refuses to run against another site" |
| SEC6 | model output escaped before markup | holds | `markdown.js` escapes first and inserts its own tags second; the comment pins the order. Pinned: `markdown.test.mjs` — `<script>`, `<img onerror>`, `javascript:` URLs |
| SEC7 | no privilege escalation through the chat | holds | `authorize()` checks tool roles then per-write doctype permission against Frappe's matrix and fails closed on checker errors; writes run as the caller (ADR-0087). Pinned: `tests/test_authority.py`, `albanna/tests/test_integration.py` |
| SEC8 | conversations scoped to the owner | holds | `assert_owns` at every conversation endpoint and service entry, re-checked server-side. Pinned: `albanna/tests/test_integration.py::TestConversationOwnership` |
| SEC9 | audit trail stores no question/answer text | holds | `Albanna Chat Log` carries metadata only — user, conversation, provider, model, status, rounds, tokens, cost, error class. Pinned: `tests/test_security_pins.py` |
| SEC10 | attachments respect Frappe file permissions | **was exposed, fixed** | see below |
| SEC11 | no code execution from model output | holds | no `eval`/`exec`/dynamic import in shipped Python or panel JS. Pinned: `tests/test_security_pins.py` |
| SEC12 | origin enforced on socket.io | holds | Frappe's realtime middleware requires host == origin, a cookie or authorization header, and validates the site namespace through `get_user_info`; the albanna vhost forwards `Origin`. The panel opens no socket of its own — pinned by `tests/test_security_pins.py` |

## The exposure: the read-back trusted `get_doc`

`load_attached_files` (`albanna/services/attachments.py`) reads a turn's
stored attachments back from disk to hand their bytes to the model.  Its
docstring said the read was "permission-checked twice over, by accident
and by rule: `get_doc` answers to the acting user" — and that is not a
rule.  `frappe.get_doc` runs no permission check; permission is
enforced by the REST layer, by `get_list`, and by explicit calls, none
of which this path goes through.

So a turn whose request named another user's private file URL — a
crafted request, since the browser cannot produce one, but a request
nevertheless — would have carried that file's bytes to the model.  Every
*tool* path that reads a file is guarded by `_may_read_file`
(`albanna/tools/erpnext.py`, `frappe.has_permission("File", "read", doc=…)`,
failing closed); only the read-back was not.

**The fix** is the smallest one that closes the door: the read-back
makes the same check the tools make, with the same helper — a file the
turn's user may not read is skipped, and the turn's note says the
contents could not be read, which is the honesty the tools already
show.  The false sentence in the docstring is replaced by the rule it
should have been.

**The pin** is `albanna/tests/test_attachment_read_guard.py`: the file's
owner has it read back; another user asking for the same URL gets
emptiness.  It was red-checked — with the check disabled the second
test fails, so the pin bites.

## What the walking tests mean

A security fact that lives in source code is a fact that dies by edit:
a field's type changes, a decorator grows an argument, a helper gets
inlined away.  The pins in `tests/test_security_pins.py` are therefore
walkers, not assertions about behaviour — they read the DocType JSON,
the whitelisted endpoints, the shipped Python and the panel modules the
same way the SEC-a reading did, and refuse the drift.  Six facts are
held this way; the behavioural ones (SEC5, SEC6, SEC7, SEC8) were
already held by the site's own tests.

## Consequences

- A turn can no longer read a file its user may not read, no matter how
  the URL reached the request.
- Twelve facts are pinned; a regression in any of them fails a suite
  rather than a future reading.
- SEC12 rests partly on Frappe's middleware (`realtime/middlewares/
  authenticate.js`), which the app does not own — the app's own half
  (no raw sockets in the panel) is pinned, and the framework's half is
  documented here as evidence rather than guarded as code.
