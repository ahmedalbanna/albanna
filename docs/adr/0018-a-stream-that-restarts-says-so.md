# ADR-0018: A stream that restarts says so

Status: **Accepted**
Date: 2026-11-05

## Context

A turn's model call is retried, and it falls back to the next provider in
the chain.  Both restart the *same* round, and both start streaming from
the beginning again.

`ChatService._complete` calls `_stream` fresh on every attempt, and
`_stream` emits a `token` event per delta as it goes.  The client
accumulates: `answer.content += event.text`.  Nothing ever reset it.

So provider A streamed twenty tokens, its connection dropped, the turn
retried A or fell back to B, and B streamed the whole answer from the
beginning.  The reader's bubble held the tail of one attempt followed by
an entire second answer — one confident-looking reply made of two.

The accumulation is *correct* across tool rounds.  Round one's preamble
("let me look that up") and round two's answer are one continuous answer,
and concatenating them is exactly right.  That is what makes this subtle:
the same mechanism that makes the ordinary case work makes the failure
case wrong, and the difference between them — a retry restarts a round, a
new round continues one — is visible only to the server.

The client cannot work it out for itself.  The `status` event carries a
round number, but it is emitted once per round *before* `_complete` runs,
so a retry inside `_complete` is invisible from the client's side.  There
was no signal, and there was no place for the client to derive one.

## Decision

**The server tells the client when a round's stream restarts, and the
client drops what that round had accumulated.**

`_complete` carries a flag across attempts and providers — a fallback is a
second stream of the same round — and emits `{"event": "reset"}` before it
starts streaming again, but only when tokens had already gone out.  The
flag is plumbed into `_stream` as a one-element list the caller owns,
because `_stream` is the only place that knows a token was emitted and
`_complete` is the only place that knows an attempt is starting.

The client remembers where each round began — `answer._roundStart` is set
on the `status` event, before the round's first token — and truncates back
to it on `reset`.  Earlier rounds survive; only the stale tail of the
restarted round goes.

`tests/test_stream_restart.py` drives `_complete` against a provider that
dies mid-stream and asserts the reset arrives, arrives *before* the
replacement tokens, is preceded by the stale tokens that make it
necessary, and is not emitted by a stream that never restarted.  Three of
its four cases fail without the emission.

## Alternatives considered

**Let the client detect the restart from the round number.**  Rejected:
the round number does not change.  `status` is emitted once per round by
the round loop, and a retry happens inside `_complete`, below it.  The
client sees one round and two streams, and has no way to tell which stream
is the live one.

**Buffer the round's text server-side and emit it only at the end.**
Rejected: it defeats streaming, which is the feature.  The reader would
watch a spinner for the whole round and then get the answer at once.

**Reset on every round.**  Rejected: rounds are a genuine continuation.
Round one's preamble and round two's answer are one answer, and dropping
the preamble would leave the reader with an answer that starts mid-thought.

**Reset everything on any provider change.**  Rejected: it has the same
problem as resetting per round, and the client does not know what a
provider is.  The client knows rounds and tokens; the server knows
providers and attempts.  The signal belongs where the knowledge is.

**Have the client discard the answer and start again.**  Rejected: it
would lose the earlier rounds' text, which is real and correct, and it
would show the reader a visible flash of an answer being thrown away.

## Consequences

* A mid-stream failure now shows one answer instead of two concatenated
  ones, and the reader is never shown a reply made of a failed attempt's
  tail.
* The ordinary turn is untouched: no reset is emitted when nothing
  restarted, which the fourth test pins.
* `_complete` grew a mutable flag threaded through `_stream`.  It is the
  price of the server being the only party that knows, and it is contained
  to those two functions.
* `answer._roundStart` is per-message state on a reactive object,
  underscore-prefixed to mark it as the transport's rather than the
  panel's.  It is the one field on a message that exists for the protocol
  rather than for the reader.
* The protocol gained an event.  It is the third progress event after
  `token` and `status`, and it is the first one whose whole job is to say
  "forget what you just saw".

## See also

* [ADR-0003](0003-canonical-message-format.md) — the message format this
  event travels beside, and the rule that the provider adapter is the only
  place that knows a wire format exists.
* `albanna/services/chat_service.py` — `_complete` and `_stream`, where the
  flag lives.
* `albanna/public/js/side-chat/turn.mjs` — the transport, and the comment
  that already said the poll is the guarantee rather than the transport.
