"""Application services.

The layer between the interface (:mod:`albanna.api`) and the domain
(:mod:`albanna.core`, :mod:`albanna.providers`, :mod:`albanna.tools`).

A service owns a *use case* — "run one turn of the chat", "remember this
conversation", "read the site's configuration" — and is the only place where
the pieces below it are put together.  The API layer stays thin because
everything it needs is already a function here.
"""
