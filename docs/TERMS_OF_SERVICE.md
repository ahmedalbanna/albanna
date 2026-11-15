# Terms of Service

**Albanna — the ERPNext side chat**
Effective: 15 November 2026 · Publisher: Albanna Software Solutions

## 1. What this covers

These terms govern the Albanna software ("the app"), a Frappe/ERPNext
application published under the MIT licence, and any hosted instance of it
that Albanna Software Solutions ("we", "the publisher") operates for you.

The app is installed **on your own ERPNext site**. Where an instance is
hosted by us, the hosting terms below apply alongside these; where you
self-host, sections 5–7 (data) still describe how the software behaves.

## 2. What the app does

Albanna adds a chat panel to the Desk. It answers questions about your
site's data in plain language, and can act on it — create, update, cancel —
using the same tools your ERPNext install already exposes. Its central
guarantee is **permission parity**: the assistant can never see or do more
than the signed-in user who asked.

## 3. Who is responsible for what

- **You** are responsible for the accounts you give access to, the
  providers and API keys you configure, and the decisions your users
  confirm inside the app. Write actions are gated by an explicit
  confirmation card, recorded in the app's ledger.
- **We** are responsible for the software: that it behaves as documented,
  that it enforces the permission parity above, and that its audit trail
  records what it did.

The app is provided **"as is"**, under the MIT licence, **without warranty
of any kind** — see section 7. It is an assistant, not an accountant: a
figure it reports is a reading of your data, and a write it makes is one a
person confirmed. Verify both before you rely on either.

## 4. The model provider is a third party

The app sends questions — and, when a tool call is involved, tool results —
to the **language-model provider you configure** (OpenAI-compatible,
Anthropic or Ollama). That provider is a separate service with its own
terms and privacy policy, outside these terms. What we do about it:

- the app stores your provider's API key inside **your own site's**
  encrypted storage and sends it to nobody else;
- what crosses to the provider is limited to the question, the page context
  and the tool results the turn needs — never your API keys, never your
  users' passwords;
- you can point the app at a **local model** (Ollama) so that nothing
  leaves your infrastructure at all;
- you can run the app with writes disabled or in dry-run mode.

You choose the provider; you own that choice.

## 5. Where the data lives

Everything the app stores lives **inside your own ERPNext site**: the
conversations and their messages are rows in your database, the audit
ledger is a doctype in your database, and uploaded attachments are private
files on your own file store. The publisher's own infrastructure receives
none of it, unless we host your instance — in which case section 8 applies.

## 6. Retention

- Conversations and their messages stay until the user who owns the thread
  deletes it.
- The audit ledger (what the assistant read and wrote) is retained for
  **90 days** by default, then pruned by age.
- Questions awaiting a reader's choice expire on the schedule the
  administrator sets.
- An administrator may change the retention windows in the site's
  settings.

## 7. Licence and limitation of liability

The app is licensed under the **MIT Licence**; the licence text is the one
that ships with the source. To the maximum extent permitted by law, the
authors and publisher are **not liable** for any claim, damages or other
liability arising from, out of or in connection with the app or its use —
including answers it gave, writes it performed, or data sent to the model
provider you configured.

## 8. If we host your instance

Where the publisher operates an instance for you, we also process, on your
behalf and only to run the service: the site's own database and file store,
its operational logs, and backups of both. We do not read your business
data except to respond to a support request you raised, and we do not move
it off the hosting infrastructure except at your written direction.

## 9. Changes

We will publish changes to these terms in this document. Material changes
take effect 30 days after publication.

## 10. Contact

Albanna Software Solutions · <ahmedalbanna966@gmail.com>
