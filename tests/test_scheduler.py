"""The reaper must run at least as often as the lie it is allowed to tell.

A turn that dies leaves its ledger row saying ``running``.  The row stops
being true once the turn's own timeout has passed, and the reaper's job is
to say so — it relabels the row ``interrupted``.

But the reaper is a scheduled job, and a job that runs once a day leaves
the row saying ``running`` about a turn from yesterday.  The truth of the
ledger therefore depends on the *cadence* of the job and not only on its
cutoff: the gap between two runs is the time the ledger spends being
wrong.

Nothing else fails when the cadence is wrong.  The job runs, the job
succeeds, the row is eventually relabelled, and the ledger was wrong for
a day in the meantime — which is the one thing the ledger exists to
prevent.

So the tie between the two numbers is asserted here: the reaper must run
at least as often as the window it closes.

The assertion knows about one more number.  A cron slot does not fire at
the minute it names; the scheduler wakes up on its own tick (four minutes
by default) and enqueues whatever is due, so a job fires on the first tick
after its slot.  The real gap between two runs is therefore the cron gap
*plus* up to one tick, and it is the real gap that has to fit inside the
window.
"""

from __future__ import annotations

import ast
import datetime
import pathlib

from croniter import croniter

from albanna.tasks import STALE_AFTER_MINUTES

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS = APP_ROOT / "albanna" / "hooks.py"
REAPER = "albanna.tasks.interrupt_stale_chat_logs"

#: The scheduler wakes up this often and enqueues whatever is due
#: (``frappe.utils.scheduler.DEFAULT_SCHEDULER_TICK``).  It is read from
#: the framework rather than copied, so a change upstream is a change
#: here too.
try:  # pragma: no cover - the framework is always present in a bench
    from frappe.utils.scheduler import DEFAULT_SCHEDULER_TICK
except Exception:  # pragma: no cover
    DEFAULT_SCHEDULER_TICK = 4 * 60


def _scheduler_events() -> dict:
    """The scheduler events, read without importing Frappe."""
    tree = ast.parse(HOOKS.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "scheduler_events":
                return ast.literal_eval(node.value)
    raise AssertionError("hooks.py does not define scheduler_events")


def _crons_for(event: str) -> list[str]:
    """The cron expressions that schedule one event."""
    events = _scheduler_events()
    return [cron for cron, scheduled in (events.get("cron") or {}).items() if event in scheduled]


def test_the_reaper_is_scheduled_by_cron():
    """A daily job is a job that lies for a day."""
    assert _crons_for(REAPER), (
        f"{REAPER} is not scheduled by a cron expression.  The scheduler's "
        "'daily' bucket runs once a night, and a row that says 'running' "
        "about a turn from yesterday is not true."
    )


def test_the_reaper_runs_at_least_as_often_as_its_cutoff():
    """The real gap between two runs must fit inside the window it closes."""
    for cron in _crons_for(REAPER):
        runs = croniter(cron, datetime.datetime(2026, 1, 1, 0, 0))
        first = runs.get_next(datetime.datetime)
        second = runs.get_next(datetime.datetime)
        gap = (second - first).total_seconds()

        # A cron slot fires on the first scheduler tick after it, so the
        # real gap is the cron gap plus up to one tick.
        real_gap = gap + DEFAULT_SCHEDULER_TICK

        assert real_gap <= STALE_AFTER_MINUTES * 60, (
            f"the reaper runs every {gap / 60:.0f} minutes, and the "
            f"scheduler's tick adds up to {DEFAULT_SCHEDULER_TICK // 60} "
            f"more, so a row may say 'running' for up to "
            f"{real_gap / 60:.0f} minutes after its turn died — but the row "
            f"stops being true after {STALE_AFTER_MINUTES} minutes.  The "
            "ledger would say 'running' about a turn that finished by "
            "dying, for as long as the gap between two runs."
        )
