"""The reach-back tool, as the thread actually holds it.

The handler's contract, against a real thread of real rows: page 0 of
the browse mode is the window's edge (the messages immediately behind
what the model already sees), positions are absolute, the search is a
plain contains-match over the whole thread, and the ceilings hold.

Site tests: they need the message table and the settings document.
"""

from __future__ import annotations

import json
from unittest import mock

import frappe

from albanna.providers.base import ProviderConfig
from albanna.services.conversation_service import append_messages, new_conversation
from albanna.services.settings_service import AppSettings
from albanna.tests.base import AlbannaTestCase
from albanna.tools import history
from albanna.tools.base import Principal, ToolContext


def _settings(history_limit: int) -> AppSettings:
    return AppSettings(
        enabled=True,
        provider=ProviderConfig(
            kind="openai", base_url="http://127.0.0.1:59998/v1", model="m", timeout=5
        ),
        fallback=None,
        widget_position="bottom-right",
        max_tool_rounds=5,
        history_limit=history_limit,
        turn_timeout=120,
        turns_per_minute=60,
        system_prompt="",
    )


def _context(conversation: str) -> ToolContext:
    return ToolContext(
        principal=Principal(user="albanna.test.history@albanna.dev", roles=frozenset()),
        site="test.localhost",
        conversation=conversation,
    )


class TestReachBack(AlbannaTestCase):
    OWNER = "albanna.test.history@albanna.dev"

    def setUp(self):
        super().setUp()
        if not frappe.db.exists("User", self.OWNER):
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = self.OWNER
                user.first_name = "Albanna"
                user.last_name = "History"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        frappe.set_user(self.OWNER)
        self._conversation = None
        self._pages: list[str] = []

    def tearDown(self):
        if self._conversation:
            frappe.db.delete("Albanna Message", {"parent": self._conversation})
            frappe.db.delete("Albanna Conversation", {"name": self._conversation})
            frappe.db.commit()
        super().tearDown()

    def _thread(self, count: int, prefix: str = "msg") -> str:
        self._conversation = new_conversation(self.OWNER, "test|history|")
        rows = []
        for i in range(1, count + 1):
            role = "user" if i % 2 else "assistant"
            rows.append({"role": role, "content": f"{prefix} {i}"})
        append_messages(self._conversation, rows)
        return self._conversation

    def _read(self, thread: str, **arguments) -> dict:
        raw = history.read_thread_history(
            context=_context(thread),
            **arguments,
        )
        return json.loads(raw)

    def test_page_zero_is_the_windows_edge(self):
        """The newest messages the model cannot see are page zero."""
        thread = self._thread(45)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["total"], 45)
        self.assertEqual(payload["data"]["behind"], 35)
        # Page 0: the twenty immediately behind the window's edge — the
        # newest the model cannot see — oldest of the page first.
        positions = [m["position"] for m in payload["data"]["messages"]]
        self.assertEqual(positions, list(range(16, 36)))
        self.assertIn("msg 16", payload["data"]["messages"][0]["content"])
        self.assertIn("page=1", json.dumps(payload["hints"]), "the older edge was not announced")

    def test_the_next_page_goes_further_back(self):
        thread = self._thread(45)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread, page=1)

        positions = [m["position"] for m in payload["data"]["messages"]]
        # Page 0 held 16..35; page 1 holds 1..15, the thread's first.
        self.assertEqual(positions, list(range(1, 16)))
        self.assertNotIn("page=2", json.dumps(payload["hints"]), "there is nothing older than the first message")

    def test_positions_are_absolute_and_say_so(self):
        thread = self._thread(14)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread)

        self.assertEqual(payload["data"]["messages"][0]["position"], 1)
        self.assertIn("of 14", payload["message"])

    def test_the_search_reaches_the_whole_thread_and_escapes_the_term(self):
        thread = self._thread(30)
        # A term the LIKE language would read as a pattern: a literal
        # percent sign must match itself and nothing else.
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread, search="msg 1%")

        matched = [m["position"] for m in payload["data"]["messages"]]
        self.assertEqual(matched, [], "the percent sign was read as a wildcard")

    def test_a_search_that_finds_nothing_says_so(self):
        thread = self._thread(30)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread, search="nothing like this anywhere")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["messages"], [])
        self.assertIn("no", payload["message"].lower())

    def test_a_long_message_is_clipped_and_says_so(self):
        thread = self._thread(4, prefix="x" * 30)
        # One message far past the ceiling.
        frappe.db.sql(
            "update `tabAlbanna Message` set content = %s where parent = %s and role = 'user' limit 1",
            ("y" * 900, thread),
        )
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(2),
        ):
            payload = self._read(thread, search="yyy")

        body = payload["data"]["messages"][0]["content"]
        self.assertLessEqual(len(body), history.MESSAGE_CEILING + 80)
        self.assertIn("cut", body)

    def test_a_thread_fully_inside_the_window_has_nothing_behind(self):
        thread = self._thread(8)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data"]["messages"], [])
        self.assertEqual(payload["data"]["behind"], 0)
        self.assertIn("nothing behind the window", payload["message"])

    def test_the_tool_is_visible_to_a_plain_chat_reader(self):
        """The reach is in the registry the model is told about."""
        from albanna.core.authority import Authority
        from albanna.core.tools import TOOL_MANIFEST
        from albanna.permissions import current_principal

        principal = current_principal()
        authority = Authority(TOOL_MANIFEST, principal, None)
        self.assertIn("read_thread_history", authority.visible_names())

    def test_no_context_and_no_conversation_are_refused(self):
        raw = history.read_thread_history(context=None)
        self.assertEqual(json.loads(raw)["status"], "refused")

        context = _context("   ")
        raw = history.read_thread_history(context=context)
        self.assertEqual(json.loads(raw)["status"], "refused")

    def test_a_negative_page_is_refused(self):
        thread = self._thread(30)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread, page=-1)
        self.assertEqual(payload["status"], "refused")

    def test_a_page_beyond_the_end_is_refused(self):
        thread = self._thread(30)
        with mock.patch(
            "albanna.services.settings_service.get_settings",
            return_value=_settings(10),
        ):
            payload = self._read(thread, page=99)
        self.assertEqual(payload["status"], "refused")
