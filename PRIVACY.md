# Privacy Policy

_Last updated: 2026-10-21_

Albanna is a Frappe app that runs **on your own Frappe site**. It does not
run a service of its own, it has no account system, and it sends nothing to
anywhere except the model provider **that you configured**.

## What the app stores

Everything the app stores stays in **your site's database**, under your
control, and is subject to your own backups and your own retention rules.

| What | Where | Why |
|---|---|---|
| Conversations and their messages | `Albanna Conversation`, `Albanna Message` | so a person can come back to what they asked |
| A per-turn record | `Albanna Chat Log` | who asked, which model, how many steps, what it cost |
| The configuration | `Albanna Settings` | the provider, the model, the key, the limits |
| The per-user key | `User.api_key` | the Frappe session's own credential, used only to run the tools as that person |

The `Albanna Chat Log` deliberately holds **no question text and no answer
text**. It records counts, timings, error classes and the name of any
document a write created.

## What leaves your site

Only the question, and only to the model provider you configured in
**Albanna Settings**:

- the text of the question, and the page context (the document or list the
  user was looking at);
- the tool results, so the model can reason over them.

The provider is whichever endpoint you configured. The app sends the
**provider's own API key** with the request; it never sends a Frappe
password, and it never sends a database credential.

**Tool results are bounded by the caller's own permissions.** The app runs
every read and every write as the signed-in person, so a model can only
ever see what that person could see, and can only ever change what that
person could change. A question asked by a user without an accounting role
cannot surface accounting data, and cannot create a document that role
would not allow.

## What the app does not do

- It does not phone home. There is no telemetry, no analytics and no
  crash reporting.
- It does not read the request text of a question into any log.
- It does not give the model a credential it could use to reach anything
  else.

## Removing the data

Deleting a conversation removes its messages. Deleting a site removes
everything. The daily scheduler prunes chat-log rows older than 90 days.

## Contact

Questions about this policy: **admin@albanna.dev**
