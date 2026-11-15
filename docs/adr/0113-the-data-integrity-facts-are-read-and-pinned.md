# ADR-0113: The data integrity facts are read and pinned

Date: 2026-11-15 · Status: accepted · The eleventh NFR batch, after the
S-, R-, SEC- (ADR-0105), U- (ADR-0106), A- (ADR-0107), M- (ADR-0108),
C- (ADR-0109), I- (ADR-0110), D- (ADR-0111) and O-series (ADR-0112);
answers the NFR-DI1–DI5 questions raised against the app's data
integrity.

## What the reading found

Two of the five requirements were exposed and are now fixed; the other
three hold, and two of those hold *because* of a documented design
decision this record keeps.

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| DI1 | messages stored in the order said, sequence enforced | **exposed, fixed** | the order was already by `idx` and every reader honours it (`order by idx asc`, history and position), but the index was allocated read-then-insert: `_next_index` read `max(idx)+1` with no lock and no unique constraint, so two turns queued for one thread — one per open tab — could both walk away with the same index and no order between them.  The allocation now takes the conversation's own row `FOR UPDATE` first, so concurrent appends queue instead of colliding; the same locked read is the existence check, so a thread deleted while its turn ran stores nothing rather than orphan rows.  Delete paths take the same lock first |
| DI2 | ledger cost deterministic | **holds, pinned** | one calculator (`albanna/core/cost.py::cost_of_turn`), a pure function of (input tokens, output tokens, price) — imports no Frappe, `round(..., 6)`, a zero or absent price reads 0.0 rather than a random-looking figure.  It is called at write time only: the ledger stores the number, and nothing recomputes it for display (the panel's `localeNumber` only formats).  Pinned: same arguments give the same value, byte for byte, and the calculator is the only one in the app |
| DI3 | deleting a conversation cascades | **holds with one recorded deviation** | the cascade covers the messages (`delete … where parent = …`), the questions and their options.  The ledger is deliberately **not** deleted: its `conversation` link is nulled and the row kept, because the ledger is the operator's record of what the assistant wrote, and DI4 makes its rows append-only — deleting them because a reader emptied a thread would break exactly that.  The deviation is the resolution: DI3's cascade for the ledger is *unlink, not delete*, which is also what referential integrity wants — no dangling link survives |
| DI4 | audit trail append-only | **holds with two recorded interpretations** | the audit trail is the `Albanna Chat Log` row.  It is updated in place — 'running' at turn start, merged to its final state at close, by three writers under a row lock — and that update is the state machine the interrupted-turn feature reads; the strict reading ("no updates after creation") would remove the very property DI3's ledger retention protects.  The interpretations, both pinned: the *content* only ever accumulates (the `_log` merge reads the row's existing approvals back before overwriting `tools`, so the record of what was confirmed never shrinks), and the desk has no write path at all — permissions grant read only to System Manager, the retention prune in `tasks.py` is the only delete path in the app, and every write is code with `ignore_permissions` |
| DI5 | attachments keep referential integrity | **exposed, fixed both ways** | a message's references are `attachment_urls` (+ the parallel `attachment_texts`) on the child row; the bytes live in private File records the chat stored, attached to no document the reader owns.  Nothing connected the ends: deleting a turn or a thread orphaned the File records and bytes for ever, and deleting a File outside the chat left every row that named it pointing at a dead link.  Now: `release_message_files` follows the deleted rows' addresses and removes the files no surviving row still names (a regeneration's replacement carries the old addresses, so a still-named file is kept), and a `File.on_trash` hook strips the dead address — and the text that travelled beside it, so the parallel lists stay aligned — from the rows that carried it.  Files the chat did not store (private, named `albanna-…`) are never touched by either path |

## The decisions worth keeping

**The two requirements collide, and the ledger wins.**  DI3 asks for
the ledger to cascade; DI4 makes its rows append-only.  Deleting the
ledger with the conversation would satisfy the first by breaking the
second — and the ledger is the one place that can still answer "did
the assistant write this?" after the thread it wrote about is gone.
The resolution is recorded rather than silent: the cascade unlinks the
ledger, and the ADR says so.

**Append-only is held where it matters.**  The row's status moves
running → final, and that movement is load-bearing (the unfinished-turn
feature, the reaper).  What the requirement is really about — an audit
trail nobody can rewrite or erase — is held and pinned: content only
accumulates, the desk cannot write or delete, and the one delete path
is the documented retention prune.

## What is pinned

`tests/test_data_integrity_pins.py`, thirteen walkers and behavioural
tests; three red-checked live (the `FOR UPDATE` removed from the
append → FAILED; a `write: 1` granted on the ledger's doctype →
FAILED; the `on_trash` wire removed from the hooks → FAILED; each
reverted from a saved copy):

- DI1: the append takes the conversation row `FOR UPDATE` before it
  reads `max(idx)`, and the locked read is the existence check;
  `_next_index` still continues the sequence; every history read still
  orders by it.
- DI2: one calculator, pure (no Frappe import), rounded, and
  deterministic — same arguments, same value, byte for byte.
- DI3: the conversation delete unlinks the ledger and does not delete
  from it anywhere; it releases the message files.
- DI4: no role holds write/create/delete/cancel/amend on the Chat Log;
  the retention prune is the only delete path; the `_log` merge reads
  the row's approvals before it overwrites the tools payload.
- DI5: the released files are recognised as the chat's own (private,
  `albanna-` prefix); `delete_turn` releases its files; the `on_trash`
  hook strips the address and the parallel text, and is wired in the
  hooks.
