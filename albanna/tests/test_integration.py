"""The safety properties of the in-process tool path.

These tests need a site, and they are excluded from the default ``pytest``
run by the ``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna

What is here, and why each one matters
--------------------------------------
The domain suite (``test_messages``, ``test_authority``, …) is pure: no
site, no database, no network.  That is what makes it fast, and it is also
why it cannot cover the properties that only exist once a real Frappe
session is involved:

*   **The site assertion.**  A tool must never run against a site other
    than the one the request was resolved for.  ``sites/currentsite.txt``
    names the production site on this bench, so a tool that resolved its
    site from the environment would read and write the wrong database.

*   **The per-call-user marker.**  The tool functions bypass Frappe's
    permission engine by default, because the backend used to be the
    authority.  The marker is what switches that off, so a write runs under
    the caller's real permissions instead of Administrator's.

*   **The permission engine's own verdict.**  Albanna's authority layer
    asks Frappe whether a document may be created; the answer has to be
    Frappe's, not a re-implementation of it.

*   **The conversation's order.**  Messages are written with direct SQL and
    an index that has to keep going up.  An index that restarts makes the
    history interleave, and the model then reads its own earlier answer as
    though it came after the new question.

Three of these four broke while the app was being built.  None of them
announced itself; all of them were found by hand.  That is the argument for
this file.
"""

from __future__ import annotations

import frappe
import pytest
from frappe.tests.utils import FrappeTestCase

from albanna.api.conversations import (
    conversation_for_page,
    delete_conversation,
    delete_turn,
    list_conversations,
    new_conversation,
    open_conversation,
    rename_conversation,
)
from albanna.core.authority import Authority
from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import FrappePermissionChecker, current_principal
from albanna.services.conversation_service import (
    append_messages,
    ensure_conversation,
    load_messages,
    load_transcript,
    name_after_question,
    transcript_window,
)
from albanna.services.settings_service import get_settings
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

SALES_USER = "albanna.test.sales@albanna.dev"
ACCOUNTS_USER = "albanna.test.accounts@albanna.dev"


@pytest.mark.integration
class TestToolPath(FrappeTestCase):
    """The properties that only exist with a real Frappe session."""

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "Albanna"
            user.last_name = "Test"
            user.flags.ignore_permissions = True
            user.insert()
            user.add_roles(role)
        return email

    def setUp(self):
        super().setUp()
        self.sales_user = self._make_user(SALES_USER, "Sales User")
        self.accounts_user = self._make_user(ACCOUNTS_USER, "Accounts User")
        self.backend = ErpnextBackend()

    def _as(self, email: str):
        """Act as *email*, the way a request for that user would."""
        frappe.set_user(email)
        frappe.local.session.user = email
        # The role permissions are cached per request; a fresh identity needs
        # a fresh cache or it reads the previous one's.
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str, site: str | None = None) -> ToolContext:
        self._as(email)
        return ToolContext(
            principal=current_principal(),
            site=site if site is not None else frappe.local.site,
        )

    def _invoice_arguments(self) -> dict:
        """The arguments of a Sales Invoice that will insert cleanly.

        The company is named explicitly because the write tool does not
        guess it: the model is told the site's company in the system prompt
        and passes it, the same way a person filling in a form would.
        """
        companies = frappe.get_all("Company", pluck="name", limit=1)
        company = companies[0] if companies else ""
        currency = frappe.db.get_value("Company", company, "default_currency") if company else ""
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")
        return {
            "doctype": "Sales Invoice",
            "data": {
                "company": company,
                "currency": currency,
                "customer": customer,
                "items": [{"item_code": item, "qty": 1, "rate": 10}],
            },
        }

    # -- the site assertion ------------------------------------------------

    def test_a_tool_refuses_to_run_against_another_site(self):
        """A tool must not run against a site other than the request's."""
        context = self._context(self.sales_user, site="some-other-site")

        with self.assertRaises(Exception) as caught:
            self.backend.call(TOOL_MANIFEST.get("list_docs"), {"doctype": "Item"}, context)

        self.assertIn("site", str(caught.exception).lower())

    def test_a_tool_runs_against_its_own_site(self):
        context = self._context(self.sales_user)

        result = self.backend.call(TOOL_MANIFEST.get("list_docs"), {"doctype": "Item"}, context)

        self.assertTrue(result.ok, result.content)

    # -- the per-call-user marker ------------------------------------------

    def test_a_write_runs_as_the_calling_user_not_as_administrator(self):
        """The document's owner is the caller.

        This is the direct test of the per-call-user marker.  The tool
        functions default to bypassing Frappe's permission engine, which
        means they would also insert as Administrator; the marker is what
        makes the insert run as the person who asked.
        """
        arguments = self._invoice_arguments()
        self.assertTrue(arguments["data"]["customer"], "the site needs a customer")

        context = self._context(self.accounts_user)

        result = self.backend.call(TOOL_MANIFEST.get("create_doc"), arguments, context)

        self.assertTrue(result.ok, result.content)
        name = (result.data or {}).get("name")
        self.assertTrue(name, result.content)
        self.assertEqual(frappe.db.get_value("Sales Invoice", name, "owner"), self.accounts_user)

    def test_the_tool_runs_as_the_caller_and_leaves_the_session_alone(self):
        """The tool runs as the caller, and does not change who is logged in.

        The tools are the app's own, so they run in the request's own
        session and the framework applies that person's permissions to
        every read and write.  There is no marker to leave behind, and no
        window in which the tool could run as somebody else.
        """
        context = self._context(self.sales_user)

        result = self.backend.call(TOOL_MANIFEST.get("list_docs"), {"doctype": "Item"}, context)

        self.assertTrue(result.ok, result.content)
        self.assertEqual(frappe.session.user, self.sales_user)

    # -- the permission engine ---------------------------------------------

    def test_the_checker_agrees_with_frappes_own_verdict(self):
        """Albanna asks Frappe; it does not re-implement Frappe."""
        self._as(self.sales_user)
        checker = FrappePermissionChecker()

        # A Sales User creates Sales Orders, and does not create Sales
        # Invoices — that is ERPNext's own role model, not Albanna's.
        self.assertTrue(checker.can_create("Sales Order"))
        self.assertFalse(checker.can_create("Sales Invoice"))
        self.assertFalse(checker.can_create("Company"))

    def test_the_authority_refuses_a_write_the_user_may_not_make(self):
        self._as(self.sales_user)
        authority = Authority(TOOL_MANIFEST, current_principal(), FrappePermissionChecker())

        decision = authority.authorize("create_doc", {"doctype": "Company", "data": {}})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "not_permitted")

    def test_the_tool_itself_refuses_a_write_the_user_may_not_make(self):
        """Even with the authority layer bypassed, Frappe refuses the insert.

        The authority layer is the first gate; this is the second.  Both have
        to hold, because the first one is this app's code and the second one
        is the framework's.
        """
        arguments = self._invoice_arguments()
        context = self._context(self.sales_user)

        before = frappe.db.count("Sales Invoice")
        result = self.backend.call(TOOL_MANIFEST.get("create_doc"), arguments, context)

        self.assertFalse(result.ok)
        self.assertEqual(frappe.db.count("Sales Invoice"), before)

    def test_the_visible_tools_follow_the_users_roles(self):
        self._as(self.sales_user)
        authority = Authority(TOOL_MANIFEST, current_principal(), FrappePermissionChecker())
        self.assertIn("list_docs", authority.visible_names())


@pytest.mark.integration
class TestRateLimit(FrappeTestCase):
    """The per-user, per-minute ceiling on questions.

    The counter lives in the site cache with a TTL, and reading it has to
    bypass the request-local cache: that cache memoises a *miss* under the
    key the reader is given, so a counter that has not been written yet
    would read as zero for the rest of the request.  The limit would then
    apply to the first question of a request and to no others, which is the
    same as having no limit at all.
    """

    def test_the_limit_is_enforced(self):
        from albanna.services.rate_limit import SURFACE_ASK, check_turn_allowed
        from albanna.services.settings_service import get_settings

        user = "albanna.test.ratelimit@albanna.dev"
        settings = get_settings(refresh=True)
        limit = settings.turns_per_minute
        self.assertGreater(limit, 0, "the limit has to be on for this test to mean anything")

        key = f"albanna:turns:{SURFACE_ASK}:{user}"
        frappe.cache().delete_value(key)

        try:
            for _ in range(limit):
                check_turn_allowed(user, SURFACE_ASK)  # must not raise

            with self.assertRaises(frappe.TooManyRequestsError):
                check_turn_allowed(user, SURFACE_ASK)
        finally:
            frappe.cache().delete_value(key)

    def test_the_limit_is_per_user(self):
        from albanna.services.rate_limit import SURFACE_ASK, check_turn_allowed
        from albanna.services.settings_service import get_settings

        first = "albanna.test.ratelimit.a@albanna.dev"
        second = "albanna.test.ratelimit.b@albanna.dev"
        limit = get_settings(refresh=True).turns_per_minute

        for key_user in (first, second):
            frappe.cache().delete_value(f"albanna:turns:{SURFACE_ASK}:{key_user}")

        try:
            for _ in range(limit):
                check_turn_allowed(first, SURFACE_ASK)
            with self.assertRaises(frappe.TooManyRequestsError):
                check_turn_allowed(first, SURFACE_ASK)

            # A different user is not affected by the first one's spending.
            check_turn_allowed(second, SURFACE_ASK)
        finally:
            for key_user in (first, second):
                frappe.cache().delete_value(f"albanna:turns:{SURFACE_ASK}:{key_user}")


@pytest.mark.integration
class TestRemovingATurn(FrappeTestCase):
    """A reader can take a turn out of their own thread.

    The data a person asked about is theirs to erase, and a question that
    was asked wrongly is a thing they should be able to remove rather than
    scroll past.  The endpoint is the caller's own: chat access and
    ownership, the same two gates every other conversation endpoint has.
    """

    def setUp(self):
        super().setUp()
        self.owner = "albanna.test.turn.owner@albanna.dev"
        self.other = "albanna.test.turn.other@albanna.dev"
        for email in (self.owner, self.other):
            if not frappe.db.exists("User", email):
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Test"
                user.flags.ignore_permissions = True
                user.insert()
                user.add_roles("Sales User")
        frappe.db.commit()

        self._original_chat_roles = frappe.db.get_single_value("Albanna Settings", "chat_roles")
        self._allow_chat()

    def tearDown(self):
        frappe.db.set_single_value("Albanna Settings", "chat_roles", self._original_chat_roles or "")
        frappe.db.commit()
        get_settings(refresh=True)
        super().tearDown()

    def _allow_chat(self):
        doc = frappe.get_single("Albanna Settings")
        doc.chat_roles = "Desk User"
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        get_settings(refresh=True)

    def _as(self, email):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _fresh(self, page: str, user: str = "") -> str:
        """A conversation on *page*, with nothing in it.

        Each test gets its own page, because a conversation is found by
        page: a shared page would mean every test appends to the one
        before it.  And the page is emptied first, because a test that
        has run before left its turns behind, and a test must not depend
        on what the last run left.
        """
        conversation = ensure_conversation(user or self.owner, page)
        frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (conversation,))
        return conversation

    def _thread(self, page: str = ""):
        """A conversation with two turns."""
        conversation = self._fresh(page or f"test|turn|{self.id()}|")
        append_messages(
            conversation,
            [
                {"role": "user", "content": "first question"},
                {"role": "assistant", "content": "first answer"},
            ],
        )
        append_messages(
            conversation,
            [
                {"role": "user", "content": "second question"},
                {"role": "assistant", "content": "second answer"},
            ],
        )
        return conversation

    def test_a_turn_is_the_question_and_the_answer_it_brought(self):
        self._as(self.owner)
        conversation = self._thread()

        transcript = load_transcript(conversation)
        names = [row["name"] for row in transcript]
        self.assertTrue(all(names), "every stored message can be named")

        result = delete_turn(conversation=conversation, message=names[0])

        self.assertEqual(result["removed"], 2)
        self.assertEqual(
            [row["content"] for row in result["messages"]],
            ["second question", "second answer"],
        )

    def test_naming_the_answer_removes_the_question_too(self):
        self._as(self.owner)
        conversation = self._thread()

        transcript = load_transcript(conversation)
        result = delete_turn(conversation=conversation, message=transcript[1]["name"])

        self.assertEqual(result["removed"], 2)
        self.assertEqual(
            [row["content"] for row in result["messages"]],
            ["second question", "second answer"],
        )

    def test_the_turn_that_is_left_is_still_a_whole_thread(self):
        self._as(self.owner)
        conversation = self._thread()

        transcript = load_transcript(conversation)
        delete_turn(conversation=conversation, message=transcript[2]["name"])

        remaining = load_transcript(conversation)
        self.assertEqual(
            [row["content"] for row in remaining],
            ["first question", "first answer"],
        )

    def test_another_user_may_not_remove_a_turn(self):
        conversation = self._thread()
        transcript = load_transcript(conversation)

        self._as(self.other)
        with self.assertRaises(frappe.PermissionError):
            delete_turn(conversation=conversation, message=transcript[0]["name"])

    def test_a_message_that_is_not_there_is_refused(self):
        self._as(self.owner)
        conversation = self._thread()

        with self.assertRaises(frappe.DoesNotExistError):
            delete_turn(conversation=conversation, message="nothing-at-all")

    def test_a_message_from_another_conversation_is_refused(self):
        self._as(self.owner)
        first = self._thread()
        second = self._fresh(f"test|turn|{self.id()}|other|")
        append_messages(second, [{"role": "user", "content": "elsewhere"}])

        names = [row["name"] for row in load_transcript(second)]

        with self.assertRaises(frappe.DoesNotExistError):
            delete_turn(conversation=first, message=names[0])

    def test_the_rows_that_were_written_can_be_named(self):
        """The turn is told what it wrote, so that it can be addressed."""
        conversation = self._fresh(f"test|turn|{self.id()}|written|", user="Administrator")
        written = append_messages(
            conversation,
            [
                {"role": "user", "content": "a question"},
                {"role": "assistant", "content": "an answer"},
            ],
        )

        self.assertEqual(len(written), 2)
        names = [name for name, _role in written]
        self.assertEqual(len(set(names)), 2, "the rows have distinct names")

        stored = [row["name"] for row in load_transcript(conversation)]
        self.assertEqual(stored, names)


@pytest.mark.integration
class TestConversationOwnership(FrappeTestCase):
    """A conversation belongs to the person who started it.

    The rows are read with direct SQL, which does not consult the
    permission hooks, so the check has to be explicit.  Without it, a caller
    who knows another user's conversation name can read their history.
    """

    def setUp(self):
        super().setUp()
        self.owner = "albanna.test.owner@albanna.dev"
        self.other = "albanna.test.other@albanna.dev"
        for email in (self.owner, self.other):
            if not frappe.db.exists("User", email):
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Test"
                user.flags.ignore_permissions = True
                user.insert()
                user.add_roles("Sales User")
        frappe.db.commit()

        # The conversation endpoints refuse anybody who may not chat, and on
        # a fresh site nobody may: the chat roles are empty until an
        # administrator sets them.  The suite sets them, so it does not
        # depend on how the site happens to be configured.
        self._original_chat_roles = frappe.db.get_single_value("Albanna Settings", "chat_roles")
        self._allow_chat()

    def tearDown(self):
        frappe.db.set_single_value("Albanna Settings", "chat_roles", self._original_chat_roles or "")
        frappe.db.commit()
        get_settings(refresh=True)
        super().tearDown()

    def _allow_chat(self):
        """Let a Desk User chat, which is the shipped configuration."""
        doc = frappe.get_single("Albanna Settings")
        doc.chat_roles = "Desk User"
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        get_settings(refresh=True)

    def _as(self, email):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def test_the_owner_may_open_their_own_conversation(self):
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, "test|own|")

        result = open_conversation(conversation=conversation)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["conversation"]["name"], conversation)

    def test_another_user_may_not_open_it(self):
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, "test|private|")

        self._as(self.other)
        with self.assertRaises(frappe.PermissionError):
            open_conversation(conversation=conversation)

    def test_another_user_may_not_rename_it(self):
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, "test|rename|")

        self._as(self.other)
        with self.assertRaises(frappe.PermissionError):
            rename_conversation(conversation=conversation, title="mine now")

    def test_another_user_may_not_delete_it(self):
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, "test|delete|")

        self._as(self.other)
        with self.assertRaises(frappe.PermissionError):
            delete_conversation(conversation=conversation)

        # And it is still there.
        self._as(self.owner)
        self.assertTrue(frappe.db.exists("Albanna Conversation", conversation))

    def test_the_list_shows_only_the_callers_conversations(self):
        self._as(self.owner)
        mine = ensure_conversation(self.owner, "test|mine|")
        self._as(self.other)
        theirs = ensure_conversation(self.other, "test|theirs|")

        self._as(self.owner)
        names = [c["name"] for c in list_conversations(limit=50)["conversations"]]
        self.assertIn(mine, names)
        self.assertNotIn(theirs, names)

    def test_a_conversation_that_does_not_exist_is_refused(self):
        self._as(self.owner)
        with self.assertRaises(frappe.DoesNotExistError):
            open_conversation(conversation="nope")


@pytest.mark.integration
class TestNewConversation(FrappeTestCase):
    """The panel's "New" button, and the conversation it makes.

    The button used to clear the panel and nothing else.  The server
    resolves a page's conversation *by page*, so the next question landed
    back in the thread the reader was trying to leave: the screen was
    empty and the assistant was not.
    """

    def setUp(self):
        super().setUp()
        self.owner = "albanna.test.new@albanna.dev"
        if not frappe.db.exists("User", self.owner):
            user = frappe.new_doc("User")
            user.email = self.owner
            user.first_name = "Albanna"
            user.last_name = "Test"
            user.flags.ignore_permissions = True
            user.insert()
            user.add_roles("Desk User")
        frappe.db.commit()

        self._original_chat_roles = frappe.db.get_single_value("Albanna Settings", "chat_roles")
        doc = frappe.get_single("Albanna Settings")
        doc.chat_roles = "Desk User"
        doc.flags.ignore_permissions = True
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        get_settings(refresh=True)

    def tearDown(self):
        frappe.db.set_single_value("Albanna Settings", "chat_roles", self._original_chat_roles or "")
        frappe.db.commit()
        get_settings(refresh=True)
        super().tearDown()

    def _as(self, email):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _page(self, label):
        """A page identity this run has not used before.

        A conversation is found by its page, and the conversations outlive
        the test run, so a fixed identity would find the last run's
        conversation and count its messages.
        """
        return f"test|{label}|{frappe.generate_hash(length=8)}|"

    def test_new_makes_a_second_conversation_on_the_same_page(self):
        self._as(self.owner)
        page = self._page("new")
        first = ensure_conversation(self.owner, page)

        second = new_conversation(page=page)["conversation"]

        self.assertNotEqual(first, second)
        self.assertTrue(frappe.db.exists("Albanna Conversation", second))
        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", second, "page"),
            page,
        )

    def test_a_new_conversation_belongs_to_the_caller(self):
        self._as(self.owner)
        second = new_conversation(page=self._page("owned"))["conversation"]

        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", second, "user"),
            self.owner,
        )

    def test_the_thread_the_button_leaves_is_untouched(self):
        self._as(self.owner)
        page = self._page("join")
        first = ensure_conversation(self.owner, page)
        append_messages(first, [{"role": "user", "content": "the first question"}])

        second = new_conversation(page=page)["conversation"]

        self.assertNotEqual(first, second)
        # The thread the reader left is still there, with its question in
        # it, and the new one is empty.
        self.assertEqual(len(load_messages(first, 20)), 1)
        self.assertEqual(len(load_messages(second, 20)), 0)

    def test_a_question_carrying_the_new_id_joins_the_new_thread(self):
        self._as(self.owner)
        page = self._page("carry")
        first = ensure_conversation(self.owner, page)
        append_messages(first, [{"role": "user", "content": "the first question"}])

        second = new_conversation(page=page)["conversation"]
        append_messages(second, [{"role": "user", "content": "the second question"}])

        # The panel carries the id, so the question goes to the thread the
        # reader asked for and not to the page's other one.
        self.assertEqual(len(load_messages(first, 20)), 1)
        self.assertEqual(len(load_messages(second, 20)), 1)

    def test_a_new_conversation_is_told_it_has_no_title_yet(self):
        self._as(self.owner)
        conversation = new_conversation(page=self._page("untitled"))["conversation"]

        titles = [c["title"] for c in list_conversations(limit=50)["conversations"]]
        self.assertIn("", titles)

        opened = open_conversation(conversation=conversation)
        self.assertEqual(opened["conversation"]["title"], "")

    def test_the_first_question_names_an_untitled_conversation(self):
        self._as(self.owner)
        conversation = new_conversation(page=self._page("naming"))["conversation"]

        name_after_question(conversation, "How many open orders are there?")

        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", conversation, "title"),
            "How many open orders are there?",
        )

    def test_the_page_s_thread_is_the_one_the_panel_shows(self):
        self._as(self.owner)
        page = self._page("follow")
        conversation = ensure_conversation(self.owner, page, title="the first question")
        append_messages(conversation, [{"role": "user", "content": "the first question"}])

        found = conversation_for_page(page=page)

        self.assertEqual(found["conversation"], conversation)
        self.assertEqual(len(found["messages"]), 1)
        self.assertEqual(found["messages"][0]["content"], "the first question")

    def test_a_page_with_no_thread_has_nothing_to_show(self):
        self._as(self.owner)
        found = conversation_for_page(page=self._page("empty"))

        self.assertEqual(found["conversation"], "")
        self.assertEqual(found["messages"], [])

    def test_asking_what_is_there_does_not_create_a_thread(self):
        self._as(self.owner)
        page = self._page("untouched")
        conversation_for_page(page=page)

        # Nothing was created, so a question on this page starts one.
        created = ensure_conversation(self.owner, page)
        self.assertTrue(frappe.db.exists("Albanna Conversation", created))

    def test_the_newest_thread_on_a_page_is_the_one_shown(self):
        self._as(self.owner)
        page = self._page("newest")
        first = ensure_conversation(self.owner, page, title="the first thread")
        second = new_conversation(page=page)["conversation"]

        found = conversation_for_page(page=page)

        self.assertEqual(found["conversation"], second)
        self.assertNotEqual(found["conversation"], first)

    def test_a_renamed_conversation_keeps_its_name(self):
        self._as(self.owner)
        conversation = new_conversation(page=self._page("renamed"))["conversation"]
        rename_conversation(conversation=conversation, title="The one I want")

        name_after_question(conversation, "How many open orders are there?")

        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", conversation, "title"),
            "The one I want",
        )


@pytest.mark.integration
class TestSettings(FrappeTestCase):
    """The settings, and the two ways they used to fail silently.

    A role name that is not a role was ignored, so a typo left the people
    an administrator had chosen unable to chat, with nothing saying why.
    And a provider with no base URL was not one the app would call, even
    though the request code had a default for it — so a deployment that
    followed the instructions had no provider at all.
    """

    def _restore(self, fieldname, value):
        frappe.db.set_single_value("Albanna Settings", fieldname, value or "")
        frappe.db.commit()
        get_settings(refresh=True)

    def test_a_role_name_that_is_not_a_role_is_refused(self):
        original = frappe.db.get_single_value("Albanna Settings", "chat_roles")
        try:
            doc = frappe.get_single("Albanna Settings")
            doc.chat_roles = "Desk User\nNot A Role At All"
            with self.assertRaises(frappe.ValidationError) as caught:
                doc.save(ignore_permissions=True)
            self.assertIn("Not A Role At All", str(caught.exception))
        finally:
            self._restore("chat_roles", original)

    def test_a_real_role_is_accepted(self):
        original = frappe.db.get_single_value("Albanna Settings", "chat_roles")
        try:
            doc = frappe.get_single("Albanna Settings")
            doc.chat_roles = "System Manager"
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        finally:
            self._restore("chat_roles", original)

    def test_a_provider_with_no_base_url_uses_the_provider_default(self):
        from albanna.providers.openai import OpenAIProvider

        original = frappe.db.get_single_value("Albanna Settings", "base_url")
        original_kind = frappe.db.get_single_value("Albanna Settings", "provider_kind")
        try:
            frappe.db.set_single_value("Albanna Settings", "base_url", "")
            frappe.db.set_single_value("Albanna Settings", "provider_kind", "openai")
            frappe.db.commit()
            get_settings(refresh=True)

            settings = get_settings()

            self.assertEqual(settings.provider.base_url, OpenAIProvider.default_base_url)
            self.assertTrue(settings.provider.usable)
        finally:
            frappe.db.set_single_value("Albanna Settings", "base_url", original or "")
            frappe.db.set_single_value(
                "Albanna Settings", "provider_kind", original_kind or ""
            )
            frappe.db.commit()
            get_settings(refresh=True)

    def test_a_provider_with_no_model_is_refused_by_the_test(self):
        from albanna.api.provider import test_provider

        with self.assertRaises(frappe.ValidationError):
            test_provider(kind="openai", base_url="https://example.invalid", model="")


@pytest.mark.integration
class TestTouchedDocuments(FrappeTestCase):
    """The documents a tool call looked at.

    They are what the panel turns into links, so that an answer is a
    doorway into the Desk.  The names come from the tools, so a name in
    the answer is a link only when it *is* a document name.
    """

    def _call(self, name, arguments):
        from albanna.core.messages import ToolCall

        return ToolCall(id="call-1", name=name, arguments=arguments)

    def _as(self, email):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def setUp(self):
        super().setUp()
        self.sales_user = "albanna.test.docs@albanna.dev"
        if not frappe.db.exists("User", self.sales_user):
            user = frappe.new_doc("User")
            user.email = self.sales_user
            user.first_name = "Albanna"
            user.last_name = "Test"
            user.flags.ignore_permissions = True
            user.insert()
            user.add_roles("Sales User")
        frappe.db.commit()

    def test_a_read_reports_the_document_it_read(self):
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call("get_doc", {"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"})
        result = ToolResult.success("Read it", data={"name": "SAL-ORD-2026-00001"})

        self.assertEqual(
            touched_documents(call, result),
            [{"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"}],
        )

    def test_a_listing_reports_the_documents_it_returned(self):
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call("list_docs", {"doctype": "Sales Order"})
        result = ToolResult.success(
            "Found 2",
            data=[{"name": "SAL-ORD-2026-00001"}, {"name": "SAL-ORD-2026-00002"}],
        )

        self.assertEqual(
            touched_documents(call, result),
            [
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"},
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"},
            ],
        )

    def test_a_write_reports_the_document_it_created(self):
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call("create_doc", {"doctype": "Sales Order", "data": {}})
        result = ToolResult.success(
            "Created it",
            data={"doctype": "Sales Order", "name": "SAL-ORD-2026-00009"},
        )

        self.assertEqual(
            touched_documents(call, result),
            [{"doctype": "Sales Order", "name": "SAL-ORD-2026-00009"}],
        )

    def test_a_tool_with_no_doctype_reports_nothing(self):
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call("run_report", {"report": "Sales Register"})
        result = ToolResult.success("Done", data={"rows": [{"name": "x"}]})

        self.assertEqual(touched_documents(call, result), [])

    def test_a_tool_call_reports_the_documents_it_looked_at(self):
        """The event the panel reads carries the documents.

        This is the whole path, with the real tool: the tool runs, and the
        event that comes out of it names the documents it read.
        """
        from albanna.core.authority import Authority
        from albanna.core.messages import ToolCall
        from albanna.core.tools import TOOL_MANIFEST
        from albanna.permissions import FrappePermissionChecker, current_principal
        from albanna.services.chat_service import ChatService

        self._as(self.sales_user)
        principal = current_principal()
        authority = Authority(TOOL_MANIFEST, principal, FrappePermissionChecker())

        events: list[dict] = []
        call = ToolCall(
            id="call-1",
            name="list_docs",
            arguments={"doctype": "Item", "limit": 3},
        )

        result = ChatService()._run_tool(
            call,
            authority,
            principal,
            frappe.local.site,
            list(TOOL_MANIFEST.all()),
            events.append,
        )

        self.assertTrue(result.ok, result.content)

        done = [event for event in events if event.get("event") == "tool_done"]
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0]["documents"], done[0])
        for document in done[0]["documents"]:
            self.assertEqual(document["doctype"], "Item")
            self.assertTrue(document["name"])

    def test_the_documents_survive_a_stored_conversation(self):
        """A conversation opened again still links to the documents.

        The documents are stored with the tool call, so that the answer
        in a conversation from yesterday links to the same documents the
        answer named.
        """
        import json

        conversation = ensure_conversation("Administrator", "test|documents|")
        append_messages(
            conversation,
            [
                {
                    "role": "user",
                    "content": "which orders are open?",
                },
                {
                    "role": "assistant",
                    "content": "Two of them.",
                    "tool_calls": json.dumps(
                        [
                            {
                                "name": "list_docs",
                                "ok": True,
                                "summary": "Found 2 Sales Order",
                                "documents": [
                                    {"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"},
                                    {"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"},
                                ],
                            }
                        ]
                    ),
                },
            ],
        )

        transcript = load_transcript(conversation)

        documents = transcript[1]["tools"][0]["documents"]
        self.assertEqual(
            documents,
            [
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"},
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"},
            ],
        )

    def test_a_stored_document_that_is_not_one_is_dropped(self):
        import json

        conversation = ensure_conversation("Administrator", "test|bad-documents|")
        append_messages(
            conversation,
            [
                {
                    "role": "assistant",
                    "content": "Something.",
                    "tool_calls": json.dumps(
                        [
                            {
                                "name": "list_docs",
                                "ok": True,
                                "documents": [
                                    {"doctype": "Sales Order"},
                                    {"name": "SAL-ORD-2026-00001"},
                                    "not a document",
                                    {"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"},
                                ],
                            }
                        ]
                    ),
                },
            ],
        )

        transcript = load_transcript(conversation)

        self.assertEqual(
            transcript[0]["tools"][0]["documents"],
            [{"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"}],
        )

    def test_a_name_is_reported_once(self):
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call("list_docs", {"doctype": "Sales Order"})
        result = ToolResult.success(
            "Found 2",
            data=[{"name": "SAL-ORD-2026-00001"}, {"name": "SAL-ORD-2026-00001"}],
        )

        self.assertEqual(
            touched_documents(call, result),
            [{"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"}],
        )


@pytest.mark.integration
class TestConversationOrder(FrappeTestCase):
    """The messages of a conversation, in the order they were said."""

    def test_the_messages_are_stored_in_the_order_they_were_said(self):
        conversation = ensure_conversation("Administrator", "test|order|")

        append_messages(conversation, [{"role": "user", "content": "first question"}])
        append_messages(conversation, [{"role": "assistant", "content": "first answer"}])
        append_messages(conversation, [{"role": "user", "content": "second question"}])
        append_messages(conversation, [{"role": "assistant", "content": "second answer"}])

        loaded = load_messages(conversation, 20)

        self.assertEqual(
            [(m.role, m.content) for m in loaded],
            [
                ("user", "first question"),
                ("assistant", "first answer"),
                ("user", "second question"),
                ("assistant", "second answer"),
            ],
        )

    def test_a_conversation_belongs_to_its_owner(self):
        conversation = ensure_conversation("Administrator", "test|owner|")
        self.assertEqual(frappe.db.get_value("Albanna Conversation", conversation, "user"), "Administrator")

    def test_the_index_keeps_going_up(self):
        conversation = ensure_conversation("Administrator", "test|index|")
        append_messages(conversation, [{"role": "user", "content": "one"}])
        append_messages(conversation, [{"role": "assistant", "content": "two"}])

        rows = frappe.db.sql(
            "select idx from `tabAlbanna Message` where parent = %s order by idx asc",
            (conversation,),
        )
        indexes = [row[0] for row in rows]

        self.assertEqual(len(indexes), 2)
        self.assertEqual(indexes, sorted(indexes))
        self.assertEqual(len(set(indexes)), len(indexes))


@pytest.mark.integration
class TestTranscriptWindow(FrappeTestCase):
    """A conversation is read in windows, not all at once.

    A conversation of two hundred messages is twenty thousand nodes, and
    the widget drew all of them.  So the server hands out windows — the
    newest messages, and the page behind them on request — and says
    whether there is more.
    """

    def _conversation(self, turns: int = 6):
        """A conversation with *turns* questions and answers."""
        conversation = ensure_conversation("Administrator", f"test|window|{self.id()}|")
        frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (conversation,))
        for turn in range(turns):
            append_messages(
                conversation,
                [
                    {"role": "user", "content": f"question {turn}"},
                    {"role": "assistant", "content": f"answer {turn}"},
                ],
            )
        return conversation

    def test_the_window_is_the_newest_messages(self):
        conversation = self._conversation()

        transcript = load_transcript(conversation, limit=4)

        self.assertEqual(
            [message["content"] for message in transcript],
            ["question 4", "answer 4", "question 5", "answer 5"],
        )

    def test_the_window_is_bounded_in_the_query(self):
        """Not sliced in Python: the whole conversation is not read to
        show a part of it."""
        conversation = self._conversation()

        transcript = load_transcript(conversation, limit=2)

        self.assertEqual(len(transcript), 2)

    def test_the_older_page_is_the_one_below_the_index(self):
        conversation = self._conversation()

        # The window is the newest four messages; the page behind it is
        # the four below the oldest of those.
        window = load_transcript(conversation, limit=4)
        oldest = window[0]["idx"]

        older = load_transcript(conversation, limit=4, before_idx=oldest)

        self.assertEqual(
            [message["content"] for message in older],
            ["question 2", "answer 2", "question 3", "answer 3"],
        )

    def test_every_message_carries_the_index_it_is_stored_at(self):
        conversation = self._conversation()

        transcript = load_transcript(conversation, limit=100)

        self.assertEqual([message["idx"] for message in transcript], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_the_window_says_how_many_the_conversation_holds(self):
        conversation = self._conversation(turns=4)

        window = transcript_window(conversation, limit=2)

        self.assertEqual(window["total"], 8)
        self.assertEqual(len(window["messages"]), 2)

    def test_the_window_says_whether_there_is_more_behind_it(self):
        conversation = self._conversation(turns=4)

        window = transcript_window(conversation, limit=2)
        self.assertTrue(window["has_more"], "there are older messages behind the window")

    def test_a_whole_conversation_has_nothing_behind_it(self):
        conversation = self._conversation(turns=4)

        window = transcript_window(conversation, limit=100)
        self.assertFalse(window["has_more"])

    def test_an_empty_conversation_has_nothing_behind_it(self):
        conversation = ensure_conversation("Administrator", f"test|window|empty|{self.id()}|")

        window = transcript_window(conversation, limit=10)

        self.assertEqual(window["messages"], [])
        self.assertEqual(window["total"], 0)
        self.assertFalse(window["has_more"])


@pytest.mark.integration
class TestRequestPrivacy(FrappeTestCase):
    """The user's own words stay in the conversation.

    Frappe's request logger appends the request's parsed parameters to
    every log record the request emits, so a question that arrives as a
    request parameter is copied into the site log — outside the
    conversation, where deleting the conversation does not remove it.
    """

    def test_the_decorator_redacts_before_the_body_runs(self):
        from albanna.privacy import redacted_request_text

        @redacted_request_text("question")
        def endpoint(question=""):
            return question

        frappe.local.form_dict = {"question": "a secret question", "cmd": "x"}

        # The endpoint still receives the real value: the redaction is
        # of the log, not of the request.
        self.assertEqual(endpoint(question="a secret question"), "a secret question")
        self.assertEqual(frappe.local.form_dict["question"], "[redacted]")
        self.assertEqual(frappe.local.form_dict["cmd"], "x", "other parameters are untouched")

    def test_a_page_description_is_redacted_too(self):
        from albanna.privacy import redacted_request_text

        @redacted_request_text("question", "page_context")
        def endpoint(question="", page_context=""):
            return question

        frappe.local.form_dict = {"question": "q", "page_context": '{"selection": "private"}'}

        endpoint(question="q", page_context='{"selection": "private"}')

        self.assertEqual(frappe.local.form_dict["page_context"], "[redacted]")

    def test_the_chat_endpoints_are_decorated(self):
        """Every endpoint that takes the user's words redacts them.

        A gate that some endpoints remember and others forget is a gate
        that fails open, and so is a redaction.
        """
        from albanna.api.chat import ask, ask_stream

        for endpoint in (ask, ask_stream):
            self.assertTrue(
                getattr(endpoint, "__wrapped__", None) is not None,
                f"{endpoint.__name__} does not redact the request",
            )

    def test_a_refused_turn_leaves_no_question_in_the_log(self):
        """A refused turn is exactly the one that ends up in the log with
        the question in it, so the redaction happens before the gate."""
        from albanna.api.chat import ask

        # A user with no chat access: the gate refuses, and the turn
        # never runs.
        frappe.set_user("albanna.test.nobody@albanna.dev")
        frappe.local.session.user = "albanna.test.nobody@albanna.dev"
        frappe.local.form_dict = {"question": "a secret question"}

        with self.assertRaises(frappe.PermissionError):
            ask(question="a secret question")

        self.assertEqual(frappe.local.form_dict["question"], "[redacted]")


@pytest.mark.integration
class TestUsageSummary(FrappeTestCase):
    """What the chat has cost, and where it went.

    The ledger is written by every turn.  The summary is the read side
    of it, and it is the operator's: a System Manager, and nobody else.
    """

    def setUp(self):
        super().setUp()
        self.user = "albanna.test.usage@albanna.dev"
        if not frappe.db.exists("User", self.user):
            user = frappe.new_doc("User")
            user.email = self.user
            user.first_name = "Albanna"
            user.last_name = "Usage"
            user.flags.ignore_permissions = True
            user.insert()
            user.add_roles("Sales User")
        frappe.db.commit()
        self._clear_ledger()

    def tearDown(self):
        self._clear_ledger()
        frappe.db.commit()
        super().tearDown()

    def _clear_ledger(self):
        frappe.db.sql("delete from `tabAlbanna Chat Log`")

    def _turn(self, model="a-model", cost=1.0, tokens=100, status="ok", estimated=0):
        doc = frappe.new_doc("Albanna Chat Log")
        doc.user = self.user
        doc.provider = "a-provider"
        doc.model = model
        doc.status = status
        doc.input_tokens = tokens
        doc.output_tokens = 0
        doc.cost = cost
        doc.estimated = estimated
        doc.flags.ignore_permissions = True
        doc.insert()

    def test_a_month_with_no_turns_says_so(self):
        from albanna.services.usage_service import usage_summary

        summary = usage_summary()

        self.assertEqual(summary["turns"], 0)
        self.assertEqual(summary["cost"], 0)
        self.assertEqual(summary["by_model"], [])

    def test_the_totals_are_the_months(self):
        from albanna.services.usage_service import usage_summary

        self._turn(model="a-model", cost=1.5, tokens=100)
        self._turn(model="a-model", cost=2.5, tokens=200)
        self._turn(model="another-model", cost=1.0, tokens=50, status="error")

        summary = usage_summary()

        self.assertEqual(summary["turns"], 3)
        self.assertEqual(summary["cost"], 5.0)
        self.assertEqual(summary["tokens"], 350)
        self.assertEqual(summary["errors"], 1)

    def test_the_breakdown_says_which_model_and_which_user(self):
        from albanna.services.usage_service import usage_summary

        self._turn(model="a-model", cost=1.0)
        self._turn(model="a-model", cost=3.0)
        self._turn(model="another-model", cost=2.0)

        summary = usage_summary()

        models = {entry["name"]: entry for entry in summary["by_model"]}
        self.assertEqual(models["a-model"]["turns"], 2)
        self.assertEqual(models["a-model"]["cost"], 4.0)
        self.assertEqual(models["another-model"]["cost"], 2.0)

        users = {entry["name"]: entry for entry in summary["by_user"]}
        self.assertIn(self.user, users)

    def test_a_turn_the_provider_did_not_price_is_counted_apart(self):
        """A cost of zero is not a free turn when the tokens are not
        zero: it is a cost nobody knows."""
        from albanna.services.usage_service import usage_summary

        self._turn(model="a-model", cost=0.0, tokens=100)
        self._turn(model="a-model", cost=2.0, tokens=100)

        summary = usage_summary()

        self.assertEqual(summary["uncosted_turns"], 1)
        self.assertEqual(summary["cost"], 2.0)

    def test_an_estimated_count_says_so(self):
        from albanna.services.usage_service import usage_summary

        self._turn(estimated=1)

        summary = usage_summary()

        self.assertTrue(summary["estimated"], "an estimate must not look measured")

    def test_only_a_system_manager_may_read_the_ledger(self):
        from albanna.api.usage import summary as api_summary

        frappe.set_user(self.user)
        frappe.local.session.user = self.user
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

        with self.assertRaises(frappe.PermissionError):
            api_summary()


@pytest.mark.integration
class TestTheCostOfATurn(FrappeTestCase):
    """The cost in the ledger is the site's own.

    A provider reports tokens, and money only when its API happens to
    carry a price — and that price is in the provider's currency.  So the
    site prices the turn itself, in its own currency, and the provider's
    own number is kept beside it.
    """

    def setUp(self):
        super().setUp()
        self.conversation = ensure_conversation("Administrator", "test|cost|turn|")
        frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (self.conversation,))
        frappe.db.sql("delete from `tabAlbanna Chat Log`")

    def tearDown(self):
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        frappe.db.commit()
        super().tearDown()

    def _log(self, usage, price_per_million=0.0):
        from albanna.providers.base import Usage
        from albanna.services.chat_service import ChatService

        ChatService()._log(
            self.conversation,
            "Administrator",
            "a-provider",
            "a-model",
            1,
            [],
            usage,
            0.0,
            "ok",
            "",
            "",
            price_per_million=price_per_million,
        )
        frappe.db.commit()
        return frappe.db.get_value(
            "Albanna Chat Log",
            {"conversation": self.conversation},
            ["cost", "provider_cost", "input_tokens", "output_tokens"],
            as_dict=True,
        )

    def test_a_turn_with_no_price_costs_nothing_known(self):
        from albanna.providers.base import Usage

        row = self._log(Usage(input_tokens=1000, output_tokens=500, cost=0.25))

        self.assertEqual(row.cost, 0, "a turn with no price has no known cost")
        self.assertEqual(row.provider_cost, 0.25, "but the provider's own number is kept")

    def test_a_turn_is_priced_in_the_sites_own_currency(self):
        from albanna.providers.base import Usage

        row = self._log(
            Usage(input_tokens=500_000, output_tokens=500_000, cost=0.25),
            price_per_million=3.0,
        )

        self.assertEqual(row.cost, 3.0, "a million tokens at three riyals")
        self.assertEqual(row.provider_cost, 0.25, "and the provider's number beside it")
        self.assertEqual(row.input_tokens, 500_000)


@pytest.mark.integration
class TestTheSettingsRefuseNonsense(FrappeTestCase):
    """The settings are free text, and a typo in them is caught.

    The role fields and the extra options are typed by hand.  A name
    that is not a role is ignored silently, and JSON that is not JSON
    would be ignored silently too — leaving the operator with an option
    that is simply not there, and nothing anywhere saying why.
    """

    def _validate(self, options):
        doc = frappe.get_single("Albanna Settings")
        doc.extra_options = options
        doc.validate()

    def test_options_that_are_not_json_are_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._validate('{"setCacheKey": "True",}')

    def test_options_that_are_not_an_object_are_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._validate('["setCacheKey"]')

    def test_options_that_are_json_are_accepted(self):
        self._validate('{"setCacheKey": "True"}')
        self._validate("")

    def test_the_parsed_options_reach_the_provider(self):
        from albanna.core.options import parse_options

        self.assertEqual(
            parse_options('{"setCacheKey": "True"}'),
            {"setCacheKey": True},
            "a string that spells a boolean is the boolean it means",
        )


@pytest.mark.integration
class TestATruncatedAnswer(FrappeTestCase):
    """An answer that was cut off says so.

    The reader must not be left with an answer that stops mid-sentence
    and looks finished.  The provider's reason travels with the answer,
    the log records it, and the panel says it.
    """

    def test_the_turn_says_the_answer_was_cut_off(self):
        """The provider's reason travels with the answer."""
        from albanna.core.messages import Message
        from albanna.providers.base import Completion, Usage
        from albanna.services.chat_service import ChatService, TurnRequest

        completion = Completion(
            message=Message(role="assistant", content="half an answer"),
            provider="openai",
            model="a-model",
            usage=Usage(input_tokens=10, output_tokens=5),
            truncated=True,
        )

        service = ChatService()

        def fake_complete(config, messages, tools, emit, stream):
            return completion

        service._complete = fake_complete

        outcome = service.run(
            TurnRequest(question="a question that needs no tools", page="test|truncation|")
        )

        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.truncated, "the turn must say the answer was cut off")
        self.assertEqual(outcome.reply, "half an answer")

    def test_the_log_records_the_cut_off(self):
        from albanna.core.messages import Message
        from albanna.providers.base import Completion, Usage
        from albanna.services.chat_service import ChatService, TurnRequest

        completion = Completion(
            message=Message(role="assistant", content="half an answer"),
            provider="openai",
            model="a-model",
            usage=Usage(input_tokens=10, output_tokens=5),
            truncated=True,
        )

        service = ChatService()
        service._complete = lambda config, messages, tools, emit, stream: completion

        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        outcome = service.run(
            TurnRequest(question="a question that was cut off", page="test|truncation|log|")
        )
        frappe.db.commit()

        row = frappe.db.get_value(
            "Albanna Chat Log",
            {"conversation": outcome.conversation_id},
            ["status"],
            as_dict=True,
        )
        self.assertEqual(row.status, "truncated", "the ledger must say the answer was cut off")
