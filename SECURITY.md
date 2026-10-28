# Security Policy

## Reporting a vulnerability

Please report a security issue privately to **admin@albanna.dev** rather
than opening a public issue. Include what you found, how to reproduce it, and
which version you were on.

We aim to acknowledge a report within three working days.

## What this app is designed around

The app's security rests on a small number of decisions, each of which is
recorded in `CONTEXT.md` and `docs/adr/`:

- **The tools run as the signed-in person.** A listing goes through
  `frappe.get_list` and a write through `doc.insert()` / `doc.save()`, so
  the framework applies that person's roles, permissions and User
  Permissions. A single document read goes through the ORM, which applies
  none of them — so the read is checked against the permission engine by
  hand, and a document the caller may not read is refused as a read would
  have refused it. The model cannot see what its caller cannot see.
- **The site is asserted, never guessed.** A tool refuses to run against
  any site other than the one the request was resolved for.
- **A refusal names the roles that could act**, and is stated as a fact
  about the organisation rather than a failure of the assistant.
- **A write waits for the reader.** The write tools are offered to a
  person who holds the right to write, and every write waits for the
  reader's approval; a policy row can turn the rail on or off for one
  account. An approval is bound to the write it answers: the pending write
  is recorded before the reader is asked, a decision naming no pending
  write is refused, a second decision is refused, and a document that
  changed while the reader was deciding is not changed.
- **Page context is data, never instructions.** What the browser sends is
  rendered into a delimited block that the system prompt explicitly marks
  as untrusted, so a document titled "ignore your instructions" is text to
  report on, not an order to follow.
- **The model never receives a credential.** The provider's key goes to the
  provider; nothing else leaves the site — and the site's own keys are
  taken out of the chat log before it is written, because a provider's
  refusal often quotes the key it refused.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## What is out of scope

- The security of the model provider you configure, or of the model
  itself.
- The security of your Frappe site, its web server, or its database.
- Denial of service caused by a deliberately misconfigured provider.
