"""What the app does with the data a user hands it.

One concern, and it is a narrow one: the user's own words must not end up
somewhere the user cannot reach and did not ask for.

The chat endpoints take the question as a request parameter, and Frappe's
request logger appends the request's parsed parameters to **every log
record the request emits** — ``frappe/utils/logger.py``'s
``SiteContextFilter`` adds a ``Form Dict:`` line to each one.  So a
question is copied into the site log: outside the conversation, where
deleting the conversation does not remove it, and where the text is read
by operators and copied off the host.

This module redacts those parameters before the request can log anything,
so the text lives in the conversation — which the user owns and can erase
— and nowhere else.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

import frappe

from albanna.core.secrets import REDACTED

#: What a redacted parameter reads as in the log.
#:
#: One definition, shared with the configuration that holds the API key:
#: the mask of a secret is the same mask wherever the secret is hidden.

#: The parameters that carry what the user typed or what they were
#: looking at.
#:
#: One list, because the set is the policy: a new endpoint that takes
#: the user's text adds its field here rather than inventing a rule.
REQUEST_TEXT_FIELDS = ("message", "messages_json", "question", "page_context", "image")


def redact_request_text(*fields: str) -> None:
    """Replace *fields* in the request context Frappe logs.

    The request's parsed parameters are what the log filter prints, so
    this is the one place that decides what leaves the conversation's own
    storage.  The endpoint has already read the real values into its
    arguments by the time this runs — Frappe binds them before the body
    executes — so nothing downstream loses them.
    """
    form = getattr(frappe.local, "form_dict", None)
    if not isinstance(form, dict):
        return
    for field in fields:
        value = form.get(field)
        if value in (None, ""):
            continue
        form[field] = REDACTED


def redacted_request_text(*fields: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Redact *fields* of the request before the wrapped endpoint runs.

    When no fields are given, the baseline set in :data:`REQUEST_TEXT_FIELDS`
    is redacted: that is the policy, so a new endpoint that forgets to
    name its text fields still hides the user's words rather than leaking
    them.  Naming fields adds to that baseline rather than replacing it.
    """

    fields = fields or REQUEST_TEXT_FIELDS

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap one endpoint, redacting before its body runs."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Redact the request's text, then call the endpoint."""
            redact_request_text(*fields)
            return func(*args, **kwargs)

        return wrapper

    return decorate
