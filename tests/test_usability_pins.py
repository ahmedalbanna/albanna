"""The panel's usability facts, pinned at the stylesheet.

The U-series NFRs are mostly facts about *CSS* — a colour pair's
contrast, a target's minimum size, a focus ring that exists.  Such a
fact is only a fact while the sheet stays the way it was read, so these
walkers read the same sheet the U-a reading did and refuse the drift.

The rules:

- the panel's text pairs meet WCAG 2.1 AA — 4.5:1 for normal text,
  3:1 for anything drawn but not read (U4);
- every interactive element is inside the `pointer: coarse` block that
  lifts both sides of its touch target to 44px (U10);
- every quiet button is inside the focus-visible group rule, so a
  keyboard reader's reach is drawn in the panel's own accent and not
  left to whatever outline the browser feels like (U3).

The Desk's own variable values below are read from Frappe's espresso
palette (`apps/frappe/frappe/public/scss/espresso/_colors.scss`) and its
dark theme (`apps/frappe/frappe/public/scss/desk/dark.scss`); the panel
inherits them, so a walker that made up its own greys would pin a fact
about a panel nobody ships.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[1]
    / "albanna"
    / "public"
    / "css"
    / "albanna-side-chat.bundle.css"
)

#: The Desk's values, as the panel meets them.
DESK = {
    "--text-muted": {"light": "#525252", "dark": "#c7c7c7"},  # gray-700 / gray-400
    "--text-color": {"light": "#383838", "dark": "#f8f8f8"},  # gray-800 / gray-50
    "--bg-color": {"light": "#ffffff", "dark": "#171717"},  # white / gray-900
    "--gray-100": {"light": "#f3f3f3", "dark": "#232323"},  # bubble
    "--gray-800": {"light": "#383838", "dark": "#232323"},  # dark accent
    "--red-600": {"light": "#cc2929", "dark": "#f9c6c6"},
    "--red-700": {"light": "#b52a2a", "dark": "#6b1515"},
    "--red-50": {"light": "#fff7f7", "dark": "#3a1a19"},
    "--red-300": {"light": "#f9c6c6", "dark": "#f9c6c6"},
    "--red-900": {"light": "#6b1515", "dark": "#6b1515"},
}

#: The pairs the panel actually paints, and what each must reach.
#: `mode` is WCAG's: text needs 4.5:1, non-text needs 3:1.
PAIRS = [
    ("text on surface", "--albanna-text", "--albanna-surface", 4.5),
    ("muted on surface", "--albanna-muted", "--albanna-surface", 4.5),
    ("muted on bubble", "--albanna-muted", "--albanna-bubble", 4.5),
    ("link on surface", "--albanna-link", "--albanna-surface", 4.5),
    ("ink on the accent fill", "--albanna-on-accent", "--albanna-accent", 4.5),
    ("ink on the stop fill", "--albanna-on-stop", "--albanna-stop", 4.5),
    ("ink on the danger fill", "--albanna-on-danger", "--albanna-danger", 4.5),
    ("error ink on error ground", "--albanna-error-text", "--albanna-error-bg", 4.5),
]


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [
        (lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)(
            int(value[i : i + 2], 16) / 255
        )
        for i in (0, 2, 4)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a: str, b: str) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _rules(text: str) -> list[tuple[str, str]]:
    """The sheet as (selector, body) pairs, comments and media wrappers aside.

    Nested at-rules are flattened by keeping the selector's line intact;
    a walker needs the *rule*, not the wrapper, and the selectors this
    sheet uses carry their media context in the comment lines above them.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    found: list[tuple[str, str]] = []
    stack: list[str] = []
    depth = 0
    buffer = ""
    for char in text:
        if char == "{":
            selector = buffer.strip()
            if selector.startswith("@"):
                stack.append(selector)
                buffer = ""
                depth += 1
                continue
            depth += 1
            found.append((selector, ""))
            buffer = ""
            continue
        if char == "}":
            depth -= 1
            if stack and depth < len(stack):
                stack.pop()
                continue
            if found and found[-1][1] == "":
                found[-1] = (found[-1][0], buffer)
            buffer = ""
            continue
        buffer += char
    return found


def _variable(table: dict[str, str], name: str, theme: str, sheet: dict[str, str]) -> str:
    """The colour a panel variable resolves to, following Desk fallbacks."""
    value = sheet.get(name, "")
    if value.startswith("var("):
        inner = value[4:-1]
        parts = [p.strip() for p in inner.split(",")]
        reference = parts[0]
        fallback = parts[1] if len(parts) > 1 else None
        desk_value = DESK.get(reference, {}).get(theme)
        if desk_value:
            return desk_value
        if fallback:
            return fallback.strip()
        raise AssertionError(f"{name} resolves to nothing the walker knows: {value}")
    return value


def test_the_panel_text_pairs_meet_aa():
    """A colour pair nobody computed is a pair that nobody can read (U4)."""
    text = CSS.read_text(encoding="utf-8")
    sheets: dict[str, dict[str, str]] = {"light": {}, "dark": {}}
    for selector, body in _rules(text):
        if selector not in (":root", '[data-theme="dark"]'):
            continue
        theme = "dark" if "dark" in selector else "light"
        for line in body.splitlines():
            if ":" in line and line.strip().startswith("--"):
                name, value = line.strip().rstrip(";").split(":", 1)
                sheets[theme][name] = value.strip()

    failures: list[str] = []
    for theme in ("light", "dark"):
        # The dark sheet only carries its overrides; the rest resolves
        # from the light one, exactly as the cascade does — but only
        # when the cascade is the dark one.
        sheet = dict(sheets["light"])
        if theme == "dark":
            sheet.update(sheets["dark"])
        for name, fg, bg, floor in PAIRS:
            foreground = _variable(DESK, fg, theme, sheet)
            background = _variable(DESK, bg, theme, sheet)
            ratio = _contrast(foreground, background)
            if ratio < floor:
                failures.append(f"{theme}: {name} ({fg} on {bg}) = {ratio:.2f}:1, floor {floor}")
    assert failures == [], failures


#: The interactive elements a finger reaches for.  The list is the U-a
#: inventory; a new control that is not in it is a control the touch
#: walker cannot hold — add it here when it ships.
INTERACTIVE = [
    "albanna-chat__send",
    "albanna-chat__icon",
    "albanna-chat__copy",
    "albanna-chat__remove",
    "albanna-chat__retry",
    "albanna-chat__table-copy",
    "albanna-chat__attach",
    "albanna-chat__voice",
    "albanna-chat__source",
    "albanna-chat__earlier",
    "albanna-chat__question-option",
    "albanna-chat__attach-chip",
    "albanna-chat__attach-chip-remove",
    "albanna-chat__edit-actions button",
    "albanna-chat__confirm-button",
    "albanna-drawer__action",
    "albanna-drawer__title",
    "albanna-drawer__search-input",
    "albanna-side-chat-launcher",
]


def test_every_touch_target_is_forty_four_on_coarse_pointers():
    """A finger does not know what a screen's width is (U10)."""
    text = CSS.read_text(encoding="utf-8")
    match = re.search(r"@media\s*\(pointer:\s*coarse\)\s*\{", text)
    assert match, "the pointer: coarse block is gone"
    # Take the balanced block that follows the match.
    start = match.end()
    depth = 1
    index = start
    while depth and index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    block = text[start : index - 1]

    missing = [name for name in INTERACTIVE if f".{name}" not in block]
    assert missing == [], f"touch targets the coarse block does not lift: {missing}"
    assert "min-width: 44px" in block and "min-height: 44px" in block


#: The buttons whose reach used to lean on the browser default.  The
#: group rule draws it in the panel's own accent instead.
QUIET_BUTTONS = [
    "albanna-chat__icon",
    "albanna-chat__copy",
    "albanna-chat__remove",
    "albanna-chat__retry",
    "albanna-chat__table-copy",
    "albanna-chat__attach",
    "albanna-chat__voice",
    "albanna-chat__source",
    "albanna-chat__earlier",
    "albanna-chat__question-option",
    "albanna-chat__attach-chip",
    "albanna-chat__attach-chip-remove",
    "albanna-chat__edit-actions button",
    "albanna-drawer__action",
    "albanna-drawer__item",
]


def test_every_quiet_button_has_an_explicit_focus_ring():
    """A reach the design does not draw is a reach the browser guesses (U3)."""
    text = CSS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    group = re.search(
        r"\.albanna-chat__icon:focus-visible[^{]*\{[^}]*outline:\s*2px\s*solid\s*var\(--albanna-accent",
        text,
    )
    assert group, "the quiet buttons' focus-visible group rule is gone"
    missing = [name for name in QUIET_BUTTONS if f".{name}:focus-visible" not in group.group(0)]
    assert missing == [], f"quiet buttons outside the focus group: {missing}"


def test_reduced_motion_reaches_the_whole_widget():
    """The launcher and the resize handle move too; the reader asked them not to (A3)."""
    text = CSS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    blocks = []
    for match in re.finditer(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{", text):
        start = match.end()
        depth = 1
        index = start
        while depth and index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        blocks.append(text[start : index - 1])
    assert blocks, "the reduced-motion block is gone"

    # The scope is the widget's root, not the Vue subtree: the launcher's
    # hover lift and the resize handle's fade live outside `.albanna-chat`.
    whole = any(
        re.search(r"#albanna-side-chat\s*,", block) and "#albanna-side-chat *" in block
        for block in blocks
    )
    assert whole, "no reduced-motion block reaches the widget's root"
    assert any(
        "transition: none !important" in block and "animation: none !important" in block
        for block in blocks
    )
