# ADR-0030: The read guard walks the manifest

Status: **Accepted**
Date: 2026-11-05

## Context

`tests/test_parity.py` asks one question — *"can the assistant reach past
the person it is answering?"* — and its docstring names eight holes it
covers. Each test names the hole it covers, *"because a test without a name
is a test nobody reads when it fails."*

It is the right shape, and it had one gap: it tests each hole
*individually*. Nothing held the **set** of read operations to the standard.

That is how `get_doctype_meta` came to exist with no permission check at
all. It was added, it worked, it was tested for what it returned, and nobody
asked whether it refused a caller who may not read — because there was no
test whose job that was. The hole was found by reading the code against the
question, which is how the other eight were found too, and it survived a
suite that had already found eight.

A cross-cutting requirement deserves a cross-cutting guard.

## Decision

**One test walks the read tools by name from the manifest, and requires a
denied case for each.**

`albanna/tests/test_read_guard.py` enumerates
`[spec.name for spec in TOOL_MANIFEST.all() if spec.tier == "read"]`, asserts
that every one of them has an entry in a `DENIED` map, and then calls each
with a target a Sales User may not read. A tool that returns data to that
caller fails, with the data in the message.

The enumeration is from the manifest rather than a hand-written list, and
that is the whole of the decision. A read tool added next year is covered
the day it is registered — and, more usefully, it *fails* the day it is
registered, until somebody writes its denied case. The `DENIED` map is the
one hand-maintained part, and it is the part that forces the conversation:
a new tool cannot be added silently.

`ask_question` is excluded, and the exclusion is commented where it is made:
it is tiered as a read because the write rail is about the site's business
data, and it reads none — it asks the reader a question. It has no target a
caller could be refused for.

## Alternatives considered

**A hand-written list of the read tools.** Rejected: it is a snapshot. It
would have listed the four tools that existed when it was written, and
`get_doctype_meta` would have been covered by luck rather than by rule. The
manifest is the thing that already knows what ships.

**Per-tool tests only.** Rejected: that is what was there. Eight named holes
were covered and the ninth was not, because the ninth was a *missing* check
rather than a broken one, and a per-tool test only exists for a tool somebody
has already thought about.

**Assert the gate at the authority layer.** Rejected: the authority layer
allows read tools unconditionally by design ([ADR-0002](0002-authority-and-permissions.md)),
because it decides about tools and not targets. Asserting there would test a
decision that was made deliberately.

**Scan the source for a permission call.** Rejected: a scan cannot tell a
real check from a decorative one, and this app has both — `may_read` fails
closed and a `has_permission` wrapped in a bare `except: return True` would
pass a scan and refuse nobody. The guard calls the tool and looks at the
answer.

**One test per read tool, each asserting its own refusal.** Rejected as the
*only* mechanism: it is the per-tool shape again, and it lets a new tool
arrive with no test at all. The guard sits beside the per-tool tests rather
than replacing them — the per-tool tests say *how* a tool refuses, the guard
says *that* it does.

## Consequences

* A read tool added without a denied case breaks the suite until one is
  written. That is the point, and it is the only mechanism here that works
  for a tool that does not exist yet.
* The guard was proved against the leak it exists for. With
  `get_doctype_meta`'s gate disabled it fails, and its failure message is
  the Salary Slip's entire field list reaching a Sales User — which is a
  better demonstration of the hole than any comment.
* `DENIED` is hand-maintained and small, and its assertion message names the
  tools that are missing a case, so the failure says what to do.
* The guard asserts a refusal or an empty result, never the data. It does
  not assert *which* refusal, because a tool may legitimately refuse for
  more than one reason — and [ADR-0028](0028-the-permission-check-comes-before-the-hint.md)
  exists because two refusals in one tool had an order that mattered.
* The pattern is the one [ADR-0013](0013-the-front-ends-rules-are-scanned.md)
  established for the front-end's rules: a guard that reads what ships
  rather than a list somebody maintains.

## See also

* [ADR-0013](0013-the-front-ends-rules-are-scanned.md) — the same pattern,
  applied to the front-end's rules, and the reason a scan beats a list.
* [ADR-0027](0027-a-read-tool-is-gated-by-the-doctype-it-names.md) — the hole
  this guard failed on the day it was written.
* `tests/test_parity.py` — the eight named holes, and the question both
  suites ask.
* `albanna/tests/test_read_guard.py` — the guard, and the `DENIED` map that
  makes a new tool fail until it is thought about.
