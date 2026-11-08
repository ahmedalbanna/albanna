# ADR-0049: The search matches the display title

Status: **Accepted**
Date: 2026-11-09

## Context

A thread with no title of its own is called whatever the reader's
language calls it. The doctype stores an English sentinel, and the search
matched that.

So an Arabic reader who searched for the words the drawer actually showed
them got nothing, while the same reader searching the English sentinel
found the thread. The placeholder is a storage detail and not a title,
and the search was the one place that treated it as one.

FR-6.6 recorded this as blocked, on the grounds that making the search
match what the drawer shows is *"a product decision about what a thread
with no title is called"*.

It is not. The question already has an answer in the system: whatever the
drawer shows. What was missing was the search reading it.

## Decision

**The title is read as the display title before the LIKE runs.**

```sql
if(title = %s, %s, title) like %s escape '\\'
```

The sentinel is replaced by its translation, so the search matches what
the reader sees. On an English site the translation *is* the sentinel and
the query is what it always was.

## Alternatives considered

**Stop storing an English sentinel — store `""` and let the drawer show
its translation.** Rejected: it needs a migrate, and it does not fix the
reported problem. A reader searching "محادثة جديدة" would still get
nothing, because there would be no title to match.

**Match the sentinel *and* the translation as two conditions.** Rejected:
it is the same query with more of it, and it leaves the sentinel
matchable — which is the bug.

**Match any search against every untitled thread.** Rejected: it would
make every search return every untitled thread, which is worse than the
bug.

**Translate in the browser and send the sentinel.** Rejected: the search
runs in SQL so that it reaches conversations the panel has not loaded.
Moving the match to the browser would make it a filter over one page,
which is not a search.

## Consequences

* An Arabic reader searching for the words they see finds the thread.
* The translation is the *site's*, read with `_()`. A reader whose user
  language differs from the site's is the one case this does not cover,
  and it is recorded rather than hidden: the drawer shows them their
  language, and the search matches the site's.
* The test forces the reader's language, because the drawer shows them
  the words in *their* language and the search has to match those.
* The test leaves the thread untitled rather than setting the title to
  the empty string: `rename_conversation` refuses an empty title, so that
  is a state the API cannot produce and testing it would be testing a
  case that does not exist.
* The test fails with the display-title matching removed.
* The general lesson is ADR-0048's again: a "product decision" that turns
  out to be a translation nobody wired up is not a product decision.

## See also

* [ADR-0048](0048-the-escalate-button-follows-a-permission.md) — the
  other blocked item from the same pass, and the same shape.
* `albanna/services/conversation_service.py` — `list_conversations`, and
  the `if(title = ...)` that reads the display title.
* `docs/FR-6_CONVERSATIONS.md` — the record that flagged this as
  awaiting a decision.
