"""Compact context session service for Albanna (OpenCode-style compaction)."""
from __future__ import annotations

from typing import Any, List, Tuple

# ---- token estimation (cheap heuristic; replace with tiktoken if available) ----
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def messages_token_count(messages: List[dict]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(m.get("content") or "")
        total += 4  # role/overhead
    return total


# ---- compaction policy ----
DEFAULT_THRESHOLD_RATIO = 0.75   # compact when >75% of context used
KEEP_RECENT = 6                  # keep last N raw messages
SUMMARIZE_PROMPT = (
    "Summarize the conversation below into a concise context note. "
    "Preserve: user goals, decisions made, tool results that matter, "
    "open questions, and any document IDs referenced. "
    "Drop: greetings, repetition, verbose tool output. "
    "Return only the summary text.\n\nCONVERSATION:\n{body}"
)


def should_compact(messages: List[dict], context_limit: int,
                   threshold: float = DEFAULT_THRESHOLD_RATIO) -> bool:
    return messages_token_count(messages) > int(context_limit * threshold)


def split_for_compaction(messages: List[dict], keep_recent: int = KEEP_RECENT
                        ) -> Tuple[List[dict], List[dict]]:
    if len(messages) <= keep_recent:
        return [], list(messages)
    return list(messages[:-keep_recent]), list(messages[-keep_recent:])


def build_summary_prompt(old_messages: List[dict]) -> str:
    body = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in old_messages)
    return SUMMARIZE_PROMPT.format(body=body)


def compact(messages: List[dict], context_limit: int, llm_call,
            keep_recent: int = KEEP_RECENT) -> Tuple[str, List[dict]]:
    """Return (summary_text, new_message_list).

    llm_call: callable(prompt: str) -> str  (provider completion, sync)
    """
    old, recent = split_for_compaction(messages, keep_recent)
    if not old:
        return "", list(messages)
    prompt = build_summary_prompt(old)
    summary = llm_call(prompt).strip()
    new_msgs = [{"role": "system", "content": f"Context summary (compacted): {summary}"}]
    new_msgs.extend(recent)
    return summary, new_msgs


# ---- Frappe integration sketch ----
"""
In Albanna, add to Albanna Conversation doctype: `summary` (Long Text),
`compacted_at` (Datetime), `compacted_message_count` (Int).

In services/chat_service.py, before building the prompt:
    msgs = load_messages(conv, settings.history_limit)
    if should_compact(msgs, model_context_limit):
        summary, msgs = compact(msgs, model_context_limit, provider.complete)
        save_summary(conv, summary, len(msgs))
Then pass `msgs` to the provider.

Trigger compaction proactively (OpenCode-style) when tokens > threshold,
not only at failure, so the next turn starts small.
"""