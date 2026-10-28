"""An icon is drawn, not typed.

The panel's icons are SVG: drawn on the same grid, with the same stroke
weight, in ``currentColor`` so they take the ink of the text beside them.
That is not a preference — it is the only way an icon behaves like the
words around it in both themes.

An emoji is a picture of somebody else's instructions, in a font the
browser picks.  It does not take the colour of the text beside it, it
does not sit on the text's baseline, it cannot be sized, and it renders
differently on every operating system.  It also cannot be read by a
screen reader the way an SVG with a label can.

So the rule is written down where it is checked.  The paperclip on the
attachment label was the last emoji in the app, and it was there because
nobody was told it was not allowed; a rule that lives only in somebody's
head is gone with the next contributor.

The check reads the *sources* and the built assets alike.  The bundles
are tracked in the repository, so a build that carried an emoji would
ship it, and a check that only read the sources would let that through
until the next build.
"""

from __future__ import annotations

import pathlib
import unicodedata

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
FRONT_END = APP_ROOT / "public"

#: The blocks an emoji lives in.  The pictographs (which include the
#: faces, the flags and the objects), the dingbats and the symbols that
#: render as pictures, the arrows and the stars that render as emoji when
#: a variation selector follows them, and the selector itself.
EMOJI_BLOCKS = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xFE0F, 0xFE0F),
)

#: The files that reach the reader's browser.
SOURCES = sorted(
    path
    for path in FRONT_END.rglob("*")
    if path.suffix in {".vue", ".mjs", ".js", ".css"}
)


def _emoji_in(path: pathlib.Path) -> list[tuple[int, str]]:
    """The emoji one file holds, as (line, character)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    found: list[tuple[int, str]] = []
    for index, character in enumerate(text):
        code = ord(character)
        if any(low <= code <= high for low, high in EMOJI_BLOCKS):
            found.append((text[:index].count("\n") + 1, character))
    return found


def test_the_front_end_has_no_emoji():
    """Every icon in the panel is drawn."""
    offenders: list[str] = []
    for path in SOURCES:
        for line, character in _emoji_in(path):
            name = unicodedata.name(character, "an unnamed symbol")
            offenders.append(f"{path.relative_to(APP_ROOT)}:{line}  {name}  {character}")

    assert not offenders, (
        "the front-end holds an emoji:\n"
        + "\n".join(offenders)
        + "\n\nAn emoji does not take the text colour, cannot be sized, and "
        "renders differently everywhere.  Draw the icon as an SVG with "
        "currentColor, the way the other twelve are drawn."
    )


def test_the_front_end_is_actually_being_checked():
    """A check that reads nothing passes everything.

    The rule is only worth having if the files it names are the files
    that ship, so the scan is checked against the panel's own sources.
    """
    names = {path.name for path in SOURCES}

    assert "SideChatApp.vue" in names, "the panel's own source is not being read"
    assert any(name.endswith(".bundle.js") for name in names), (
        "the built assets are not being read, so an emoji could ship in a bundle"
    )
