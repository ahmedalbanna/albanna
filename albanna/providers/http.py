"""The HTTP session the providers talk through.

Every call to a provider used to open its own connection: a new socket, a
new TLS handshake, and a connection thrown away as soon as the answer had
been read.  A turn asks the provider several times — once per tool round —
so one turn paid for several handshakes to say the same thing to the same
host.

So the providers share one session, and the session keeps its connections
alive between calls.  The provider sees one connection from this host for
a whole turn instead of one per call, and the handshake happens once.

**The session is per thread, not per process.**  ``requests`` does not
promise that a session may be used from two threads at once, and a
gunicorn worker runs many requests at the same time.  One session per
thread keeps each thread's connections to itself — and a thread's calls to
the provider, which is what a turn is, are the calls that reuse the
connection.

**The retry policy is unchanged.**  urllib3 discards a connection that
broke and fails the request; with a shared session that can happen where
it could not before, because the provider closed an idle connection and
the client did not notice.  The chat service already retries a transient
provider failure once, on a fresh connection, so the turn recovers — and
the adapter keeps urllib3's default of *no* retries, so a request that
cannot connect still fails at once, as it does now, and a connect timeout
is still one timeout rather than two.

The timeout, the headers and the body are the caller's, exactly as they
were: this module changes how the connection is carried, not what is
said on it.
"""

from __future__ import annotations

import threading
from typing import Any

import requests
from requests.adapters import HTTPAdapter

#: How many connections a session keeps per host.  A turn makes several
#: calls to one host in a row, so a handful is enough; the limit is what
#: keeps a session from holding sockets open forever.
POOL_SIZE = 4

#: The session of each thread.  A thread-local, because a session is not
#: safe to share between threads.
_local = threading.local()


def session() -> requests.Session:
    """The calling thread's session, made once and kept.

    @returns: the session
    """
    existing = getattr(_local, "session", None)
    if existing is not None:
        return existing

    created = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=POOL_SIZE,
        pool_maxsize=POOL_SIZE,
        # urllib3's default, and the policy `requests.post` used: no
        # retries.  The app retries a transient failure itself, and a
        # retry here would double a connect timeout.
        max_retries=0,
    )
    created.mount("http://", adapter)
    created.mount("https://", adapter)

    _local.session = created
    return created


def post(url: str, **kwargs: Any) -> requests.Response:
    """POST through the shared session.

    The arguments are the ones `requests.post` takes, and they mean the
    same thing — including the timeout, which is still the caller's.

    @param url: where to post
    @returns: the response
    """
    return session().post(url, **kwargs)


def close() -> None:
    """Close the calling thread's session, if it has one.

    The sockets are closed with it.  Nothing depends on this: a session
    that is dropped is closed by the operating system when it is
    collected — but a test that wants to count the connections needs to
    be able to say so.
    """
    existing = getattr(_local, "session", None)
    if existing is None:
        return

    existing.close()
    _local.session = None
