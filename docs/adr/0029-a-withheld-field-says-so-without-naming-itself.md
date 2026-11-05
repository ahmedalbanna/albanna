# ADR-0029: A withheld field says so without naming itself

Status: **Accepted**
Date: 2026-11-05

## Context

`get_doc` removes the fields a caller may not read. The whole-document path
does it thoroughly, and its comment says why:

> *"Frappe's own API leaves a hidden field in the payload with its default
> value, which is a false statement about the document: the model would
> report that a flag is off when it may well be on. A field the reader may
> not see is not in the answer at all."*

The `fields` path — where the model names the fields it wants — dropped them
too, and said nothing:

```python
data = {field: document.get(field) for field in field_list if field not in hidden}
```

The model asks for `ignore_pricing_rule`, gets a payload without it, and is
told nothing. It cannot distinguish "this field is empty" from "this field
is hidden from you" — so it may report that the flag is off, which is
precisely the false statement the whole-document path was fixed to avoid.

The fix had been applied to one branch of the function and the comment
written as though it covered both. That is the shape of most of the defects
this review found: not a missing rule, but a rule applied to the path
somebody was looking at.

## Decision

**A field withheld from the model is announced in the tool's hints, and the
hint does not name it.**

```python
if any(field in hidden for field in field_list):
    hints.append(
        "one of the fields you asked for is not readable by this account and was not returned."
    )
```

The hint goes in `hints` because that is the channel the tool's answer
carries to the model — the same channel the Communication limitation uses,
and for the same reason: a key the envelope does not read is a statement
nobody hears.

It does not name the field, and that is the load-bearing half of the
decision. `_hidden_fields`' docstring is explicit:

> *"A field at a higher permission level is hidden in the form, and the
> person asking does not know whether it is set. The model must not know
> either — not even by seeing a field that is not there."*

Naming the withheld field would tell the model it exists, which is the thing
the mechanism exists to prevent. So the hint says *that* a field was
withheld and not *which*: the model learns not to report it as empty, and
learns nothing about what it is.

## Alternatives considered

**Name the field in the hint.** Rejected: it is the leak. The model would
learn a field exists that the reader cannot see, which is the whole of what
`_hidden_fields` withholds.

**Say nothing.** This was the behaviour. Rejected: it produces the false
statement the other branch was fixed to avoid, and it does so on the branch
the model uses more often — naming fields is what keeps an answer short.

**Put it in the answer's text.** Rejected: the model writes the answer. A
fact the tool knows and the model must not contradict belongs in the
channel the tool owns, not in prose the model composes.

**Refuse the whole read.** Rejected: the read succeeded for the fields that
were readable. Refusing over one withheld field would punish the reader for
a permission they hold on everything else.

**Return the field with a marker.** Rejected: the marker is the field's name
with extra steps, and a payload that says "this field exists but is hidden"
is a payload that says the field exists.

## Consequences

* The model knows a requested field was withheld, so it does not report it
  as empty or unset.
* The field's name does not travel, in either direction.
* The hint is a plain string rather than a translated one — the only
  untranslated sentence the tool emits. It is a real inconsistency, recorded
  here rather than fixed quietly: the sentence is for the model, not the
  reader, so translating it buys nothing the reader will ever see, and
  adding it to the catalogue would claim a string the interface never shows.
  If a future hint is ever shown to a reader, that is the moment to
  translate this one too.
* The same shape now covers both branches of `get_doc`: the whole document
  drops hidden fields silently because there is nothing the model asked for
  to be missing, and the named-fields path says so because there is.

## See also

* [ADR-0020](0020-a-refused-read-leaves-no-link.md) — the neighbouring
  decision about what a refused read may still say.
* `albanna/tools/erpnext.py` — `get_doc`, `_hidden_fields`, and the two
  branches this ADR is about.
* `tests/test_parity.py:588` — the test for the whole-document path, which
  is what made the `fields` path's silence visible.
