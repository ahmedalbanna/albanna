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
    delete_conversation,
    list_conversations,
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
