# ADR-0024: The dictation's last words are merged again, not remembered

Status: **Accepted**
Date: 2026-11-05

## Context

The composer's microphone dictates into the question box.  The reader may
type alongside the dictation — a correction, a second sentence — and that
text is theirs, not the browser's.  `mergeTranscript` exists for exactly
this, and its docstring says so: the text already shown is the anchor,
whatever the reader added after it is kept, and only the spoken part is
replaced.

`onresult` calls it on every result event and emits the result.  `onend`
emitted something else:

```js
session.onresult = (event) => { … lastEmitted = mergeTranscript({…}); emit("update:modelValue", lastEmitted); };
session.onend = () => { … emit("update:modelValue", finalText.trim()); };   // spoken words only
```

`finalText` is the spoken words plus whatever was in the box when the
session *started*.  So a reader who dictated, typed a correction while the
microphone was still open, and then ended the session lost the correction.

The first fix was to emit `lastEmitted` instead — what `onresult` last
produced.  That is right until the reader types *after* the last result
event, and that is not an exotic case: a session ends three ways (the
two-minute limit, a deliberate stop, the browser giving up), and
"dictate, correct, click stop" is the ordinary shape of using it.  The
correction arrives after the last `onresult`, so `lastEmitted` is stale by
then and the correction goes anyway.

The defect survived one fix because both versions treated the merged text
as a *value to remember* rather than a *function to re-evaluate*.

## Decision

**The merge is run again at session end, against the box as it stands.**

```js
emit("update:modelValue", mergeTranscript({
	spoken: finalText,
	current: props.modelValue,
	lastEmitted,
}).trim());
```

`mergeTranscript` already computes the right answer from those three
inputs: it takes the anchor, works out what the reader added after it, and
returns the spoken words with that addition preserved.  Calling it again
costs nothing and cannot go stale, because it reads the box at the moment
it is called.

`voice.test.mjs` grew a case pinning the contract in the shape `onend`
uses it — text typed after the last result event survives the session
ending — and it was proved to fail when the merge's anchor logic is
broken.

## Alternatives considered

**Emit `finalText`.**  This was the original code, and it throws away
everything typed since the session began.  Rejected.

**Emit `lastEmitted`.**  The first fix, and it throws away everything typed
since the last result event.  Rejected — but recorded here, because it is
the kind of fix that looks complete and is not, and the reason it is not
complete is worth more than the fix.

**Track the typed text separately and reassemble at the end.**  Rejected:
it is a second implementation of what `mergeTranscript` already does, and
two implementations of one rule drift.  The module exists precisely so the
rule lives once.

**Emit on every keystroke during the session.**  Rejected: the composer
already holds the reader's text; emitting it back would fight the reader's
own cursor and selection.

**Keep the microphone open until the reader stops typing.**  Rejected: a
microphone left open is one of the things a reader does not expect, and the
session already has a life of its own for that reason.

## Consequences

* A correction typed after the last spoken word survives the session
  ending, by any of the three routes a session can end.
* The merge is called at both ends of the session rather than cached at
  one, which is the same shape as the rest of the module: `readResults` and
  `mergeTranscript` are pure functions of what the browser just said.
* The test that pins it is a test of `mergeTranscript`'s contract in the
  shape `onend` uses, not a test of the component — which is the only way
  it could be tested at all, given the component holds the browser object.
* The general lesson is the one this ADR is really for: when a value is
  derived from inputs that keep changing, re-derive it rather than
  remembering it.  The first fix remembered.

## See also

* [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md) — why
  `voice.mjs` is a pure module with a test beside it, which is what made
  this fixable and testable at all.
* `albanna/public/js/side-chat/voice.mjs` — `mergeTranscript`, and the
  docstring that already described the rule the wiring was breaking.
* `PRIVACY.md` — the disclosure added in the same pass, because the
  browser's speech recognition sends the reader's audio to Google while the
  microphone is open, and the privacy document had never said so.
