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

import contextlib
import json

import frappe
import pytest

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
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext
from albanna.tools.erpnext import PROTECTED_FIELDS

SALES_USER = "albanna.test.sales@albanna.dev"
ACCOUNTS_USER = "albanna.test.accounts@albanna.dev"


@pytest.mark.integration
class TestToolPath(AlbannaTestCase):
    """The properties that only exist with a real Frappe session."""

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            # The user is created as the administrator: the framework makes
            # the session's own settings for a new user, so a session left
            # as somebody else — a user another test made, and one this
            # transaction has already rolled back — fails the insert for a
            # reason that has nothing to do with what this test is about.
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Test"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role, "Albanna User")
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
class TestRateLimit(AlbannaTestCase):
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
class TestRemovingATurn(AlbannaTestCase):
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
            user = frappe.get_doc("User", email)
            user.flags.ignore_permissions = True
            user.add_roles("Sales User", "Albanna User")
        frappe.db.commit()

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
class TestConversationOwnership(AlbannaTestCase):
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
            user = frappe.get_doc("User", email)
            user.flags.ignore_permissions = True
            user.add_roles("Sales User", "Albanna User")
        frappe.db.commit()

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

    def test_the_service_itself_refuses_another_users_conversation(self):
        """The check is in the service, and not only in the endpoint.

        The rows are deleted with direct SQL and the document is deleted
        with its permissions ignored, so a caller that forgot the check
        would delete somebody else's history without any complaint from
        the framework.  The endpoint is not the only thing that may call
        these.
        """
        from albanna.services import conversation_service

        self._as(self.owner)
        conversation = ensure_conversation(self.owner, "test|service|")
        append_messages(conversation, [{"role": "user", "content": "a question"}])
        transcript = load_transcript(conversation)

        self._as(self.other)
        for call in (
            lambda: conversation_service.rename_conversation(conversation, "mine now"),
            lambda: conversation_service.delete_turn(conversation, transcript[0]["name"]),
            lambda: conversation_service.delete_conversation(conversation),
        ):
            with self.assertRaises(frappe.PermissionError):
                call()

        # And it is all still there.
        self._as(self.owner)
        self.assertTrue(frappe.db.exists("Albanna Conversation", conversation))
        self.assertTrue(load_transcript(conversation))

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
class TestNewConversation(AlbannaTestCase):
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
            user = frappe.get_doc("User", self.owner)
            user.flags.ignore_permissions = True
            user.add_roles("Desk User", "Albanna User")
            frappe.db.commit()

    def tearDown(self):
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
class TestSettings(AlbannaTestCase):
    """The settings, and the way a provider with no base URL used to fail.

    A provider with no base URL was not one the app would call, even
    though the request code had a default for it — so a deployment that
    followed the instructions had no provider at all.
    """

    def _restore(self, fieldname, value):
        frappe.db.set_single_value("Albanna Settings", fieldname, value or "")
        frappe.db.commit()
        get_settings(refresh=True)

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
            frappe.db.set_single_value("Albanna Settings", "provider_kind", original_kind or "")
            frappe.db.commit()
            get_settings(refresh=True)

    def test_a_provider_with_no_model_is_refused_by_the_test(self):
        from albanna.api.provider import test_provider

        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            with self.assertRaises(frappe.ValidationError):
                test_provider(kind="openai", base_url="https://example.invalid", model="")
        finally:
            frappe.set_user(former)


@pytest.mark.integration
class TestTouchedDocuments(AlbannaTestCase):
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
        user = frappe.get_doc("User", self.sales_user)
        user.flags.ignore_permissions = True
        user.add_roles("Sales User", "Albanna User")
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

    def test_a_bulk_change_names_the_documents_it_changed(self):
        """A bulk change names no document in its arguments.

        It names a condition, and the documents it touched are the ones
        the tool found.  A write that changed fifty tickets changed
        fifty tickets, and the reader is entitled to know which — the
        audit row is what answers *did it happen?* after a turn dies.
        """
        from albanna.services.chat_service import touched_documents
        from albanna.tools.base import ToolResult

        call = self._call(
            "bulk_update_doc",
            {
                "doctype": "Sales Order",
                "filters": [["status", "=", "Draft"]],
                "data": {"priority": "High"},
            },
        )
        result = ToolResult.success(
            "Changed 2",
            data={
                "doctype": "Sales Order",
                "changed": 2,
                "names": ["SAL-ORD-2026-00001", "SAL-ORD-2026-00002"],
            },
        )

        self.assertEqual(
            touched_documents(call, result),
            [
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00001"},
                {"doctype": "Sales Order", "name": "SAL-ORD-2026-00002"},
            ],
        )


@pytest.mark.integration
class TestConversationOrder(AlbannaTestCase):
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
        self.assertEqual(
            frappe.db.get_value("Albanna Conversation", conversation, "user"), "Administrator"
        )

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
class TestTranscriptWindow(AlbannaTestCase):
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

        self.assertEqual(
            [message["idx"] for message in transcript], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        )

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
class TestRequestPrivacy(AlbannaTestCase):
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
class TestTheChatLogHoldsNoSecret(AlbannaTestCase):
    """The log is read by operators, exported, and copied off the host.

    A provider's refusal often quotes the key it refused — "Incorrect API
    key provided: sk-…" — and that message is the turn's error message.
    So the key has to be taken out of the row before it is written.
    """

    def setUp(self):
        super().setUp()
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        super().tearDown()

    def test_a_key_quoted_by_the_provider_does_not_reach_the_log(self):
        import time

        from albanna.services.chat_service import ChatService, TurnAudit
        from albanna.services.settings_service import get_settings

        settings = get_settings(refresh=True)
        key = settings.provider.api_key
        if not key:
            self.skipTest("this site has no provider key to leak")

        ChatService()._log(
            TurnAudit(
                conversation="",
                user="Administrator",
                provider="a-provider",
                model="a-model",
                status="error",
                error_class="provider_error",
                error_message=f"Incorrect API key provided: {key}",
                started=time.monotonic(),
            )
        )

        rows = frappe.db.sql_list("select error_message from `tabAlbanna Chat Log`")
        self.assertTrue(rows, "the turn must have been logged")
        for message in rows:
            self.assertNotIn(key, message, "the provider's key reached the chat log")
            self.assertIn("[redacted]", message, "the key must be masked, not dropped")


@pytest.mark.integration
class TestUsageSummary(AlbannaTestCase):
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
        user = frappe.get_doc("User", self.user)
        user.flags.ignore_permissions = True
        user.add_roles("Sales User", "Albanna User")
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
class TestTheCostOfATurn(AlbannaTestCase):
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
        from albanna.services.chat_service import ChatService, TurnAudit

        ChatService()._log(
            TurnAudit(
                conversation=self.conversation,
                user="Administrator",
                provider="a-provider",
                model="a-model",
                rounds=1,
                tool_calls=[],
                usage=usage,
                started=0.0,
                status="ok",
                price_per_million=price_per_million,
            )
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
class TestTheSettingsRefuseNonsense(AlbannaTestCase):
    """The settings are free text, and a typo in them is caught.

    The extra options are typed by hand.  JSON that is not JSON would be
    ignored silently — leaving the operator with an option that is simply
    not there, and nothing anywhere saying why.
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
class TestATruncatedAnswer(AlbannaTestCase):
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


@pytest.mark.integration
class TestTheUpdatePath(AlbannaTestCase):
    """Changing a document that already exists.

    A tool set that could only make things and never change them would
    leave the person who mistyped a field with no way to fix it — and they
    would ask the assistant, because it is the one that made the mistake.

    These are the properties of that path: who the change runs as, what it
    refuses, and — the one that is easy to get wrong — what a failure
    leaves behind.
    """

    def setUp(self):
        super().setUp()
        self.sales_user = self._make_user("albanna.test.update@albanna.dev", "Sales User")
        self.accounts_user = self._make_user(
            "albanna.test.update.accounts@albanna.dev", "Accounts User"
        )
        self.backend = ErpnextBackend()

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            # The user is created as the administrator.  The session may
            # still be somebody else — a user another test made, and one
            # this transaction has already rolled back — and the
            # framework makes the session's own settings for a new user,
            # which then points at a user that is not there.
            former = frappe.session.user
            frappe.set_user("Administrator")
            try:
                user = frappe.new_doc("User")
                user.email = email
                user.first_name = "Albanna"
                user.last_name = "Update"
                user.flags.ignore_permissions = True
                user.insert()
            finally:
                frappe.set_user(former)
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role, "Albanna User")
        return email

    def _customer(self) -> str:
        """A customer of this test's own, to change.

        Each test makes its own, because the framework commits the
        transaction between test *classes* and rolls it back at the end of
        one — so the tests in a class share a transaction, and a customer
        one of them changed would be a changed customer for the next.  The
        name carries the test's name, so two of them cannot collide.
        """
        name = f"Albanna Update Test {self._testMethodName}"
        if not frappe.db.exists("Customer", name):
            customer = frappe.new_doc("Customer")
            customer.customer_name = name
            customer.customer_type = "Company"
            customer.customer_group = self._customer_group()
            customer.flags.ignore_permissions = True
            customer.insert()
        return name

    def _customer_group(self) -> str:
        """A customer group that exists on this site."""
        group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
        self.assertTrue(group, "the site needs a customer group")
        return group

    def _as(self, email: str):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str) -> ToolContext:
        self._as(email)
        return ToolContext(principal=current_principal(), site=frappe.local.site)

    def _update(self, context, data, name=None, doctype="Customer"):
        return self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {"doctype": doctype, "name": name or self._customer(), "data": data},
            context,
        )

    # -- it works ----------------------------------------------------------

    def test_an_update_changes_the_document(self):
        context = self._context(self.sales_user)
        marker = "Albanna update test marker"
        customer = self._customer()

        result = self._update(context, {"customer_details": marker}, name=customer)

        self.assertTrue(result.ok, result.content)
        self.assertEqual(
            frappe.db.get_value("Customer", customer, "customer_details"),
            marker,
        )

    def test_an_update_runs_as_the_caller(self):
        """The change is made by the person who asked for it.

        The framework stamps the document with the session user, so the
        stamp is the evidence: it cannot be anything else, because the
        write goes through ``doc.save()`` with the caller's own
        permissions.
        """
        context = self._context(self.sales_user)
        customer = self._customer()

        result = self._update(
            context, {"customer_details": "Albanna update test marker"}, name=customer
        )

        self.assertTrue(result.ok, result.content)
        self.assertEqual(
            frappe.db.get_value("Customer", customer, "modified_by"),
            self.sales_user,
        )

    def test_the_result_says_what_it_changed(self):
        """A change nobody can check is not a report.

        The result names the fields, so the assistant can say which field
        it changed rather than "something was updated".
        """
        context = self._context(self.sales_user)
        customer = self._customer()

        result = self._update(
            context, {"customer_details": "Albanna update test marker"}, name=customer
        )

        self.assertTrue(result.ok, result.content)
        self.assertIn("customer_details", result.content)
        self.assertIn(customer, result.content)

    def test_a_change_that_changes_nothing_is_not_a_write(self):
        """Writing the value a document already has is not a change.

        Saving it would touch the modified timestamp, run every hook on
        the document, and tell the reader that something was done when
        nothing was.
        """
        context = self._context(self.sales_user)
        customer = self._customer()
        current = frappe.db.get_value("Customer", customer, "customer_details") or ""

        result = self._update(context, {"customer_details": current}, name=customer)

        self.assertTrue(result.ok, result.content)
        self.assertIn("nothing was changed", result.content)

    # -- what it refuses ---------------------------------------------------

    def test_a_submitted_document_is_refused(self):
        """A submitted document is read-only, and the chat says so.

        The framework would let a server-side save rewrite a submitted
        document — the guard is in the form, not in ``db_update`` — so the
        guard is in the tool, and the refusal names the way a person does
        it.

        The account asking is one that may read the document: a Sales
        User cannot read a Sales Invoice at all, and what that account
        gets is the other refusal (below).
        """
        name = self._submitted_invoice()
        context = self._context(self.accounts_user)

        result = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {"doctype": "Sales Invoice", "name": name, "data": {"remarks": "changed"}},
            context,
        )

        self.assertFalse(result.ok)
        self.assertIn("submitted", result.error.lower())
        self.assertNotEqual(frappe.db.get_value("Sales Invoice", name, "remarks"), "changed")

    def test_a_document_the_caller_may_not_read_is_refused_as_a_read(self):
        """A document the account cannot see is not even a submitted one.

        The refusal a read would have produced is the one that is given,
        so the answer does not tell the account that the document exists
        or what state it is in.  A Sales User cannot read a Sales Invoice
        on this site, which makes it the honest case.
        """
        name = self._submitted_invoice()
        context = self._context(self.sales_user)

        result = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {"doctype": "Sales Invoice", "name": name, "data": {"remarks": "changed"}},
            context,
        )

        self.assertFalse(result.ok)
        self.assertIn("could not be read", result.error.lower())
        self.assertNotIn("submitted", result.error.lower())
        self.assertNotEqual(frappe.db.get_value("Sales Invoice", name, "remarks"), "changed")

    def test_a_framework_field_is_refused(self):
        """The framework's own fields are not the assistant's to set.

        ``Document.update()`` assigns ``name`` first, so a data object
        that carried one would rename the document rather than change it.
        """
        context = self._context(self.sales_user)
        customer = self._customer()

        result = self._update(context, {"name": "Renamed By The Chat"}, name=customer)

        self.assertFalse(result.ok)
        self.assertIn("framework", result.error.lower())
        self.assertEqual(
            frappe.db.get_value("Customer", customer, "name"),
            customer,
        )

    def test_a_read_only_field_is_refused(self):
        """A field the form will not let a person change is not changed either.

        The chat must not be a way around that: it would make the
        assistant the only actor on the site who can set a field nobody
        else can.
        """
        meta = frappe.get_meta("Customer")
        read_only = [
            df.fieldname
            for df in meta.fields
            if df.read_only and df.fieldname not in PROTECTED_FIELDS
        ]
        if not read_only:
            self.skipTest("this site has no read-only field on Customer")

        context = self._context(self.sales_user)

        result = self._update(context, {read_only[0]: "something"})

        self.assertFalse(result.ok)
        self.assertIn("read-only", result.error.lower())

    def test_a_field_that_does_not_exist_is_refused(self):
        context = self._context(self.sales_user)

        result = self._update(context, {"nonsense_field": "x"})

        self.assertFalse(result.ok)
        self.assertIn("unknown field", result.error.lower())

    def test_a_document_that_does_not_exist_is_reported_as_such(self):
        """ "Not found" and "not permitted" are different answers.

        Telling a reader that a document they named does not exist is
        useful.  Telling them they may not change a document that does not
        exist is a wall.
        """
        context = self._context(self.sales_user)

        result = self._update(context, {"customer_details": "x"}, name="No Such Customer")

        self.assertFalse(result.ok)
        self.assertIn("not found", result.error.lower())

    def test_a_user_who_may_not_write_is_refused(self):
        """Even with the authority layer bypassed, Frappe refuses the change.

        The authority layer is the first gate; this is the second.  Both
        have to hold, because the first is this app's code and the second
        is the framework's.
        """
        name = self._draft_invoice()
        context = self._context(self.sales_user)

        result = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {"doctype": "Sales Invoice", "name": name, "data": {"remarks": "changed"}},
            context,
        )

        self.assertFalse(result.ok)
        self.assertNotEqual(frappe.db.get_value("Sales Invoice", name, "remarks"), "changed")

    # -- what a failure leaves behind -------------------------------------

    def test_a_failed_update_does_not_undo_an_earlier_write(self):
        """A write that fails must not take the turn's other writes with it.

        A rollback is transaction-wide unless it is given a savepoint, and
        a transaction-wide rollback in the middle of a turn undoes
        *everything* the turn has done so far — including a document the
        assistant has already told the reader it created.  The reader would
        be told about a document that does not exist.
        """
        context = self._context(self.sales_user)
        name = f"Albanna Write Isolation Test {self._testMethodName}"

        created = self.backend.call(
            TOOL_MANIFEST.get("create_doc"),
            {
                "doctype": "Customer",
                "data": {
                    "customer_name": name,
                    "customer_type": "Company",
                    "customer_group": self._customer_group(),
                },
            },
            context,
        )
        self.assertTrue(created.ok, created.content)
        name = (created.data or {}).get("name")
        self.assertTrue(name, created.content)

        # A change that cannot succeed: the name is mandatory.
        failed = self._update(context, {"customer_name": ""}, name=name)

        self.assertFalse(failed.ok)
        self.assertTrue(
            frappe.db.exists("Customer", name),
            "the earlier write was undone by the later failure",
        )

    # -- helpers -----------------------------------------------------------

    def _submitted_invoice(self) -> str:
        """A submitted Sales Invoice on the site.

        One that is already there, rather than one this test submits: the
        submission of a Sales Invoice runs whatever hooks the site's apps
        put on it, and a test that depends on the site's app set is a test
        that breaks when the app set changes.
        """
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 1}, "name")
        if not name:
            self.skipTest("this site has no submitted Sales Invoice")
        return name

    def _draft_invoice(self) -> str:
        """A Sales Invoice on the site that is still in draft."""
        name = frappe.db.get_value("Sales Invoice", {"docstatus": 0}, "name")
        if name:
            return name

        company = frappe.get_all("Company", pluck="name", limit=1)[0]
        currency = frappe.db.get_value("Company", company, "default_currency")
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        item = frappe.db.get_value("Item", {"disabled": 0}, "name")

        invoice = frappe.new_doc("Sales Invoice")
        invoice.company = company
        invoice.currency = currency
        invoice.customer = customer
        invoice.append("items", {"item_code": item, "qty": 1, "rate": 10})
        invoice.flags.ignore_permissions = True
        invoice.insert()
        return invoice.name


@pytest.mark.integration
class TestWriteApproval(TestToolPath):
    """A write waits for the reader before it runs."""

    def setUp(self):
        super().setUp()
        self.accounts_user = self._make_user("accounts-approval@example.com", "Accounts User")

    def _make_policy(self, email: str, override: str = "always"):
        frappe.clear_cache()
        frappe.set_user("Administrator")
        frappe.local.session.user = "Administrator"
        frappe.local.role_permissions = {}
        frappe.local.perms = {}
        existing = frappe.db.get_value("Albanna User Policy", {"user": email}, "name")
        if existing:
            frappe.delete_doc("Albanna User Policy", existing, force=True)
        doc = frappe.get_doc(
            {
                "doctype": "Albanna User Policy",
                "user": email,
                "confirm_writes_override": {"always": "Always", "never": "Never"}.get(
                    override, override
                ),
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()

    def _restore_policy(self, email: str):
        frappe.clear_cache()
        frappe.set_user("Administrator")
        frappe.local.session.user = "Administrator"
        frappe.local.role_permissions = {}
        frappe.local.perms = {}
        existing = frappe.db.get_value("Albanna User Policy", {"user": email}, "name")
        if existing:
            frappe.delete_doc("Albanna User Policy", existing, force=True)
        frappe.db.commit()

    def _completion(self):
        from albanna.core.messages import Message, ToolCall
        from albanna.providers.base import Completion, Usage

        return Completion(
            message=Message(
                role="assistant",
                content="I will create the invoice.",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="create_doc",
                        arguments=self._invoice_arguments(),
                    ),
                ),
            ),
            provider="openai",
            model="a-model",
            usage=Usage(input_tokens=10, output_tokens=5),
        )

    def _run(self, email, decision):
        self._make_policy(email, "always")
        try:
            self._as(email)

            # The reader's decision is fed back through the emit callback,
            # so the worker's poll exits at once with the chosen answer.
            # It is recorded the way the endpoint records it, against the
            # pending write the worker left behind.
            from albanna.services.approval import record_decision

            def make_emit(decision):
                def emit(event):
                    if event.get("event") == "confirm":
                        with contextlib.suppress(Exception):
                            record_decision(
                                event["request_id"],
                                email,
                                decision,
                                ttl=60,
                            )

                return emit

            from albanna.services.chat_service import ChatService, TurnRequest

            service = ChatService()

            def fake_complete(config, messages, tools, emit, stream):
                return self._completion()

            service._complete = fake_complete

            outcome = service.run(
                TurnRequest(question="create an invoice", page="test|approval|"),
                emit=make_emit(decision),
            )
            return outcome
        finally:
            self._restore_policy(email)

    def test_an_approved_write_runs(self):
        outcome = self._run(self.accounts_user, "approve")
        self.assertTrue(outcome.ok, "an approved write must complete the turn")
        self.assertFalse(
            any(t.get("approved") is False for t in outcome.tool_calls),
            "no tool call may be recorded as declined",
        )
        # The approval must not merely be recorded — the write itself must
        # have *run*.  A flag that cannot be set on a frozen result turned
        # into a tool failure once, and the turn still looked successful:
        # the ledger said ok, the document was never made.
        self.assertTrue(
            any(t.get("ok") for t in outcome.tool_calls),
            "the approved write must actually have run",
        )
        # And "ran" means the document exists.  A tool can report that it
        # wrote something it never wrote — the result is a sentence, and
        # the sentence is not the document.  This is the assertion that
        # would have caught it.
        created = [entry.get("created") for entry in outcome.tool_calls if entry.get("created")]
        self.assertTrue(created, "the approved write must name what it created")
        for name in created:
            self.assertTrue(
                frappe.db.exists("Sales Invoice", name),
                f"the approved write reported creating {name}, and {name} does not exist",
            )

    def test_a_declined_write_does_not_run(self):
        outcome = self._run(self.accounts_user, "reject")
        self.assertTrue(outcome.ok, "a declined write is still a completed turn")
        self.assertTrue(
            any(t.get("approved") is False for t in outcome.tool_calls),
            "the declined write must be recorded as declined",
        )

    def test_a_decision_written_after_the_first_poll_is_seen(self):
        """The reader's answer arrives *after* the worker has started waiting.

        This is the production ordering, and it is the one that broke: the
        cache keeps a *miss* in the request's local cache, so a poll that
        does not ask for ``expires=True`` reads that miss back for ever
        and the reader's approval is never seen.  The write then times out
        whatever the reader did.
        """
        from albanna.services.approval import (
            await_decision,
            record_decision,
            record_pending,
        )

        email = self.accounts_user
        request_id = "late-decision-test"

        # A clean slate: the decision is written after the first poll.
        record_pending(request_id, email, "create_doc", {"doctype": "Customer"}, ttl=60)

        polls = {"n": 0}

        def answering_sleep(_seconds):
            polls["n"] += 1
            if polls["n"] == 2:
                # The reader answers after the first miss.
                record_decision(request_id, email, "approve", ttl=60)

        decision = await_decision(
            request_id,
            email,
            timeout=5.0,
            interval=0.01,
            sleep=answering_sleep,
        )

        self.assertEqual(decision, "approve", "the decision must be seen, whatever it is")
        self.assertGreaterEqual(polls["n"], 2, "the first poll must have missed")

    def test_a_timeout_is_recorded_as_not_approved(self):
        # A decision of "timeout" is what the worker records when the
        # reader does not answer in time; seeding it simulates that path
        # without holding the test for the real two-minute window.
        outcome = self._run(self.accounts_user, "timeout")
        self.assertTrue(outcome.ok)
        self.assertTrue(
            any(t.get("approved") is False for t in outcome.tool_calls),
            "a timed-out write must be recorded as not approved",
        )

    # -- the decision is bound to the write --------------------------------

    def test_a_decision_for_a_request_nobody_is_waiting_on_is_refused(self):
        """A decision is an answer to a question somebody asked.

        The endpoint used to write the answer into a cache key and report
        success, whether or not any write was waiting for it.  So the
        answer it gave was "yes" to a question that had not been asked —
        and a caller could not tell the difference between a decision
        that was recorded and one that was not.
        """
        from albanna.api.chat import confirm_write
        from albanna.services.approval import pending_key

        self._as(self.accounts_user)
        frappe.cache().delete_value(pending_key("no-such-request"), user=self.accounts_user)

        with self.assertRaises(frappe.ValidationError):
            confirm_write(request_id="no-such-request", decision="approve")

    def test_the_second_decision_on_a_write_is_refused(self):
        """The first decision is the decision.

        The docstring said a second decision left the first in place; the
        code overwrote it.  So a reader who changed their mind, or a
        double click, could turn an approval into a refusal — or an
        approval into a second approval of a write that had already run.
        """
        from albanna.api.chat import confirm_write
        from albanna.services.approval import record_pending

        self._as(self.accounts_user)
        request_id = "one-shot-test"
        record_pending(
            request_id, self.accounts_user, "create_doc", {"doctype": "Customer"}, ttl=60
        )

        first = confirm_write(request_id=request_id, decision="approve")
        self.assertEqual(first["decision"], "approve")

        with self.assertRaises(frappe.ValidationError):
            confirm_write(request_id=request_id, decision="reject")

    def test_a_decision_by_another_account_does_not_answer_the_write(self):
        """A decision is the reader's own.

        The pending write is kept under the reader's own namespace, so
        another account's answer is not found by the worker — and the
        other account is told there is nothing to answer.
        """
        from albanna.services.approval import (
            NoPendingWrite,
            read_pending,
            record_decision,
            record_pending,
        )

        other = self._make_user("albanna.test.approval.other@example.com", "Sales User")

        self._as(self.accounts_user)
        request_id = "other-account-test"
        record_pending(
            request_id, self.accounts_user, "create_doc", {"doctype": "Customer"}, ttl=60
        )

        self._as(other)
        with self.assertRaises(NoPendingWrite):
            record_decision(request_id, other, "approve", ttl=60)

        self.assertEqual(
            read_pending(request_id, self.accounts_user).get("decision"),
            "",
            "another account's decision answered the write",
        )

    def test_a_document_that_changed_while_the_reader_decided_is_not_changed(self):
        """The reader approved a change to a document as it was.

        If the document has moved since they were asked, the change would
        land on top of somebody else's edit, and the approval would be an
        approval of something else.  So the write is refused, and the
        model is told why.
        """
        from albanna.core.messages import Message, ToolCall
        from albanna.providers.base import Completion, Usage
        from albanna.services.approval import record_decision
        from albanna.services.chat_service import ChatService, TurnRequest

        email = self.sales_user

        customer = f"Albanna Approval Test {self._testMethodName}"
        if not frappe.db.exists("Customer", customer):
            group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
            doc = frappe.new_doc("Customer")
            doc.customer_name = customer
            doc.customer_type = "Company"
            doc.customer_group = group
            doc.flags.ignore_permissions = True
            doc.insert()

        marker = "Albanna approval marker"

        completion = Completion(
            message=Message(
                role="assistant",
                content="I will change the customer.",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="update_doc",
                        arguments={
                            "doctype": "Customer",
                            "name": customer,
                            "data": {"customer_details": marker},
                        },
                    ),
                ),
            ),
            provider="openai",
            model="a-model",
            usage=Usage(input_tokens=10, output_tokens=5),
        )

        self._make_policy(email, "always")
        try:
            self._as(email)

            def emit(event):
                if event.get("event") == "confirm":
                    record_decision(event["request_id"], email, "approve", ttl=60)
                    # Somebody else changes the document while the reader
                    # is looking at the card.
                    frappe.db.set_value(
                        "Customer",
                        customer,
                        "customer_details",
                        "changed by somebody else",
                    )

            service = ChatService()
            service._complete = lambda config, messages, tools, emit, stream: completion

            outcome = service.run(
                TurnRequest(question="change the customer", page="test|approval|moved|"),
                emit=emit,
            )
        finally:
            self._restore_policy(email)

        self.assertNotEqual(
            frappe.db.get_value("Customer", customer, "customer_details"),
            marker,
            "the change landed on a document that had moved",
        )
        self.assertTrue(
            any(t.get("approved") is False for t in outcome.tool_calls),
            "a write on a document that moved must not be recorded as approved",
        )
        errors = " ".join(str(entry.get("error") or "") for entry in outcome.tool_calls)
        self.assertIn(
            "changed while the reader was deciding",
            errors,
            "the refusal must say why the write did not run",
        )

    # -- what the row knows ------------------------------------------------

    def test_the_panel_names_a_confirmed_change_that_never_ran(self):
        """The whole claim, end to end.

        A real turn asks the reader; the reader's answer goes through the
        **real endpoint**; the write does not run; and the panel — the
        reader's own polling of a turn that is gone — names the change
        the reader confirmed and says that it did not run.

        Nothing here is a hand-written row.  The row is the one the turn
        wrote as it ran, and the answer in it is the one the endpoint
        wrote, which is the only way to know that the three of them —
        worker, endpoint and panel — agree.
        """
        from albanna.api.chat import confirm_write, status
        from albanna.core.messages import Message, ToolCall
        from albanna.providers.base import Completion, Usage
        from albanna.services.chat_service import ChatService, TurnRequest

        email = self.sales_user

        customer = f"Albanna Approval Dead Turn {self._testMethodName}"
        if not frappe.db.exists("Customer", customer):
            group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
            doc = frappe.new_doc("Customer")
            doc.customer_name = customer
            doc.customer_type = "Company"
            doc.customer_group = group
            doc.flags.ignore_permissions = True
            doc.insert()

        marker = "Albanna dead turn marker"

        completion = Completion(
            message=Message(
                role="assistant",
                content="I will change the customer.",
                tool_calls=(
                    ToolCall(
                        id="call_1",
                        name="update_doc",
                        arguments={
                            "doctype": "Customer",
                            "name": customer,
                            "data": {"customer_details": marker},
                        },
                    ),
                ),
            ),
            provider="openai",
            model="a-model",
            usage=Usage(input_tokens=10, output_tokens=5),
        )

        self._make_policy(email, "always")
        try:
            self._as(email)

            def emit(event):
                if event.get("event") != "confirm":
                    return
                # The reader's answer goes through the endpoint, as it
                # does in the browser — not through the cache alone.
                confirm_write(request_id=event["request_id"], decision="approve")
                # And the document moves while they are looking at the
                # card, so the write does not run.
                frappe.db.set_value(
                    "Customer",
                    customer,
                    "customer_details",
                    "changed by somebody else",
                )

            service = ChatService()
            service._complete = lambda config, messages, tools, emit, stream: completion

            service.run(
                TurnRequest(question="change the customer", page="test|approval|dead|"),
                emit=emit,
            )
        finally:
            self._restore_policy(email)

        row = self._row_of(email)
        approvals = row["payload"].get("approvals") or []
        self.assertTrue(approvals, "the row did not record the approval")
        self.assertEqual(approvals[0].get("decision"), "approve")
        self.assertFalse(approvals[0].get("ran"), "the write did not run, and the row says it did")

        # A worker killed before it can write its final status leaves the
        # row as it was: 'running', with the payload it had written as it
        # went.  That is the state the panel reads.
        frappe.db.set_value("Albanna Chat Log", row["name"], "status", "running")
        frappe.db.commit()

        # The panel answers to the reader, so the reader is the one who
        # asks it.
        self._as(email)

        try:
            answer = status(stream_id="a-turn-that-never-finished")
        finally:
            frappe.db.delete("Albanna Chat Log", row["name"])
            frappe.db.commit()

        self.assertEqual(answer.get("status"), "error")
        self.assertIn(
            customer,
            answer["error"],
            "the panel did not name the change the reader confirmed",
        )
        self.assertIn("did not run", answer["error"])

    def _row_of(self, user: str) -> dict:
        """The reader's own audit row, with its payload."""
        rows = frappe.get_all(
            "Albanna Chat Log",
            filters={"user": user},
            fields=["name", "status", "tools"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(rows, "the turn left no audit row behind")
        row = dict(rows[0])
        row["payload"] = json.loads(row.get("tools") or "{}")
        return row

    def _run_once(self, email: str, decision: str, capture: dict | None = None):
        """A turn that proposes one write, and answers after it.

        The fake provider asks for the write once and answers in plain
        text after that — the shape of a real turn, and a fast one.  The
        reader's decision is fed back through the emit callback, the way
        the endpoint feeds it back in production.

        *capture* is filled with the row's payload **at the moment the
        reader is asked**, which is the moment the row has to know.
        """
        from albanna.core.messages import Message
        from albanna.providers.base import Completion, Usage
        from albanna.services.approval import record_decision
        from albanna.services.chat_service import ChatService, TurnRequest

        self._make_policy(email, "always")
        try:
            self._as(email)

            service = ChatService()
            asked = {"n": 0}

            def fake_complete(config, messages, tools, emit, stream):
                asked["n"] += 1
                if asked["n"] == 1:
                    return self._completion()
                return Completion(
                    message=Message(role="assistant", content="Done."),
                    provider="openai",
                    model="a-model",
                    usage=Usage(input_tokens=5, output_tokens=2),
                )

            service._complete = fake_complete

            def make_emit():
                def emit(event):
                    if event.get("event") != "confirm":
                        return
                    if capture is not None:
                        raw = frappe.db.get_value("Albanna Chat Log", service._audit_name, "tools")
                        capture["payload"] = json.loads(raw or "{}")
                        capture["request_id"] = event["request_id"]
                    record_decision(event["request_id"], email, decision, ttl=60)

                return emit

            return service.run(
                TurnRequest(question="create an invoice", page="test|approval|row|"),
                emit=make_emit(),
            )
        finally:
            self._restore_policy(email)

    def test_the_approval_is_recorded_in_the_row_before_the_reader_is_asked(self):
        """The row must know what the reader was asked, before they are asked.

        The answer arrives in a later request, and the worker may die
        between the two.  A row that learned about the approval only
        after the answer would know nothing about a change the reader
        confirmed — which is exactly the turn the panel has to explain.
        """
        seen: dict = {}

        self._run_once(self.accounts_user, "reject", capture=seen)

        approvals = (seen.get("payload") or {}).get("approvals") or []
        self.assertTrue(approvals, "the row did not record the approval it asked about")
        approval = approvals[0]
        self.assertEqual(approval.get("request_id"), seen.get("request_id"))
        self.assertEqual(approval.get("tool"), "create_doc")
        self.assertEqual(approval.get("doctype"), "Sales Invoice")

    def test_the_readers_decision_is_written_into_the_row(self):
        """The reader's answer must outlive the cache it was recorded in.

        The cache record expires with the wait it answers; the row does
        not.  So the answer is written into the row as well — otherwise
        a worker that dies after the answer leaves a row that never
        learned the reader said yes.

        The row already holds what the worker asked for, and the answer
        is *added* to it: a record that replaced the approval would hold
        the answer and lose the question, and the panel would have
        nothing to name.
        """
        from albanna.api.chat import confirm_write
        from albanna.services.approval import record_pending

        request_id = "decision-in-the-row"

        doc = frappe.new_doc("Albanna Chat Log")
        doc.user = self.accounts_user
        doc.status = "running"
        doc.tools = json.dumps(
            {
                "calls": [],
                "approvals": [
                    {
                        "request_id": request_id,
                        "tool": "create_doc",
                        "doctype": "Sales Invoice",
                        "name": "",
                    }
                ],
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()

        self._as(self.accounts_user)
        record_pending(
            request_id,
            self.accounts_user,
            "create_doc",
            {"doctype": "Sales Invoice"},
            ttl=60,
            row=doc.name,
        )

        confirm_write(request_id=request_id, decision="approve")

        payload = json.loads(frappe.db.get_value("Albanna Chat Log", doc.name, "tools") or "{}")
        approvals = payload.get("approvals") or []
        self.assertEqual(len(approvals), 1, "the decision was not written into the row")
        self.assertEqual(approvals[0].get("request_id"), request_id)
        self.assertEqual(approvals[0].get("decision"), "approve")
        self.assertEqual(approvals[0].get("tool"), "create_doc")
        self.assertEqual(approvals[0].get("doctype"), "Sales Invoice")
        self.assertTrue(approvals[0].get("decided_at"), "the answer has no timestamp")

    def test_an_approved_write_is_recorded_as_ran(self):
        """The row must not say a change never ran when it did.

        The approval and the write behind it are recorded in the same
        transaction, so the row cannot claim the reader confirmed a
        change that is in the database and never ran — which is what
        would send the reader to make the same change twice.
        """
        self._run_once(self.accounts_user, "approve")

        row = self._row_of(self.accounts_user)
        approvals = row["payload"].get("approvals") or []
        self.assertTrue(approvals, "the row did not record the approval")
        self.assertTrue(
            approvals[0].get("ran"),
            "the row says the confirmed change never ran, and it did",
        )

    def test_a_dry_run_does_not_record_the_change_as_having_run(self):
        """A dry run changes nothing, and the row must not say it did.

        The "ran" flag is what tells the panel whether a change the
        reader confirmed is in the database.  A dry run rolls the change
        back, so the flag must not be set — and if the turn dies, the
        panel says the change did not run, which is exactly true.
        """
        from albanna.services.settings_service import get_settings

        frappe.db.set_value("Albanna Settings", "Albanna Settings", "dry_run", 1)
        frappe.db.commit()
        get_settings(refresh=True)

        try:
            self._run(self.accounts_user, "approve")
        finally:
            frappe.db.set_value("Albanna Settings", "Albanna Settings", "dry_run", 0)
            frappe.db.commit()
            get_settings(refresh=True)

        row = self._row_of(self.accounts_user)
        approvals = row["payload"].get("approvals") or []
        self.assertTrue(approvals, "the row did not record the approval")
        self.assertFalse(
            approvals[0].get("ran"),
            "the row says the change ran, and a dry run changes nothing",
        )

    def test_the_turns_final_row_keeps_the_approvals(self):
        """The turn's own payload must not drop what it recorded on the way.

        The row is written twice: once as the turn runs, and once when
        it ends.  The second write carries the turn's calls and its
        timings — and must carry the approvals too, or the record of
        what the reader confirmed is lost by the turn finishing.
        """
        self._run_once(self.accounts_user, "approve")

        row = self._row_of(self.accounts_user)
        self.assertEqual(row["status"], "ok", "the turn did not finish")
        self.assertTrue(
            row["payload"].get("approvals"),
            "the finished turn's row dropped the approvals",
        )


@pytest.mark.integration
class TestDisabledToolsAreHonoured(AlbannaTestCase):
    """A tool named in the settings is hidden from everyone.

    The setting used to be a column that nobody read.  Now it narrows the
    registry both the chat service and the widget build from, so a hidden
    tool is never mentioned to the model at all.
    """

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._original = frappe.db.get_single_value("Albanna Settings", "disabled_tools")
        frappe.db.set_single_value("Albanna Settings", "disabled_tools", "create_doc, delete_doc")
        frappe.db.commit()
        get_settings(refresh=True)

    def tearDown(self):
        frappe.db.set_single_value("Albanna Settings", "disabled_tools", self._original or "")
        frappe.db.commit()
        get_settings(refresh=True)
        super().tearDown()

    def test_a_disabled_tool_is_not_offered(self):
        from albanna.services.toolset import tool_registry

        names = [s.name for s in tool_registry("Administrator").enabled()]
        self.assertNotIn("create_doc", names, "a disabled tool must not be offered")
        self.assertNotIn("delete_doc", names, "a disabled tool must not be offered")

    def test_an_enabled_tool_is_still_offered(self):
        from albanna.services.toolset import tool_registry

        names = [s.name for s in tool_registry("Administrator").enabled()]
        self.assertIn("get_doc", names, "a tool that is not disabled must remain")


@pytest.mark.integration
class TestContextEndpoints(AlbannaTestCase):
    """The list-page context endpoints: counts and nudges."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def test_count_doctype_returns_a_number(self):
        from albanna.api.context import count_doctype

        result = count_doctype("User")
        self.assertIn("count", result)
        self.assertGreaterEqual(result["count"], 1)

    def test_nudge_for_page_returns_a_message_or_empty(self):
        from albanna.api.context import nudge_for_page

        result = nudge_for_page("User")
        self.assertIn("message", result)
        # User is not an invoice doctype, so no nudge.
        self.assertEqual(result["message"], "")

    def test_nudge_for_page_refuses_unknown_doctype(self):
        from albanna.api.context import nudge_for_page

        result = nudge_for_page("NoSuchDoctype")
        self.assertIn("message", result)


@pytest.mark.integration
class TestTheSettingsHealAPlainTextKey(AlbannaTestCase):
    """A key that was stored in the clear is repaired, not refused.

    The old behaviour was to throw, which left the operator with a
    document they could not save *and* the secret still sitting in the
    table — the worst of both.  A repair that happens on the next
    ordinary save needs no operator action at all.
    """

    DOCTYPE = "Albanna Settings"
    NAME = "Albanna Settings"

    def setUp(self):
        super().setUp()
        # The settings are a Single, so writing one touches every reader
        # on the site: the test runs as the operator who owns it.
        self._original_user = frappe.session.user
        frappe.set_user("Administrator")
        self._snapshot()

    def tearDown(self):
        self._restore()
        frappe.set_user(self._original_user)
        super().tearDown()

    # -- the secret store ------------------------------------------------

    def _secret(self, fieldname):
        """What the encrypted store holds, or None."""
        from frappe.utils.password import get_decrypted_password

        return get_decrypted_password(self.DOCTYPE, self.NAME, fieldname, raise_exception=False)

    def _column(self, fieldname):
        return frappe.db.get_single_value(self.DOCTYPE, fieldname, cache=False)

    def _snapshot(self):
        self._saved = {
            fieldname: (self._secret(fieldname), self._column(fieldname))
            for fieldname in ("api_key", "fallback_api_key")
        }

    def _restore(self):
        from frappe.utils.password import remove_encrypted_password, set_encrypted_password

        for fieldname, (secret, column) in self._saved.items():
            remove_encrypted_password(self.DOCTYPE, self.NAME, fieldname)
            if secret is not None:
                set_encrypted_password(self.DOCTYPE, self.NAME, secret, fieldname)
            frappe.db.set_single_value(self.DOCTYPE, fieldname, column or "")

    # -- the tests -------------------------------------------------------

    def test_a_plain_text_key_is_encrypted_and_masked_on_save(self):
        frappe.db.set_single_value(self.DOCTYPE, "api_key", "sk-plain-text-secret")

        doc = frappe.get_single(self.DOCTYPE)
        doc.api_key = "sk-plain-text-secret"
        doc.save()

        self.assertNotIn(
            "sk-plain-text-secret",
            str(self._column("api_key") or ""),
            "the plain text must not survive in the column",
        )
        self.assertEqual(
            self._secret("api_key"),
            "sk-plain-text-secret",
            "the key must be readable from the encrypted store",
        )

    def test_a_plain_text_key_no_longer_blocks_the_save(self):
        """The regression itself: the save must go through."""
        frappe.db.set_single_value(self.DOCTYPE, "api_key", "sk-another-secret")

        doc = frappe.get_single(self.DOCTYPE)
        doc.api_key = "sk-another-secret"
        # The old code raised ValidationError here.
        doc.save()

        self.assertTrue(doc.name, "the settings document must still save")

    def test_a_mask_is_left_alone(self):
        """A saved key must not be re-encrypted as the literal asterisks."""
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(self.DOCTYPE, self.NAME, "sk-a-real-key", "api_key")

        doc = frappe.get_single(self.DOCTYPE)
        doc.api_key = "*" * 10
        doc.validate()

        self.assertEqual(
            self._secret("api_key"),
            "sk-a-real-key",
            "a mask means 'unchanged' and must not overwrite the key",
        )

    def test_the_settings_service_can_still_read_the_key(self):
        """The whole point: the reader gets the key back, not the mask."""
        from frappe.utils.password import set_encrypted_password

        set_encrypted_password(self.DOCTYPE, self.NAME, "sk-read-back", "api_key")

        settings = get_settings(refresh=True)
        self.assertEqual(settings.provider.api_key, "sk-read-back")

    def test_the_plain_text_is_never_written_to_the_table(self):
        """The stronger half of the fix: validate masks before db_insert.

        A save that only cleaned up *afterwards* would still leave the
        plain text in ``tabSingles`` for as long as the request ran.
        """
        frappe.db.set_single_value(self.DOCTYPE, "api_key", "sk-never-stored")

        doc = frappe.get_single(self.DOCTYPE)
        doc.api_key = "sk-never-stored"
        doc.validate()

        self.assertEqual(
            doc.api_key,
            "*" * 10,
            "validate must mask the value before the document is written",
        )


class TestUndo(AlbannaTestCase):
    """Taking a turn's writes back.

    Undo is the one feature in the app that *removes* something the
    assistant did, so it has to be the most careful thing in here: it must
    undo exactly what was done, and nothing else.

    The bug this class exists for: the transcript recorded a document's
    name out of the tool's envelope, and every tool names the document it
    touched — so a **read** was recorded as a creation.  The undo of a
    turn that read a document and changed it reverted the change
    correctly and then deleted the document, because the read's entry
    said "delete".  The reader pressed undo to take back a change, and
    the ticket was gone.

    The rule the app now follows: the *tool* decides what its own undo
    may be, and the stored entry only says which one it wants.  Only a
    creation may be undone by deleting it.
    """

    def setUp(self):
        super().setUp()
        self.owner = self._make_user("albanna.test.undo@albanna.dev", "Sales User")
        self.backend = ErpnextBackend()

    # -- helpers -----------------------------------------------------------

    def _make_user(self, email: str, role: str) -> str:
        if not frappe.db.exists("User", email):
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "Albanna"
            user.last_name = "Undo"
            user.flags.ignore_permissions = True
            user.insert()
        user = frappe.get_doc("User", email)
        user.flags.ignore_permissions = True
        user.add_roles(role, "Albanna User")
        frappe.db.commit()
        return email

    def _as(self, email: str):
        frappe.set_user(email)
        frappe.local.session.user = email
        frappe.local.role_permissions = {}
        frappe.local.perms = {}

    def _context(self, email: str) -> ToolContext:
        self._as(email)
        return ToolContext(principal=current_principal(), site=frappe.local.site)

    def _customer_group(self) -> str:
        group = frappe.db.get_value("Customer", {"disabled": 0}, "customer_group")
        self.assertTrue(group, "the site needs a customer group")
        return group

    def _customer(self) -> str:
        """A customer of this test's own, to read and then change."""
        name = f"Albanna Undo Test {self._testMethodName}"
        if not frappe.db.exists("Customer", name):
            customer = frappe.new_doc("Customer")
            customer.customer_name = name
            customer.customer_type = "Company"
            customer.customer_group = self._customer_group()
            customer.flags.ignore_permissions = True
            customer.insert()
        return name

    def _call(self, name, arguments):
        from albanna.core.messages import ToolCall

        return ToolCall(id="call-1", name=name, arguments=arguments)

    def _turn(self, entries: list[dict]) -> tuple[str, str]:
        """A conversation with one assistant message carrying *entries*."""
        self._as(self.owner)
        conversation = ensure_conversation(self.owner, f"test|undo|{self.id()}|")
        frappe.db.sql("delete from `tabAlbanna Message` where parent = %s", (conversation,))
        written = append_messages(
            conversation,
            [
                {
                    "role": "assistant",
                    "content": "I changed it.",
                    "tool_calls": json.dumps(entries),
                }
            ],
        )
        return conversation, written[0][0]

    # -- what is recorded --------------------------------------------------

    def test_a_read_is_not_recorded_as_a_creation(self):
        """The bug, at the place it started.

        The envelope of a read carries the name of the document it read,
        exactly as the envelope of a creation carries the name of the
        document it created.  Reading the name out of the envelope alone
        cannot tell the two apart — so the tool has to.
        """
        from albanna.services.chat_service import tool_entry
        from albanna.tools.base import ToolResult

        call = self._call("get_doc", {"doctype": "Customer", "name": "CUST-0001"})
        result = ToolResult.success(
            "Read it",
            data={"doctype": "Customer", "name": "CUST-0001"},
        )

        entry = tool_entry(call, result)

        self.assertNotIn("undo", entry, "a read must not carry an undo")
        self.assertNotIn("created", entry, "a read must not claim to have created")

    def test_a_creation_is_recorded_as_one(self):
        from albanna.services.chat_service import tool_entry
        from albanna.tools.base import ToolResult

        call = self._call("create_doc", {"doctype": "Customer", "data": {}})
        result = ToolResult.success(
            "Created it",
            data={"doctype": "Customer", "name": "CUST-0009"},
        )

        entry = tool_entry(call, result)

        self.assertEqual(entry.get("created"), "CUST-0009")
        self.assertEqual(entry["undo"]["action"], "delete")
        self.assertEqual(entry["undo"]["name"], "CUST-0009")

    def test_an_update_is_undone_by_writing_the_old_values_back(self):
        from albanna.services.chat_service import tool_entry
        from albanna.tools.base import ToolResult

        call = self._call(
            "update_doc",
            {"doctype": "Customer", "name": "CUST-0009", "data": {"customer_name": "new"}},
        )
        result = ToolResult.success(
            "Updated it",
            data={
                "doctype": "Customer",
                "name": "CUST-0009",
                "before": {"customer_name": "old"},
                "changed": {"customer_name": "new"},
            },
        )

        entry = tool_entry(call, result)

        self.assertEqual(entry["undo"]["action"], "update")
        self.assertEqual(entry["undo"]["data"], {"customer_name": "old"})

    # -- what the undo does -----------------------------------------------

    def test_the_undo_of_a_turn_that_read_and_changed_keeps_the_document(self):
        """The whole path, on a real document.

        A read and a change in one turn, exactly as the assistant does it:
        read the ticket, change the ticket.  The undo must put the field
        back — and must leave the document where it found it.
        """
        from albanna.api.conversations import undo_turn
        from albanna.services.chat_service import tool_entry

        name = self._customer()
        context = self._context(self.owner)

        read = self.backend.call(
            TOOL_MANIFEST.get("get_doc"),
            {"doctype": "Customer", "name": name},
            context,
        )
        self.assertTrue(read.ok, read.content)

        updated = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {
                "doctype": "Customer",
                "name": name,
                "data": {"customer_name": f"{name} changed"},
            },
            context,
        )
        self.assertTrue(updated.ok, updated.content)
        self.assertEqual(
            frappe.db.get_value("Customer", name, "customer_name"),
            f"{name} changed",
        )

        entries = [
            tool_entry(
                self._call("get_doc", {"doctype": "Customer", "name": name}),
                read,
            ),
            tool_entry(
                self._call(
                    "update_doc",
                    {"doctype": "Customer", "name": name, "data": {"customer_name": "x"}},
                ),
                updated,
            ),
        ]
        conversation, message = self._turn(entries)

        result = undo_turn(conversation=conversation, message=message)

        self.assertTrue(
            frappe.db.exists("Customer", name),
            "the undo deleted a document the turn had only read",
        )
        self.assertEqual(
            frappe.db.get_value("Customer", name, "customer_name"),
            name,
            "the undo did not write the old value back",
        )
        self.assertEqual([row["action"] for row in result.get("undone") or []], ["reverted"])

    def test_the_stored_answer_stops_claiming_a_change_that_was_undone(self):
        """The answer must not go on claiming what was taken back.

        The answer said *I changed it*.  After the undo the document is
        back where it was, so the sentence is false — and it is the
        durable kind of false: the panel's notice goes away, while the
        stored answer stays and is what the reader finds when the thread
        is reopened.  The correction belongs in the stored answer.
        """
        from albanna.api.conversations import undo_turn
        from albanna.services.chat_service import tool_entry

        name = self._customer()
        context = self._context(self.owner)

        updated = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {
                "doctype": "Customer",
                "name": name,
                "data": {"customer_name": f"{name} changed"},
            },
            context,
        )
        self.assertTrue(updated.ok, updated.content)

        conversation, message = self._turn(
            [
                tool_entry(
                    self._call(
                        "update_doc",
                        {
                            "doctype": "Customer",
                            "name": name,
                            "data": {"customer_name": "x"},
                        },
                    ),
                    updated,
                )
            ]
        )

        result = undo_turn(conversation=conversation, message=message)

        self.assertTrue(result.get("undone"), "the undo took nothing back")

        stored = frappe.db.get_value("Albanna Message", message, "content") or ""
        self.assertIn(
            "This change was undone.",
            stored,
            "the stored answer still claims a change that was taken back",
        )
        self.assertIn(
            "I changed it.",
            stored,
            "the correction replaced the answer instead of correcting it",
        )

        # The transcript the endpoint hands back is what the panel
        # renders, so the correction has to be in it — not only in the
        # database.
        shown = [row for row in result.get("messages") or [] if row.get("name") == message]
        self.assertTrue(shown, "the transcript lost the message")
        self.assertIn("This change was undone.", shown[0].get("content") or "")

    def test_an_undo_that_took_nothing_back_leaves_the_answer_alone(self):
        """A turn with nothing to take back gets no marker.

        The marker says a change was undone.  A turn that only read
        something changed nothing, so a marker on it would be a new lie —
        a smaller one, but a lie.
        """
        from albanna.api.conversations import undo_turn

        conversation, message = self._turn(
            [
                {
                    "name": "get_doc",
                    "ok": True,
                    "summary": "Read it",
                }
            ]
        )

        undo_turn(conversation=conversation, message=message)

        stored = frappe.db.get_value("Albanna Message", message, "content") or ""
        self.assertNotIn("This change was undone.", stored)

    def test_the_marker_is_not_stacked_when_the_undo_is_asked_for_twice(self):
        """The second undo has nothing to take back, so it says nothing.

        The marker is written once, by the undo that carried something
        back.  An undo that takes nothing back must not write it again —
        two markers on one answer read as a bug.
        """
        from albanna.api.conversations import undo_turn
        from albanna.services.chat_service import tool_entry

        name = self._customer()
        context = self._context(self.owner)

        updated = self.backend.call(
            TOOL_MANIFEST.get("update_doc"),
            {
                "doctype": "Customer",
                "name": name,
                "data": {"customer_name": f"{name} changed"},
            },
            context,
        )
        self.assertTrue(updated.ok, updated.content)

        conversation, message = self._turn(
            [
                tool_entry(
                    self._call(
                        "update_doc",
                        {
                            "doctype": "Customer",
                            "name": name,
                            "data": {"customer_name": "x"},
                        },
                    ),
                    updated,
                )
            ]
        )

        undo_turn(conversation=conversation, message=message)
        undo_turn(conversation=conversation, message=message)

        stored = frappe.db.get_value("Albanna Message", message, "content") or ""
        self.assertEqual(
            stored.count("This change was undone."),
            1,
            "the marker was written more than once",
        )

    def test_an_entry_that_claims_a_read_created_a_document_is_refused(self):
        """The guard on the server, against the stored entry.

        The transcript is written by an older version of the app, and a
        stored entry may say "delete" for a read.  The undo reads the
        *tool* as well as the entry, and a read is never a creation.
        """
        from albanna.api.conversations import undo_turn

        name = self._customer()
        conversation, message = self._turn(
            [
                {
                    "name": "get_doc",
                    "ok": True,
                    "summary": "Read it",
                    "undo": {"action": "delete", "doctype": "Customer", "name": name},
                }
            ]
        )

        undo_turn(conversation=conversation, message=message)

        self.assertTrue(
            frappe.db.exists("Customer", name),
            "a stored read entry deleted the document it read",
        )

    def test_the_transcript_does_not_offer_the_undo_of_a_read(self):
        """The button is offered only for what may be taken back.

        A read is never undoable, even when an older version of the app
        stored an entry that says otherwise — the entry is a claim, and
        the tool is the truth.
        """
        from albanna.services.conversation_service import transcript_window

        name = self._customer()
        conversation, message = self._turn(
            [
                {
                    "name": "get_doc",
                    "ok": True,
                    "summary": "Read it",
                    "undo": {"action": "delete", "doctype": "Customer", "name": name},
                }
            ]
        )

        window = transcript_window(conversation, 50)

        self.assertFalse(
            window["messages"][0]["tools"][0]["undoable"],
            "the transcript offered the undo of a read",
        )

    def test_the_transcript_offers_the_undo_only_while_there_is_something_to_take_back(self):
        """The button disappears once the undo has been carried out.

        A button that stays says "you can take this back" about a change
        that has already been taken back, and the reader is left clicking
        a button that does nothing.
        """
        from albanna.api.conversations import undo_turn
        from albanna.services.conversation_service import transcript_window

        name = self._customer()
        conversation, message = self._turn(
            [
                {
                    "name": "update_doc",
                    "ok": True,
                    "summary": "Changed it",
                    "undo": {
                        "action": "update",
                        "doctype": "Customer",
                        "name": name,
                        "data": {"customer_name": name},
                    },
                }
            ]
        )

        before = transcript_window(conversation, 50)
        self.assertTrue(
            before["messages"][0]["tools"][0]["undoable"],
            "a turn with something to take back must offer it",
        )

        result = undo_turn(conversation=conversation, message=message)

        after = transcript_window(conversation, 50)
        self.assertFalse(
            after["messages"][0]["tools"][0]["undoable"],
            "the undo has been carried out; the turn must not offer it again",
        )
        self.assertFalse(
            result["messages"][0]["tools"][0]["undoable"],
            "the transcript the endpoint returns must say the same thing",
        )


@pytest.mark.integration
class TestTurnDurability(AlbannaTestCase):
    """A write that ran is committed before the turn can die.

    The worker's transaction is the reader's safety net: a document the
    assistant created must exist even if the model fails afterwards.  The
    test spies on ``frappe.db.commit`` rather than reading the row back,
    because the test harness shares one transaction and an uncommitted
    insert is visible to the assertion either way.
    """

    def setUp(self):
        super().setUp()
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        super().tearDown()

    def test_a_write_is_committed_before_the_turn_can_die(self):
        from albanna.core.messages import Message
        from albanna.core.tools import ToolSpec
        from albanna.providers.base import Completion, Usage
        from albanna.services.chat_service import ChatService, TurnRequest
        from albanna.tools.base import ToolResult

        service = ChatService()

        # Two model calls: one that asks for a write, one that answers.
        calls = {"n": 0}

        def fake_complete(config, messages, tools, emit, stream):
            calls["n"] += 1
            if calls["n"] == 1:
                from albanna.core.messages import ToolCall

                return Completion(
                    message=Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="c1",
                                name="create_doc",
                                arguments={"doctype": "ToDo", "data": {"description": "x"}},
                            )
                        ],
                    ),
                    provider="openai",
                    model="a-model",
                    usage=Usage(input_tokens=1, output_tokens=1),
                )
            return Completion(
                message=Message(role="assistant", content="done"),
                provider="openai",
                model="a-model",
                usage=Usage(input_tokens=1, output_tokens=1),
            )

        service._complete = fake_complete

        # The backend reports success without touching the database, so the
        # spy observes only the durability commit and not a real write.
        service._backend.call = lambda spec, arguments, context: ToolResult(
            ok=True, content="Created ToDo 'X'", data={"doctype": "ToDo", "name": "X"}
        )

        import albanna.user_policy as up

        _orig = up.confirm_writes_for
        up.confirm_writes_for = lambda user=None: False

        committed = []
        original = frappe.db.commit
        frappe.db.commit = lambda *a, **k: committed.append(1) or original(*a, **k)

        try:
            outcome = service.run(TurnRequest(question="create a todo", page="test|durability|"))
        finally:
            frappe.db.commit = original
            up.confirm_writes_for = _orig

        self.assertTrue(outcome.ok)
        # At least one commit beyond the audit row's own commits: the
        # write's.  The running row and the terminal row each commit, so a
        # turn with a write commits strictly more than a turn without one.
        self.assertGreaterEqual(len(committed), 3, "the write must have been committed")

    def test_a_read_only_turn_commits_no_write(self):
        from albanna.core.messages import Message
        from albanna.providers.base import Completion, Usage
        from albanna.services.chat_service import ChatService, TurnRequest

        service = ChatService()

        def fake_complete(config, messages, tools, emit, stream):
            return Completion(
                message=Message(role="assistant", content="nothing to do"),
                provider="openai",
                model="a-model",
                usage=Usage(input_tokens=1, output_tokens=1),
            )

        service._complete = fake_complete

        committed = []
        original = frappe.db.commit
        frappe.db.commit = lambda *a, **k: committed.append(1) or original(*a, **k)

        try:
            outcome = service.run(TurnRequest(question="hello", page="test|durability2|"))
        finally:
            frappe.db.commit = original

        self.assertTrue(outcome.ok)
        # Only the running row and the terminal row commit: two.
        self.assertEqual(len(committed), 2, "a read-only turn commits only the audit rows")


class TestTheAuditRowNamesTheWrites(AlbannaTestCase):
    """What a turn wrote, for the question the panel has to answer.

    A turn that dies leaves its audit row behind, and the row is the
    truth about what it did before it died.  The reader's question when
    the panel says the turn did not finish is *did it happen?* — so the
    row is read, and the writes in it are named.

    The rules are narrow on purpose: only a turn that has not finished,
    only the reader's own, and only when there is exactly one such turn
    to mean.  A reader told about the wrong turn's writes goes looking
    for a change that was never made, and that is worse than being told
    nothing at all.
    """

    def setUp(self):
        super().setUp()
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.sql("delete from `tabAlbanna Chat Log`")
        super().tearDown()

    def _call(self, name, arguments):
        from albanna.core.messages import ToolCall

        return ToolCall(id="call-1", name=name, arguments=arguments)

    def _row(self, calls, status="running", approvals=None):
        """An audit row of a turn that has not finished."""
        doc = frappe.new_doc("Albanna Chat Log")
        doc.user = "Administrator"
        doc.status = status
        payload: dict = {"calls": calls}
        if approvals is not None:
            payload["approvals"] = approvals
        doc.tools = json.dumps(payload)
        doc.flags.ignore_permissions = True
        doc.insert()
        return doc.name

    def _approval(
        self,
        decision="approve",
        ran=False,
        doctype="Customer",
        name="CUST-0001",
        request_id="req-1",
    ):
        """An approval the row holds: what was asked, and what was said."""
        return {
            "request_id": request_id,
            "tool": "update_doc",
            "doctype": doctype,
            "name": name,
            "decision": decision,
            "ran": ran,
        }

    def _write_call(self, doctype="Customer", name="CUST-0001"):
        return {
            "name": "update_doc",
            "ok": True,
            "write": True,
            "documents": [{"doctype": doctype, "name": name}],
        }

    def _status(self):
        from albanna.api.chat import status

        return status(stream_id="a-turn-that-never-finished")

    def test_the_entry_says_which_calls_were_writes(self):
        """The manifest says which tools write, and the entry says so too.

        A write recorded as a read is a change nobody can name — and a
        reader who is told that nothing was changed is told a lie.
        """
        from albanna.services.chat_service import tool_entry
        from albanna.tools.base import ToolResult

        write = tool_entry(
            self._call(
                "update_doc",
                {"doctype": "Customer", "name": "CUST-0001", "data": {"customer_name": "x"}},
            ),
            ToolResult.success(
                "Updated it",
                data={
                    "doctype": "Customer",
                    "name": "CUST-0001",
                    "before": {"customer_name": "old"},
                    "changed": {"customer_name": "x"},
                },
            ),
        )
        read = tool_entry(
            self._call("get_doc", {"doctype": "Customer", "name": "CUST-0001"}),
            ToolResult.success("Read it", data={"doctype": "Customer", "name": "CUST-0001"}),
        )

        self.assertTrue(write["write"], "a change was recorded as a read")
        self.assertFalse(read["write"], "a read was recorded as a change")

    def test_a_dead_turn_names_what_it_wrote(self):
        """The question the reader is left with is *did it happen?*.

        The row answers it: the write in the row is a write that was
        committed, and the panel says which document it was.
        """
        self._row([self._write_call()])

        result = self._status()

        self.assertEqual(result["status"], "error")
        self.assertIn(
            "Customer CUST-0001",
            result["error"],
            "the panel did not say what the dead turn had written",
        )

    def test_a_dead_turn_that_only_read_names_nothing(self):
        """A turn that changed nothing has nothing to name.

        Naming a document that was only read would send the reader
        looking for a change that was never made.
        """
        self._row(
            [
                {
                    "name": "get_doc",
                    "ok": True,
                    "write": False,
                    "documents": [{"doctype": "Customer", "name": "CUST-0001"}],
                }
            ]
        )

        result = self._status()

        self.assertNotIn("CUST-0001", result["error"])
        self.assertIn("did not finish this question", result["error"])

    def test_a_refused_write_names_nothing(self):
        """A write that was refused changed nothing.

        The refusal is in the row, and the row says it was refused — so
        the document is not named as one that was changed.
        """
        call = self._write_call()
        call["ok"] = False
        call["denied"] = True
        self._row([call])

        result = self._status()

        self.assertNotIn("CUST-0001", result["error"])

    def test_two_unfinished_turns_name_nothing(self):
        """When the row is not certainly the reader's turn, nothing is said.

        Two unfinished turns, and no way to tell which one the reader is
        asking about.  Naming one of them would be a guess, and a guess
        about what changed is not a thing to send a reader on.
        """
        self._row([self._write_call(name="CUST-0001")])
        self._row([self._write_call(name="CUST-0002")])

        result = self._status()

        self.assertNotIn("CUST-000", result["error"])

    def test_a_finished_turn_is_not_the_turn_the_reader_is_asking_about(self):
        """A turn that ended with an answer is not a dead turn.

        Its row is a record of a turn that worked, and naming its
        writes would be naming a change that the reader was already
        told about.
        """
        self._row([self._write_call()], status="ok")

        result = self._status()

        self.assertNotIn("CUST-0001", result["error"])

    # -- what the reader confirmed -----------------------------------------

    def test_a_confirmed_change_that_never_ran_is_named(self):
        """The reader confirmed a change, and it did not happen.

        This is the worst of both: the reader believes a change was
        made, and it was not.  The panel's answer to *did it happen?*
        must say that it did not — otherwise the reader goes looking
        for a change that was never made, and finds nothing, and cannot
        tell that the assistant asked them to approve it first.
        """
        self._row([], approvals=[self._approval()])

        result = self._status()

        self.assertIn("Customer CUST-0001", result["error"])
        self.assertIn("did not run", result["error"])

    def test_a_confirmed_change_that_ran_is_not_named_as_one_that_did_not(self):
        """A change that ran is a change the row names as made.

        The row holds both facts — the reader confirmed it, and the
        write behind it ran.  Saying it did not run would be a lie, and
        a reader who is told their change did not happen will look for
        it again, and make it twice.
        """
        self._row([self._write_call()], approvals=[self._approval(ran=True)])

        result = self._status()

        self.assertIn("Customer CUST-0001", result["error"])
        self.assertNotIn("did not run", result["error"])

    def test_a_declined_change_names_nothing(self):
        """A change the reader turned down did not run — and they know it.

        Naming it would send them looking for a change they themselves
        refused, which is a worse sentence than silence.
        """
        self._row([], approvals=[self._approval(decision="reject")])

        result = self._status()

        self.assertNotIn("CUST-0001", result["error"])

    def test_a_confirmed_change_and_a_change_that_ran_are_both_named(self):
        """A turn can have written one thing and been about to write another.

        The reader is told about both: what was changed is what is
        there to check, and what was confirmed and did not run is what
        has to be asked for again.
        """
        self._row(
            [self._write_call(name="CUST-0001")],
            approvals=[self._approval(name="CUST-0002")],
        )

        result = self._status()

        self.assertIn("Customer CUST-0001", result["error"])
        self.assertIn("Customer CUST-0002", result["error"])

    def test_two_confirmed_changes_that_never_ran_are_named_together(self):
        """Two approvals, one sentence — and both named.

        Naming one of them would leave the other in the dark, and the
        reader cannot tell which one it was.
        """
        self._row(
            [],
            approvals=[
                self._approval(name="CUST-0001", request_id="req-1"),
                self._approval(name="CUST-0002", request_id="req-2"),
            ],
        )

        result = self._status()

        self.assertIn("Customer CUST-0001", result["error"])
        self.assertIn("Customer CUST-0002", result["error"])
        self.assertIn("changes you confirmed", result["error"])
