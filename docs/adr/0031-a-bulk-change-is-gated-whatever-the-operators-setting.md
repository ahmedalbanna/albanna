# ADR-0031: A bulk change is gated whatever the operator's setting

Status: **Accepted**
Date: 2026-11-06

## Context

The approval rail is configurable. `confirm_writes_for(user)` reads a site
setting whose default is `False`, and a per-user policy row may turn it on for
one account or off for one account. With the shipped configuration, writes run
immediately and no card is shown.

That is a reasonable default for a single write. The reader named one document
and asked for one change; they are watching the panel, and the change is
visible the moment it lands.

`bulk_update_doc` is a different shape of action. It changes the same fields on
every document matching a condition — up to two hundred of them — and the
reader described that set rather than naming it. Its schema promised the gate
unconditionally:

> *"The change is proposed first and waits for the reader's approval before it
> runs."*

`create_doc` and `update_doc` make no such promise; their descriptions say what
the tool does. `bulk_update_doc` was the only tool that promised a rail, and
with the default setting it was the one tool whose promise was quietly false —
a change of two hundred documents, approved by nobody.

## Decision

**`bulk_update_doc` is gated unconditionally. Every other write keeps the
operator's setting.**

```python
gated = spec.mutating and (call.name == "bulk_update_doc" or confirm_writes_for(principal.user))
```

The narrowest shape was chosen: a per-tool exception in `_run_tool`'s gate
expression, with a comment saying why this tool is the one. The
`confirm_writes` site default is untouched, so nothing else on the site changes
behaviour.

The justification is the blast radius, and it is a categorical difference
rather than a matter of degree. A single write changes a document the reader
named; a bulk change changes a set the reader described. The reader can see the
one and has to imagine the other, and the card is what turns the imagination
into a count and a list of names.

## Alternatives considered

**Correct the schema's promise instead.** Rejected as the primary fix: it would
make the documentation honest and leave the behaviour as it was, which is the
worst of the two — a reader who read the schema would still be wrong about what
happens. The schema's promise was the *correct* promise; it was the code that
did not keep it.

**Flip the `confirm_writes` site default to `True`.** Rejected: it changes every
write on the site, for every reader, and it is not this requirement's to make.
An operator who has deliberately chosen not to gate single writes should keep
that choice.

**Gate bulk only above some count.** Rejected: the threshold would be arbitrary,
and a change of forty documents the reader did not count is no safer than one of
two hundred. The categorical line is "described by a condition", not "many".

**Leave it to the setting and rely on the reader noticing.** Rejected: that is
the argument for every unguarded destructive action, and the reader cannot
notice two hundred documents changing until afterwards.

## Consequences

* A bulk change always shows a card with the count and the names, whatever the
  operator has configured.
* Every other write is unchanged, including for an operator who has
  deliberately switched the rail off.
* The behaviour change is real and was flagged for the owner: with the shipped
  default, a bulk change that used to run immediately now waits.
* The test that proves it sets the policy to `"never"` — the configuration a
  real reader is most likely to be in. Every other approval test in the class
  sets it to `"always"`, which is why none of them could have caught this: with
  `"always"` everything is gated, so such a test would have passed before the
  change and after it.
* If the owner prefers the old behaviour, the revert is one line — and FR-4.3's
  requirement then needs the schema corrected instead, which is the alternative
  this ADR rejected.

## See also

* [ADR-0032](0032-the-approved-set-is-carried-through-to-the-write.md) — the
  other half of the same card: what the reader counted has to be what runs.
* [ADR-0030](0030-the-read-guard-walks-the-manifest.md) — the guard pattern this
  pass applied to the write surface.
* `albanna/services/chat_service.py` — `_run_tool`, where the gate is decided.
