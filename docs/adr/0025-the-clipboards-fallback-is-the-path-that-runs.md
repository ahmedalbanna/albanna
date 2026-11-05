# ADR-0025: The clipboard's fallback is the path that runs

Status: **Accepted**
Date: 2026-11-05

## Context

An answer's table can be copied as tab-separated values, so the paste lands
in a spreadsheet as a table rather than as a column of text.  The copy
confirmed itself, and both failure modes had their own sentence.

`copyTable` called `navigator.clipboard.writeText` directly.  `copyAnswer`,
a few lines above it in the same file, guarded the call and fell back to
`fallbackCopy` — a hidden textarea and `document.execCommand("copy")`.

`navigator.clipboard` exists only in a **secure context**: `https`,
`localhost`, or `127.0.0.1`.  This deployment is
`http://185.190.140.93:8000`.  So in production `navigator.clipboard` is
`undefined`, the call throws a `TypeError`, and the reader is told *"The
table could not be copied."* — while the "Copy answer" button beside it
works, because it has the fallback.

That is the hardest kind of defect to catch.  It passes every test.  It
works on every developer machine, because `127.0.0.1` is a secure context.
And it fails for every real reader.

## Decision

**The clipboard's fallback is not an optional extra on this site; it is the
path that runs.**

`copyTable` now guards the call the way `copyAnswer` does, and
`fallbackCopy` is shared rather than copied — there is one of it.  The
comment says why the guard is not defensive programming here: the site is
served over plain HTTP, so the Clipboard API is absent for every reader,
and the fallback is the primary path.

The consequence worth recording is not about this one button.  It is that
**any future use of `navigator.clipboard` in this app must carry the
fallback**, because the deployment's origin will not change to suit it.  A
contributor writing a new copy button on a developer machine will find the
Clipboard API works perfectly, and will ship a button that fails for
everybody.

## Alternatives considered

**Serve the site over HTTPS.**  Rejected as out of scope for this pass, and
not the app's decision alone — it needs a certificate and a hostname.  It
is also the *right* long-term answer, and this ADR should be revisited when
it happens: the fallback stays correct either way, but the comment saying
it is the primary path would become wrong.

**Require a secure context and refuse otherwise.**  Rejected: it would make
the feature unavailable to every reader in order to keep the code simple.

**Copy via a server round trip.**  Rejected: the text is already in the
browser.  Moving it to the server and back to put it on the reader's
clipboard is a long way round a short problem.

**Use `document.execCommand` only.**  Rejected: it is deprecated, and it is
the fallback rather than the primary.  The guarded pair is the correct
shape — try the modern API, fall back to the old one.

**Leave it, because the reader can download the CSV instead.**  Rejected:
the download exists and is good, but it is a different job.  Copying puts
the table into a spreadsheet the reader already has open; downloading gives
them a file they then have to open.  Refusing one because the other exists
is how a feature quietly disappears.

## Consequences

* The table copy works in production, by the path that was already written
  and already tested for the answer copy.
* There is one `fallbackCopy` rather than two, so the two copy buttons
  cannot drift apart again.
* The comment records the environmental fact, so the next contributor does
  not have to rediscover it on a machine where the Clipboard API works.
* If the site ever moves to HTTPS, the guard stays correct and the comment
  needs one line changed.  That is the right trade.

## See also

* `albanna/public/js/side-chat/SideChatApp.vue` — `copyTable`, `copyAnswer`
  and the shared `fallbackCopy`.
* `docs/FR-2_ASKING.md` — the requirement this closed, and the two gaps in
  the same feature that were recorded rather than fixed.
