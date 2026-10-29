"""The backup script is part of the app's promise, so it is held to a contract.

The site databases are the one thing on this host that nothing else covers:
the MCP control-plane backup takes PostgreSQL, Redis and the secrets, and
says plainly that the MariaDB site databases are not included.  Before the
scheduled backup existed, the only copy of production's data was a manual
dump on the same disk as the database it protected.

A backup that is not *verified* is a file, so the script verifies each dump
before it declares the run good — and the properties that make it worth
running are asserted here, so a later edit cannot quietly undo them:

* the production site is covered, and the disposable test clone is not;
* the tables the script insists on are tables this app actually owns, so a
  renamed DocType cannot leave the check looking for a table that is never
  there;
* no `… | grep -q` pipeline, which under `set -o pipefail` reports a
  *missing* pattern when the pattern is present;
* the systemd unit runs the script in this repository, so there is one copy
  of it and no installed copy to drift.

The script's own run is the test that matters for the rest: it was run
against both live sites during development, and it caught two real defects
— a missing `--with-files`, and the SIGPIPE trap above — before either
could reach the timer.
"""

from __future__ import annotations

import json
import pathlib
import re
import stat

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "site_backup.sh"
UNIT = REPO / "scripts" / "systemd" / "albanna-site-backup.service"
TIMER = REPO / "scripts" / "systemd" / "albanna-site-backup.timer"

PRODUCTION_SITE = "albanna.localhost"
DISPOSABLE_SITE = "test.localhost"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _default_sites() -> list[str]:
    match = re.search(r'SITE_BACKUP_SITES:-"([^"]*)"', _script())
    assert match, "the script does not declare a default list of sites"
    return match.group(1).split()


def _sentinels(site: str) -> list[str]:
    match = re.search(rf'\[{re.escape(site)}\]="([^"]*)"', _script())
    assert match, f"the script names no sentinel tables for {site}"
    return [table for table in match.group(1).split("|") if table]


def test_the_script_is_committed_and_runnable():
    assert SCRIPT.exists(), "scripts/site_backup.sh is missing"
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "the script is not executable"
    assert _script().startswith("#!/usr/bin/env bash"), "the script has no shebang"


def test_the_production_site_is_covered_and_the_test_clone_is_not():
    sites = _default_sites()
    assert PRODUCTION_SITE in sites, (
        f"{PRODUCTION_SITE} holds the production data and is not backed up"
    )
    assert DISPOSABLE_SITE not in sites, (
        f"{DISPOSABLE_SITE} is a disposable clone that the test suite "
        "overwrites; backing it up would fill the disk to protect nothing"
    )


def test_the_sentinel_tables_are_tables_this_app_owns():
    """A renamed DocType must not leave the check looking for a table that is never there."""
    owned = set()
    for path in (REPO / "albanna").rglob("*.json"):
        if "doctype" not in path.parts:
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        name = meta.get("name")
        if name:
            owned.add(f"tab{name}")

    sentinels = _sentinels(PRODUCTION_SITE)
    assert sentinels, "the production site has no sentinel tables"
    for table in sentinels:
        assert table in owned, (
            f"the backup insists on `{table}`, which is not a table this app "
            "owns — either the DocType was renamed or the check is wrong"
        )


def test_no_pipeline_ends_in_a_quiet_grep():
    """`zcat dump | grep -q pattern` reports a missing pattern under pipefail.

    grep exits as soon as it matches, the producer dies of SIGPIPE, and the
    pipeline's status is the failure — so the check would reject every good
    dump and accept nothing.
    """
    offenders = [
        line.strip()
        for line in _script().splitlines()
        # A comment may *name* the trap; only code can walk into it.
        if not line.strip().startswith("#")
        and re.search(r"\|\s*grep\b[^|]*\s-q\b", line)
    ]
    assert not offenders, (
        "a pipeline ends in a quiet grep, which under `set -o pipefail` "
        f"reports a missing pattern when the pattern is present: {offenders}"
    )


def test_the_unit_runs_the_script_in_this_repository():
    assert UNIT.exists(), "the systemd service is missing"
    assert TIMER.exists(), "the systemd timer is missing"
    unit = UNIT.read_text(encoding="utf-8")
    assert "ExecStart=" in unit
    exec_start = next(
        line for line in unit.splitlines() if line.startswith("ExecStart=")
    )
    assert str(SCRIPT) in exec_start, (
        "the unit runs an installed copy of the script, so the version that "
        "runs can drift from the version that is committed"
    )
    timer = TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=" in timer, "the timer has no schedule"
    assert "Persistent=true" in timer, (
        "the timer must fire after a missed run, or a host that was down at "
        "03:47 silently skips a day's backup"
    )
