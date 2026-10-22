# ADR-0005: A small fixed set, and no raw SQL

Status: **Accepted** (amended 2026-10-22, when the sixth tool was added)
Date: 2026-10-21

## Context

`erpnext-mcp` publishes ~500 tools.  A model given 500 tool schemas spends
its context on reading them, and spends its turns discovering which one it
wants.  The connector this app grew out of solved that with a *pack*: a
query-aware selection of twenty or so tools per round, drawn from a
ten-tool "core set" that was always included.

That machinery is a response to having 500 tools.  Albanna does not have
500 tools.

## Decision

**A small fixed set, and the model is told about exactly the tools the user
may reach.**

| Tool | Tier | Why it is here |
|---|---|---|
| `list_docs` | read | the "what do I have" question: which orders are open, which items are low, which customers have a balance |
| `get_doc` | read | the "what is this one" question: read the detail behind a name |
| `get_doctype_meta` | read | the fieldnames of a DocType, so the model uses real fieldnames instead of plausible guesses |
| `run_report` | read | the "what do the numbers say" question: receivables, stock balance, sales register |
| `create_doc` | write | making a document, so the write path exists and is exercised from the first release |
| `update_doc` | write | changing one — see [ADR-0007](0007-the-second-write.md) |

The set was five when this was written.  The sixth is a *change* to the
decision and has its own record; the shape of the decision — small, fixed,
and filtered by what the user may reach — did not change.

### Why `run_sql_query` is not among them

It bypasses Frappe's permission engine completely — including User
Permissions and every row-level rule built on them.  A side chat is
reachable by ordinary users, so a raw SELECT behind it is a privilege
escalation with a chat interface on top.

If it is ever added, it must be System Manager only, and it must not be
part of this set.

### Why `find_tools` is not among them

It exists to let a model discover the tool set at runtime.  Albanna *has* a
fixed set, and a discovery tool inside a fixed set is a way to spend a turn
saying what is already known.

### Why `run_flow` is not among them

A flow is several tool calls with a transaction of its own.  It is a good
tool and the wrong first one: its failure modes belong to a later release,
once the single-step write path has proven itself.

## Consequences

* The prompt carries six schemas.  A turn's tool overhead is small enough
  that the conversation is the expensive part, not the tool list.
* The selection machinery the connector had — packs, cores, query-aware
  ranking — is not needed and is not carried over.  That is most of the
  difference between the two apps' size.
* The manifest is plain data in `core/tools.py`, and the adapter maps names
  to functions.  A seventh tool is two entries, and a test fails if the two
  halves name different tools.
* A tool the user may not reach is **not sent to the model at all** — see
  [ADR-0002](0002-authority-and-permissions.md).  With a set this small,
  the difference between "told about six" and "told about five" is visible
  to the user, and that visibility is the point.
