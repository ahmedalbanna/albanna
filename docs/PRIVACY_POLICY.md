# Privacy Policy

**Albanna — the ERPNext side chat**
Effective: 15 November 2026 · Publisher: Albanna Software Solutions

## 1. The short version

Albanna runs **inside your own ERPNext site**. Your questions, the
answers, the record of what the assistant did, and the files you attach
never leave your infrastructure — except for one thing: the text of a
question and the tool results a turn needs are sent to the **language-model
provider your administrator configured**. That is the only outbound path,
it is one the administrator chooses, and it can be pointed at a model
running on your own network.

## 2. What the app stores, and where

| Data | Where it lives | How long |
|---|---|---|
| Conversations and messages | rows in **your site's** database | until the owner deletes the thread |
| The audit ledger — what the assistant read, wrote and was confirmed to write | a doctype in **your site's** database | 90 days by default, then pruned by age; the window is the administrator's |
| Attached files | **private** File records on your site's own file store | until the message or thread that holds them is deleted |
| Provider API keys | your site's encrypted password storage | until the administrator removes them |
| Rate-limit counters, running-turn markers | your site's Redis, with TTLs | seconds to hours, by design |

The publisher's infrastructure receives none of this, unless the publisher
hosts your instance (section 7).

## 3. What leaves your site, and to whom

- **The model provider you configure.** The app sends the question, the
  context of the page it was asked on, and the results of the tools the
  turn ran. It never sends: your API keys, user passwords, whole
  documents, or data outside the permissions of the signed-in user.
- **Nobody else.** The app has no telemetry, no licence server, no phone
  home. Its one outbound HTTP surface is the model provider — this is
  enforced and pinned by the app's own test suite.

The provider processes that text under **their** terms and privacy policy,
which the administrator should read when choosing. Choosing a local model
(Ollama) keeps even this on your network.

## 4. Who can read what

The app's guarantee is **permission parity**: the assistant reads and
writes with exactly the roles of the signed-in user, never more. Inside
your site:

- a user reads only their own conversations;
- the audit ledger is readable by System Managers, who are your own
  administrators;
- attachments are private files, readable by their session;
- the publisher's support staff read your data **only** if you ask us to,
  and only what the request needs.

## 5. What the app does not do

- It does **not** train models. It sends a turn's text to the provider for
  that turn's answer only.
- It does **not** log question or answer text to files. Its logs carry
  identifiers and numbers — user, model, status, tokens, duration —
  deliberately not words.
- It does **not** share data between sites. Sites sharing one code base
  keep separate databases, and the app never crosses that line.

## 6. Your rights, and how to exercise them

Because everything is in your own database, you exercise rights directly
with your own tools:

- **Access / portability:** export a conversation from the panel, or read
  the rows in your database.
- **Erasure:** delete a thread from the panel — its messages go, and the
  files only that thread pointed at are removed with it. Ledger rows are
  the operator's audit trail and outlive the thread by the retention
  window; an administrator can prune them sooner.
- **Rectification:** edit your own last question in the panel, and have
  its answer regenerated.

If the publisher hosts your instance and you need our help with any of
these, write to the address below and we will action it within 30 days.

## 7. If we host your instance

We process, on your behalf: your site's database and file store (to run
the service), its operational logs (to keep it healthy), and backups of
both (so it can be restored). We do not sell it, we do not use it to train
anything, and we do not move it off the hosting infrastructure except at
your written direction.

## 8. Changes

We publish changes to this policy in this document. Material changes take
effect 30 days after publication.

## 9. Contact

Albanna Software Solutions · <ahmedalbanna966@gmail.com>
