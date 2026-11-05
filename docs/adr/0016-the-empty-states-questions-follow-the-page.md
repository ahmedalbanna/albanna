# ADR-0016: The empty state's questions follow the page

Status: **Accepted**
Date: 2026-11-05

## Context

An empty panel has to say something.  The something it says is the first
thing a new reader reads, and it is the app's only chance to explain what
it is for before the reader has committed to typing anything.

The cheap answer is a fixed list: *Which Sales Orders are still open?
What is the total value of open orders? How many customers are there?*
Three questions that are reasonable on a sales site, on any page, forever.

The widget's whole claim is that it knows what the reader is looking at.
An empty panel that offers a question about Sales Orders on an HR page is
a panel that does not, and it says so at the exact moment the reader is
deciding whether to believe it.  The suggestions are the proof of the
claim; a generic list is a disproof of it.

So the suggestions follow the page.  A form gets questions about *that*
document, a list gets questions about the list the reader is looking at,
a report gets questions about the report, and only a page with nothing to
anchor on falls back to the generic set.

Two further things were found while writing this down, and both are
decisions rather than details.

**The suggestions are data-aware.**  The panel asks the server how many
rows the current list holds.  An empty list does not get *How many Issues
are there?* — it gets *Create a Issue*, because the honest answer to
"how many" on an empty list is zero and the useful next question is what
to do about it.

**The generic fallback was the wrong persona.**  The product's persona
was re-cut from a sales rep closing an order to a support agent
(`docs/ROADMAP.md` §7, 2026-10-27), and that section says the empty-state
suggestions became support-shaped.  The Issue-specific sets did.  The
generic fallback — shown on the desk home, the one page with nothing to
anchor on — still asked about Sales Orders and open orders.  It is now
support-shaped, and the reason is written in the code so the next
re-cut does not have to find it again.

## Decision

**The empty state's questions are derived from the page, and the page is
named.**

`examplesFor(context, count, party)` in `examples.mjs` is a pure function
of the page's identity, the list's row count, and the party on a
brand-new document.  It returns one of five sets:

| Page | Questions |
|---|---|
| Issue form | What is the customer asking for? / What has already been done? / What is still open? |
| Other form with a document | Summarise this {doctype} / What is the status of this {doctype}? / What is the total of this {doctype}? |
| New document | Copy this {doctype} from the last one for {party}, or What fields are required for this {doctype}? |
| Issue list | the three above, plus Show my open tickets |
| Other list | Create a {doctype} when the count is zero; otherwise How many / Which are still open / What is the total value |
| Report | Summarise this report / What are the totals? / Which rows stand out? |
| Nothing to anchor on | How many open Issues are there? / Which Issues are still open? / How many customers are there? |

**And the empty state says what it is asking about.**  A form names the
document — *Asking about Issue ISS-0001*.  A list names the list —
*Asking about the Issue list*.  A report names the report.  Only a page
with genuinely nothing to name says nothing.

That last part was the gap.  The context line was derived from the open
*document*, so it appeared on a form and nowhere else — while the panel
was already fetching the list's count and offering list-specific
questions.  The panel knew the page and did not say so, which is the same
disproof of the claim wearing a quieter hat.

**"My" is banned from the generic set.**  The assistant is told the page,
not the reader, so it has no way to know who "my" is: asked *Show my open
tickets*, it answers with every open ticket and calls them the reader's.
The Issue list carries that suggestion anyway, because on a list of
tickets the reader's own are a reasonable guess and the failure is
visible and correctable.  The generic set does not carry it, because
there is nothing there to make the guess reasonable.

## Alternatives considered

**A fixed generic list.**  Rejected: it disproves the widget's central
claim at the moment the reader is evaluating it, and it is the same three
questions on every page forever.

**Describe the suggestions instead of asking them.**  Rejected: a
suggestion the reader has to translate into a question costs more than it
gives.  They are written as questions, in the reader's language, so one
click sends them.

**Ask the server for suggestions per page.**  Rejected: it would put a
model call or a per-doctype configuration table behind the empty state,
which is the first thing a reader sees and therefore the thing that must
not be slow or missing.  The sets are derived in the browser from the
page identity the widget already resolves.

**Keep the sales-shaped generic set.**  Rejected: the persona decision
already retired it, and the set that survived was the one nobody looked
at because it only appears on the page with nothing on it.

## Consequences

* The empty state is the proof of the widget's claim, so the claim is
  only as good as the page resolution behind it.  `context.mjs` resolves
  the page; `examples.mjs` turns it into questions; both are pure and
  tested under node.
* The suggestion logic is a pure function of `(context, count, party)`,
  which is what let it move out of the component and be tested branch by
  branch — see [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md).
* A new DocType gets a reasonable empty state for free, because the
  generic form and list sets are written against the doctype name rather
  than a hardcoded list.
* The Issue-specific sets are the persona made concrete.  If the persona
  changes again, those sets and the generic fallback are the two places
  to look, and the code says so.
* The count is a second request on every page change.  It is one call to
  `count_doctype`, it fails silently to `null`, and a `null` count falls
  back to the ordinary list questions rather than to *Create a*.

## See also

* [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md) — why
  the suggestion logic is a pure function in a module rather than a
  computed in the component.
* `docs/ROADMAP.md` §2 items 2 and 4, and §7 — the persona decision, and
  the "my" problem this ADR's ban comes from.
* `docs/FR-1_DESK_PANEL.md` — FR-1.7, the requirement this decides.
