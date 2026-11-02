# The tools the assistant may use

Albanna's assistant can use exactly twelve tools. There is no hidden
thirteenth: `run_sql_query` is deliberately absent, because a raw SELECT
behind a chat that ordinary users can reach is a privilege escalation with a
chat interface on top. Every tool runs in-process, under the caller's own roles and User
Permissions, so the assistant can never see or do more than the person
asking.

The manifest is the contract. `tests/test_tool_manifest.py` fails if the
manifest and the adapter name different tools, so this list cannot drift from
the code.

## Read tools

| Tool | What it does | Authorised against |
|---|---|---|
| `list_docs` | Find documents of one DocType, with filters, sorting and pagination. | Frappe's `read` permission on that DocType. |
| `get_doc` | Read one document by name. | Frappe's `read` permission on that DocType. |
| `get_doctype_meta` | The fieldnames and types of a DocType. | Frappe's `read` permission on that DocType. |
| `run_report` | Run an ERPNext report. | The report's own permission. |
| `ask_question` | Ask the reader a question, with the answers the assistant found, and wait for their answer in the chat. | Nothing: it touches no document. It is tiered as a read because the write rail is about the site's *business* data, and a question changes none of it. |

## Write tools

Each write is authorised against a *different* Frappe right, so a role model
that grants one does not necessarily grant another. A write tool is only
offered to a caller who holds its right on at least one DocType on the site;
whether they hold it on the *target* of a particular call is decided per call.

| Tool | What it does | Authorised against |
|---|---|---|
| `create_doc` | Create a document. | Frappe's `create` permission. |
| `update_doc` | Change the fields of a document that exists. A submitted document cannot be edited this way. | Frappe's `write` permission. |
| `bulk_update_doc` | Change the same fields on many documents at once, under one approval card that names every document it would touch. | Frappe's `write` permission on every document it would touch. |
| `submit_doc` | Submit a draft document, making it permanent. | Frappe's `submit` permission. |
| `cancel_doc` | Cancel a submitted document. | Frappe's `cancel` permission. |
| `amend_doc` | Cancel a submitted document and create a new draft from it. | Frappe's `amend` permission. |
| `delete_doc` | Delete a draft or cancelled document. | Frappe's `delete` permission. |

## The question

`ask_question` is the one tool that does not act on the site's data: it puts
a question in front of the reader, with the options the assistant found, and
the reader picks one.

* **It is a row, not a cache entry.** The reader may answer it tomorrow.
* **Asking it ends the assistant's freedom to act** for the rest of the
  turn: the rest of that round's tool calls do not run, and the next round
  is given no tools at all.
* **The answer is the reader's next message.** It names the question it
  answers, and carries the option's *value* — the document's name — because
  the value is the one that goes into a document.
* **Only the reader the question names may answer it**, the first answer is
  the answer, and an answer the reader was never offered is refused.

The whole of it is in
[ADR-0011](adr/0011-the-question-is-asked-in-the-chat.md).

## What a write cannot do

- `update_doc` will not touch framework fields (`owner`, `docstatus`, `name`),
  will not touch a read-only field, and will not change a submitted document.
- `delete_doc` will not delete a submitted document; it must be cancelled
  first, which `delete_doc` does not do.
- `submit_doc`, `cancel_doc`, `amend_doc` and `delete_doc` each run the
  document's own rules, so a document that fails validation is refused and
  the reason is returned to the reader.
- Every write takes a savepoint first. A failure rolls back to it and no
  further, so a document that was already created is not undone by a later
  failure in the same turn.

## Approval

When the operator has turned on "confirm writes" in Albanna Settings, a
write does not run until the reader approves it. The approval card shows
what will change, counts down from the operator's configured wait, and
stops accepting answers when the wait runs out. A destructive write
(`cancel_doc`, `delete_doc`) is shown with a danger style and a consequence
line stating what will happen and that it cannot be undone from here.

## Audit

Every turn is recorded in `Albanna Chat Log`: who asked, which model, how
many rounds, how many tool calls, what it cost. No question text and no
answer text. The settings page sums the month by model and by user.
