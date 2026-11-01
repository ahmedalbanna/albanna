"""The clocks a turn runs against.

A turn has two budgets and one slack, and the queue is given their sum.
The clock is what killed real turns before this existed: the job's
timeout covered the work alone, so every second the reader spent
answering an approval card was a second taken from the model's rounds,
and a turn was killed *inside the wait* — the reader told the worker
had "not completed the turn" while it sat asleep waiting for exactly
the click the reader was about to make.

These cases pin the sum down.  ``turn_timeout`` stays the budget of the
turn's labour, ``confirm_timeout`` the budget of the wait, and the
queue's clock is their sum plus the slack (``job_budget_seconds``).
"""

from __future__ import annotations

from albanna.providers.base import ProviderConfig
from albanna.services.settings_service import (
    AppSettings,
    TURN_SLACK_SECONDS,
    job_budget_seconds,
)

#: The defaults the settings document reads when the operator said
#: nothing of their own.
DEFAULT_TURN = 600
DEFAULT_WAIT = 120


def _settings(turn: int = DEFAULT_TURN, wait: int = DEFAULT_WAIT) -> AppSettings:
    return AppSettings(
        enabled=True,
        provider=ProviderConfig(
            kind="openai",
            base_url="https://example.test/v1",
            model="a-model",
        ),
        fallback=None,
        widget_position="bottom-right",
        max_tool_rounds=25,
        history_limit=50,
        turn_timeout=turn,
        turns_per_minute=6,
        system_prompt="",
        confirm_timeout=wait,
    )


def test_the_budget_is_the_work_plus_the_wait_plus_the_slack():
    settings = _settings(turn=600, wait=120)

    assert job_budget_seconds(settings) == 600 + 120 + TURN_SLACK_SECONDS


def test_the_sum_has_a_number_of_its_own():
    """The int form exists for callers that already hold the two parts."""

    assert job_budget_seconds(600, 120) == 600 + 120 + TURN_SLACK_SECONDS


def test_the_budget_always_covers_both_parts():
    """Whatever the operator dialled, the job is never given less than
    the work needs on its own."""

    settings = _settings(turn=1800, wait=300)
    budget = job_budget_seconds(settings)

    assert budget > settings.turn_timeout
    assert budget > settings.turn_timeout + settings.confirm_timeout


def test_the_slack_survives_zero_budgets():
    """A budget of nothing still gets the slack, so the clock never
    reads as an instant kill."""

    assert job_budget_seconds(_settings(turn=0, wait=0)) == TURN_SLACK_SECONDS
