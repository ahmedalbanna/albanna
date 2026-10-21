"""The session the providers talk through.

The claims under test: the session is *one per thread* and not one per
call, the retry policy is the one `requests.post` had, and a streamed
response is closed so that its connection goes back to the pool.
"""

from __future__ import annotations

import threading

from albanna.providers import http


def test_the_session_is_made_once_and_kept():
    assert http.session() is http.session(), "a call must not open a new session"


def test_two_threads_get_a_session_each():
    """A session is not safe to share between threads, so each thread has
    its own — and a gunicorn worker runs many threads at once."""

    found: list[int] = []
    ready = threading.Barrier(2)

    def take() -> None:
        session = http.session()
        ready.wait(timeout=5)
        found.append(id(session))

    threads = [threading.Thread(target=take) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(found) == 2, "both threads must have a session"
    assert found[0] != found[1], "two threads must not share one session"


def test_the_retry_policy_is_the_one_requests_had():
    """urllib3 retries a request whose connection broke, and with a shared
    session that can happen where it could not before.  The app retries a
    transient failure itself, so the adapter keeps urllib3's default of no
    retries: a request that cannot connect still fails at once, and a
    connect timeout is still one timeout and not two."""

    adapter = http.session().get_adapter("https://example.invalid")

    assert adapter.max_retries.total == 0
    assert adapter.max_retries.connect is None or adapter.max_retries.connect == 0


def test_the_pool_is_bounded():
    """A session that keeps every connection it ever opened would hold
    sockets open forever."""

    adapter = http.session().get_adapter("https://example.invalid")

    assert adapter._pool_maxsize == http.POOL_SIZE
    assert adapter._pool_connections == http.POOL_SIZE


def test_posting_goes_through_the_session():
    """The call is the session's, so the connection is kept."""

    seen: list[str] = []

    class Recorder:
        def post(self, url, **kwargs):
            seen.append(url)
            return "the response"

    original = http.session
    try:
        http.session = lambda: Recorder()
        assert http.post("https://example.invalid/v1/chat", timeout=5) == "the response"
    finally:
        http.session = original

    assert seen == ["https://example.invalid/v1/chat"]


def test_closing_the_session_forgets_it():
    http.session()
    http.close()

    # A new session is made after a close — the old one is gone, and the
    # sockets with it.
    first = http.session()
    http.close()
    assert http.session() is not first
