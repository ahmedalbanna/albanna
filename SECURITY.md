# Security Policy

## Reporting a vulnerability

Please report a security issue privately to **admin@albanna.dev** rather
than opening a public issue. Include what you found, how to reproduce it, and
which version you were on.

We aim to acknowledge a report within three working days.

## What this app is designed around

The app's security rests on a small number of decisions, each of which is
recorded in `CONTEXT.md` and `docs/adr/`:

- **The tools run as the signed-in person.** Every read goes through
  `frappe.get_list` / `frappe.get_doc` and every write through
  `doc.insert()`, so the framework applies that person's roles, permissions
  and User Permissions. The model cannot see what its caller cannot see.
- **The site is asserted, never guessed.** A tool refuses to run against
  any site other than the one the request was resolved for.
- **A refusal names the roles that could act**, and is stated as a fact
  about the organisation rather than a failure of the assistant.
- **The write capability is a switch.** `Allow Writes` is off by default.
- **Page context is data, never instructions.** What the browser sends is
  rendered into a delimited block that the system prompt explicitly marks
  as untrusted, so a document titled "ignore your instructions" is text to
  report on, not an order to follow.
- **The model never receives a credential.** The provider's key goes to the
  provider; nothing else leaves the site.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## What is out of scope

- The security of the model provider you configure, or of the model
  itself.
- The security of your Frappe site, its web server, or its database.
- Denial of service caused by a deliberately misconfigured provider.
