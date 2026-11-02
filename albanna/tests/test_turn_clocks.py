"""The clocks, as the site actually turns them.

The pure cases are in :mod:`tests.test_clocks`; these need a site,
because they read the settings document for real, enqueue the way the
endpoint enqueues, and read the marker back through the cache the
polling fallback reads.

They are excluded from the default ``pytest`` run by the
``integration`` marker.  They run with:

    bench --site test.localhost run-tests --app albanna

Three properties are held here:

*   the job the queue is handed is given the *whole* budget — the work
    plus the wait — because the old error was a job killed while it
    slept inside the approval wait;
*   a card the socket never delivered is still offered by ``status``,
    for the reader who watched a working turn with no way to answer it;
*   a card is cleared from the marker the moment the turn has moved
    past the wait, so a decided card cannot be resurrected by a slow
    poll.
"""

from __future__ import annotations

import time
from unittest import mock

import frappe

from albanna.api import chat as chat_api
from albanna.services.chat_job import _mirror_to_marker
from albanna.services.settings_service import get_settings, job_budget_seconds
from albanna.tests.base import AlbannaTestCase


def _marker(stream_id: str, payload: dict) -> None:
    frappe.cache().set_value(
        chat_api.TURN_CACHE_KEY.format(stream_id=stream_id),
        payload,
        expires_in_sec=600,
    )


def _drop_marker(stream_id: str) -> None:
    frappe.cache().delete_value(
        chat_api.TURN_CACHE_KEY.format(stream_id=stream_id),
    )


class TestTheQueueClock(AlbannaTestCase):
    def tearDown(self):
        _drop_marker("test-clock-stream")
        super().tearDown()

    def test_the_endpoint_gives_the_job_the_whole_budget(self):
        """A turn that waits for the reader is killed by the queue, and
        the queue kills by this number — so it must hold the wait."""

        captured = {}
        stream_id = "test-clock-stream"

        def fake_enqueue(method, **kwargs):
            captured["method"] = method
            captured.update(kwargs)
            return stream_id

        settings = get_settings()

        with mock.patch("frappe.enqueue", side_effect=fake_enqueue):
            result = chat_api.ask_stream(question="a question with a card")

        assert result["status"] == "queued"
        assert captured["timeout"] == job_budget_seconds(settings)
        assert captured["method"] == "albanna.services.chat_job.run_turn_job"
        # The marker that backs the polling fallback must outlive the
        # job's own clock, never be shorter than it.
        assert (
            job_budget_seconds(settings) + chat_api.STALE_GRACE_SECONDS >= chat_api._turn_deadline()
        )


class TestTheParkedCard(AlbannaTestCase):
    def tearDown(self):
        _drop_marker("test-card-stream")
        super().tearDown()

    def _marker_with_pending(self) -> dict:
        self.stream_id = "test-card-stream"
        return {
            "status": "running",
            "started_at": time.time(),
            "question": "a question",
            "page_context": "",
            "image": "",
        }

    def test_status_offers_a_card_the_socket_never_delivered(self):
        marker = self._marker_with_pending()
        marker["pending_approval"] = {
            "request_id": "req-card-1",
            "at": time.time() * 1000,
            "name": "create_doc",
            "arguments": {"doctype": "Bank", "data": {"bank_name": "X"}},
            "preview": "Create Bank: X",
            "diff": None,
            "window_seconds": 300,
        }
        _marker(self.stream_id, marker)

        result = chat_api.status(stream_id=self.stream_id)

        assert result["status"] == "awaiting_approval"
        assert result["pending"]["request_id"] == "req-card-1"
        assert result["pending"]["preview"] == "Create Bank: X"

    def test_the_card_and_its_clock_travel_together(self):
        """The card's clock starts when the worker opened the wait, not
        when the poll first found it: a reader who arrives minutes late
        is shown the time that remains."""

        at = (time.time() - 120) * 1000  # the wait opened two minutes ago
        marker = self._marker_with_pending()
        marker["pending_approval"] = {
            "request_id": "req-card-2",
            "at": at,
            "name": "create_doc",
            "arguments": {},
            "preview": "Create Bank: X",
            "diff": None,
            "window_seconds": 300,
        }
        _marker(self.stream_id, marker)

        result = chat_api.status(stream_id=self.stream_id)

        assert result["status"] == "awaiting_approval"
        assert result["pending"]["at"] == at

    def test_a_later_event_clears_the_card(self):
        """A decided card is history: the turn moved on, and a slow poll
        must not resurrect a card the answer already belongs to."""

        marker = self._marker_with_pending()
        marker["pending_approval"] = {"request_id": "req-gone"}
        _marker(self.stream_id, marker)

        _mirror_to_marker(self.stream_id, "Administrator", {"event": "progress"})

        cleared = frappe.cache().get_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            expires=True,
        )
        assert "pending_approval" not in cleared

    def test_a_confirm_event_parks_the_card_with_the_servers_clock(self):
        self.stream_id = "test-card-stream"
        _marker(
            self.stream_id,
            {"status": "running", "started_at": time.time()},
        )

        at = time.time() * 1000
        _mirror_to_marker(
            self.stream_id,
            "Administrator",
            {
                "event": "confirm",
                "request_id": "req-card-3",
                "name": "create_doc",
                "arguments": {"doctype": "Bank", "data": {"bank_name": "X"}},
                "preview": "Create Bank: X",
                "diff": None,
                "window_seconds": 300,
                "at": at,
            },
        )

        parked = frappe.cache().get_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            expires=True,
        )
        pending = parked.get("pending_approval") or {}
        assert pending.get("request_id") == "req-card-3"
        assert pending.get("at") == at

    def test_a_confirm_event_without_a_clock_still_parks_the_card(self):
        """The card does not need a clock to be parked.

        The turn always sends the moment the wait opened, but a card
        that arrives without one must still reach the reader — a card
        with no clock is a card that can be counted down from now, which
        is wrong, but a card that was never parked at all is a reader
        with no way to answer.

        The mirror used to raise a ``NameError`` here — it read the
        clock from a module it had not imported — and every test that
        exercised the mirror sent the clock, so the missing import was
        never reached.
        """

        self.stream_id = "test-card-stream"
        _marker(
            self.stream_id,
            {"status": "running", "started_at": time.time()},
        )

        _mirror_to_marker(
            self.stream_id,
            "Administrator",
            {
                "event": "confirm",
                "request_id": "req-no-clock",
                "name": "create_doc",
                "arguments": {"doctype": "Bank", "data": {"bank_name": "X"}},
                "preview": "Create Bank: X",
                "diff": None,
                "window_seconds": 300,
            },
        )

        parked = frappe.cache().get_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            expires=True,
        )
        pending = parked.get("pending_approval") or {}
        assert pending.get("request_id") == "req-no-clock"
        assert pending.get("at"), "the card must carry a clock of some kind"

    def test_a_mirror_never_touches_a_marker_that_is_not_running(self):
        """The final answer parks itself over the marker; a mirror that
        arrived after that must not overwrite the final payload with a
        running marker shaped like a card."""

        self.stream_id = "test-card-stream"
        frappe.cache().set_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            {"status": "ok", "reply": "the answer"},
            expires_in_sec=600,
        )

        _mirror_to_marker(
            self.stream_id,
            "Administrator",
            {
                "event": "confirm",
                "request_id": "req-late",
                "at": time.time() * 1000,
                "preview": "Create Bank: X",
            },
        )

        parked = frappe.cache().get_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            expires=True,
        )
        assert parked.get("status") == "ok"
        assert "pending_approval" not in parked

    def test_a_stale_local_copy_cannot_write_running_over_a_finished_turn(self):
        """The one bug that made a finished turn poll as running forever.

        ``frappe.cache().get_value`` answers from ``frappe.local.cache`` —
        this process's own mirror — before it touches redis, and any read
        without ``expires=True`` fills that mirror.  The job's own first
        read of the marker fills it with ``running``; every mirror after
        that is served the stale copy; and the last event of the turn —
        the one the job emits once the answer is parked — is told by the
        stale copy that the turn is still running, clears the card, and
        writes ``running`` back over the parked answer.

        What the reader then sees is a turn that never finishes, on a job
        that finished fine, with a ledger row that says ``ok``: the worst
        state of the three, because it keeps saying "working" for as long
        as the marker lives instead of ever naming the answer or the
        failure.
        """
        self.stream_id = "test-card-stream"
        # The process-local mirror, as the job's first read leaves it.
        stale = {"status": "running", "started_at": time.time()}
        chip = frappe.cache().make_key(chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id))
        frappe.local.cache[chip] = stale

        # The cache as the job's park left it.
        _marker(
            self.stream_id,
            {"status": "ok", "reply": "the answer", "rounds": 3},
        )

        _mirror_to_marker(self.stream_id, "Administrator", {"event": "done"})

        parked = frappe.cache().get_value(
            chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
            expires=True,
        )
        assert parked.get("status") == "ok", "the finished answer was overwritten"
        assert parked.get("reply") == "the answer"
        # And the local mirror is not trusted again afterwards.
        frappe.local.cache.pop(chip, None)
        assert (
            frappe.cache()
            .get_value(
                chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id),
                expires=True,
            )
            .get("status")
            == "ok"
        )

    def test_a_user_cache_clear_cannot_take_the_marker_with_it(self):
        """The marker must outlive the framework's housekeeping.

        ``frappe.cache_manager.clear_user_cache(user)`` deletes every key
        under ``<db>|user:<user>:`` — a login, a logout, a User save, a
        role change.  The marker used to live there, and every one of
        those events deleted it mid-turn: the job was still running, its
        row was still ``running``, and the polling fallback answered the
        reader's ``status`` with the ledger's "the turn did not finish"
        — about a turn that later returned ``OK`` and wrote its documents.
        A reader told a finished turn failed goes looking for work that
        was done, or repeats it.

        So the marker lives in the site's namespace instead, and this is
        the case that says it stays there.
        """
        self.stream_id = "test-card-stream"
        key = chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id)
        _marker(
            self.stream_id,
            {"status": "ok", "reply": "the answer", "rounds": 3},
        )
        before = frappe.cache().get_value(key, expires=True)
        assert before and before.get("status") == "ok"

        # What the framework does on any of the events above.
        frappe.cache().delete_keys("user:Administrator")

        after = frappe.cache().get_value(key, expires=True)
        assert after and after.get("status") == "ok", (
            "the marker was deleted by a user-cache clear, and the "
            "polling fallback will call a finished turn lost"
        )
        assert not key.startswith(b"user:") if isinstance(key, bytes) else True
        # And it is not parked in the user namespace in the first place.
        redis_key = frappe.cache().make_key(key)
        assert b"|user:" not in redis_key, (
            f"the marker is namespaced per user ({redis_key!r}); "
            "clear_user_cache empties that prefix"
        )

    def test_the_card_still_lands_when_the_local_copy_is_stale(self):
        """The other half of the same trap: the card must still reach
        the cache when the process-local copy knows nothing about it."""

        self.stream_id = "test-card-stream"
        key = chat_api.TURN_CACHE_KEY.format(stream_id=self.stream_id)
        _marker(self.stream_id, {"status": "running", "started_at": time.time()})
        # A stale process-local copy: it knows the turn is running and
        # nothing else — in particular, not the card about to land.
        frappe.local.cache[frappe.cache().make_key(key)] = {
            "status": "running",
            "started_at": time.time(),
        }

        _mirror_to_marker(
            self.stream_id,
            "Administrator",
            {
                "event": "confirm",
                "request_id": "req-stale",
                "name": "create_doc",
                "arguments": {"doctype": "Bank", "data": {"bank_name": "X"}},
                "preview": "Create Bank: X",
                "diff": None,
                "window_seconds": 300,
                "at": time.time() * 1000,
            },
        )

        parked = frappe.cache().get_value(key, expires=True)
        pending = parked.get("pending_approval") or {}
        assert pending.get("request_id") == "req-stale"
        # The stale running copy must not be written back clean of the card.
        assert parked.get("pending_approval"), "the card was lost to the stale copy"
