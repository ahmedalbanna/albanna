"""Pins for the compatibility facts (NFR C-series, ADR-0109).

These are walkers, not feature tests: they read the source the way a
reviewer would, and fail when a fact the compatibility claims rest on
stops being true.

*   C1 — the Frappe API surface is deliberately checked.  Every
    ``frappe.*`` chain in the app must appear in the v15-verified list;
    a new symbol fails the suite until someone reads it against the
    version-15 branch.  And the declared version range must include
    Frappe Cloud's stable line (v15 and v16) and stop before v17.
*   C2 — ERPNext is a required app.  The escalation path targets the
    ERPNext ``Issue`` doctype; without the requirement the install
    would promise a support module that cannot exist.
*   C6 — the panel's browser budget is respected: no CSS feature that
    the four engines' stable releases do not all carry, no JS API that
    Safari's stable releases lag, and every `dvh` declared after a
    `vh` fallback in the same rule.
*   C7 — the responsive layers exist: the ≤991px overlay, the ≤640px
    full-screen sheet, the touch-target lift.

The verified-API list is a maintenance surface, on purpose: it is the
cheapest honest form of "we support v15" an app on a v16 bench can
carry — a reviewer adding a new frappe call is forced past the
question "does v15 have this?" instead of around it.
"""

from __future__ import annotations

import pathlib
import re

import tomllib

APP = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = APP / "pyproject.toml"
PANEL = APP / "albanna" / "public" / "js" / "side-chat"
BUNDLE_CSS = APP / "albanna" / "public" / "css" / "albanna-side-chat.bundle.css"

#: The `frappe.*` chains the app uses, each one read against the
#: `version-15` branch of frappe/frappe (2026-11-15).  Grouped for
#: readability; the walker flattens it.
FIFTEEN_VERIFIED = frozenset(
    {
        # exceptions and helpers on the root module
        "frappe.DoesNotExistError",
        "frappe.DuplicateEntryError",
        "frappe.PermissionError",
        "frappe.TooManyRequestsError",
        "frappe.ValidationError",
        "frappe._",
        "frappe._dict",
        "frappe.cache",
        "frappe.clear_cache",
        "frappe.conf",
        "frappe.delete_doc",
        "frappe.enqueue",
        "frappe.generate_hash",
        "frappe.get_all",
        "frappe.get_cached_doc",
        "frappe.get_doc",
        "frappe.get_list",
        "frappe.get_meta",
        "frappe.get_roles",
        "frappe.get_single",
        "frappe.get_site_path",
        "frappe.get_traceback",
        "frappe.has_permission",
        "frappe.local",
        "frappe.log_error",
        "frappe.msgprint",
        "frappe.new_doc",
        "frappe.parse_json",
        "frappe.publish_realtime",
        "frappe.session",
        "frappe.set_user",
        "frappe.throw",
        "frappe.whitelist",
        # the database layer — checked against v15's database.py
        "frappe.db.add_column",
        "frappe.db.add_index",
        "frappe.db.commit",
        "frappe.db.count",
        "frappe.db.delete",
        "frappe.db.escape",
        "frappe.db.exists",
        "frappe.db.get_all",
        "frappe.db.get_single_value",
        "frappe.db.get_value",
        "frappe.db.has_column",
        "frappe.db.rename_column",
        "frappe.db.rollback",
        "frappe.db.savepoint",
        "frappe.db.set_single_value",
        "frappe.db.set_value",
        "frappe.db.sql",
        "frappe.db.sql_ddl",
        "frappe.db.sql_list",
        # utils and the modules the app reaches into
        "frappe.utils",
        "frappe.model",
        "frappe.db",
        "frappe.utils.add_days",
        "frappe.utils.add_to_date",
        "frappe.utils.cint",
        "frappe.utils.file_manager",
        "frappe.utils.file_manager.get_content_hash",
        "frappe.utils.file_manager.save_file",
        "frappe.utils.now",
        "frappe.utils.now_datetime",
        "frappe.utils.nowdate",
        "frappe.utils.password",
        "frappe.cache_manager",
        "frappe.cache_manager.clear_user_cache",
        "frappe.desk",
        "frappe.desk.form",
        "frappe.desk.form.assign_to",
        "frappe.desk.form.assign_to.add",
        "frappe.tests",
        "frappe.model.db_query",
        "frappe.model.document",
        "frappe.model.meta",
        "frappe.permissions",
        "frappe.permissions.has_permission",
        "frappe.tests.utils",
    }
)

#: Attribute chains under `frappe.local` and `frappe.session` — the
#: request's scratch space, whose members are stable across v15/v16.
LOCAL_CHAIN_PREFIXES = ("frappe.local", "frappe.session")

#: JS APIs Safari's stable releases have only recently carried, or the
#: panel does not need.  Nothing here is banned by syntax — the build
#: targets es2017 — these are runtime APIs the walker refuses.
BANNED_JS_APIS = re.compile(
    r"\b(structuredClone|findLast\w*\s*\(|\.at\s*\(|Object\.groupBy|Map\.groupBy|Array\.fromAsync)\b"
)

#: CSS features beyond the four engines' stable releases, or ones whose
#: absence is not a graceful drop.  `@layer` and `@container` change the
#: *meaning* of everything inside them, so a browser without them does
#: not merely skip a declaration — the rules they wrap land differently.
#: `:has()` invalidates a whole rule rather than one declaration, so it
#: stays out too.  What the panel *does* use — `color-mix()`, `oklch`,
#: `text-wrap: balance` — is inside the latest-two budget and degrades
#: to a dropped declaration: the destructive card keeps its border and
#: loses its tint.  The support dates are in ADR-0109.
BANNED_CSS_FEATURES = re.compile(r":has\(|@layer\b|@container\b")

MIN_FRAPPE = "15.0.0"


def _frappe_chains(source: str) -> set[str]:
    """Every `frappe.<chain>` word the source names, with its prefixes.

    A chain is identified by its prefixes so a call like
    ``frappe.desk.form.assign_to.add`` can be verified by its full name
    while a bare ``frappe.utils`` attribute stays distinguishable.
    """
    chains = set()
    for match in re.finditer(r"\bfrappe\.[a-zA-Z_][a-zA-Z0-9_.]*", source):
        chain = match.group(0)
        parts = chain.split(".")
        if parts[:2] in (["frappe", "local"], ["frappe", "session"]):
            chains.add(".".join(parts[:3]) if len(parts) >= 3 else ".".join(parts[:2]))
        else:
            chains.update(".".join(parts[:i]) for i in range(2, len(parts) + 1))
    return chains


def test_every_frappe_symbol_is_verified_against_v15():
    """C1: the API surface is read against the version-15 branch."""
    offenders: list[str] = []
    for path in sorted((APP / "albanna").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for chain in _frappe_chains(line):
                if chain.startswith(LOCAL_CHAIN_PREFIXES):
                    continue
                if chain not in FIFTEEN_VERIFIED:
                    offenders.append(f"{path.name}:{line_number}: {chain}")
    assert offenders == [], offenders


def test_the_declared_version_range_covers_the_stable_line():
    """C1: Frappe Cloud's stable line is v15 and v16; v17 is not out."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    deps = data["tool"]["bench"]["frappe-dependencies"]
    for package in ("frappe", "erpnext"):
        constraint = deps[package]
        assert f">={MIN_FRAPPE}" in constraint, f"{package}: the stable line starts at v{MIN_FRAPPE}"
        assert constraint.endswith("<17.0.0"), f"{package}: v17 is not a stable line"


def test_erpnext_is_a_required_app():
    """C2: the support surface this app promises is ERPNext's."""
    hooks = (APP / "albanna" / "hooks.py").read_text(encoding="utf-8")
    assert re.search(r'^required_apps\s*=\s*\[\s*"erpnext"\s*\]', hooks, re.M)


def test_the_panel_uses_no_safari_lagging_apis():
    """C6: the JS API budget, beyond what the build transpiles."""
    offenders: list[str] = []
    for path in sorted(PANEL.rglob("*.mjs")) + sorted(PANEL.glob("*.vue")):
        if path.name.endswith(".test.mjs"):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if match := BANNED_JS_APIS.search(line):
                offenders.append(f"{path.name}:{line_number}: {match.group(0)}")
    assert offenders == [], offenders


def test_the_bundle_css_stays_inside_the_engines_budget():
    """C6: no CSS feature the four engines' stable releases lack."""
    text = BUNDLE_CSS.read_text(encoding="utf-8")
    offenders: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if match := BANNED_CSS_FEATURES.search(line):
            offenders.append(f"{BUNDLE_CSS.name}:{line_number}: {match.group(0)}")
    assert offenders == [], offenders


def test_every_dvh_is_declared_after_a_vh_fallback():
    """C6: the one modern unit ships with its fallback, in the rule."""
    text = BUNDLE_CSS.read_text(encoding="utf-8")
    rule_blocks = re.findall(r"[^{}]+\{[^{}]*\}", text)
    offenders = [
        block.split("{")[0].strip().splitlines()[-1]
        for block in rule_blocks
        if "dvh" in block
        and "vh" not in re.sub(r"\d+dvh", "", block)
    ]
    assert offenders == [], offenders


def test_the_responsive_layers_exist():
    """C7: the overlay, the sheet and the touch lift are in the CSS."""
    text = BUNDLE_CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 991px)" in text, "the dock-off overlay block is gone"
    assert "@media (max-width: 640px)" in text, "the full-screen sheet block is gone"
    assert "@media (pointer: coarse)" in text, "the touch-target lift is gone"
    assert "100dvh" in text, "the sheet does not size to the dynamic viewport"
