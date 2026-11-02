# ADR-0011: The question is asked in the chat, and the reader answers it in the chat

Status: **Accepted**
Date: 2026-11-02

## Context

The assistant runs out of road in one way only: it needs something the
reader has and it does not — which customer, which item, which of two
ways.  The only way to get it was for the reader to *type* it.

That is a bad way to get it, and it is bad in a way the reader feels.
The names the assistant needs are usually the names it had just looked
up: the twelve customers on the production site, the hundred and eleven
items.  The reader is asked to retype, from memory or from a list of
their own, something the assistant was looking at a moment earlier — and
the reader who picks the wrong one is not corrected, because the
assistant never learned which customer the reader meant.

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
button that opens a keyboard.  *(Amended 2026-11-02: the card now carries
its own text box — see the review below. The composer remains where it
was; the reader answering the card need not scroll to it.)*

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
  widget fetches the pending questions with the thread.  Until, that
  is, the reader answers the thread some other way (the cancel rule of
  the review below) or the question reaches its expiry.
* The answer is in the transcript as the reader's message, and the
  question's row holds the rest: the options, who answered, and when.
* The assistant cannot act on a guess: the turn that asks ends with the
  question, and the turn that follows starts with the answer.
* `tests/test_turn_payload.py` and `albanna/tests/test_questions.py`
  hold the properties: the payload carries the question, the tools are
  taken away once it is asked, only the question tool may ask, only the
  reader may answer, and the first answer is the answer.

## Review of 2026-11-02: the card, measured against opencode's

The owner asked for the flow opencode's own question tool has, and for two
decisions above to be verified rather than assumed: whether the question
belongs in storage or in fast memory, and whether "via MCP" still means
something to build. Both came back with the original decision standing, and
the comparison against opencode surfaced three gaps that *were* real. What
follows is what the review found; the code below it implements it.

**Storage, against the use case.** opencode's question lives in the running
session: the tool call blocks the agent until the person answers, the pending
question survives navigating away *because the process is still there*, and it
is gone the moment the session ends. Nothing of it needs storage — the
transcript in memory is the record.

A chat in the browser does not have that process. The turn runs as a
background job on the chat worker, and the reader's request returns before the
job even starts; there is no process alive between the reply they got and the
click they will make. The card they see after a reload, from another tab, or
tomorrow, is drawn by fetching the thread's pending questions from the
*server* — which means the state must be somewhere the server can read.
In-memory is the one thing it cannot be: the pending question would vanish at
the first reload while still pending, and the reader would be answering a
question nobody kept. Turns run as separate jobs, so the *next* turn also
reads its ground from the database, not from any caller's memory.

So the row stays, and it stays for the same reason the messages do: in this
architecture, "ephemeral" and "findable again" are opposites. The approval is
the contrast that proves the rule — it is bounded by the wait it answers, and
the wait is over when the coffee is. A question has no such bound.

**MCP, verified.** The claim the decision rests on — "it travels over MCP
unchanged" — was checked against the code, not asserted. The tool is an
ordinary function behind `ToolBackend`
([ADR-0001](0001-in-process-tools.md)), and the context the backend resolves
carries the conversation the question belongs to; a backend that spoke MCP
would call the same function with the same context. That part of the claim is
true. What "via MCP" cannot give the page is the card: a question served over
MCP is served to some *other* agent, which renders it with whatever UI *it*
has, in that agent's session, not the app's. The app stays in-process on its
own site, because the site is not on the MCP service's licence allow-list. No
MCP work is left to do here; the sentence in the tool docstring describes
compatibility, and it stays.

**And three things opencode had that we did not.**

* **A direct reply aborts the question.** In opencode, a person who types
  instead of answering has *decided* not to answer — the pending tool call is
  aborted and the message takes over. Ours left the question Pending forever
  and its card on the screen: a card offering a choice the thread had already
  moved past. Fixed: the turn that follows a *typed* message cancels the
  thread's pending questions first. The cancellation is recorded — status
  `Cancelled`, not Deleted — so the thread still says a question was asked
  there and whose turn it went unread in.
* **The session ends somewhere.** opencode's question dies with the session; a
  row does not, and a question with no deadline is a card pinned to a thread
  for as long as the site lives. So unanswered questions now expire, by a
  daily job, at a bound the operator sets (`question_expiry_hours`, 24 by
  default). A question older than its bound when the job reaches it is
  cancelled, with the same reasoning the rest of the app's odd timekeeping
  uses: a question nobody could act on forever is not patience, it is
  clutter that lies about the state of the conversation.
* **"Type your own answer" lives on the card.** The alternative above said
  the composer is right there — true, and it was enough, but the reader is
  answering *this* question, and opencode puts the free-text option next to
  the choices rather than one scroll away. The card now carries its own text
  box: what it submits is an ordinary message — the cancel rule above is why
  it works — and the question's card goes when the turn it started ends.

## See also

* [ADR-0001](0001-in-process-tools.md) — the tools are the app's own,
  and the port is where an MCP backend would plug in.
* [ADR-0002](0002-authority-and-permissions.md) — a write the reader
  has not approved does not run.
* [ADR-0009](0009-the-turns-clock-covers-the-wait.md) and
  [ADR-0010](0010-the-card-the-socket-lost.md) — the approval's wait,
  which is bounded, and therefore lives in the cache.
