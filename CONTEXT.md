# Context: Albanna

Status: **Accepted**
Last reviewed: 2026-10-29

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
| **tool** | One named operation the model may ask for. Eleven exist. |
| **tool spec** | The manifest entry for a tool: name, description, JSON schema, tier, required roles. The contract the model sees. |
| **manifest** | The eleven tool specs, in `core/tools.py`. Plain data, no code. |
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

There are eleven tools.  The manifest is filtered by the authority layer
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

### 4. A write survives the turn, and a failed write takes nothing else with it

A write that ran is committed before the turn can die.  The service commits
after each successful mutating tool, so a document that was created is
created — even if the model fails afterwards, and even if the worker is
killed at the ten-minute wall.  The user asked for the document; the
assistant's ability to describe it is a separate concern.

The other half of that is the failure.  A rollback is transaction-wide
unless it is given a savepoint, and a transaction-wide rollback in the
middle of a turn undoes *everything* the turn has done so far — including
a document the assistant has already told the reader it created.  So every
write takes a savepoint first, and a failure rolls back to it and no
further.

### 4b. The audit row is written before the turn can die

A turn writes an `Albanna Chat Log` row with status `running` at its start,
commits it, and updates it in place to its terminal status at the end.  A
turn that dies leaves the row as `running`; a scheduled task re-labels
rows older than the turn timeout as `interrupted`.  `usage_summary`
excludes both, so the ledger counts turns that finished.  The per-round
timings are carried inside the existing `tools` field as
`{"calls": [...], "round_ms": [...]}` rather than a new column, so no
DDL is needed on production.

The reaper that does the re-labelling runs every five minutes, and the
cadence is tied to the cutoff it uses — a job that runs less often than
the window it closes leaves the row saying `running` about a turn that
finished by dying.  The tie is asserted in `tests/test_scheduler.py`.

### 4c. The stored answer is corrected when the undo is carried out

The undo took the change back, and the panel said so — while the stored
answer went on saying what the assistant had changed.  A transient notice
is not enough to take a sentence back: the notice goes, the thread stays,
and the answer is what a reader — or the model, on the next turn — finds
there.

So the correction goes where the answer is stored: one sentence, in the
language of the reader who asked for the undo.  A turn with nothing to take
back gets no marker, because a marker on a turn that only read something
would be a new lie.

### 4d. A dead turn names what it wrote

The audit row is the truth about a turn, and it outlives the turn.  So when
a turn dies, the panel reads the row and names the writes in it: the
reader asked *did it happen?*, and the answer is the list.

The rules are narrow on purpose — only a turn that has not finished, only
the reader's own, and only when there is exactly one such turn to mean.  A
reader told about the wrong turn's writes goes looking for a change that
was never made, which is worse than being told nothing.

A write that survives a dead turn has no undo handle in the panel: the
transcript is written at the turn's end, and there was no end.  The
document itself is the way back.

The row is kept up to date **while the turn runs**, not only when it ends.
Its calls used to be written at the end, so a worker killed half-way
through left a row that named nothing — and a turn that wrote a document
and then died was a change the reader was never told about.  The write now
records itself in the same transaction as the change it made.  See
invariant 4e and decision 79.

### 4e. A change the reader confirmed and that never ran is named

The reader's *yes* and the write behind it are two facts, and both have to
outlive the turn that collected them.  The panel's answer to *did it
happen?* has to cover the case where the reader said yes and the change
never happened — a reader who confirmed a change and is told only that the
turn did not finish has no way to know the change is not in the database.

So the approval is written into the turn's audit row **before the reader is
asked**, the reader's answer is written into it **when they answer**, and
the write records itself **in the same transaction as the change it made**.
The row can then say both things — that a change was confirmed, and
whether it ran — and the panel names the confirmed change that did not.

The record holds the document's identity and not the values the model
wanted to write: the ledger is read by operators, and a value the reader
alone may see has no business there.

### 4a. The two writes are different rights

`create_doc` is authorised against Frappe's `create` permission and
`update_doc` against `write`.  A role model that grants one does not
necessarily grant the other, and a refusal has to name the right that is
missing: "creating a Customer is done by these roles" is the wrong
sentence when the assistant was asked to *change* one.

### 5. The site is asserted, never guessed

`site_context.resolve()` is the only place the site is decided, and the
tool adapter checks the Frappe context's site against it before **every**
call.  `sites/currentsite.txt` names the production site on this bench, and
a tool that fell back to it would read and write the wrong database.  See
[ADR-0004](docs/adr/0004-site-resolution.md).

### 6. The acting identity is the session user, never Administrator

The tool adapter sets the session to the requesting user before every call,
so the tool runs under that user's roles and User Permissions.  The
authority layer refuses the call first; the permission engine refuses it
second.  Defence in depth, and both layers are tested.

The tools do not stop there.  Frappe's ORM applies no permission check
when a document is *read* — `frappe.get_doc` hands a document to whoever
asks — so every read asks the permission engine itself, and a document the
caller may not read is refused as a read would have refused it.  The
listing and the count go through `frappe.get_list`, which checks.  The one
answer to "may this account read this document" lives in
`albanna.permissions`, so the tools and the confirmation card cannot
disagree about it.

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

It carries no secret either.  A provider's refusal often quotes the key it
refused, and that message is the turn's error message — so the site's own
keys are taken out of the row before it is written.  The log is read by
operators, exported, and copied off the host.

### 11. The chat and the writes are granted by Frappe, not by the app

The app keeps no list of roles that may chat, and no switch that turns
writes on or off.  Chatting is a read permission on `Albanna Conversation`,
and the write tools appear when the caller holds the corresponding right
(`create` for `create_doc`, `write` for `update_doc`) on at least one
DocType.  Both are answered by Frappe's permission matrix, so the
operator grants the chat the same way they grant anything else on the
site, and the answer cannot drift from what the matrix says.

The two lines of defence are unchanged: a tool the caller may not reach is
never mentioned to the model, and a call that names a DocType the caller
may not write is refused with the roles that could.

One exception, and it is narrow: a row in `Albanna User Policy` may
switch the chat off for one account, or on for one account whose roles
would not carry it.  The matrix is granted by *role*, and a role cannot
say "everyone except this one" — so the matrix cannot answer the one
question a per-account exception is for.  It is an exception to the rule,
not a second rule: one account, one visible row, written by the same
people who own the matrix, and read in the same place the matrix is read
— so the widget and the endpoints cannot disagree about who may chat.
See decision 76.

The shipped matrix names one role, `Albanna User`, and the app does not
widen it for the sake of the site's own administrators: a role is a door
for everybody who holds it.  See decision 78.

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

The services check it as well, because the rows are deleted with direct
SQL and the conversation document is deleted with its permissions ignored.
A check that only the caller remembers is a check that is one refactor away
from gone.

The permission hooks now say the same thing.  They used to let a System
Manager see every conversation in a list view, which contradicted this
decision; they do not any more.  See decision 78.

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

### 36. A turn in flight survives a reload

The worker is working, and the answer is parked in the cache; what a
reload loses is the browser's memory of the stream it was waiting for.
So the stream is written down — in the session's storage, which a reload
keeps and a closed tab does not — and the panel picks the turn up again
when the page comes back.

The entry is per **page**: a turn belongs to the thread of the page it
was asked on, and re-attaching it on another page would put the answer
in the wrong thread.

### 37. The user's own words stay in the conversation

A secret has two lives: the value itself, and every place the value is
*not*.  The API key is the app's one secret, and it had a third life it
should never have had — the **printed form** of the configuration that
holds it.  A dataclass prints itself, so anything that printed the
settings printed the key: a traceback, a `bench execute`, a log line, a
test failure.  An accidental leak is not a smaller leak — it is the same
leak, in a place nobody was looking.

So the configuration's representation is written by hand, and it says
only *that* there is a key.  Not how long it is, not its first few
characters: a mask that reveals the shape of the secret is a mask with
holes in it.


A question is the user's words, and the conversation is where they
belong: a place the user owns and can erase.  Two things used to carry
them out of it.

**The request.** Frappe's request logger appends the request's parsed
parameters to every log record the request emits, so a question that
arrives as a request parameter is copied into the site log — outside the
conversation, where deleting the conversation does not remove it, and
where the text is read by operators and copied off the host.  The
endpoints that take the user's words now redact them before the request
can log anything, and before the access gate can refuse: a refused turn
is exactly the one that ends up in the log with the question in it.

**The job.** A job's arguments are logged too, when the job runs.  So
the question and the page description travel in the cache — where the
answer is parked already — and the job is given the key.  The log holds
a stream id instead of a sentence.

### 38. The list and the report are read for what they show

A list is the reader's page as much as a form is, and the route says
only which list — not the filters on it, not how many rows it shows,
not which columns are in it and not what it is sorted by.  So the list
view is read for those, and a report is read for its name and its
filters, because a report *is* a query with filters on it and the
filters are the question the reader is asking.

And they are read the way the open document is read: **only when the
route agrees that this is one.**  `cur_list` is cleared when the
doctype changes and not otherwise, and `frappe.query_report` is built
and never cleared at all, so on the page the reader walked to they
still hold the page they walked away from.  The route decides; the live
object supplies the details.

What the panel sends is a *description*, and the description is capped
and collapsed before it travels: a list can carry a hundred filters and
a hundred columns, and a value that carries a newline would be two
lines in the block — and the second would look like part of the framing
rather than part of the data.

### 39. The ledger says what it does not know

Every turn writes a row: the model, the tokens, the cost, the duration,
whether it worked.  A ledger is a list of rows, and an operator does not
want a list of rows — they want the month's total, and they want to
know which model and which user it went to.  So the settings page sums
the month, and the sum is a **System Manager's**: a reader who may use
the chat has no business knowing what the site spends on it.

Two numbers in that sum are honest about their limits.

**A cost of zero is not a free turn** when the tokens are not zero: it
is a cost the provider did not report, and the turns like that are
counted apart.  A ledger that shows a zero and says nothing is saying
something the operator would believe.

**The cost is the provider's own** — its currency, its own reckoning —
and not the site's.  A provider that bills in dollars and a site that
keeps its books in riyals are two currencies, and the ledger records
the number the provider sent because that is the number there is.

### 40. The cost in the ledger is the site's own

A provider reports **tokens** — exactly, when it reports them at all — and
money only when its API happens to carry a price.  And that price is in
the *provider's* currency: a price in dollars in a ledger kept in riyals
is a number nobody can read, and a Currency field that holds it says
something false about it.

So the site prices the turn itself.  The operator says what a million
tokens cost *them*, in *their* currency, and the cost in the ledger is
computed from the tokens and that price.  It is an estimate — the
operator's price is an estimate too, and prices move — and it is in the
currency the ledger is for.

**A turn with no price has no *known* cost, not no cost.**  The total is
zero and the turns that have no price are counted apart, because a zero
that reads as "free" is a lie the ledger would tell.

The provider's own number is not thrown away: it is recorded beside the
site's, in its own column, for whoever reconciles the two.

### 41. The providers share one connection

Every call to a provider used to open its own connection: a new socket, a
new TLS handshake, and a connection thrown away as soon as the answer had
been read.  A turn asks the provider several times — once per tool round —
so one turn paid for several handshakes to say the same thing to the same
host.

So the providers share one session, and the session keeps its connections
alive between calls.  The provider sees one connection from this host for
a whole turn instead of one per call.

**The session is per thread, not per process.**  `requests` does not
promise that a session may be used from two threads at once, and a
gunicorn worker runs many requests at the same time.  One session per
thread keeps each thread's connections to itself — and a thread's calls
to the provider, which is what a turn is, are the calls that reuse the
connection.

**The retry policy is unchanged.**  urllib3 discards a connection that
broke and fails the request; with a shared session that can happen where
it could not before, because the provider closed an idle connection and
the client did not notice.  The chat service already retries a transient
provider failure once, on a fresh connection, so the turn recovers — and
the adapter keeps urllib3's default of *no* retries, so a request that
cannot connect still fails at once, as it does now, and a connect timeout
is still one timeout rather than two.

**A streamed response is closed by the generator that owns it.**  A
connection belongs to the pool only once the response is closed, and a
streamed response that is not closed holds its socket — so the next call
opens another one, and the sharing is undone.  The closing cannot be left
to a nested generator either: its `finally` runs when the garbage
collector gets to it, which is not soon enough for a socket that should
be back in the pool now.

### 43. The operator's extra options go in the request

Some providers take options the app knows nothing about — a cache key, a
vendor's own flag.  The operator writes them as JSON, and they are added
to the request body, where the provider reads them.  The app has no field
for them, and it does not need one: they are the provider's, not the
app's.

Two rules, and both of them are about not surprising the operator.

**A value that spells a boolean is a boolean.**  A provider's own
configuration for an OpenAI-compatible endpoint writes `"True"` — a
string — where it means the boolean, and the SDK that reads it parses it
into one.  So the app parses it too.

**The app's own keys win.**  The extra options are *extra*: they fill the
gaps the app has no field for.  What the app has a field for — the
model, the temperature, the token ceiling — is the operator's too, and
was written with a purpose.

And the options are refused at save time when they are not a JSON
object, because a typo in them would otherwise be ignored silently: the
option the operator wanted would simply not be there, with nothing
anywhere saying why.

### 45. An answer that was cut off says so

A provider stops for two reasons: it finished, or it hit the token
ceiling.  The app could not tell the two apart — the reason was never
read — so an answer cut off mid-sentence was stored as a complete answer,
recorded in the ledger as `ok`, and shown to the reader as if it were
finished.

An answer that looks complete and is not is worse than one that says it
was cut, because the reader cannot check what they cannot see.  So the
reason is read (`finish_reason` in the OpenAI-compatible shape,
`stop_reason` in Anthropic's, `done_reason` in Ollama's — the same fact,
three vocabularies, one rule), and it travels with the answer: the panel
says the answer was cut off, and the ledger records the turn as
`truncated` rather than `ok`.

**One place builds the wire shape of a turn.**  A turn reaches the
browser twice over: the endpoint that runs it here and now, and the
worker that runs it there and now.  Both send the same shape, so both
build it from one function — a field that is added to one of them and
forgotten in the other is a field the reader never sees, and the bug is
invisible until someone waits for an answer that was never announced.
That is not a hypothesis: it is how the first version of this went, and
a test now holds the two paths to the same shape.

### 46. A write waits for the reader's approval

A write tool does not commit until the reader has approved it.  The
turn pauses, a card appears in the transcript with a compact summary of
what will happen — "Create Customer: Acme" — and the reader confirms
or cancels.  A refusal or a timeout is reported to the model as a denial,
so it can say so rather than pretend it happened.

The card is in the transcript, not a dialog, so the thread keeps its
place.  The preview says what will change, in the reader's words rather
than the JSON's.

The rail is site-wide by default and per-user on top of it: a policy row
may turn it on for a user who would not otherwise have it, or off for a
user who would.  A blank override inherits the site default — the same
rule the connector used, and for the same reason: a missing override is
the inheritance, not a refusal.

### 47. The reader is shown an error they can read

A provider that answers in anything but Latin-1 — a Chinese error, an em
dash — used to arrive as mojibake, because the error path read the body
before anything said how to decode it, and `requests` decodes a response
with no charset as ISO-8859-1.

That message is what the reader is shown.  An error that is a puzzle is
worse than an error that is dull, because the reader cannot tell whether
the assistant is broken or the message is.

### 42. A write waits for the reader

When the site asks for it, a write does not run until the reader has
approved it.  The turn pauses inside the tool call: the worker emits the
proposed call — the tool, the DocType, the name, the fields that would
change — and then waits, polling a cache key under the reader's own
namespace for up to two minutes.  The browser shows the proposal and
offers **Approve** and **Decline**; clicking either one sets the key, and
the worker reads it and goes on.  A reader who closes the panel, or who
does not answer, gets the timeout, and the turn records the write as not
approved.

The wait is *in the turn*, not beside it.  The worker holds the queue
slot for the whole window, which is why the window is two minutes and not
twenty: a turn that holds a worker for twenty minutes is a turn that has
taken the site's queue hostage.  The alternative — splitting the job at
the approval point and continuing on a second job when the reader
answers — is the design that scales, and it is deliberately not here,
because the messages the continuation needs would have to be carried in
the cache and re-validated, and the cost of getting that wrong is a turn
that resumes in the wrong thread.

A declined or timed-out write is a **refusal**, not a failure.  The tool
returns the refusal to the model with a code of `user_denied`, and the
model is told in the system prompt that such a result is not a tool
failure and must not be retried — it should say what it would have
changed and stop.  The ledger records it as a refusal too, in the tool's
own entry, with no text.

The rail is off by default, and it is turned on per account through an
`Albanna User Policy` row: `always` turns it on for one user, `never`
turns it off for one user, and a blank override inherits the site
default.  A System Manager is not exempt from the policy — the rail is
about the *reader*, and an administrator who writes through the chat is
still a reader.

### 48. A turn belongs to its thread, and the panel waits for the thread it shows

A turn is a background job, and a job outlives the screen that asked for
it.  So the *turn* and the *waiting* are two different things, and the
code keeps them apart: the worker finishes every turn whatever the
browser does, and the browser waits for the turns of the thread it is
showing — one thread at a time, because the reader is reading one
thread.

Three things follow, and each one is a bug that was shipped before the
rule was written down:

*   **A turn that finishes in another thread must not move the panel.**
    The answer lands in its own thread on the server, where it belongs;
    the reader stays where they chose to be.  A panel that jumped back to
    the thread whose turn just ended put every later question in the
    wrong conversation.
*   **Each turn remembers its own address.**  The remembered turns are a
    list keyed by stream id, not a single slot: a second question asked
    in another thread overwrites nothing, and a turn finishing erases
    only its own entry.
*   **Leaving a thread stops the watching, not the work.**  The turn's
    address survives an aborted wait, so coming back picks the turn up
    again, mid-answer if that is where it is.  A wait that is aborted
    forgets nothing: erasing the address there would turn "unwatched"
    into "lost".  The reader is never told a turn was "stopped" when it
    is still running — "stopped" means they asked it to stop, and the
    Stop button only exists on the thread being read.

The turn's phase is the *thread's*: running while the thread shown has a
wait, idle when it has none.  One turn ending while another of the same
thread still runs leaves it running, because the Stop button that
vanished early is a button that stopped nothing.

### 49. The server owns the deadline it tells the reader about

The approval wait is one number, and the server is the side that holds
it.  `settings.confirm_timeout` sets it (clamped to 30–600 seconds, both
at the operator's save and at the read), the worker waits that long, and
the `confirm` event carries it to the browser as `window_seconds`.  The
card counts down from *that*, and stops accepting answers at it.

A countdown computed on the browser's clock against a constant of its
own is a countdown that lies — it tells the reader they have time they
do not have, and the reader decides how long to take by it.  One
deadline, told to both sides.

When it runs out the card says so, in the danger colour, with its
buttons disabled.  A card that stays clickable past its deadline
accepts an answer nobody is reading any more, and the reader who clicks
it gets silence — which reads as the assistant ignoring them.  Silence
at a deadline is the one outcome worse than the deadline.

An approval belongs to the turn that is waiting for it, so the card is
keyed by stream id: two writes waiting in one thread are two cards, a
write proposed while its reader is in another thread is remembered all
the same, and leaving a thread takes its cards with it and brings them
back on return.

### 50. An undo that cannot undo is not offered

Every write the app performs is recorded with the operation that would
reverse it: a created document is undone by deleting it, an updated
document by writing the previous values back, a submitted document by
cancelling it.  The button appears on those turns, and on no others.

Cancel, amend and delete are deliberately absent from that list, and that
is a decision rather than an omission.  A cancelled document is not the
document that was there — its state, its ledger entries and its children
have all moved — and an amended document has been superseded by another
one.  Putting "undo" on those would mean either a promise the app cannot
keep or a promise it keeps by doing something the reader did not agree to.

A button labelled "undo" that quietly does something else is worse than no
button at all, because the reader has already decided what they are
agreeing to.  So the rule is: offer undo exactly where the reversal is
the same operation in the opposite direction, and say nothing where it is
not.

### 51. A picture is a file in the site, and bytes on the wire

An image attached to a question arrives twice.  The bytes travel with the
turn as a data URL, because that is what a vision-capable provider can
read.  The same picture is stored as a Frappe File under `Home/Albanna`
with a hashed name, and its URL is put into the page context so the
assistant can set that picture on a document.

Storing it matters for one reason: a file has an address that outlives
the request that created it, so the picture is still there after a reload
or a cleared cache, and the same picture can be attached to two records
without being uploaded twice.

The upload is narrow on purpose.  Five media types are accepted — PNG,
JPEG, WebP, GIF and PDF — and anything else is rejected rather than
stored under a guessed extension, because a broad accept would happily
file `image/svg+xml` (which executes as HTML) away as a `.bin`.  The file
is private and belongs to the reader, and the right to put it on a
document is Frappe's decision, not ours.

A provider that cannot see images is told so, and the reader is told the
image was dropped rather than the picture travelling silently and
vanishing.

### 52. The reader sees the change before it happens

The approval card carries the diff: the field, the value it holds now,
the value it would hold.  A card that said only "update this document"
asks the reader to approve a change they have not seen, which is a
rubber stamp with a countdown on it.

The diff is a report of *the change that was asked for*, not of everything
that moved: a field the caller did not name is never in it, and a field
whose value did not actually change is never in it.  A diff that carries
the noise of a save is a diff the reader learns to skim, and a diff that
is skimmed is the same as no diff.

### 53. The answer names the records behind it

Under the answer is a line of the documents the tools actually read, each
one a link.  The tool calls were already folded behind a summary line;
this says what was behind them without exposing the raw JSON.

The list is made of names the tools returned, never of names the model
wrote.  A link that the model invented is a link to nothing, and a link
to nothing in a line that exists to be trusted is worse than no line.

### 54. The browser's ear, not the server's

Voice input is the Web Speech API in the reader's own browser.  The
transcript arrives as text and the rest of the app cannot tell it from a
typed question.

The alternative — audio on the server, transcribed by a speech service —
is a second provider, a second bill, a second set of secrets, and a
second place where a customer's voice is stored.  A site that wants
server-side transcription can put it behind the proxy the provider
settings already accept.  What is not acceptable is a feature that only
exists on the deployments that configured it, and the browser's own API
is on every browser that runs the Desk.

### 55. A handoff to a human is a document, not a message

"Ask a human" creates a Frappe Issue carrying the transcript, so a person
can pick the work up with the whole conversation in front of them rather
than with a summary of it.

A document, because a document has an owner, a status, a queue and an
audit trail; a chat message has none of those and is read once.  The
Issue is created as the reader, so Frappe's own permission engine decides
whether they may create one — the app does not get to decide that.

### 56. The tool decides its own undo, not the transcript

A turn can read a document and change a document.  The two look the same
from the outside: both name a document.  The undo used to believe the
transcript, and the transcript said "this turn touched a document", so
the undo could delete a document the turn had only read.

The undo now believes the *tool*.  `create_doc` may be undone by
deleting; `update_doc` and `bulk_update_doc` by writing the old values
back; `submit_doc` by cancelling; and nothing else may be undone at all.
A stored entry that says "delete" but comes from anything else is
refused, so the old bad entries — the ones already in a site's log — are
inert instead of dangerous.

The rule is deliberately narrow: the reversal has to be the same
operation in the opposite direction.  A cancel is not an undo, an amend
is not an undo, and a delete cannot be undone by anything this app
offers — so the reader is not offered a button that cannot be honest.

### 57. A colour that means two things means one thing wrongly

The accent is the fill of the reader's own bubble.  It was also the ink
of a source link.  In the light theme the two are the same colour, so
the shortcut was invisible; in the dark theme the accent is a dark grey
and the links went with it — a dark grey link on a near-black bubble,
which is a link nobody can see.

The same thing happened to the danger red: it is *light* in the dark
theme, and white was the ink on it, so the button that removes a turn
was white on a light red.

So a colour that is a fill gets one variable, and a colour that is ink
gets another: `--albanna-link` is the Desk's own text colour, and
`--albanna-on-danger` is white in the light theme and dark in the dark
one.  A screenshot of the light theme cannot catch this, so a test
asserts it instead.

### 58. A search that finds nothing must say so, and stay editable

The conversation list is searched on the server, so a term that matches
nothing comes back as an empty list.  The drawer could not tell that
apart from a reader who has no conversations at all: it said "no
conversations yet" — a false statement about the reader's own history —
and hid the search box, so the wrong word could only be corrected by
closing the drawer and finding the button again.

The message "no matches" was written and translated all along; it was
simply unreachable, because the branch that showed it also required the
list to be non-empty.

### 59. An undo is spent when it is carried out

The undo button stayed after the undo.  The ticket had changed back, the
panel said "the turn has been undone", and the button still said "you can
take this back" — because nothing had *spent* the undo.  The entry was
still in the message's stored tool calls, and the panel decided for
itself what was undoable by looking at the tool's name.

That last part was the deeper problem.  The panel had its own rule and the
server had its own, so the panel could offer a turn the server would
refuse — a read, a refused write, a cancel, a delete — and could offer a
turn that had already been taken back.

So the rules moved into one place (`albanna.core.undo`), and both sides
read them: the transcript says whether a call may still be taken back, the
live panel is told the same thing when the call ends, and the undo obeys
the same rule when it acts.  The rules did not change — they were the
rules the server already followed but kept to itself.  What changed is
that there is now only one of them.

And an undo that has been carried out is *spent*: its entry is taken out
of the stored tool calls.  The turn has nothing left to take back, so it
is not offered again.  A button that stays after the undo is a promise
the app cannot keep.

### 60. A turn that dies must still say what happened to the write

The live run found a hole that no test could see, because it needs a
provider slow enough to kill a turn.  A turn waited for an approval, the
reader approved, the turn then hit the ten-minute wall — and the
approved write never ran.  No audit row was written either.

So the reader was left with the only question that matters — *did it
happen?* — and no answer at all.  The panel said the turn did not
finish, which is true and useless: the reader had approved a change, and
the change's fate was silence.

This is not a bug in the timeout; it is a bug in the shape of the trust
layer.  The approval gate owns the write, so the gate must end in a
sentence about the write — *it ran*, *it was refused*, *the turn died
before it could run* — and the audit row has to be written before the
turn can die.  Otherwise the app's promise ("you approve, and it
happens") is true only when the model is fast.

### 61. "Ran" has to mean the document exists

The approval test asked the tool whether it had run, and the tool said
yes.  That is the tool's own word — the same sentence a reader would
have believed if the write had quietly failed.

A tool's result is a sentence, and a sentence is not a document.  So
the test now asks the database: the turn says it created
`SINV-0001`, and `SINV-0001` has to be there.  The same principle as
entry 60, seen from the test's side: the thing that must not lie about a
write is the write itself.

### 62. The assistant may not reach past the person it is answering

The app's moat is *governed autonomy with permission parity*.  That is a
claim about a seam, and a claim about a seam is only worth what the tests on
both sides of it are worth.  So the whole app was read against one question
— **can the assistant reach past the person it is answering?** — and six
ways through were found.

*   A creation could arrive **submitted**: `docstatus` in the data.  The
    document was permanent without the submit permission and without the
    hooks a submission runs.
*   A **bulk** change reached past the permission engine to find its
    targets, and skipped the field checks a single change gets — so `owner`
    and `docstatus` were writable there and nowhere else.  Two paths to the
    same write, one of them unguarded, is the shape of every permission bug
    that has ever been found.
*   A **read** handed the model the document in full, including the fields
    hidden from the person at a higher permission level.
*   A **lifecycle action** could act on — and report the state of — a
    document the person may not read, because a write permission is not a
    read permission, and the roles that hold one do not always hold the
    other.
*   A **change** could be made to a document the caller may not read, for
    the same reason.
*   A **private file** belonging to somebody else could be copied into a
    document and published with it, which takes the bytes out of the
    private folder.

The fix is not a list of special cases; it is that each tool has one place
that answers "what does this refuse?", and the single change and the bulk
change get the same answer.  The framework's own fields are refused
everywhere.  A document the caller may not read is refused, as a read would
have refused it, so the refusal does not say whether the document exists or
what state it is in.  And the read check itself moved out of the tools
module into `albanna.permissions`, so there is one answer to "may this
account read this document" rather than two that could disagree.

### 63. A hidden field is removed, not defaulted

Frappe's own API, asked for a document a reader may not read in full,
returns the hidden fields with their *defaults*: a Sales Order read by a
Sales User comes back with `ignore_pricing_rule: 0`.  The framework is
not wrong there — the Desk's form simply never renders the field — but
`0` is a statement about the document, and it is a false one.  A model
that reads `0` will say "pricing rules are not ignored", and the reader
will believe it.

So the app is stricter than the framework on this one point, on purpose: a
field the caller may not read is **removed** from the payload entirely.  A
missing field says "there is no answer here"; a defaulted field says "the
answer is no", and only one of those is true.

### 64. A number offered before a question is asked is still a leak

The empty state asks the server how many documents there are, to decide
whether to offer "create one" rather than "which are still open".  The
answer was `frappe.db.count` — the size of the table, every row, including
the ones the reader may not see.  The docstring said the count went through
Frappe's permission engine.  It did not.

This is the leak in the one place the reader is least suspicious of one: a
number in an empty state, offered before they have asked anything.  The
difference between "you have three invoices" and "there are forty invoices
and three are yours" is the difference between a count and a disclosure.

The count is now the one the list view shows — the same query, so the
permission query conditions, the row-level rules and the ownership
constraint all apply.

### 65. The card is shown to the reader, so it may not describe what the reader may not read

The confirmation card is the one place a write is described *before* it
runs, and it is shown to the reader.  Three things on it were described
without asking whether the reader may read them: the **name** of the
document a change was about, the **values** the model wanted to change (the
model may have read them from the document), and the **before** column of
the diff (the document's own content, read through the ORM, which applies
no permission check at all).  And the bulk card counted the whole table:
"Change 42 Sales Invoices", asked of a reader who may see three of them.

A description that names a document the reader cannot see is a leak with a
confirmation button on it.  So the card says only what the reader may read,
and the read check is the same one the tools use.

### 66. A decision is bound to the write it answers

The approval was a string in a cache key.  Three things followed from that,
and none of them is what an approval is supposed to be.

It was not **bound to a write**.  The endpoint took any request id and any
decision and reported success — "yes" to a question nobody had asked — and
the worker never checked that the write it was about to run was the one the
reader had been shown.  It was not **one-shot**: the docstring said a
second decision left the first in place, and the code overwrote it, so a
reader who changed their mind, or a double click, could turn an approval
into a refusal.  And it did not notice that the **document had moved**: the
reader approved a change to a document as it was when they were asked, and
if it changed while they were deciding, the change landed on top of
somebody else's edit and the approval was an approval of something else.

So the worker now records the pending write before it asks — under the
reader's own namespace, with a fingerprint of the arguments — and the
decision is recorded *against that record*.  A decision naming no pending
write is refused, a second decision on the same write is refused, another
account's decision is not found.  And when the reader approves, the
document's timestamp is checked against the one taken when they were asked:
a document that has moved is not changed.

### 67. The check belongs in the service, not only in the endpoint

The conversation rows are read and deleted with direct SQL, and the
conversation document is deleted with its permissions ignored.  So the
ownership check lived in the endpoint that calls the service, and a caller
that forgot it would delete somebody else's history without any complaint
from the framework.

A check that only the caller remembers is a check that is one refactor away
from gone.  So the ownership check is in the service as well, and the
`force=True` that skipped the framework's own rules is gone.

### 68. A secret in the log is a secret on a hundred laptops

A provider's refusal often quotes the key it refused — "Incorrect API key
provided: sk-…" — and that message is the turn's error message, and the
error message was written into the chat log.  The log is read by
operators, exported, and copied off the host.

So the log is written with the site's own keys taken out of it.  The mask
is the same one the configuration prints, and an empty key changes nothing:
there is nothing to take out, and replacing every character of the text
with the mask would be a different bug.

### 69. The undo's correction belongs in the stored answer

The undo carried the change back and the panel said so.  The stored answer
went on saying what the assistant had changed: *"Priority changed from
Medium to High."*  A reader who reopened the thread tomorrow would read the
old claim as a fact about the document, and so would the model, which is
given the stored transcript on the next turn.

There were two places to put the correction: in the panel's notice, or in
the answer.  The notice is transient by design — it is what the reader sees
while the thread is on screen — and a transient notice cannot correct a
durable claim.  So the correction goes into the answer, as its own
paragraph, in the language of the reader who asked for the undo.

The check for "already corrected" is made against that same sentence, so a
second undo in one session does not stack two markers.  A reader in another
language may add a second marker in their own words: a cosmetic
repetition, which is better than a stale claim.

### 70. The audit row is the truth, but only when it is certainly the reader's turn

A turn that dies used to leave the reader with the only question that
matters — *did it happen?* — and no answer at all.  The panel said the turn
did not finish, which was true and useless: the reader had approved a
change and wanted to know its fate.

The audit row already knows.  A turn writes its row at the start, keeps it
up to date as its tools run, and commits each write as it runs, so a write
in the row is a write that was committed, and a turn that dies leaves its
row behind saying what it did.

So the row is read, and the writes in it are named.  The rules are narrow
on purpose:

- only a turn that **has not finished** — a turn that ended with an answer
  is not the turn the reader is asking about;
- only the **reader's own** turn;
- and only when there is **exactly one** such turn to mean.

That last rule is the one that matters.  A reader told about the wrong
turn's writes goes looking for a change that was never made, and that is
worse than being told nothing at all.  So when the row is not certainly
the reader's turn, the panel says the turn did not finish and stops there.

Which row is the reader's turn is found by the conversation when the
browser knows it, and by the reader's own unfinished turns when it does not
— the first question on a page is asked before the conversation exists, and
the browser only learns its name when the turn ends, which is exactly when
it did not.

### 71. An icon is drawn, not typed

An emoji is a picture of somebody else's instructions, in a font the
browser picks.  It does not take the colour of the text beside it, it does
not sit on the text's baseline, and it cannot be sized.  The paperclip on
the attachment label was the last one in the app.

So the paperclip is drawn like the panel's other icons: the same grid, the
same stroke weight, `currentColor` for the ink, and a label beside it in a
flex row so the icon and the words share a middle line.  The rule is
checked by a test, because a rule that is only in somebody's head is gone
with the next contributor.

### 72. The app states the limitation it cannot fix

The assistant cannot list the customer email threads on this site, and the
reason is not a permission the app forgot to ask for: Frappe scopes
`Communication` to the reader's own `User Email` accounts, and the site's
support mailbox has no `User Email` row.  The role already holds read on
`Communication`; granting it again would change nothing.

The app cannot fix that — it is the framework's rule and the site's setup —
so it does the next best thing: it *says* so, deterministically, in the
tool's own answer, rather than hoping the model notices that the listing
came back empty.  A note that is derived from the site rather than asked
for is true in every language and in every configuration; a request to the
model is a hope.

The same reasoning is why the note names the way out rather than only the
problem: a reader who is told that the mailbox is not attached to the site
can ask somebody to attach it, and a reader who is told only "no
communications" can do nothing at all.

### 73. The answer keeps the document an undone change was made to

An undo that deletes a created document leaves the answer's Sources line
pointing at a document that no longer exists.  A reader who follows the
link finds nothing.

There are two ways to make that go away, and both are worse than the dead
link.  Dropping the document from the sources leaves an answer that says
"a ToDo was created" and names nothing at all.  Naming the document in the
marker — "ToDo X was undone" — is wrong for the other kind of undo, the
one that changes a document back rather than deleting it: there the
document is still there, and it was the *change* that was undone.

So the sources keep the document and the marker keeps its wording, and the
reader is left with the two facts side by side: what was changed, and that
it was taken back.  The link to a document that is gone is the price of an
answer that still says what it did.

This was found by the live run, not by a test: a turn on production
created a ToDo, the ToDo was undone, and the answer kept the link.  The
dead link is visible in the screenshot and deliberate.

### 74. The reaper's cadence is part of what it says

The task that re-labels a dead turn's row was scheduled once a day, and
the row it re-labels stops being true a quarter of an hour after the
turn died.  So the ledger spent up to a day saying `running` about a turn
that had finished by dying — the one thing the ledger exists not to do.

Nothing about that failure is loud.  The job ran, the job succeeded, the
row was eventually relabelled, and the numbers were right the whole time
because `usage_summary` excludes `running` rows whether they are stale or
not.  Only the row's own text was wrong, and only for a while — which is
exactly the class of defect that survives to production.

So the cutoff moved out of the SQL and into a named constant, and the
cadence is now a cron expression that runs every five minutes.  The two
numbers are tied by a test: the gap between two runs of the reaper must
be no longer than the window the reaper closes.  A test that only checked
the cutoff would have passed while the ledger lied for a day, because the
cutoff was never the thing that was wrong.

The scheduling is a cron expression rather than one of the framework's
named buckets because the buckets are `hourly` at best, and an hour of
`running` is still an hour of a lie.  The framework accepts a cron
expression as a key of the `cron` section of `scheduler_events`, so the
cadence can be as fine as the truth needs.

Five minutes rather than ten, because a cron slot does not fire at the
minute it names: the scheduler wakes on its own tick — four minutes by
default — and enqueues whatever is due, so a job fires on the first tick
after its slot.  The real gap is the cron gap plus up to one tick, and
that is the number the test asserts against, because that is the number
the ledger feels.  Ten minutes plus a tick leaves one minute of margin
against a fifteen-minute window; five leaves nine.

### 75. The backup that protects this app's data lives in this app's repository, and it is verified before it is believed

The MCP control-plane backup covers PostgreSQL, Redis and the file-based
secrets, and its own header says plainly that the MariaDB site databases
are not included.  Until 2026-10-29 the only copy of production's data was
a manual dump sitting on the same disk as the database it protected, which
protects against a bad edit and not against the disk.

Two decisions, both about where the truth lives.

**The script is in the repository, not installed on the host.**  The MCP
backup's script lives only in `/usr/local/bin`, which means the version
that runs is the version nobody can read from a commit.  This app's script
is in `scripts/site_backup.sh` and the systemd unit runs *that path*, so
there is one copy of it and no installed copy to drift.  The unit files
live beside it, in `scripts/systemd/`, and are installed with `install`.

**A dump is not good until it has been checked.**  A file that exists is
not a backup, and the checks are the point: the gzip stream is intact,
mysqldump's completion footer is present — a truncated dump is still a
valid gzip stream, so that footer is what catches a cut-short dump — the
site's own tables are in it, and it holds no fewer tables than the last
good dump, because the schema only grows.  A run that fails any of these
exits non-zero and leaves `last_ok` alone.

`last_ok` is the alert, because there is no mail on this host and no
Email Account is configured.  A stale marker is the only signal there is,
so it is written only when every site's artifacts have been verified.

The script's own first run is what found the two defects that are now
impossible by construction: a missing `--with-files`, and the
`zcat dump | grep -q pattern` trap — under `set -o pipefail` that pipeline
reports a *missing* pattern when the pattern is there, because grep exits
early and the producer dies of SIGPIPE.  A test now refuses that shape
anywhere in the script.

### 76. The matrix is the rule; a policy row is the exception for one account

The chat is granted by read permission on `Albanna Conversation`, shipped
as the `Albanna User` role.  That is the right way to grant it, and it is
the answer for every account that has no policy row.

It cannot answer one question.  The matrix is granted by *role*, and a
role cannot say "everyone except this one": a support team that gets the
chat with its role cannot have one person left out of it without
stripping that person's other rights along with it.  Frappe's own answer
— a User Permission — does not fit either, and the reason is in the
framework's code: User Permissions are applied at the *row* level, while
this gate is a doctype-level check (`frappe/permissions.py` consults them
only when a document is in hand).  A User Permission on `Albanna
Conversation` would limit which conversations a person can see, and would
not touch whether they may start one.

So `Albanna User Policy` carries a `Chat access override`: *Site default*
(inherit the matrix), *On* (allow this account whatever the matrix says)
or *Off* (refuse it whatever the matrix says).  It is the same shape as
the `confirm_writes_override` the table already carries, and it is read
by the same kind of reader — one row, one account, inherited by
everyone else.

Three things keep this from becoming a second matrix.

**It is an exception, not a list.**  There is still no list of role names
in this app.  A policy row says nothing about anybody else, and it is
visible in the same place the operator looks for everything else about a
person's access — a table only System Managers can read or write.

**Both layers are read in one place.**  `chat_access()` answers "may this
account chat, and if not, why", and the widget's options and every
endpoint ask it that one question.  A gate the panel and the API read
differently is a gate that fails open somewhere.

**The refusal names the reason that applies.**  A person switched off by
a policy is told that, rather than being pointed at the roles that hold
the right — because the policy outranks the roles, and a refusal that
named them would send the reader to ask for a role that would not open
the chat.  The refusal is still in the reader's own language.

"On" is the half that needs saying out loud.  It lets an account whose
roles would not carry the chat have it anyway — a contractor with a Desk
role of their own, or a person on a team that has not been given the
chat.  It does not grant any tool: what the assistant may read and write
is still answered by that account's own permissions, so a chat opened this
way is a chat that can do only what its holder could do by hand.

### 77. The button waits for the answer

Every reader was given the "Ask Albanna" button on every form, whether or
not they could use it.  For a reader who may not chat the button was
dead: the launcher had not mounted, so there was no panel behind it, and
clicking did nothing at all.  The widget's own gate had already decided
that this reader was not to have a widget — and the button contradicted
it in the only way a reader can see.

The cause was two bundles answering the same question separately.  The
launcher asked the server and decided; the button assumed, and added
itself to every form on every page.  The answer now has one home: the
launcher publishes it (`side-chat/access.mjs`), and the button reads it.

The button *waits* for the answer rather than guessing.  An unanswered
question is not a yes — a button that appears before the answer and
disappears after it is worse than one that never appears — so it is
added when the widget exists for this reader and not before.  And when
the answer lands after the form has already been drawn, the button is
added then: the reader who *may* chat must not be the one left without
it.

The rule is held by a test that fails against the old button and passes
against this one: a reader the gate refuses is given no button, a reader
it allows is given one, and an answer that arrives late still gives them
one.

### 78. The chat has one door, and the shipped matrix is it

The shipped matrix carried two rows: `Albanna User`, and `System Manager`
without `if_owner`.  The second row was a convenience — it meant that
everybody who runs the site could try the chat without anybody having to
grant them anything.

It is also a door for every account on the site that holds that role, and
`System Manager` is one of the most widely held roles on a Frappe site.
The owner of the site asked for the opposite: the chat belongs to the
`Albanna User` role, and a System Manager who wants it takes that role
like anybody else.

So the row is gone, and the shipped matrix names one role.

**The Administrator is inside, by Frappe's rule and not this app's.**
`frappe.permissions.has_permission` returns `True` for the Administrator
before it looks at a single row, and `frappe.get_roles` gives the
Administrator every role on the site — `Albanna User` among them.  An app
that wanted the Administrator out would need a second rule, and decision
11 says there is not one.  The lever for one account is the policy row of
decision 76, which is an exception to the matrix and applies to the
Administrator as it does to anybody else: an `Off` row on that account
refuses the chat, and the refusal says so in its own sentence.

**A Desk edit of the live matrix is not the same thing as this change.**
Editing the permission rows in the Desk survives a `bench migrate` — and
only because a migrate does not touch a DocType whose JSON has not
changed.  The next release that touches `albanna_conversation.json`
writes the rows from the file again, and the edit is undone; a fresh
install writes them from the file too.  So the matrix the app ships is
the matrix that holds, and `tests/test_access_matrix.py` reads that file
and holds it to one role.

**A System Manager is not exempt from the transcript either.**
Decision 13 says a System Manager is not exempt from the ownership
check, and the permission hooks said the opposite for the list view: they
let a System Manager see every conversation on the site.  The two halves
of the app disagreed — the direct-SQL path said no, the list view said
yes.  The hooks now say no as well.  An operator who needs to know what
the chat cost and what was asked for has `Albanna Chat Log`, which is the
audit trail and is not the transcript.

### 79. A confirmation is a durable fact, and it is kept beside the write it answers

The gate holds the write in the cache while the reader decides: a
`pending` record with a two-minute life, polled every tenth of a second.
That is the right place for a **wait** — it is short, it is hot, and it is
nobody else's business.

It is the wrong place for a **fact**.  The reader's answer to "shall this
change happen?" is not a wait; it is the fact that a change was approved,
and it has to outlive the wait that collected it.  The wait ends when the
worker dies — which is exactly when the reader needs the answer most.  A
reader who confirmed a change, and whose worker was killed before the
write ran, was told by the old panel only that the turn did not finish:
true, and useless, because the change they confirmed is not there and
nothing says so.

So the approval and the answer live in the turn's audit row, in the
database, and the cache keeps only the handshake it is good at.  The
worker records what it asked for before the reader is asked; the endpoint
records what the reader said when they answer; the write records itself
in the same transaction as the change it made.

**One writer per fact.**  The endpoint owns the decision — it is what
refuses a second answer — and the worker owns the write.  Neither writes
the other's fact, and the row is *merged* rather than overwritten, so an
answer recorded while the worker was running is not lost by the worker's
next update.

**The merge happens under a lock on the row.**  Without it the worker can
read the row, the endpoint can write the answer into it, and the worker
can then write its own version over the top — and what is lost is the
reader's answer, silently, in the one case where the reader needs it
most.  A lock is cheap here: the row is written by a turn, not by a
request that has to be fast.

**The panel names what never ran.**  A change the reader confirmed and
that never ran is the worst of both — the reader believes it happened, and
it did not — so it is named as exactly that, by document, rather than left
to the reader's imagination.

## What is deliberately not here
* **Document Q&A / retrieval.**  The connector indexes files and embeds them.
  It is a good feature and it is a separate one; v1 has no retrieval.
* **Guest chat.**  A guest has no identity and no history.  It is a
  different product with different rules, not a flag.
* **Conversation management.**  The widget's list, rename, delete, pin,
  server-side title search and Markdown export are in place.  What is not
  there is a way to filter the list by anything but the page it belongs
  to.
* **A second write tool.**  One write, exercised, is worth more than two
  writes, one of them untested.
