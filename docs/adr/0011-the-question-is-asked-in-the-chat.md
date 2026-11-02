# ADR-0011: The question is asked in the chat, and the reader answers it in the chat

Status: **Accepted**
Date: 2026-11-02

## Context

The assistant runs out of road in one way only: it needs something the
reader has and it does not — which customer, which item, which of two
ways.  The only way to get it was for the reader to *type* it.

That is a bad way to get it, and it is bad in a way the reader feels.
The names the assistant needs are usually the names it had just looked
up: the twenty-one customers, the twenty-two items.  The reader is asked
to retype, from memory or from a list of their own, something the
assistant was looking at a moment earlier — and the reader who picks the
wrong one is not corrected, because the assistant never learned which
customer the reader meant.

So the question is asked as a question.  The assistant offers the answers
it found, the reader picks one, and the thread carries on.

The request that started this was for "a tool that asks a question and
interacts with the chat as a user interface, where the user chooses the
answer the AI poses, via MCP".  Two of those words carry decisions.

*"A tool"*: the question must reach the model the way everything else
does — as a call it makes, with a schema it fills in.  A question that
arrived by some other road would be a second way for the assistant to
talk, and the app has one.

*"Via MCP"*: the app's tools are in-process today
([ADR-0001](0001-in-process-tools.md)); there is no MCP transport in it,
and the production site is not on the licence allow-list of the MCP
service.  What the app *does* have is a port — `ToolBackend` — and the
docstring on it says that "a second implementation that spoke MCP over
HTTP to a remote server would satisfy the same port, and the chat
service, the authority layer and the model-facing manifest would not
change by a line".  So the question is built as an ordinary tool behind
that port: it travels over MCP unchanged when an MCP backend is plugged
in, and it works today without one.

## Decision

**The question is a tool, and the answer is the reader's next message.**

### 1. The question is a tool

`ask_question` is in the manifest, with the same shape as every other
tool: a name, a description, and a JSON Schema.  The model calls it with
a question and a list of options, each option carrying what the reader
sees (the label) and what the assistant goes on to use (the value).

It is tiered as a **read**, and that is not a dodge: the write rail is
about changes to the site's *business* data — the documents the reader
would have to undo — and a question changes none.  What it does write is
a row of the app's own chat data, the same kind of thing the assistant's
own reply writes.

### 2. The question is a row, not a cache entry

The reader may answer it minutes later, from another tab, tomorrow.  A
record that expires while the reader is thinking has thrown the question
away, and the assistant is left waiting for an answer to a question that
no longer exists.

The approval is different, and it lives in the cache for that reason: it
is bounded by the wait it answers
([ADR-0009](0009-the-turns-clock-covers-the-wait.md),
[ADR-0010](0010-the-card-the-socket-lost.md)).  A question has no
deadline — the reader is not required to answer before the coffee is
cold.

So `Albanna Question` is a DocType: the question, the options, the
reader it was asked of, the thread it was asked in, the turn that asked
it, and the answer when it comes.

### 3. Asking ends the assistant's freedom

Once the reader has been asked, the assistant may only speak.

* The tool calls that came **in the same round** as the question do not
  run.  They are refused with a reason, and the reason reaches the model
  as the tool's result.
* The **next round is given no tools at all**.  The model cannot call a
  write, cannot call a read, cannot call the question tool again: it can
  only say the question in the reader's language.

A question that is asked and then acted on in the same breath is a
question that was never asked.  This is the app's own rule — a write the
reader has not approved does not run ([ADR-0002](0002-authority-and-permissions.md))
— applied to the choice the reader has not made.

### 4. The answer is a new turn

The reader's choice is sent as their next message, and the assistant
continues with the whole thread in view.  No worker is held while the
reader thinks, and the answer does not die with the worker that asked
the question.

The message names the question it answers:

> The answer to “أي عميل تريد؟”: CUST-0002

Two things are in that sentence on purpose.  The **question**, because the
card and the assistant's reply are not in the transcript — without it, an
answer of `CUST-0002` is a string with no meaning attached to it.  And
the **value**, not the label: a customer may be called "أحمد عبدالله"
and be named `CUST-0002`, and the assistant goes on to put one of them
in a document.  The value is the one that goes in the document.

### 5. Only the reader may answer, and the first answer is the answer

The question names the account it was asked of, and the endpoint that
takes the answer refuses anybody else's word for it — the same rule the
write rail uses for an approval, and for the same reason: the answer is
acted on.

A second click on a card whose answer has already been acted on is
refused, not applied.  And an answer the reader was never offered is
refused: it would put a value into the thread that the assistant did not
ask about and the reader did not see.

## Alternatives considered

**The turn waits for the answer, like the approval.**  The reader clicks
and the assistant carries on in the same turn, which is a smoother
story.  It was rejected because it holds a worker slot for as long as the
reader thinks, because the question dies with the worker if the worker
dies, and because the wait would need a window measured in minutes — the
reader is not required to answer before the coffee is cold, and a
question that expires is a question that was thrown away.  The cost of
the choice is one extra turn in the transcript, and the answer is a turn
of its own: the reader's answer is *their* message, in *their* words,
and the ledger records it as one.

**The question asks for free text.**  A reader who wants a customer that
was not on the list has to be able to say so.  They can: the composer is
right there, and a message that is not an answer to a question is simply
the next question.  A question with a text box is a question with a
button that opens a keyboard.

**A separate MCP service for the question.**  It would put the question
on the other side of a network hop, add a licence to the list of things
that must work, and put the app's chat data in a service that does not
know what a conversation is.  The port is where an MCP backend belongs;
the question does not need a service of its own.

**The answer writes the document.**  The reader picks a customer and the
invoice is created.  Rejected: the model knows what the reader meant, and
the write rail is what decides whether a document may be made — and it
asks the reader again, because a choice about a *customer* is not a
choice about *this invoice*.

## Consequences

* The reader chooses a customer, an item, or a field value from the
  candidates the assistant found, instead of typing a name.
* A question the reader ignores stays pending, and its card is still
  there when they come back — because the question is a row and the
  widget fetches the pending questions with the thread.
* The answer is in the transcript as the reader's message, and the
  question's row holds the rest: the options, who answered, and when.
* The assistant cannot act on a guess: the turn that asks ends with the
  question, and the turn that follows starts with the answer.
* `tests/test_turn_payload.py` and `albanna/tests/test_questions.py`
  hold the properties: the payload carries the question, the tools are
  taken away once it is asked, only the question tool may ask, only the
  reader may answer, and the first answer is the answer.

## See also

* [ADR-0001](0001-in-process-tools.md) — the tools are the app's own,
  and the port is where an MCP backend would plug in.
* [ADR-0002](0002-authority-and-permissions.md) — a write the reader
  has not approved does not run.
* [ADR-0009](0009-the-turns-clock-covers-the-wait.md) and
  [ADR-0010](0010-the-card-the-socket-lost.md) — the approval's wait,
  which is bounded, and therefore lives in the cache.
