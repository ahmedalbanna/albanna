"""The question the assistant asks the reader.

These tests need a site, and they are excluded from the default ``pytest``
run by the ``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna

What is under test
------------------
A question is the assistant's way of saying *I need something only you
can choose*.  It is asked through the tool surface, so it travels over
whatever backend the app uses, and it is answered in the chat, so the
reader never has to type a document's name to go on with a task the
assistant had just looked up.

Four properties are held here, and each one is a way the feature could
lie:

*   **the question is a row** — it outlives the turn that asked it, so
    the reader may answer it later, from another tab;
*   **only the reader may answer** — the question names the account it
    was asked of, and the answer is acted on;
*   **the first answer is the answer** — the reader's choice is one
    choice, and a second click lands after the fact;
*   **only an offered answer is accepted** — a value the reader was
    never shown is not an answer to this question.
"""

from __future__ import annotations

import frappe
import pytest

from albanna.api import questions as questions_api
from albanna.core.tools import TOOL_MANIFEST
from albanna.permissions import current_principal
from albanna.services import questions as questions_service
from albanna.services.conversation_service import new_conversation
from albanna.tests.base import AlbannaTestCase
from albanna.tools.backend import ErpnextBackend
from albanna.tools.base import ToolContext

READER = "albanna.test.question.reader@albanna.dev"
OTHER = "albanna.test.question.other@albanna.dev"

OPTIONS = [
    {"label": "عميل نقدي", "value": "عميل نقدي"},
    {"label": "CUST-0002", "value": "CUST-0002"},
]


def _make_user(email: str) -> str:
    """A reader who may chat."""
    if not frappe.db.exists("User", email):
        # The user is created as the administrator: the framework makes
        # the session's own settings for a new user, and a session left as
        # somebody else fails the insert for a reason that has nothing to
        # do with what the test is about.
        former = frappe.session.user
        frappe.set_user("Administrator")
        try:
            user = frappe.new_doc("User")
            user.email = email
            user.first_name = "Albanna"
            user.last_name = "Question"
            user.flags.ignore_permissions = True
            user.insert()
        finally:
            frappe.set_user(former)
    user = frappe.get_doc("User", email)
    user.flags.ignore_permissions = True
    user.add_roles("Albanna User")
    return email


def _as(email: str) -> None:
    """Act as *email*, the way a request for that user would."""
    frappe.set_user(email)
    frappe.local.session.user = email
    frappe.local.role_permissions = {}
    frappe.local.perms = {}


@pytest.mark.integration
class TestTheQuestion(AlbannaTestCase):
    """A question the assistant asked, and the answer the reader gave."""

    def setUp(self):
        super().setUp()
        self.reader = _make_user(READER)
        self.other = _make_user(OTHER)
        self.backend = ErpnextBackend()
        # A fresh thread for every test.  The framework rolls a test class
        # back at the end of the class, not after each test, so a thread
        # shared by two tests would carry the first test's questions into
        # the second one's list.
        self.conversation = new_conversation(self.reader)

    # -- helpers -----------------------------------------------------------

    def _ask(self, options=None, conversation: str | None = None) -> dict:
        """The tool, called the way the model calls it."""
        _as(self.reader)
        context = ToolContext(
            principal=current_principal(),
            site=frappe.local.site,
            conversation=self.conversation if conversation is None else conversation,
        )
        raw = self.backend.call(
            TOOL_MANIFEST.get("ask_question"),
            {"question": "أي عميل تريد؟", "options": OPTIONS if options is None else options},
            context,
        )
        assert raw.ok, raw.content
        return raw.data

    def _the_question(self) -> dict:
        """The card the tool returned."""
        return self._ask()["question"]

    # -- asking ------------------------------------------------------------

    def test_the_question_is_recorded(self):
        """The question outlives the turn that asked it.

        It is a row, not a note in the browser: the reader may answer
        it minutes later, from another tab, tomorrow.
        """
        card = self._the_question()

        assert frappe.db.exists("Albanna Question", card["name"])

        row = frappe.get_doc("Albanna Question", card["name"])
        assert row.question == "أي عميل تريد؟"
        assert row.conversation == self.conversation
        assert row.user == self.reader
        assert row.status == questions_service.PENDING
        assert len(row.options) == 2
        assert row.options[0].label == "عميل نقدي"
        assert row.options[1].value == "CUST-0002"

    def test_the_question_is_the_readers_own(self):
        card = self._the_question()

        assert card["conversation"] == self.conversation
        assert card["options"][0]["value"] == "عميل نقدي"

    def test_a_question_with_no_options_is_refused(self):
        """A card with no buttons is a question the reader cannot answer."""
        result = self.backend.call(
            TOOL_MANIFEST.get("ask_question"),
            {"question": "أي عميل تريد؟", "options": []},
            ToolContext(
                principal=current_principal(),
                site=frappe.local.site,
                conversation=self.conversation,
            ),
        )

        assert not result.ok
        assert "answer" in result.content.lower()

    def test_a_question_with_no_conversation_is_refused(self):
        """A question that belongs to no thread is a question nobody sees."""
        result = self.backend.call(
            TOOL_MANIFEST.get("ask_question"),
            {"question": "أي عميل تريد؟", "options": OPTIONS},
            ToolContext(
                principal=current_principal(),
                site=frappe.local.site,
                conversation="",
            ),
        )

        assert not result.ok
        assert "conversation" in result.content.lower()

    # -- answering ---------------------------------------------------------

    def test_the_reader_may_answer(self):
        card = self._the_question()

        _as(self.reader)
        answered = questions_service.answer(card["name"], self.reader, "CUST-0002")

        assert answered["status"] == questions_service.ANSWERED
        assert answered["answer"] == "CUST-0002"
        assert answered["answer_value"] == "CUST-0002"

        row = frappe.get_doc("Albanna Question", card["name"])
        assert row.answered_by == self.reader
        assert row.answered_at

    def test_the_answer_keeps_both_the_label_and_the_value(self):
        """The reader saw a name; the assistant goes on to use a value.

        A customer may be called "أحمد عبدالله" and be named
        "CUST-0002", and the two are not the same string — so the row
        keeps the one the reader chose *and* the one to use.
        """
        card = self._the_question()

        _as(self.reader)
        answered = questions_service.answer(card["name"], self.reader, "عميل نقدي")

        assert answered["answer"] == "عميل نقدي"
        assert answered["answer_value"] == "عميل نقدي"

    def test_somebody_else_may_not_answer(self):
        """The question names the account it was asked of."""
        card = self._the_question()

        _as(self.other)
        with pytest.raises(questions_service.NotTheReader):
            questions_service.answer(card["name"], self.other, "CUST-0002")

    def test_the_first_answer_is_the_answer(self):
        card = self._the_question()

        _as(self.reader)
        questions_service.answer(card["name"], self.reader, "CUST-0002")

        with pytest.raises(questions_service.AlreadyAnswered):
            questions_service.answer(card["name"], self.reader, "عميل نقدي")

    def test_an_answer_that_was_not_offered_is_refused(self):
        """A value the reader was never shown is not an answer."""
        card = self._the_question()

        _as(self.reader)
        with pytest.raises(questions_service.NotAnOption):
            questions_service.answer(card["name"], self.reader, "CUST-9999")

    def test_a_question_that_does_not_exist_is_refused(self):
        _as(self.reader)
        with pytest.raises(questions_service.QuestionNotFound):
            questions_service.answer("no-such-question", self.reader, "CUST-0002")

    def test_a_typed_reply_cancels_the_pending_question(self):
        """A reader who types instead of choosing has answered some other way.

        The pending question is cancelled, not deleted: the thread still
        says a question was asked there, and a second click on its card
        is refused rather than applied.
        """
        card = self._the_question()

        _as(self.reader)
        cancelled = questions_service.cancel_pending(self.conversation)

        assert [entry["name"] for entry in cancelled] == [card["name"]]
        assert questions_service.pending(self.conversation, self.reader) == []

        with pytest.raises(questions_service.QuestionCancelled):
            questions_service.answer(card["name"], self.reader, "CUST-0002")

    def test_a_cancelled_question_is_refused_by_the_endpoint(self):
        card = self._the_question()

        _as(self.reader)
        questions_service.cancel_pending(self.conversation)

        with pytest.raises(frappe.PermissionError):
            questions_api.answer_question(name=card["name"], value="CUST-0002")

    # -- the pending list --------------------------------------------------

    def test_only_pending_questions_are_offered(self):
        card = self._the_question()

        _as(self.reader)
        pending = questions_service.pending(self.conversation, self.reader)
        assert [entry["name"] for entry in pending] == [card["name"]]

        questions_service.answer(card["name"], self.reader, "CUST-0002")

        assert questions_service.pending(self.conversation, self.reader) == []

    def test_another_readers_question_is_not_offered(self):
        self._the_question()

        _as(self.other)
        assert questions_service.pending(self.conversation, self.other) == []

    # -- the endpoints -----------------------------------------------------

    def test_the_endpoint_records_the_answer(self):
        card = self._the_question()

        _as(self.reader)
        result = questions_api.answer_question(name=card["name"], value="CUST-0002")

        assert result["question"]["status"] == questions_service.ANSWERED
        assert result["answer"] == "CUST-0002"

    def test_the_endpoint_refuses_somebody_elses_question(self):
        card = self._the_question()

        _as(self.other)
        with pytest.raises(frappe.PermissionError):
            questions_api.answer_question(name=card["name"], value="CUST-0002")

    def test_the_endpoint_offers_the_readers_pending_questions(self):
        card = self._the_question()

        _as(self.reader)
        result = questions_api.pending_questions(conversation=self.conversation)

        assert [entry["name"] for entry in result["questions"]] == [card["name"]]

    def test_the_endpoint_refuses_another_readers_thread(self):
        _as(self.other)
        with pytest.raises(frappe.PermissionError):
            questions_api.pending_questions(conversation=self.conversation)

    def test_a_deleted_thread_takes_its_questions_with_it(self):
        """A thread the reader asked to be gone is gone with its questions.

        The questions hold what the assistant was looking for and what
        the reader was being asked to choose, and a row that outlives
        the thread it belongs to is a row nobody asked to keep.
        """
        from albanna.services.conversation_service import delete_conversation

        card = self._the_question()

        _as(self.reader)
        delete_conversation(self.conversation)

        assert not frappe.db.exists("Albanna Question", card["name"])
        assert not frappe.db.exists(
            "Albanna Question Option",
            {"parent": card["name"]},
        )


@pytest.mark.integration
class TestTheTurnThatAsks(AlbannaTestCase):
    """A turn that asks the reader something.

    The property is the one the whole feature rests on: **once the reader
    has been asked, the assistant may only speak.**  The turn that asks
    ends there, and the turn that follows starts with the reader's
    answer.
    """

    def setUp(self):
        super().setUp()
        self.reader = _make_user(READER)

    def _run_a_turn(self) -> tuple[object, list[list[str]]]:
        """A turn whose model asks a question and then answers in prose.

        The model is faked, so the turn runs for real — the tools, the
        question row, the transcript — without a provider and without a
        network.
        """
        from albanna.core.messages import Message, ToolCall
        from albanna.providers.base import Completion
        from albanna.services.chat_service import ChatService, TurnRequest

        rounds: list[list[str]] = []

        def fake_complete(config, messages, tools, emit, stream):
            rounds.append([spec.name for spec in tools])
            if len(rounds) == 1:
                return Completion(
                    message=Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="call-1",
                                name="ask_question",
                                arguments={
                                    "question": "أي عميل تريد؟",
                                    "options": OPTIONS,
                                },
                            )
                        ],
                    ),
                    provider="openai",
                    model="a-model",
                )
            return Completion(
                message=Message(role="assistant", content="اختر من القائمة."),
                provider="openai",
                model="a-model",
            )

        service = ChatService()
        service._complete = fake_complete

        _as(self.reader)
        outcome = service.run(
            TurnRequest(question="أنشئ فاتورة مبيعات", page="test|question|turn|")
        )
        return outcome, rounds

    def test_the_turn_ends_with_the_question(self):
        outcome, _rounds = self._run_a_turn()

        assert outcome.ok
        assert outcome.question is not None
        assert outcome.question["question"] == "أي عميل تريد؟"
        assert frappe.db.exists("Albanna Question", outcome.question["name"])

    def test_the_model_is_given_no_tools_once_the_reader_is_asked(self):
        """A question that is asked and then acted on is not a question.

        The first round has the question tool among its tools; the round
        after it has none at all, so the assistant cannot act on an
        answer the reader has not given.
        """
        _outcome, rounds = self._run_a_turn()

        assert len(rounds) == 2, rounds
        assert "ask_question" in rounds[0]
        assert rounds[1] == []

    def test_the_question_names_the_turn_that_asked_it(self):
        """The record of what was asked sits next to the record of the turn.

        A question with no turn behind it cannot be traced back to the
        answer that answered it, and a turn nobody can trace is a turn
        nobody can audit.
        """
        outcome, _rounds = self._run_a_turn()

        assert outcome.question is not None
        row = frappe.get_doc("Albanna Question", outcome.question["name"])
        assert row.turn
        assert frappe.db.exists("Albanna Chat Log", row.turn)

    def test_a_typed_reply_cancels_the_thread_pending_question(self):
        """The reader who types instead of choosing moves the thread on.

        The question the assistant asked is cancelled when the next turn
        starts — its card goes — and the thread carries on with the
        typed message.  The question row stays, as Cancelled, so the
        thread still says a question was asked there.
        """
        from albanna.core.messages import Message, ToolCall
        from albanna.providers.base import Completion
        from albanna.services import questions as questions_service
        from albanna.services.chat_service import ChatService, TurnRequest

        rounds: list[list[str]] = []

        def fake_complete(config, messages, tools, emit, stream):
            last_user = str(
                next((m.content for m in reversed(messages) if getattr(m, "role", "") == "user"), "")
            )
            if "typed reply" in last_user:
                return Completion(
                    message=Message(role="assistant", content="understood."),
                    provider="openai",
                    model="a-model",
                )
            rounds.append([spec.name for spec in (tools or [])])
            if len(rounds) == 1:
                return Completion(
                    message=Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="call-1",
                                name="ask_question",
                                arguments={
                                    "question": "أي عميل تريد؟",
                                    "options": OPTIONS,
                                },
                            )
                        ],
                    ),
                    provider="openai",
                    model="a-model",
                )
            return Completion(
                message=Message(role="assistant", content="اختر من القائمة."),
                provider="openai",
                model="a-model",
            )

        service = ChatService()
        service._complete = fake_complete

        _as(self.reader)
        first = service.run(TurnRequest(question="أنشئ فاتورة مبيعات", page="test|question|turn|"))
        assert first.question is not None
        question_name = first.question["name"]

        second = service.run(
            TurnRequest(
                question="typed reply, not an option",
                conversation_id=first.conversation_id,
                page="test|question|turn|",
            )
        )

        assert second.ok
        assert [q.get("name") for q in (second.cancelled_questions or [])] == [question_name]
        assert questions_service.pending(first.conversation_id, self.reader) == []

        row = frappe.get_doc("Albanna Question", question_name)
        assert row.status == questions_service.CANCELLED
