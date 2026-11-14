"""A turn that fails mid-execution, as the thread and the ledger see it.

The claim (NFR-R5) is that a failed turn does not lose conversation
data.  The mechanism is read in :mod:`albanna.services.chat_service`:
the question and answer rows are appended *together*, at the end, only
after a completion is in hand — so a turn that dies mid-execution cannot
leave a half-written answer behind it.  What it does leave is its ledger
row, started before the turn could die and updated in place, recording
the tool calls that ran before the failure.

These cases pin that with a real endpoint: round one returns a tool
call, the tool runs, and round two fails with a transient HTTP 500 the
chain retries once and then gives up on.  The mock lives on loopback.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import frappe

from albanna.providers.base import LLMConfig, ProviderConfig
from albanna.services.chat_service import ChatService, TurnRequest
from albanna.services.conversation_service import (
    append_messages,
    load_transcript,
    new_conversation,
)
from albanna.services.settings_service import AppSettings
from albanna.tests.base import AlbannaTestCase

MOCK_PORT = 18412
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"
MOCK_MODEL = "mock-mid-turn"

#: Round one: the model asks for a listing.  The tool runs, its result
#: becomes part of the transcript, and the next round calls the provider
#: again — which is where the failure is staged.
_TOOL_CALL_SSE = (
    b'data: {"model": "mock-mid-turn", "choices": [{"delta": {"tool_calls": '
    b'[{"index": 0, "id": "call-r5", "type": "function", "function": '
    b'{"name": "list_docs", "arguments": "{\\"doctype\\": \\"Role\\"}"}}]}, '
    b'"finish_reason": null}]}\n\n'
    b'data: {"model": "mock-mid-turn", "choices": [{"delta": {}, '
    b'"finish_reason": "tool_calls"}]}\n\n'
    b"data: [DONE]\n\n"
)


class _MidTurnFailureHandler(BaseHTTPRequestHandler):
    """First call of a turn: a tool call.  Every call after: HTTP 500."""

    calls = 0

    def do_POST(self):  # noqa: N802 - http.server's name
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        type(self).calls += 1
        if type(self).calls == 1:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(_TOOL_CALL_SSE)))
            self.end_headers()
            self.wfile.write(_TOOL_CALL_SSE)
        else:
            body = json.dumps({"error": {"message": "collapsed in round two"}}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def _settings() -> AppSettings:
    return AppSettings(
        enabled=True,
        provider=ProviderConfig(
            kind="openai", base_url=MOCK_BASE, model=MOCK_MODEL, timeout=5
        ),
        fallback=None,
        widget_position="bottom-right",
        max_tool_rounds=5,
        history_limit=50,
        turn_timeout=120,
        turns_per_minute=60,
        system_prompt="",
    )


class TestAPartialTurn(AlbannaTestCase):
    @classmethod
    def setUpClass(cls):
        cls._server = HTTPServer(("127.0.0.1", MOCK_PORT), _MidTurnFailureHandler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls.owner = "albanna.test.partial.owner@albanna.dev"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("User", self.owner):
            user = frappe.new_doc("User")
            user.email = self.owner
            user.first_name = "Albanna"
            user.last_name = "Test"
            user.flags.ignore_permissions = True
            user.insert()
        got = frappe.get_doc("User", self.owner)
        got.flags.ignore_permissions = True
        got.add_roles("Sales User", "Albanna User")
        frappe.db.commit()

    def tearDown(self):
        _MidTurnFailureHandler.calls = 0
        if getattr(self, "_conversation", None):
            frappe.db.delete("Albanna Message", {"parent": self._conversation})
            frappe.db.delete("Albanna Conversation", {"name": self._conversation})
            frappe.db.commit()
        super().tearDown()

    def test_a_turn_that_fails_after_a_tool_leaves_the_thread_whole(self):
        """The thread keeps exactly what it had; the ledger says what ran."""

        frappe.set_user(self.owner)
        conversation = new_conversation(self.owner, "test|partial|turn|")
        before = [
            {"role": "user", "content": "an earlier question"},
            {"role": "assistant", "content": "an earlier answer"},
        ]
        append_messages(conversation, before)
        self._conversation = conversation

        with mock.patch(
            "albanna.services.settings_service.get_settings", return_value=_settings()
        ):
            service = ChatService()
            outcome = service.run(
                TurnRequest(
                    question="a question that will fail in its second round",
                    conversation_id=conversation,
                    stream=True,
                ),
                emit=lambda event: None,
            )

        self.assertFalse(outcome.ok)
        # The reader's sentence is words, not the provider's detail; the
        # detail belongs to the ledger row.
        self.assertNotIn("collapsed", outcome.error)

        # The thread is whole: the failed turn's question was never
        # appended half-done, and nothing of the turn's is missing
        # either — append happens once, at the end, with the answer.
        transcript = load_transcript(conversation)
        self.assertEqual(
            [(row["role"], row["content"]) for row in transcript],
            [("user", "an earlier question"), ("assistant", "an earlier answer")],
        )

        # The ledger row records what happened, including the tool that
        # ran before the failure and the provider's own detail.
        row = frappe.get_doc("Albanna Chat Log", service._audit_name)
        self.assertEqual(row.status, "error")
        self.assertEqual(row.tool_calls, 1)
        self.assertEqual(row.conversation, conversation)
        self.assertIn("collapsed in round two", row.error_message)
