# Feature Implementation Guide — MCP AI Chat (Frappe) via Reverse Engineering

Source of patterns: Open WebUI (open-source reference) + REA's own MCP integration.
Use this as a blueprint; adapt Python/Frappe + JS to your app.

## 1. Human-in-the-Loop (tool approval gates)
Pattern (Open WebUI `ToolCallDisplay.svelte`, `CallOverlay.svelte`):
- When the model emits a `tool_call`, render a pending card with tool name + args.
- Provide Approve / Reject buttons; on decision, send a follow-up message
  containing the tool result or a "rejected" marker.
- Backend: keep a state machine per message: `pending_tool` -> `approved`/`rejected`.
- Frappe: add DocType `AI Tool Call` with fields: chat, message, tool_name, args_json,
  status (Pending/Approved/Rejected), result_json. Expose whitelisted method
  `approve_tool_call(name)` that executes the MCP tool and appends result to chat.

## 2. Compact Context Sessions (summarization)
Pattern: when token count exceeds threshold, summarize older turns into one
"system" message and drop raw history.
- Backend: estimate tokens (tiktoken or char/4 heuristic). If > threshold
  (e.g. 80% of model context), call LLM with a summarization prompt over
  older messages, store summary in `AI Chat Session.summary`, and keep only
  recent N messages + summary.
- Frappe: add field `summary` (Long Text) to `AI Chat Session`; job
  `compact_session(session)` runs on message append or scheduled.

## 3. Chat with File Upload
Pattern (Open WebUI upload flow):
- Frontend: multipart upload to `/api/files`; store file, extract text (PDF/DOCX)
  server-side; attach file id to message.
- Backend: endpoint accepts file, saves to Frappe File doctype, runs extractor,
  returns `{file_id, extracted_text}`. On chat completion, inject extracted text
  into context (or pass as attachment metadata to model).
- Frappe: use `frappe.utils.file_manager.save_file`; add `AI Chat Attachment`
  doctype linking file + chat + message.

## 4. AI Model Provider Connector (multi-provider)
Pattern (Open WebUI `routers/openai.py`, `routers/ollama.py`, `utils/chat.py`):
- Abstract provider behind a common interface:
  `generate_chat_completion(provider, model, messages, stream) -> iterator`.
- Each provider implements: list_models(), chat_completion(), stream().
- Store provider config in `AI Provider` doctype: base_url, api_key (encrypted),
  type (openai/anthropic/ollama/gemini), headers.
- Frappe: whitelisted method `chat_completion(provider, model, messages)` dispatches
  to the correct adapter; supports SSE streaming via `frappe.response` or socketio.

## 5. Inline Message Actions (copy, regenerate, edit, branch)
Pattern (frontend message component):
- Each message renders an action bar with buttons.
- Actions call backend endpoints:
  - regenerate: delete assistant reply, re-run completion from user message.
  - edit: update user message content, then regenerate.
  - branch: duplicate conversation up to that message into new session.
- Frappe: add methods on `AI Chat Message`: `regenerate()`, `edit(content)`,
  `branch()`; update child table `AI Chat Message` rows accordingly.

## 6. Connect to Many MCP Tools
Pattern (REA's own integration + Claude Desktop):
- On startup, call `tools/list` on each configured MCP server; cache tool schemas.
- Build a tool registry: `{server, name, description, inputSchema}`.
- When model requests a tool, route by server, call `tools/call`, return result
  as a tool message; loop until model finishes.
- Frappe: add `MCP Server` doctype (name, url/command, enabled); job
  `sync_mcp_tools()` populates `MCP Tool` child table. Chat completion loop
  handles tool_calls array and executes via REA/HTTP.

## Frappe-specific notes
- Use `frappe.whitelist()` for all endpoints called from JS.
- Store secrets via `frappe.conf` or encrypted Password fields; never log keys.
- Use Frappe's realtime (socketio) for streaming tokens.
- Add permissions: only chat owner can view/approve tool calls.
- Index `AI Chat Message.creation` and `session` for history queries.

## Suggested delivery order
1. Provider connector (foundation) -> 2. File upload -> 3. MCP tool registry ->
4. Human-in-the-loop -> 5. Inline actions -> 6. Context compaction.

## Reverse-engineering next step
Use REA to capture the reference app's network bundle for any feature you want
to mirror exactly:
  rea analyze-web-bundle <reference-url>
Then inspect the returned modules/routes/IPC and adapt.