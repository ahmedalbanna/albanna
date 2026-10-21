# Context: Albanna

Status: **Accepted**
Last reviewed: 2026-10-21

> This file is the vocabulary and the invariants.  A word that appears here
> means one thing, everywhere in the app.  A word that does not appear here
> should not be used to describe a concept in Albanna.

## What Albanna is

One Frappe app that puts a chat panel inside the Desk and lets the person
using it ask questions about the site's data — and act on it.

It is the combination of two projects that used to meet over the network:

* **`erpnext_mcp`** — the tool layer. ~500 ERPNext operations implemented as
  plain Python functions, each returning a JSON envelope.  Albanna uses five
  of them, and **implements them itself** (`tools/erpnext.py`), because
  `erpnext-mcp` on PyPI is a *different* project — an earlier release by
  another author — so the version this app needed could never be installed
  by a site that was not handed it by hand.
* **`erpnext_mcp_connector`** — the chat layer. A floating side-chat widget,
  a provider abstraction for Ollama / OpenAI-compatible / Anthropic, and a
  tool-calling loop.

Albanna runs neither as a service, and depends on neither.  See
[ADR-0001](docs/adr/0001-in-process-tools.md).

## The vocabulary

| Term | The one meaning |
|---|---|
| **side chat** | The docked panel in the Desk, and the launcher that opens it. Not a page, not a modal, not a route. |
| **turn** | One question and the work it causes, from the question to the final answer. |
| **round** | One model call inside a turn. A round may contain several tool calls. |
| **tool** | One named operation the model may ask for. Five exist. |
| **tool spec** | The manifest entry for a tool: name, description, JSON schema, tier, required roles. The contract the model sees. |
| **manifest** | The five tool specs, in `core/tools.py`. Plain data, no code. |
| **adapter** | The code that actually runs a tool, or calls a model. One per backend, one per vendor. |
| **principal** | The person a call is made for: their user name, their roles, whether they are a System Manager. |
| **reachability** | Whether a principal may reach a tool at all. Static: does not depend on the arguments. |
| **authorisation** | Whether a principal may make *this* call. Dynamic: depends on the arguments. |
| **visibility** | Which tools the model is told about. The set of reachable tools. |
| **canonical message** | The one message format the app speaks internally. See [ADR-0003](docs/adr/0003-canonical-message-format.md). |
| **provider** | A model endpoint: a kind, a base URL, a model, a key. |
| **chain** | The providers to try in order: the primary, then the fallback. |
| **page identity** | `view|doctype|name` — which page a conversation belongs to. |
| **page context** | The description of the user's screen. Untrusted. |
| **untrusted block** | The delimited region of the system prompt that holds page context, framed as data. |
| **audit row** | One `Albanna Chat Log` row per turn. Counts, timings, cost. No question text, no answer text. |

### Retired words

`policy` meaning "the list of tools a user may call", `profile`,
`grant`, `dormant`, `posture`, `fragment`, `effective policy`, `write-access`,
`access_mode`.  These were the vocabulary of the connector's retired policy
layer; reusing them in Albanna would recreate the ambiguity that layer was
deleted to remove.  Albanna says **reachability** and **authorisation**.

## The layers

```
api/  →  services/  →  {providers/, tools/}  →  core/
```

* `core/` imports the standard library and **nothing else** — not Frappe,
  not `providers/`, not `tools/`.  It is pure domain, and it is where the
  tests that matter live.
* `providers/` and `tools/` both depend on `core/` for the types they speak
  in.  Neither depends on the other, and neither depends on `services/`.
* `services/` is the only place the layers below are joined.
* `api/` is thin.  Everything it needs is already a function in `services/`.

## The invariants

These are the rules the code holds.  Each one is a decision that was
expensive to get wrong.

### 1. The tool set is fixed, and the model only sees what it may use

There are five tools.  The manifest is filtered by the authority layer
*before* the schemas are sent to the model, so a tool the user may not
reach is never mentioned — not mentioned and then refused, **never
mentioned**.  A model that can see a tool it cannot use spends a turn
discovering that.

### 2. A tool failure is not a turn failure

A tool that errors returns its error to the model as the tool's result.
The model can usually fix it: add the filter the report asked for, use the
right fieldname.  The turn only fails when the *model* fails.

### 3. A turn is bounded, and hitting the bound produces a diagnosis

`max_tool_rounds` is a hard ceiling.  Reaching it produces a description of
what the turn was doing — the tool called most often, the last failure, how
many rounds — rather than a silence.  "I could not finish that, and here is
why" is a usable answer.

### 4. A write survives the turn

The tool functions commit their own transaction.  A document that was
created is created, even if the model fails afterwards.  The user asked for
the document; the assistant's ability to describe it is a separate concern.

### 5. The site is asserted, never guessed

`site_context.resolve()` is the only place the site is decided, and the
tool adapter checks the Frappe context's site against it before **every**
call.  `sites/currentsite.txt` names the production site on this bench, and
a tool that fell back to it would read and write the wrong database.  See
[ADR-0004](docs/adr/0004-site-resolution.md).

### 6. The acting identity is the session user, never Administrator

The tool functions default to bypassing Frappe's permission engine, because
the backend used to be the authority and the backend ran as a mapped user.
In-process there is no mapped user, so the adapter sets the backend's own
per-call-user marker before each call.  The tool then applies the
requesting user's roles.  The authority layer refuses the call first; the
permission engine refuses it second.  Defence in depth, and both layers are
tested.

### 7. Page context is data, never instructions

Everything the browser sends is attacker-controlled.  It is rendered into a
delimited block, described as data, and the system prompt says outright that
nothing in it is an instruction.  The delimiters are a convenience; the
defence is the instruction.

### 8. One canonical message format, translated only at the boundary

Every provider adapter translates from the canonical format and back.  No
foreign shape reaches the caller, the stored history, or the next provider
in a chain.  A mixed history breaks a later fallback, and a fallback that
breaks is not a fallback.

### 9. A turn is delivered, or the user is told it was lost

The finished answer is published over socket.io *and* parked in the cache.
The cache copy is the guarantee: a client whose socket died still gets its
answer.  A turn whose worker dies without answering is reported as lost
rather than polled for ever.

### 10. The audit trail holds no question text and no answer text

`Albanna Chat Log` answers "what did the assistant do, and what did it
cost".  The conversation answers "what was said".  Keeping the two apart is
what makes it safe to show the log to a manager.

The one thing the log *does* carry is the **name of a document a write
created**.  That is an identifier, not a statement, and it is what turns
"the assistant called a tool" into "the assistant created
ACC-SINV-2026-00008".

### 11. The write capability is a switch, and it is off by default

While `Allow Writes` is off the write tool is not in the tool set at all.
The model is never told it exists, so there is nothing for it to ask for,
and a call to it by name is refused.  The system prompt's instruction not
to write without being asked is a second line of defence, not the first.

### 12. A turn is bounded, and the bound is a cost control rather than a boundary

The per-minute limit is per user and per surface, so no path is unlimited.
It is read and then written rather than incremented atomically, so two
simultaneous requests can both be let through.  The window is a
millisecond and the consequence is one extra question.  A boundary that
needed to be exact would need an atomic counter, and the cache wrapper
does not offer one.

### 13. A conversation's rows are read with direct SQL, so ownership is checked explicitly

The permission hooks narrow *list views*: they make a conversation of
somebody else's invisible in a list.  They do not help with a name that
arrives in a request, because the rows are read with SQL that never
consults them.

So every endpoint that takes a conversation name checks it against the
caller with `assert_owns`, and so does the chat service when a turn
continues an existing conversation.  A System Manager is *not* exempt
there: an administrator reading somebody else's chat is a different act
from an administrator running the site, and the audit trail should not
contain a conversation nobody asked for.

### 14. The interface follows the reading direction

The widget sits on the **inline end** of the screen — the right in a
left-to-right interface, the left in a right-to-left one — and the Desk
gives up that space rather than having the panel cover it.

The position is expressed as a *logical* side (`inset-inline-end`), not a
physical one, and the reason is mechanical rather than aesthetic: the
build's RTL pass mirrors every `left` and `right` in a stylesheet, so a
physical rule comes out swapped in the RTL sheet, and a widget placed with
one lands on the opposite side from the corner its class names.  A logical
property is left alone by that pass and resolved by the browser, which is
the only thing that knows the direction.

The tool descriptions in the manifest stay in English.  They are
instructions to the model, not to the person, and the model reads them
best in English.

### 15. The assistant is told the boundary before it starts

Every turn's system prompt names the document types the caller's account
may create, and says that creating any other is not possible for it.

Without that line, the assistant discovers the boundary by trying: it
calls the write, is refused, and only then learns the rule — having spent
a dozen calls on the way.  Naming the boundary up front turns "I cannot
create that" from a discovery into a statement, and it costs one query
(milliseconds) rather than a dozen tool calls.

The list is capped, because an account with many roles can create a
thousand document types and the prompt is not the place for a thousand
names.

### 16. A refusal is a fact about the organisation, not a failure of the assistant

The string the model receives when a write is refused names the roles that
*could* do it, and says explicitly that the assistant should state it as a
fact and not apologise for it.  A refusal that reads like the assistant's
own failure makes it apologise, and the reader concludes the tool is
broken.  It is not.

The same applies to a *read* that the framework refuses: the tool's empty
failure is filled in with who can read that DocType.  An empty reason is
the most confusing thing an assistant can be handed — it cannot tell "you
may not read this" from "this does not exist", so it tries again, and
again, and burns its steps on a question that was never going to work.

### 17. A wrong DocType name is answered with the names that exist

"Sales Taxes and Templates" does not exist; "Sales Taxes and Charges
Template" does.  A bare "not found" is a dead end, so the tool looks the
near-misses up and returns them with the error.

The tool set does not grow for this: the answer to "that does not exist"
becomes an answer instead of a wall.

### 18. The ceilings are backstops, not budgets

`max_tool_rounds` is a backstop against a runaway loop, not a budget the
assistant works to.  When it is reached, the assistant is asked to answer
with what it has found — it does not compose an apology about a limit
that is not its own, and the limit is stated as a fact about the question.

### 19. The panel is a frame, and the transcript is what scrolls inside it

The panel's height is fixed.  The app fills it, the transcript takes what
is left and scrolls, and the composer stays pinned to the bottom — visible
at every moment, whatever the length of the answer.

The chain is three links long, and it broke at the second one.  The mount
point the app is mounted into had an auto height, so the app's
`height: 100%` resolved to `auto`, so the transcript had no height to
scroll against, and the panel's `overflow: hidden` cut the answer off
*and* the composer with it.  A long answer was not a long answer; it was
a widget that stopped working, and nothing in the source said so.

The three links: the panel is a fixed-height flex column, the mount point
is a flex child of it, the app is a flex child of the mount point.  Each
has to be, or the height never reaches the transcript.

### 20. The tokens arrive as they are produced

The answer appears in the panel as the model writes it, not when the turn
ends.  This is a promise about the *screen*, not about the server: the
server may take four minutes, and the panel says so the whole time.

The promise is easy to break and hard to see.  A message held in a `ref`
array is a plain object unless it is made reactive, and a plain object
pushed into a reactive array is stored raw — the template reads it
through a proxy, and a mutation of the raw object bypasses that proxy.
The tokens arrive, are appended to an object nobody is watching, and
appear all at once when the turn ends and something else changes.  Every
visible part of the feature worked; only the timing was wrong.

So the messages are reactive *before* they are pushed, and the rule is
the general one: **a value the panel shows as it changes has to be
reactive where it is changed, not only where it is read.**

### 21. The reader is told what the assistant did, in the reader's words

`list_docs` and `run_report` are the model's names for two things, and
they are not the reader's.  A person wants to know that the assistant is
looking something up, not which function it reached for.

So the progress is one line — a sentence, in the reader's language, that
says what is happening now — and the turn's tool calls are folded behind
one line that says what it did.  The names are still there, a click away,
for the reader who wants them; they are simply not the first thing the
reader has to read.

The version before this put a chip on the panel for every call.  Seven
calls meant seven chips and four rows, which said less than one sentence
and took more room than the answer — and their labels were hardcoded
English in an interface that is Arabic half the time.

### 22. A page may hold more than one conversation, and "New" makes one

A conversation belongs to a page, and a page's context is the context
behind every question asked on it — so the page's conversation is the
one a question joins when the panel has no thread to continue.

But a page may hold several, and the panel's "New" button makes one.  It
has to ask the server for it: the server resolves a page's conversation
*by page*, so a "new" conversation that existed only in the browser would
land back in the thread the reader was trying to leave.  The button
would clear the screen, and the assistant would carry on with the old
thread's memory of what had been asked before.

A conversation with no title is named after the first question asked in
it, and only then: a conversation the reader has renamed keeps the name
they gave it.

### 23. The panel's width is the reader's, and the Desk pays for it

The panel can be dragged wider, because the one thing in it that is
genuinely wide is the answer's table.  400px is enough for a sentence
and not enough for four columns of a sales order, and a table the reader
has to scroll sideways *inside* a 400px window is a table nobody reads.

The width is one CSS variable, and both the panel and the Desk's margin
are written against it.  A wider panel takes more of the Desk, which is
what the dock means: the Desk was already giving the space up, and now
it gives up more of it.

The handle is on the panel's *logical* edge — the one that faces the
Desk — because the panel is pinned to one edge of the screen and the
handle is on the other.  A handle on a physical edge would land on the
wrong side of the panel in a right-to-left interface, which is the same
trap as the position itself.

### 24. The panel shows the page's thread, and the model reads the same one

The server resolves a page's conversation *by page*, so the thread the
assistant will answer in is the page's thread.  The panel shows that
thread: a panel that opened empty on a page with a conversation on it
would be telling the reader one thing and the assistant another, and the
reader would not know which of them to believe.

So the panel asks the server what is there when it opens on a page and
when it moves to one.  Asking does not create: a page with no thread is
a page with nothing to show, which is an answer and not a failure.

The reader can still start a new thread on the same page, and the new
one is the page's thread from then on — which is what the server's own
lookup says, and what the assistant reads.

And the panel says which page it is on.  The widget's whole claim is
that it knows what you are looking at, and an empty panel that says
nothing about it leaves the reader wondering whether it does.  With a
document open, the panel names it and the questions it offers are about
*that* document — a reader with a Sales Order open wants to know about
the Sales Order in front of them, not about sales orders in general.

A list is not named, because a list's route is a slug and not a name:
"erpnext/sales-order" is not "Sales Order".  Better to say nothing than
to say a slug.

### 25. The question box and the send button are one thing

A box and a button beside it read as a *form*: something to fill in and
submit.  A chat is not a form.  It is a place you say something, and the
arrow in the corner says "go" rather than "submit".

So the button is inside the field, and it is a circle of a fixed size.
It holds that size when it becomes a stop, so the thing the reader is
about to click does not move under their cursor at the moment the turn
starts.

The field carries the focus ring and the box inside it has none: a ring
around the whole thing says where the reader's words are going, which is
more use than a ring around the text alone.

### 26. The markdown is the answer, and it is rendered as markdown

The renderer is a small subset — headings, emphasis, code, lists, tables,
links, quotes — and the subset is chosen by what an assistant actually
produces.

Two things it gets right that are easy to get wrong:

*   A **nested list** stays nested.  Flattening it loses the structure
    that made the list worth writing.
*   A **wrapped line** belongs to the item it continues.  A line that is
    not an item is the way a sentence wraps, and it belongs *inside* that
    item — the version before this dropped it outside the list, where it
    read as a stray paragraph.

A link is only a link when its scheme is `http`, `https` or `mailto`.
Everything else — `javascript:`, `data:`, a bare path — is left as the
text it was written as, because a link the reader clicks is the one
place the model's output becomes an action rather than a sentence.

### 27. The settings fail loudly, because a quiet failure is worse

Two ways to configure this app used to fail in silence.

**A role name that is not a role** was ignored.  The operator typed
`Sale User` instead of `Sales User`, and the people they had chosen
simply could not chat — with nothing, anywhere, saying that the name was
wrong.  Now the save is refused and the names that are not roles are
named.

**A provider with no base URL** was not one the app would call.  The
check for whether a provider is usable happens *before* the request is
made, and the request is where the default would have been applied — so
a deployment that followed the instructions, with a key and a model and
nothing else, had no provider at all.  The settings now ask the provider
what its default endpoint is, and use it.

And the settings page can **test the provider**: one message, no tools,
the smallest question that means anything.  It costs nothing worth
counting and it proves the three things that are wrong in practice — the
base URL, the model id, and the key.  An operator who has mistyped a
base URL should find that out at the moment they press the button, and
not at the first question in front of a user.

### 28. The answer is a doorway into the Desk

A name in the answer is a link, and it opens the document.

The names that are linked are the ones the **tools** were given — the
document a call read, the documents a listing returned, the document a
call created.  Nothing is guessed from the shape of the text, and a name
the assistant never opened is not a link.  A word that only looks like a
document name is left as a word.

The links are the Desk's own: the same URL the Desk's list view makes,
from the same slug, so a name in an answer opens exactly what a name in a
list opens.

And they are stored with the tool call, so a conversation opened again
links to the same documents.  An answer you read yesterday should still
be a doorway today.

### 29. A table in an answer is data, and data can be taken away

The answer's table is copied as **tab-separated values**, with the header
row first, so that a paste into a spreadsheet lands as a table and not as
a column of text.

The markdown is not data.  A cell that says `**24**` is a cell that says
24, and a spreadsheet that reads `**24**` is reading the emphasis rather
than the number — so the emphasis markers are stripped on the way out.

There are two copy buttons, and they do different things: the icon takes
the answer, and "Copy table" takes the data out of it.  They are not the
same button twice, because a reader should not have to guess which is
which.

### 30. The live line says what is being looked at

"Searching" tells the reader that the assistant is busy.  "Searching
Sales Order" tells the reader that the answer is being assembled against
the thing they are looking at — which is the difference between a chat
that is working and a chat that is working *on your question*.

### 31. The widget hears the Desk, and the Desk says "change"

The Desk is a single-page application, so a navigation does not reload the
page — it changes the route, and the router says so.  It says so with the
event **"change"**.

It does not say so with "route-change".  That event does not exist, and a
listener for an event that does not exist is a listener that never
fires.  The widget listened for one for a long time, and the cost was not
a panel that failed to update: it was a panel that was *right about the
wrong thing*.  The page the widget believed it was on was frozen at the
page it had been opened on, so the assistant was asked about the wrong
page, the answer was filed under the wrong page, and the transcript
showed the wrong conversation — while looking, to the reader, perfectly
correct.

So the name of the Desk's event lives in one place, `page.mjs`, and
`page.test.mjs` holds it to account: the test fires the event the Desk
fires and the widget must respond, and it fires an event the Desk does
not and the widget must not.

### 32. The question is asked about the page the reader is on *now*

The panel keeps the page it is showing, because that is what the reader
sees.  But the page context that goes to the model is read at the moment
the question is asked, not read from that cache.

A cache is a cache and a context is a fact, and a fact is read when it
is needed.  So a route event that was missed costs the panel its label
and not the assistant its question.  The two can disagree; they are not
allowed to *pretend* they are the same thing.

### 33. The route says what the page is, and `cur_frm` does not

The Desk sets `cur_frm` when a form opens and never clears it when the
reader walks away from that form — only a *page* view clears it.  So on
the list the reader walked to, `cur_frm` still points at the form they
walked away from.

A widget that trusts it answers about a page the reader has already
left, and looks perfectly correct while doing it.  So the route is the
authority: it is the Desk's own statement of what is on the screen, and
it is the only statement that is always true.  The open document is
consulted only for the details the route does not carry — the title —
and only when it is the document the route names.

The shape of a page's identity is unchanged by this: a form is
`form|<doctype>|<name>` and everything else is the route itself, so the
conversations already on a site are still found.

### 34. The turn's state is a state machine, and it is written down

The states of a turn are the part of this widget a reader can see being
wrong: a turn that is "running" and has already finished, a stop button
that stops nothing, an error that hides a message.

So they are written down once, in `state.mjs`, as transitions over a
plain object, and the component is a view over it.  There is one phase
rather than a flag and a per-message flag that can disagree; the error
and the notice are separate channels rather than one slot; and the
transitions are tested with no Vue, no browser and no site.

### 35. A turn can be taken out of the reader's own thread

The data a person asked about is theirs to erase, and a question that was
asked wrongly is a thing they should be able to remove rather than scroll
past.  So a turn can be removed from the caller's own conversation.

The `Albanna Message` doctype deliberately has no permissions of its own,
so the only way in is the app's own endpoint — chat access and ownership,
the same two gates every other conversation endpoint has.  A turn is
removed whole: an answer with no question is not a conversation, so
naming either row of the turn removes both.

**A row that can be named is a row that can be addressed.**  The server
tells the browser which rows a turn wrote, and the transcript carries the
name of every stored row.  An index would have been the obvious address
and the wrong one: an index shifts as the conversation grows, and the
transcript is a window of the conversation, not all of it.  A name does
not shift.

### 36. The reader is shown an error they can read

A provider that answers in anything but Latin-1 — a Chinese error, an em
dash — used to arrive as mojibake, because the error path read the body
before anything said how to decode it, and `requests` decodes a response
with no charset as ISO-8859-1.

That message is what the reader is shown.  An error that is a puzzle is
worse than an error that is dull, because the reader cannot tell whether
the assistant is broken or the message is.

## What is deliberately not here

* **Document Q&A / retrieval.**  The connector indexes files and embeds them.
  It is a good feature and it is a separate one; v1 has no retrieval.
* **Guest chat.**  A guest has no identity and no history.  It is a
  different product with different rules, not a flag.
* **Conversation management.**  The widget's list, rename and delete are
  in place.  What is not there is a way to search, filter or export them.
* **A second write tool.**  One write, exercised, is worth more than two
  writes, one of them untested.
