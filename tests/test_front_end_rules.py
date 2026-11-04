"""The front-end's own rules, written down where they are checked.

Two rules, both of which used to live in somebody's head and were lost
with the next contributor:

*   everything inside the panel is *logical* — ``padding-inline-start``,
    not ``padding-left``.  The build's RTL pass mirrors every ``left`` and
    ``right`` in the stylesheet, so a physical rule written for one reading
    direction lands on the wrong side in the other, and a logical property
    is left alone and resolved by the browser — which is the only thing
    that knows the direction.  See the comment at the top of
    ``albanna/public/css/albanna-side-chat.bundle.css``.

*   every colour is a token.  ``--albanna-*`` is declared once and
    referenced everywhere, so a theme change is one edit and a new colour
    is a decision rather than an accident.  An undefined token such as
    ``--albanna-primary`` silently becomes its fallback, and a fallback is
    a colour that follows nothing — which is how one filled state in the
    panel stayed blue in both themes until it was found by hand.
"""

from __future__ import annotations

import pathlib
import re

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "albanna"
FRONT_END = APP_ROOT / "public"

SOURCES = sorted(
    path
    for path in FRONT_END.rglob("*")
    if path.is_file()
    and path.suffix in {".vue", ".mjs", ".js", ".css"}
    and "public/dist" not in str(path)
)


def _strip_comments(text: str) -> str:
    """Blank out comments so they cannot masquerade as code."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("//"):
            lines.append("\n" if line.endswith("\n") else "")
        else:
            lines.append(line)
    return "".join(lines)


#: Physical direction properties.  The build mirrors ``left``/``right``, so
#: a physical one is a bug in an RTL sheet.
PHYSICAL_PATTERNS = (
    re.compile(r"\b(left|right)\s*:"),
    re.compile(r"\bmargin-(left|right)\b"),
    re.compile(r"\bpadding-(left|right)\b"),
    re.compile(r"\bborder-(left|right)\b"),
    re.compile(r"\bfloat\s*:\s*(left|right)\b"),
    re.compile(r"\btext-align\s*:\s*(left|right)\b"),
)


def test_no_physical_direction_property():
    """Every direction in the front-end is logical."""
    offenders: list[str] = []
    for path in SOURCES:
        text = _strip_comments(path.read_text(encoding="utf-8"))
        for index, line in enumerate(text.splitlines(), 1):
            for pattern in PHYSICAL_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(APP_ROOT)}:{index}  {line.strip()}")
                    break

    assert not offenders, (
        "the front-end carries a physical direction property:\n"
        + "\n".join(offenders)
        + "\n\nThe build's RTL pass mirrors every 'left' and 'right', so a "
        "physical rule lands on the wrong side in an RTL sheet.  Use the "
        "logical form (inline-start/end, padding-inline-*, ...) — the "
        "browser resolves it from the document's direction."
    )


TOKEN_REF = re.compile(r"var\(\s*(--albanna-[A-Za-z0-9-]+)")
TOKEN_DECL = re.compile(r"(--albanna-[A-Za-z0-9-]+)\s*:")


def test_every_albanna_token_is_declared():
    """Every ``var(--albanna-*)`` resolves to a declaration somewhere."""
    referenced: set[str] = set()
    declared: set[str] = set()
    for path in SOURCES:
        text = path.read_text(encoding="utf-8")
        referenced |= set(TOKEN_REF.findall(text))
        declared |= set(TOKEN_DECL.findall(text))

    missing = sorted(referenced - declared)
    assert not missing, (
        "the front-end references an undeclared token:\n"
        + "\n".join(f"  {name}" for name in missing)
        + "\n\nAn undefined token silently becomes its fallback, and a "
        "fallback is a colour that follows nothing.  Declare it, or stop "
        "referencing it."
    )


HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB = re.compile(r"rgba?\s*\(", re.I)


def _css_text(path: pathlib.Path) -> str:
    """The CSS a file contributes: a stylesheet, or a Vue style block."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".vue":
        blocks = re.findall(r"<style[^>]*>(.*?)</style>", text, flags=re.S | re.I)
        return "\n".join(blocks)
    if path.suffix == ".css":
        return text
    return ""


def test_no_colour_outside_a_token():
    """A colour literal appears only inside a ``--albanna-*`` declaration."""
    offenders: list[str] = []
    for path in SOURCES:
        css = _css_text(path)
        if not css:
            continue
        css = _strip_comments(css)
        for index, line in enumerate(css.splitlines(), 1):
            # A declaration: property: value (up to the next ; or }).
            for match in re.finditer(r"([A-Za-z-]+)\s*:\s*([^;}]*)", line):
                prop = match.group(1).strip()
                value = match.group(2).strip()
                if prop.startswith("--albanna-"):
                    continue
                # Fallbacks inside var(...) are allowed: drop them before
                # looking for a bare colour.
                value_no_var = re.sub(r"var\([^)]*\)", "", value)
                if HEX.search(value_no_var) or RGB.search(value_no_var):
                    offenders.append(f"{path.relative_to(APP_ROOT)}:{index}  {prop}: {value}")

    assert not offenders, (
        "a colour is painted outside a token:\n"
        + "\n".join(offenders)
        + "\n\nA bare hex or rgb()/rgba() in a rule does not follow the "
        "theme.  Put the colour in a --albanna-* token and reference it "
        "with var(...), the way every other filled state does."
    )


def test_the_front_end_is_actually_being_checked():
    """A check that reads nothing passes everything."""
    names = {path.name for path in SOURCES}

    assert "SideChatApp.vue" in names, "the panel's own source is not being read"
    assert any(name.endswith(".bundle.js") for name in names), (
        "the built assets are not being read, so a rule could ship in a bundle"
    )
    assert any(name.endswith(".bundle.css") for name in names), "the stylesheet is not being read"
