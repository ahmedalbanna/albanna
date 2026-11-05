# ADR-0034: The write guard walks the manifest

Status: **Accepted**
Date: 2026-11-06

## Context

ADR-0030 recorded the read guard: one test that walks the read tools by name
from the manifest and requires a denied case for each, so a read tool added next
year fails the day it is registered. It was written because the parity suite
tested each hole individually and nothing held the *set* of read operations to
the standard — which is how `get_doctype_meta` came to exist with no permission
check at all.

The write side had the same shape, and the same gap.

`tests/test_authority.py` exercises `_authorize_write` thoroughly, and every
write-tool case in it is `create_doc`. The mechanism is generic — it reads
`spec.write_permission` and calls `can_<permission>` — so the mechanism is
tested. But no test showed `submit_doc` refused for a user without the submit
permission, or `delete_doc` for one without delete. The manifest asserts each
tool's `write_permission` value, which proves the declaration and not the
behaviour.

And three of the seven write tools had no behavioural test at all: `cancel_doc`,
`amend_doc` and `delete_doc` appeared in the suite only as the framework's own
function in cleanup.

## Decision

**One test walks the write tools by name from the manifest, and requires a
denied case for each.**

`albanna/tests/test_write_guard.py` mirrors `test_read_guard.py`: enumerate the
write tools from `TOOL_MANIFEST`, assert every one has an entry in a `DENIED`
map, and call each with a target the caller may not write. A tool that returns
anything other than a refusal fails, with the result in the message.

**The denied cases are built by factories, not static arguments.** A lifecycle
tool needs a document in a particular state — a submitted Sales Order for
`cancel_doc`, a draft for `submit_doc` — and a static document name rots the day
the site's data changes. So the map holds a factory per tool that builds the
refused case at run time. That is the one place this guard is harder than the
read guard's, and the reason is worth stating: a read tool's denied case is a
DocType name, and a write tool's is a document in a state.

## Alternatives considered

**A hand-written list of the write tools.** Rejected: it is a snapshot. It would
have listed the seven tools that existed when it was written, and an eighth
would arrive uncovered. The manifest is the thing that already knows what ships.

**Per-tool tests only.** Rejected: that is what was there. The mechanism was
tested through `create_doc` and three tools had nothing, because a per-tool test
only exists for a tool somebody has already thought about.

**Assert the gate at the authority layer only.** Rejected: the authority layer
is the first gate and the tool is the second, and ADR-0002's whole point is that
both have to hold. A guard that only exercises the first would pass with the
second removed.

**Static denied arguments, for simplicity.** Rejected after consideration: it is
simpler to write and it rots. A test that fails because the site's data changed
is a test somebody disables, and a disabled guard is worse than a maintained one.

## Consequences

* A write tool added without a denied case breaks the suite until one is
  written — the same property the read guard has, and the same reason it earns
  its keep.
* The authority layer's write gate is now exercised for every write permission,
  not only `create`.
* The factories are the one hand-maintained part, and they are the part that
  forces the conversation: a new tool cannot be added silently.
* The guard asserts a refusal, not *which* refusal, because a tool may
  legitimately refuse for more than one reason — and ADR-0033 exists because two
  refusals in one tool had an order that mattered.
* Three tools that had no test now have a denied case each, which is not the
  same as having their happy path tested. ADR-0034's guard says *that* a write
  tool refuses; the lifecycle tests say *how* it behaves.

## See also

* [ADR-0030](0030-the-read-guard-walks-the-manifest.md) — the read guard this
  mirrors, and the hole that produced it.
* [ADR-0002](0002-authority-and-permissions.md) — the two layers, both of which
  have to hold.
* `albanna/tests/test_write_guard.py` — the guard, and the factories that make
  it survive the site's data changing.
