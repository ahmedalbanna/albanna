# ADR-0003: The canonical message format is OpenAI's

Status: **Accepted**
Date: 2026-10-21

## Context

Albanna talks to three kinds of model endpoint: OpenAI-compatible,
Ollama's native API, and Anthropic's native API.  Each has its own message
shape, its own tool-call shape, and its own way of pairing a tool result
with the call that asked for it.

The connector this app grew out of chose Ollama's shape as canonical.  That
was defensible then; it is not the best choice now, and the reason is
specific.

## Decision

**The canonical format is OpenAI's chat-completions shape.**

```json
{"role": "assistant", "content": "…", "tool_calls": [
  {"id": "call_x", "type": "function",
   "function": {"name": "list_docs", "arguments": "{\"doctype\": \"Item\"}"}}]}
```

Two properties decided it, and both are about *not losing information when
the provider changes*:

1. **Tool calls carry an id.**  A tool result is paired with the assistant
   turn that asked for it by that id.  Ollama's native format has no id and
   matches a result to its call by *tool name* — which misroutes the moment
   a turn calls the same tool twice.  That is not exotic: "list the
   customers, then list the suppliers" is two calls with different names,
   but "show me SO-0001 and its items" is one tool called twice, and a
   canonical format without ids cannot represent that turn faithfully.
2. **The arguments are carried as a mapping, not a string.**  Every provider
   wants a different encoding — OpenAI wants a JSON *string*, Ollama and
   Anthropic want an *object* — so the encoding is the adapter's job.  The
   canonical form holds the parsed mapping, and an unparseable argument
   string is a provider-side error rather than a silent empty call.

The rule that follows: **the provider adapter is the only place that knows
a wire format exists.**  It translates in and translates back, and nothing
else ever sees a foreign shape.

## Consequences

* The OpenAI adapter is nearly free — the canonical shape *is* its wire
  shape — which matters, because it is the provider this app is pointed at
  today.
* The Anthropic adapter does the most work: the system prompt is a
  top-level parameter rather than a message, tool schemas are
  `input_schema`, and several tool results belong in the *same* user turn.
* The Ollama adapter drops the tool-call ids on the way out, and
  reconstructs the pairings from the order of the messages — which Ollama
  does preserve.
* A stored history is provider-independent, so a fallback to a different
  vendor mid-turn works.  A mixed history would not.
