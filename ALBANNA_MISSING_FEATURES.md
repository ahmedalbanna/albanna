# Albanna — Missing Features (codebase audit)

Audited against https://github.com/ahmedalbanna/albanna (main) plus README + source.

## Already present (do not rebuild)
- 11 in-process ERPNext tools (list/get/meta/report/create/update/bulk/submit/cancel/amend/delete)
- Single model provider + fallback (OpenAI-compatible, Ollama, Anthropic)
- Side chat panel, live streaming, stop turn
- Conversation history (list/search/rename/delete, per-user, per-page)
- Undo for create/update/submit (reversible writes only)
- Write approval card with before/after diff
- Source-document links under answers
- Image + PDF attachment (image-first, PDF text extraction)
- Voice input (browser speech API)
- Error-dialog -> chat handoff
- "Ask a human" (hand transcript to Frappe Issue) + dry-run mode
- Truncated-answer detection
- Provider extra options (JSON)
- Usage ledger + audit trail (no question/answer text)
- Arabic/RTL, resizable panel, copy table/answer, regenerate last

## Missing / gaps (vs. requested list)

### 1. Compact context sessions — MISSING
- No summarization/compaction of older turns when context grows.
- `load_messages(conversation, settings.history_limit)` just truncates to last N.
- Add: token estimate + LLM summarization of older turns into a stored
  `Albanna Conversation.summary`; keep recent N + summary.

### 2. MCP client integration (many external tools) — MISSING
- Only 11 in-process ERPNext tools. No MCP client, no tool discovery, no
  routing to external MCP servers.
- Add: `MCP Server` doctype + `sync_mcp_tools()` job + tool registry;
  chat loop must handle `tool_calls` from any registered server.
- This is the biggest gap for "big number of tools".

### 3. Human-in-the-loop — PARTIAL
- Write approval card exists for ERPNext writes.
- Missing: approval for *external/MCP* tool calls and a generic confirm flow
  beyond writes. Also "ask a human" exists but is issue-based, not inline.

### 4. Chat with files uploader — PARTIAL
- Only images + PDF. No general file upload (DOCX, XLSX, TXT, CSV) nor
  extraction pipeline for arbitrary files.
- Add: generic file handler + text extraction per MIME type; store as
  `Albanna Attachment`.

### 5. AI models provider connector — PRESENT but limited
- OpenAI-compatible / Ollama / Anthropic only.
- Missing: Gemini, Azure OpenAI, Bedrock, vLLM discovery, model capability
  flags (vision, tools), per-model pricing in ledger.

### 6. Inline message actions — PARTIAL
- Present: copy answer, copy table, regenerate-last.
- Missing: edit a message and regenerate, branch/fork conversation from a
  message, per-message regenerate (not just last), delete single message.

## Recommended next implementation order
1. Compact context sessions (small, high impact)
2. General file upload + extraction
3. Inline actions: edit/branch/regenerate-any
4. MCP client integration (largest)
5. Provider expansion (Gemini/Azure)
6. Generalize human-in-the-loop for MCP tools

## Reverse-engineering tip
To mirror a reference implementation (e.g. Open WebUI) for any gap, run:
  rea analyze-web-bundle <reference-url>
and inspect the returned modules/routes for the relevant keyword.