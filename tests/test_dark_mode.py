"""The dark theme has to be a theme, not a colour swap.

Frappe's dark theme does not darken the Desk; it *replaces* its palette.
The gray scale stays, the surfaces and the inks move: the text colour
becomes near-white, the panel surfaces become near-black, and the danger
red becomes a *light* red (the theme's own ``--red-300``).

A widget that reuses one variable for two things survives the light theme
and breaks in the dark one, because in the light theme the two things
happen to be the same colour:

- the accent is the fill of the reader's own bubble, and also the ink of
  a source link.  In the dark theme the accent is a dark grey, so a link
  painted with it is a dark grey link on a near-black bubble — invisible,
  and invisible in a way a screenshot in the light theme cannot show.
- the danger red is the fill of the "remove this turn" button, and white
  was the ink on it.  In the dark theme that red is light, so white on it
  is a word nobody can read.

These are asserted here because nothing else fails.  The page renders, the
test suite is green, and the reader simply cannot see the sources of an
answer or the label on the button that removes a turn.
"""

from __future__ import annotations

import pathlib
import re

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
STYLESHEET = APP_ROOT / "public" / "css" / "albanna-side-chat.bundle.css"

CSS = STYLESHEET.read_text(encoding="utf-8")


def _block(selector: str) -> str:
    """The body of the first rule whose selector is *selector*."""
    match = re.search(re.escape(selector) + r"\s*\{(.*?)\}", CSS, re.DOTALL)
    assert match, f"the stylesheet has no {selector} rule"
    return match.group(1)


def _rules() -> list[str]:
    """Every declaration block in the stylesheet."""
    return re.findall(r"\{([^{}]*)\}", CSS)


def _ink(rule: str) -> str | None:
    """The text colour a rule paints with, if it paints one.

    ``border-color`` is not a colour of the text, and a rule that draws a
    border in the danger red is not a rule that draws its words in it.
    """
    match = re.search(r"(?<![\w-])color\s*:\s*([^;]+);", rule)
    return match.group(1) if match else None


def test_the_accent_is_never_used_as_ink():
    """The accent is a fill.  Ink on a surface is the text colour."""
    offenders = [
        rule
        for rule in _rules()
        if re.search(r"(?<![\w-])color\s*:\s*var\(--albanna-accent\b", rule)
    ]
    assert not offenders, (
        "a rule paints text with --albanna-accent.  In the dark theme the "
        "accent is a dark grey fill, so that text is invisible.  Use "
        "--albanna-link for anything the reader reads."
    )


def test_ink_on_a_red_fill_is_its_own_variable():
    """White on the dark theme's light red is a word nobody can read."""
    for rule in _rules():
        if not re.search(r"background\s*:\s*var\(--albanna-danger\b", rule):
            continue
        colour = _ink(rule)
        if colour is None:
            # A hover rule that only changes the fill keeps its ink.
            continue
        assert "--albanna-on-danger" in colour, (
            f"a red fill paints its text {colour!r}.  In the dark theme the "
            "red is light, so the ink on it has to be --albanna-on-danger "
            "(dark there, white in the light theme)."
        )


def test_the_dark_theme_declares_its_own_ink():
    """Every colour that has to change with the theme changes with it."""
    light = _block(":root")
    dark = _block('[data-theme="dark"]')

    for name in ("--albanna-link", "--albanna-on-danger"):
        assert name in light, f"{name} is not declared in :root"
        assert name in dark, (
            f"{name} is not declared for the dark theme, so it keeps the "
            "light theme's value on a dark surface."
        )

    for name in ("--albanna-link", "--albanna-on-danger"):
        light_value = re.search(re.escape(name) + r":\s*([^;]+);", light)
        dark_value = re.search(re.escape(name) + r":\s*([^;]+);", dark)
        assert light_value and dark_value, f"{name} has no value in one theme"
        assert light_value.group(1).strip() != dark_value.group(1).strip(), (
            f"{name} is the same in both themes, so it cannot be ink on both "
            "a light surface and a dark one."
        )


def test_the_links_of_the_panel_use_the_link_ink():
    """The things the reader can press are painted with the link ink."""
    for selector in (
        ".albanna-chat__source",
        ".albanna-chat__rating--on",
        ".albanna-chat__tour-dismiss",
    ):
        rule = _block(selector)
        assert "--albanna-link" in rule, (
            f"{selector} paints its text with something else.  On the dark "
            "theme that is a colour nobody can see."
        )
