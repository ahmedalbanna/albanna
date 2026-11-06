# ADR-0040: A guard that only runs past a threshold fails in whatever crossed it

Status: **Accepted**
Date: 2026-11-06

## Context

`trim_conversation` drops the oldest messages once a conversation outgrows
its bound. It counted first and returned early when the count was within the
bound, so the DELETE only ever ran once a conversation passed 400 messages.

The DELETE put a `LIMIT` inside an `IN` subquery:

```sql
delete from `tabAlbanna Message`
where name in (
    select name from `tabAlbanna Message`
    where parent = %s and parentfield = %s
    order by idx asc limit %s
)
```

MariaDB refuses that construct outright — *"This version of MariaDB doesn't
yet support 'LIMIT & IN/ALL/ANY/SOME subquery'"*. So the trim had never
worked. Not once, on any site, since it was written.

And it did not look broken. The early return meant the failing query ran
only when a conversation outgrew its bound, which on a test site takes
hundreds of turns. When it finally ran, it raised inside whatever turn had
just pushed the thread past the bound — so the error appeared in
`test_the_log_records_the_cut_off`, in `test_the_approval_is_recorded_in_the_row_before_the_reader_is_asked`,
in `test_an_approved_write_is_recorded_as_ran`. Four tests red, all of them
about something else, and the count growing as the data accumulated.

The natural reading of each failure was that the *turn* was broken. The
trim was nowhere in the traceback's story.

## Decision

**Delete the excess rows directly, with the ordering and the bound on the
DELETE itself.**

```sql
delete from `tabAlbanna Message`
where parent = %s and parentfield = %s
order by idx asc
limit %s
```

MariaDB supports `DELETE … ORDER BY … LIMIT`, and the two forms delete the
same rows: the *excess* oldest messages of this conversation, by `idx`.

The comment in the code says why the shape is not the obvious one, because
the obvious one is the one that never ran.

## Alternatives considered

**Fetch the names, then delete by name.** Rejected: it works, and it is two
round trips and a race — a message inserted between the read and the delete
would be missed or wrongly included. One statement that does the whole job
is both cheaper and correct.

**Delete in a loop, one row at a time.** Rejected: `excess` can be large,
and a loop of single-row deletes is the slowest possible shape of the same
operation.

**Keep the subquery and catch the exception.** Rejected: it would turn a
loud failure into a silent one, and a trim that quietly stops trimming is a
table that grows without bound while every test stays green.

**Raise the bound so the trim never runs.** Rejected: that is the failure
mode with a longer fuse.

## Consequences

* The trim works, and the four red tests are green.
* The general lesson, which is what this ADR is really for: **a guard that
  only runs past a threshold fails in whatever crossed it, not in itself.**
  The early return was correct and it was also what hid the bug — the code
  was right in every case that was ever exercised, and wrong in the one case
  it existed for.
* The same shape applies to any conditional cleanup, any lazy migration, and
  any pagination bound. The question to ask is not "does this work?" but
  "when does this run for the first time, and what will the failure look
  like then?"
* A test that forces the threshold would have caught this on the day it was
  written. There is now no such test, because the trim is a housekeeping path
  with no requirement behind it — which is the reason it went untested for as
  long as it did, and the reason it is recorded here rather than in a
  requirements document.

## See also

* `albanna/services/conversation_service.py` — `trim_conversation`, and the
  comment that says why the DELETE is shaped the way it is.
* `docs/FR-5_APPROVAL.md` — the pass that found it, recorded under "found on
  the way, and not part of any requirement".
* [ADR-0037](0037-a-bulk-changes-undo-is-one-entry-carrying-many-documents.md)
  — the other defect in this pass that survived because the test that would
  have caught it tested a hand-written entry instead of the tool.
