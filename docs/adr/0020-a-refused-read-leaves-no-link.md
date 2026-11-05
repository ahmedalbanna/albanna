# ADR-0020: A refused read leaves no link

Status: **Accepted**
Date: 2026-11-05

## Context

An answer's document names become links.  `touched_documents` decides
which ones, and its docstring states the rule it was written for: the
names are the ones the tool was *given* and the ones it *returned*, so
there is no guessing about which words in an answer are document names.

It was given the tool's result — which carries `ok` and `denied` — and for
`get_doc` and the five write tools it took the name from the arguments and
never looked at the outcome:

```python
if call.name == "get_doc":
    add(call.arguments.get("name"))  # added whether the read succeeded or was refused
```

This is reachable whenever the reader may read the *doctype* in general but
not that *row* — a User Permission, an `if_owner` restriction.  The model
calls `get_doc`, Frappe refuses, and the panel still linkifies every
occurrence of that name in the answer and lists it in the Sources line.

So the reader got a link to a document they cannot open, **and learned
that it exists**.  Two failures at once: a control that opens nothing —
the pattern already fixed once for the "Ask Albanna" button — and a small
permission leak, in an app whose stated moat is that the assistant can
never see or do more than the person asking.

The contrast inside the same function is what makes this worth recording.
`list_docs` takes its names from `result.data` — the rows the tool was
actually allowed to return — so that path was always safe.  `create_doc`
derives from `_created_name(call, result)` and `bulk_update_doc` from
`result.data["names"]`, so those were safe too.  Only the
argument-derived adds were exposed, and they were exposed precisely
because the arguments are the one source that does not know whether the
call worked.

## Decision

**A document is linked only when the call that named it succeeded.**

The argument-derived adds are gated on `result.ok and not result.denied`:
`get_doc`, the five write tools, and `amend_doc`'s second add.  The
result-derived adds are unchanged, because they were never able to name a
document the reader was refused.

A refused write names nothing either, and for a second reason worth
stating: a write that was refused — by permission, or because the reader
declined the approval — touched no document, so the Sources line has
nothing to point at.  The old comment said the document a write touched is
a document the answer is about; a refused write touched nothing.

`tests/test_integration.py::TestTouchedDocuments` grew two cases: a refused
read and a refused write each report no document.  Both were proved to fail
when the assertion is inverted.

The answer still *says* the read was refused — `core/prompt.py` already
instructs the model to name what it could not read, and a refused
`get_doc` returns an error the model can relay.  So dropping the link
leaves the reader with an explained name rather than a dangling one, which
is the property the app already ships for Communications.

## Alternatives considered

**Link anyway and let Frappe refuse at the other end.**  Rejected: it is
the "button that opens nothing" pattern, and it tells the reader a
document exists that their permissions say it does not.  Frappe guarding
the form is not a reason to advertise the form.

**Link it, but mark it as unreadable.**  Rejected: it still names the
document, and a marked link is a link the reader will click.  The
information that must not travel is the name.

**Filter the documents by permission before they reach the client.**
Rejected as the mechanism, because it would be a second permission check
in a second place — and the app's rule is that Frappe decides.  The tool
already knows; the fix is to ask it.

**Drop the whole Sources line when any read was refused.**  Rejected: it
would punish the reads that succeeded.  One refused document costs one
link, not the line.

## Consequences

* A refused read leaves no link and no Sources entry, so the answer cannot
  point at a record the reader was refused.
* The names that do appear are all names a successful call produced, which
  is what the docstring always claimed.
* `touched_documents` grew past the complexity threshold and carries a
  `# noqa: C901`.  That is honest — the function now has nine branches —
  but it is the kind of suppression that quietly gets worse, and it is
  worth a look before the next branch is added.
* The gate is `result.ok and not result.denied` rather than `not
  result.denied` alone, because a tool can fail without being refused and
  a failed read named no document either.

## See also

* [ADR-0002](0002-authority-and-permissions.md) — the authority layer, and
  why the app does not keep a second opinion about permissions.
* [ADR-0008](0008-frappe-decides-permissions.md) — Frappe decides, which is
  the rule this fix applies rather than duplicates.
* `albanna/services/chat_service.py` — `touched_documents`, and the
  result-derived paths that were always safe.
