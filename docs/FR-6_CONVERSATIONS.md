# FR-6 — Conversations

**Status:** requirements review, closed out by the pass recorded in the
commits that follow this document.  Every claim below names the file and
the line that supports it, so a reader can check the claim rather than
trust it.

**Scope:** the ten functional requirements FR-6.1 … FR-6.10, which
describe the reader's own history: the list of it, the search through
it, the thread that belongs to a page, the turns in it, and the hand-off
to a human.

---

## FR-6.1 — The panel lists the caller's conversations

**Requirement.** The panel lists the conversations the caller has had,
most recent first, and each one carries its title, the page it was
started on, when it was last active, and how many turns it holds.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/api/conversations.py:53` — `list_conversations`, the endpoint.
- `albanna/services/conversation_service.py:512` — the service: the page
  query, and then the per-conversation facts that hang off it.
- `albanna/services/conversation_service.py:558` — the totals, aggregated
  in one query for the whole page and not per row.
- `albanna/services/conversation_service.py:578` — the previews, gathered
  the same way (added this pass).
- `albanna/public/js/side-chat/ConversationDrawer.vue:192` — the drawer's
  title, and `:195` the meta line under it: the page, the time, the
  turns.
- `albanna/api/conversations.py:26` — `PAGE_SIZE`: thirty a page.

**Gaps found.**
- **G1 (fixed this pass).** The preview — the first question of each
  thread — was fetched one conversation at a time, so a page of the
  drawer cost thirty-one queries: one for the page, one for the totals,
  and one for every preview on it.  The totals had been aggregated in
  one query for the whole page, with a comment saying why; the pattern
  had been applied to one half of the function and not to the other.
  The preview is now one query over the messages of the page's
  conversations, taking the lowest-`idx` user row of each, and the
  endpoint's own helper is gone — it had one caller, and that caller was
  the loop that was the problem.
- **G2 (tested this pass).** The query count was held by nothing.
  `albanna/tests/test_integration.py` (`TestTheDrawerListing`) counts the
  queries that read the messages table and asserts that there is one of
  them for the whole page.  It was proved to have teeth: with the old
  per-row fetch it saw six queries for five conversations, and it sees
  one now.

**Blocked.** Nothing.

---

## FR-6.2 — A conversation can be reopened, and its transcript is read in windows

**Requirement.** A conversation in the list can be opened, and what comes
back is its transcript.  A long thread is read in windows rather than
all at once, and the reader is told whether there is more behind the
window.

**Status.** Shipped.

**Evidence.**
- `albanna/api/conversations.py:76` — `open_conversation`, the endpoint.
- `albanna/api/conversations.py:34` — `TRANSCRIPT_WINDOW`: fifty messages.
- `albanna/services/conversation_service.py:310` — `load_transcript`,
  which bounds the window **in the query** rather than reading the
  thread and slicing it in Python.
- `albanna/services/conversation_service.py:418` — `transcript_window`,
  which says how many messages the conversation holds and whether there
  are more behind the window.
- Tested: the window is the newest messages, the older page is the one
  below the index, every message carries the index it is stored at, the
  window says how many the conversation holds, and an empty conversation
  has nothing behind it.

**Gaps found.** None.  The window was bounded in the query before this
review, and the tests for it were already there.

**Blocked.** Nothing.

---

## FR-6.3 — A conversation can be renamed

**Requirement.** A conversation can be given a title of the reader's
choosing, and the title is the one the drawer shows.

**Status.** Shipped.

**Evidence.**
- `albanna/api/conversations.py:185` — `rename_conversation`, the
  endpoint: chat access, ownership, and a title that is not empty.
- `albanna/services/conversation_service.py:789` — the service, which
  checks ownership itself and not only in the endpoint, because the row
  is written with direct SQL and that consults no permission at all.
- `albanna/public/js/side-chat/ConversationDrawer.vue:103` —
  `commitRename`, which refuses an empty title and does not send a
  rename that would not change anything.
- Tested: another user may not rename it, and a renamed conversation
  keeps the name it was given — the first question does not rename it
  again.

**Gaps found.** None.

**Blocked.** Nothing.

---

## FR-6.4 — A conversation can be deleted

**Requirement.** A conversation can be deleted, and it goes whole: the
thread, the questions asked in it, and the messages under it.

**Status.** Shipped.

**Evidence.**
- `albanna/api/conversations.py:398` — `delete_conversation`, the
  endpoint.
- `albanna/services/conversation_service.py:806` — the service: the
  messages, then the questions and their options, then the document.
  The ledger row survives and loses its link, because the audit trail is
  the operator's and the chat is the reader's — and because a link to a
  thread that is being deleted stops the thread from being deleted at
  all.
- `albanna/public/js/side-chat/SideChatApp.vue:2179` — the drawer asks
  before it deletes, because one click is not a decision.
- Tested: another user may not delete it, and a thread that has a turn
  in the ledger can be deleted.

**Gaps found.** None in this pass.  The ledger's link was the defect
that stopped the button working on every click, and it was closed
before this review.

**Blocked.** Nothing.

---

## FR-6.5 — "New" starts a real new thread

**Requirement.** The panel's "New" button starts a new conversation on
the page the reader is on.  It is a second thread on that page, not a
cleared panel, and the first question asked in it names it.

**Status.** Shipped.

**Evidence.**
- `albanna/api/conversations.py:160` — `new_conversation`, the endpoint.
- `albanna/services/conversation_service.py:89` — the service: a second
  conversation on the same page, with the same context behind it and
  none of the previous thread's questions in it.
- `albanna/services/conversation_service.py:130` — `name_after_question`:
  the first question names the thread, and only the placeholder is
  replaced, so a conversation the reader has renamed keeps its name.
- `albanna/albanna/doctype/albanna_conversation/albanna_conversation.py:21`
  — `before_insert`, which puts the placeholder title there for a
  conversation with no title of its own.
- Tested: "New" makes a second conversation on the same page, it belongs
  to the caller, the thread the button leaves is untouched, a question
  carrying the new id joins the new thread, and the first question names
  an untitled conversation.

**Gaps found.** None.

**Blocked.** Nothing.

---

## FR-6.6 — The list is searched by title, server-side

**Requirement.** The list can be searched, and the search finds a
conversation by its title or by the page it was started on.  It runs on
the server, so it reaches conversations the panel has not loaded.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/api/conversations.py:53` — the endpoint takes the term and
  passes it down.
- `albanna/services/conversation_service.py:512` — the service's search,
  in SQL.
- `albanna/services/conversation_service.py:490` — `_like_pattern`, which
  escapes the term before it is wrapped (added this pass).
- `albanna/services/conversation_service.py:59` — `LIKE_ESCAPE`, the
  character that does the escaping.
- `albanna/public/js/side-chat/SideChatApp.vue:1912` — `showHistory`, and
  `:1935` `onHistorySearch`, which waits for the reader to stop typing.
- Tested: a search that matches one title returns that one; a search
  that matches nothing returns an empty list; a search reaches a
  conversation the panel has not loaded — the target is the *oldest* of
  thirty-one, so the first page cannot carry it; a search for `%`
  returns nothing; a search for `_` returns nothing; and a title that
  *holds* a wildcard is still found by it.

**Gaps found.**
- **G1 (fixed this pass).** The search narrowed the list with a SQL
  `LIKE`, and the term was wrapped in wildcards without being escaped.
  So `%` and `_` — the two characters a LIKE pattern gives a meaning to,
  and both of them ordinary characters in a title — were read as
  wildcards.  A reader who typed "50%" or "Q3_forecast" got every
  conversation they had, with no way to tell that this was not what they
  asked for.  This was confirmed empirically before it was fixed: a
  search for `%` returned every conversation the reader had, and a
  search for `_` returned the same, while a search for a term with no
  wildcard in it returned the one it meant.  The term is now escaped
  before it is wrapped, and the query names the character that does the
  escaping rather than leaving it to the server's default — a rule that
  lives in a default is a rule the code does not state, and the default
  is not the same on every database.  The escape character is the one
  MySQL and MariaDB already use for LIKE, and the one Frappe's own
  query builder uses, so the rule here is the rule the framework
  applies.  The value is a bound parameter, so the backslash never
  passes through the SQL string parser — the one place where a
  backslash means something else.
- **G2 (tested this pass).** The search had no test at all.  The six
  above are in `albanna/tests/test_integration.py`
  (`TestTheConversationSearch`), and the two wildcard tests were red
  before the fix and green after it.

**Closed in the pass that followed.**  The search now reads the title as
the *display* title: the sentinel is replaced by its translation before
the LIKE runs, so a reader who searches for the words the drawer shows
them finds the thread.  On an English site the translation is the
sentinel and the query is what it always was.  The question "what is a
thread with no title called" already had an answer in the system —
whatever the drawer shows — so this was a translation nobody wired up
rather than a product decision.  See ADR-0049.

---

## FR-6.7 — A conversation belongs to the page it was started on

**Requirement.** A conversation belongs to a page: the same question
asked on the Sales Order list and on the Customer form are two different
threads, because the context behind them is different.  Opening the
panel on a page the reader has used before shows the thread that page
already has.

**Status.** Shipped.

**Evidence.**
- `albanna/services/conversation_service.py:112` — `conversation_for_page`,
  which finds the page's thread and creates nothing.
- `albanna/services/conversation_service.py:69` — `ensure_conversation`,
  which finds it or makes it.
- `albanna/api/conversations.py:117` — the endpoint, which answers with
  an empty thread rather than an error when the page has none.
- Tested: the page's thread is the one the panel shows, a page with no
  thread has nothing to show, asking what is there does not create a
  thread, and the newest thread on a page is the one shown.

**Gaps found.** None.

**Blocked.** Nothing.

---

## FR-6.8 — A conversation belongs to the user who started it

**Requirement.** A conversation is private to the person who started it.
Nobody else may open it, rename it, delete it, or hand it over, and the
list shows only the caller's own conversations.

**Status.** Shipped.

**Evidence.**
- `albanna/services/conversation_service.py:659` — `assert_owns`, the
  explicit check.  It is here and not only in the endpoints because the
  rows are read with direct SQL, which consults no permission at all.
- `albanna/services/conversation_service.py:880` —
  `get_permission_query_conditions`, and `:896` `has_permission`: the
  list views and the document question, answered the same way.
- `albanna/albanna/doctype/albanna_conversation/albanna_conversation.py:29`
  — the owner cannot be changed after the insert.
- Tested: another user may not open, rename or delete it; the service
  itself refuses it, so a caller that forgot the check would not delete
  somebody else's history; and the list shows only the caller's own.

**Gaps found.** None.

**Blocked.** Nothing.

---

## FR-6.9 — A turn can be taken back

**Requirement.** A reader can remove a turn from their own thread: the
question asked and the answer that followed it go together, because an
answer with no question is not a conversation.

**Status.** Shipped.

**Evidence.**
- `albanna/api/conversations.py:223` — `delete_turn`, the endpoint, which
  brings the transcript back with it because a deletion moves everything
  after it.
- `albanna/services/conversation_service.py:687` — the service: either
  row of the turn may be named, and the partner is found by the index.
- Tested: the turn is the question and the answer it brought, naming the
  answer removes the question too, the turn that is left is still a whole
  thread, another user may not remove a turn, and a message that is not
  there is refused.

**Gaps found.** None.

**Blocked.** Nothing.

---

## FR-6.10 — A conversation can be handed to a human, with the full transcript

**Requirement.** A conversation can be handed to a person: a Frappe
Issue is created carrying the transcript, so that somebody can pick the
thread up with the whole of it.  The Issue is created as the reader, so
Frappe's own permission engine applies to it.

**Status.** Shipped after this pass.

**Evidence.**
- `albanna/api/conversations.py:272` — `escalate_conversation`: chat
  access, ownership, a subject drawn from the conversation's title, and
  the Issue raised by the caller.
- `albanna/api/conversations.py:322` — `_tool_lines`, which says what the
  assistant did (added this pass).
- `albanna/tests/test_escalate.py` — the seven properties of the
  hand-off (added this pass).
- `tests/test_api_surface.py` — the guard that reads the panel's calls
  out of the front-end and checks each one against the server's own
  source for the decorator that makes it reachable.

**Gaps found.**
- **G1 (tested this pass).** The endpoint had never been exercised by a
  test.  Not the ownership refusal, not the Issue's content, not the
  empty-conversation case.  That is not a small thing, and the reason is
  in this repository's own history: the decorator that made
  `delete_conversation` reachable became the decorator of
  `escalate_conversation` when the escalate feature was added, and the
  button failed on every click — silently, behind a sentence about the
  request.  Nothing caught it, because a test that calls a function
  directly does not go through the whitelist: the function works, and
  the *route* to it does not exist.  The guard that catches that class
  of bug now reads the front-end's calls against the server's source,
  but a guard says the route exists and says nothing about what the
  route does when it is called.  So the endpoint is now called, as a
  person, on a site with a real permission engine — because the whole
  point of the feature is that the Issue is created as the caller, so
  that Frappe's own rules apply to it.  A test that ran the hand-off as
  Administrator would have proved nothing about the thing that matters.
  The seven properties are: the hand-off carries the thread and takes
  its subject from the title; the Issue is raised by the caller and not
  by Administrator; a thread with nothing in it still escalates; another
  reader's conversation is refused before an Issue is made; the tool
  calls appear; a refused call is marked as refused; and a call with no
  summary is not rendered as an empty bullet.
- **G2 (fixed this pass).** The Issue carried the questions and the
  answers and nothing else, so a human picking the conversation up was
  not told that the assistant had read a document or changed one.  They
  would have had to re-run the conversation to find out what it touched,
  which is the one thing the hand-off was supposed to save them from.
  Each tool call is now a line under the answer that made it, carrying
  the summary the transcript already stores — the summary is written for
  a human, and it is the informative version: "Read Sales Order
  'SAL-ORD-00042'", not a count of calls.  The tool's own name is not on
  the line, because `get_doc` is the model's name for the call and not
  the reader's, and the summary already says what was read and what was
  changed.  A call with no summary is skipped rather than rendered as an
  empty bullet, and a refused call is marked, because a refusal and a
  failure read alike and they are different facts: a refusal says the
  *account* may not do it, which is the difference between "the
  assistant did not find it" and "the assistant was not allowed to
  look".

**Closed in the pass that followed.**  The site now publishes whether
this reader may escalate — read from the same permission checker the
authority layer uses for every write tool — and the button is drawn for
them.  The question "who may escalate" already had an answer in the
system: whoever Frappe lets create an Issue.  What was missing was not a
decision but the check that reads it.  See ADR-0048.

**And "my open tickets" is answerable.**  The same pass gave `list_docs`
an `assigned_to` filter the tool resolves against the site's
assignments, because the reader was named in the prompt already and
nothing turned "mine" into a condition.  See ADR-0051.

---

## Found on the way, and not part of any requirement

**The site suite was not runnable twice.** A test in
`albanna/tests/test_parity.py` made a User Permission, and a later test
in the same class committed — so the row outlived the transaction, and
the *next* run of the suite found it already there and refused to make
a second one ("User permission already exists").  The suite passed on a
clean site and failed on the second run, which is a gate that stops
being a gate.  The permission is now taken away when the test that made
it ends.  It is recorded here rather than in a requirement because it
belongs to none of them, and because the way it presented — as a
failure in an unrelated test — is the thing worth remembering.

**The preview is not drawn.** The drawer shows the title, the page, the
time and the turn count; it never shows the preview, which the server
computes for every conversation on the page.  So the field is carried
for a caller that does not exist yet, and the N+1 above was the price
of carrying it.  The field is kept — the API's shape is a contract, and
the fix made it cheap — but a reader of the drawer should know that the
preview is not on the face of it.

**Two endpoints have no test.** `toggle_pin` and `rate_message` are
reachable, they are on the panel, and nothing in the suite calls them.
They are not among this review's ten requirements, so they are recorded
here rather than fixed: a change to either would not be caught by
anything.

## Deliberate exclusions

- The escalate button's visibility (FR-6.10) and the placeholder title's
  search (FR-6.6) were both recorded as product decisions and both turned
  out to be permissions and translations nobody had wired up.  Both are
  closed; see ADR-0048 and ADR-0049.
- The preview field is kept even though the drawer does not draw it,
  because the API's shape is a contract and the cost of carrying it is
  now one query.

## Accepted trade-offs

- The search matches the *site's* translation of the placeholder.  A
  reader whose user language differs from the site's is the one case this
  does not cover, and it is recorded rather than hidden.
- The model is told how many messages of a thread are behind the window
  it can see, and instructed to say so rather than answer from the wrong
  part of the thread.  A way to reach further back is not built.  See
  ADR-0052.
- The escalated transcript carries the tool calls' summaries and not the
  tool names, so the Issue reads as what the assistant did rather than
  as the model's vocabulary.

---

## Pointer

`docs/ROADMAP.md` §0 lists the conversation features among the shipped
ones.  This document is the conversation-specific record.
