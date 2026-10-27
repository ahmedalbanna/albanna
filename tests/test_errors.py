"""What the reader is told when a turn fails.

The detail of a failure goes to the log, where an operator can act on
it.  The reader gets a sentence they can do something with — and never
the app's internals.

This is the test that would have caught what a live turn showed on
production: the panel said "JobTimeoutException: Task exceeded maximum
timeout value (600 seconds)".  The exception's class and message are the
app's internals, and an error panel is not where a reader should be
reading them.
"""

from __future__ import annotations

from albanna.core.errors import (
    AllProvidersFailed,
    ProviderBudgetExceeded,
    ProviderError,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnreachable,
    reader_message,
)


def test_a_timeout_is_explained_in_words():
    message = reader_message(ProviderTimeout("MiMo-V2.6-Flash timed out.", provider="openai"))

    assert "did not answer in time" in message
    assert "MiMo" not in message, "the reader is not the operator"
    assert "ProviderTimeout" not in message


def test_an_unreachable_provider_says_so():
    message = reader_message(ProviderUnreachable("connection refused", provider="openai"))

    assert "could not be reached" in message
    assert "connection refused" not in message


def test_a_refused_request_points_at_the_key():
    message = reader_message(ProviderRejected("401 unauthorized", provider="openai"))

    assert "API key" in message
    assert "401" not in message


def test_every_provider_failing_says_that_no_model_answered():
    exc = AllProvidersFailed(
        "openai:MiMo-V2.6-Flash: MiMo-V2.6-Flash timed out.; "
        "openai:step-5-preview: step-5-preview timed out."
    )

    message = reader_message(exc)

    assert "No model provider answered" in message
    assert "timed out" not in message, "the composed detail is the log's, not the reader's"
    assert "openai:" not in message


def test_a_budget_refusal_keeps_its_number():
    """The one message that carries a detail.

    A budget refusal names the number of tokens the request could have
    asked for, and that number is an instruction rather than a
    complaint: the request can be made again with a smaller ceiling.
    """

    exc = ProviderBudgetExceeded(
        "This request costs 40000 tokens, which is over the 12000 limit.",
        affordable_tokens=12000,
    )

    assert "12000" in reader_message(exc)


def test_an_unknown_failure_says_nothing_about_the_internals():
    message = reader_message(RuntimeError("boom at /home/frappe/frappe-bench/apps/erpnext/x.py"))

    assert "Something went wrong" in message
    assert "RuntimeError" not in message
    assert "boom" not in message
    assert "erpnext" not in message


def test_a_provider_error_that_names_no_kind_keeps_its_own_words():
    """A provider error's own message is often the useful part.

    "The key was refused" is a fact about the organisation; replacing it
    with a generic sentence would throw away the only thing the reader
    could act on.
    """
    exc = ProviderError("The API key was refused by the provider.", provider="openai")

    assert reader_message(exc) == "The API key was refused by the provider."
