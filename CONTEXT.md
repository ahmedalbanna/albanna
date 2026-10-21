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

## What is deliberately not here

* **Document Q&A / retrieval.**  The connector indexes files and embeds them.
  It is a good feature and it is a separate one; v1 has no retrieval.
* **Guest chat.**  A guest has no identity and no history.  It is a
  different product with different rules, not a flag.
* **Conversation management.**  The widget's list, rename and delete are
  in place.  What is not there is a way to search, filter or export them.
* **A second write tool.**  One write, exercised, is worth more than two
  writes, one of them untested.
