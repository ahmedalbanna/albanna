# Threat model: Albanna (ahmedalbanna/albanna)

Builds on the repository's own security model: `SECURITY.md` ("What this app is designed around", "What is out of scope"), `CONTEXT.md` (invariants 5–13, 62–68) and `docs/adr/`. Where those files state a rule, it is the owner's stated intent; the rest of this document is a reading of the code and is marked as such.

## System overview

Albanna is one Frappe app installed on the operator's own ERPNext (Frappe v16) bench. It adds a side-chat panel to the Desk; a signed-in user asks about site data, the app calls a configured LLM provider (OpenAI-compatible, Anthropic, Ollama) and runs a fixed manifest of twelve tools in-process as that user. Writes wait for the reader's approval. No separate service, no telemetry; the only egress is the configured provider.

No infrastructure-as-code exists; deployment is the operator's bench (`docs/DEPLOYMENT.md`). No infrastructure repository was used.

## Trust boundaries

1. **Browser → whitelisted API** (`albanna/api/*`): every argument and the page context are attacker-controlled (invariant 7).
2. **Model → tool layer** (`albanna/services/chat_service.py` → `albanna/tools/backend.py` → `albanna/tools/erpnext.py`): the model's tool calls are untrusted; they are checked by the authority (`albanna/core/authority.py`) and then by Frappe's permission engine as the session user (invariants 1, 6, 11, 62).
3. **Site data → model**: document content, file content and page context reach the prompt; they are data, never instructions (invariant 7). Tool results go to the external provider.
4. **App → provider** (`albanna/providers/*`): the provider key leaves the site; nothing else credential-like may (SECURITY.md).
5. **User ↔ user**: conversations, questions, approvals and parked turn results belong to one account (invariants 13, 66, 67; `hooks.py` permission hooks).
6. **Background worker** (`albanna/services/chat_job.py`, `albanna/tasks.py`): runs a turn outside the request; must re-establish the requesting user and site (invariants 5, 6).

## Components

| Component | Code it covers |
|---|---|
| **API** | `albanna/api/` (whitelisted endpoints: chat, conversations, questions, context, widget upload, provider test, usage) |
| **Chat engine** | `albanna/services/` (chat_service, chat_job, approval, undo, conversation_service, attachments, rate_limit, audit_rows, settings_service), `albanna/core/` (prompt, messages, undo, diff, attachments, secrets) |
| **Tools & authority** | `albanna/tools/`, `albanna/core/tools.py`, `albanna/core/authority.py`, `albanna/permissions.py`, `albanna/user_policy.py`, `albanna/site_context.py` |
| **Providers** | `albanna/providers/` |
| **Side-chat UI** | `albanna/public/js/`, `albanna/templates/` |
| **Data model & lifecycle** | `albanna/albanna/doctype/`, `albanna/hooks.py`, `albanna/install.py`, `albanna/tasks.py`, `albanna/patches/`, `albanna/privacy.py` |

## Entry points

- Whitelisted methods, all requiring a logged-in user with chat access (`require_chat_access`): `chat.ask`, `chat.ask_stream`, `chat.status`, `chat.confirm_write`, `conversations.*` (list/open/new/rename/pin/delete_turn/rate/escalate/undo/delete), `questions.pending_questions` / `answer_question`, `context.count_doctype` / `nudge_for_page`, `widget.upload_file` / `options`, `usage.summary`.
- System Manager only: `provider.test_provider` (accepts an arbitrary base URL and key).
- Socket.IO events published per user; cache-parked turn results keyed by stream id.
- Scheduler jobs (prune logs, expire questions, interrupt stale turns).
- Indirect: any text in an ERPNext document, file, or page the user views that the model reads (prompt injection).

## Assets

- ERPNext business data reachable by the tools (accounting, HR, stock, customers) — bounded by the caller's permissions.
- Integrity of documents changed through write tools (create/update/submit/cancel/amend/delete/bulk update).
- Conversation history and questions (private per user; invariant 13).
- Provider API key in `Albanna Settings`; per-user Frappe API keys (`User.api_key`, PRIVACY.md).
- Private files (`Home/Albanna` uploads, other users' private files; invariant 62).
- Audit trail integrity (`Albanna Chat Log`; no question/answer text, no secrets — invariants 10, 68).

## Attacker profiles

- **Low-privilege Desk user** with chat access trying to read or change data beyond their roles via the assistant (the "moat", invariant 62).
- **Another Albanna user** trying to read, act on, or approve someone else's conversation, question, pending write or parked result.
- **Content author / prompt injector**: anyone who can put text into a document, file, comment or page that a victim later asks about, steering the model to call tools as the victim.
- **Malicious or compromised model output** (treated the same as prompt injection).
- Unauthenticated web users: no guest endpoint found (reading of the code).

## Existing controls

- Fixed twelve-tool manifest, JSON-schema validation, reachability/authorisation in `core/authority.py` (fail closed).
- Tools run as the session user; document reads checked by hand in `albanna/permissions.py`; hidden fields removed; framework fields (`owner`, `docstatus`) refused (invariants 6, 62, 63).
- Site asserted before every tool call (`site_context.resolve`, invariant 5).
- Approval gate bound to a recorded pending write with fingerprint, one-shot, stale-document check (invariant 66).
- `assert_owns` on every conversation endpoint and in services (invariants 13, 67).
- Page context in a delimited untrusted block (invariant 7); markdown escaped before `v-html` (`markdown.js`).
- Secrets redacted from chat log and request log (`core/secrets.py`, `privacy.py`, invariant 68).
- Per-user, per-surface rate limit (invariant 12).

## Owner's priorities (stated by the owner)

- **Every attacker profile above matters**: low-privilege Desk users, other Albanna users, and prompt injection through documents, files or page context.
- **Every asset above matters equally**: accounting/financial data, HR/payroll data, provider and per-user Frappe API keys, and conversation-history privacy are all critical.

## Out of scope / accepted risk

From SECURITY.md and CONTEXT.md:

- Security of the configured model provider or the model itself.
- Security of the Frappe site, web server and database.
- Denial of service from a deliberately misconfigured provider.

Stated by the owner:

- **Malicious System Managers / Administrators** are trusted. Issues that need System Manager or Administrator rights (e.g. `provider.test_provider` base URL/SSRF, `Albanna Settings`, `Albanna User Policy` rows, install/patch code) are accepted risk.
- **The non-atomic rate-limit window** (invariant 12: "one extra question").
- **Abuse by users who already hold full write rights on the target DocType**: a user doing through the assistant what their own permissions already let them do is accepted risk. Reaching *past* those rights (fields, docstatus, documents they cannot read, other users' data) is not.

## Open questions

- Whether prompt injection steering a write that the reader then approves (via a misleading card) is in scope, given the approval gate. Treated as in scope until the owner says otherwise.
