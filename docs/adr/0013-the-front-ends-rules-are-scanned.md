# ADR-0013: The front-end's rules are enforced by scanning the sources

Status: **Accepted**
Date: 2026-11-05

## Context

The app has front-end rules that were written down in comments and in
nobody's job description.  Three of them were broken in the code at the
same time, and each had been broken long enough that the comment saying
it must not be broken was the only thing that knew.

* **An emoji.**  The paperclip on the attachment label.  It was the last
  one in the app, and it was there because nobody was told it was not
  allowed.  `tests/test_icons.py` was written for it, and its docstring
  says the thing worth remembering: *"a rule that lives only in
  somebody's head is gone with the next contributor."*
* **A physical direction property.**  `padding-left: 4px` on the
  attachment notice — the only one in a stylesheet whose header says
  everything inside the panel is logical.  It rendered correctly, because
  the build's RTL pass flipped it, which is precisely what made it
  survivable: a rule that works by accident is a rule nobody notices is
  load-bearing.
* **An undeclared token.**  `--albanna-primary`, referenced twice and
  declared nowhere.  The selected question option was therefore painted
  with its fallback — a hardcoded blue — in both themes, and it was the
  only filled state in the panel that did not follow the Desk.

`tests/test_dark_mode.py` did not catch the third one, and the reason
matters more than the miss.  That test checks *consequences*: the accent
is never used as ink, a red fill carries its own ink, the dark theme
declares its own ink, three named selectors use the link ink.  An
undefined token is not a *reused* one, so none of those assertions had
anything to say about it.  A test that checks what a rule implies will
pass while the rule itself is broken.

## Decision

**The front-end's rules are enforced by tests that read the sources, not
by comments and reviewer memory.**

`tests/test_front_end_rules.py` holds two scans, both shaped like
`test_icons.py`: walk `albanna/public/`, read the files that ship, and
fail on a violation with a message that says what to do instead.

* **Direction.**  No physical direction property anywhere in the
  front-end — `left:`, `right:`, `margin-left`, `padding-left`,
  `border-left`, `float: left|right`, `text-align: left|right`.  The
  build's RTL pass mirrors every `left` and `right`, so a physical rule
  written for one reading direction lands on the wrong side in the
  other; a logical property is left alone and resolved by the browser,
  which is the only thing that knows the direction.
* **Tokens.**  Every `var(--albanna-*)` referenced is declared somewhere,
  and no rule paints a colour outside a token.  A declaration whose value
  *is* a hex or `rgb()` is allowed only inside a custom property.

Both scans carry the assertion that makes a scan worth having —
`test_the_front_end_is_actually_being_checked` — because a check that
reads nothing passes everything, and the emoji scan already learned that
lesson once.

**Each guard was proved to fail before it was trusted.**  The undeclared
token, the physical property, the missing `app_include_js` entry and the
unguarded storage read were each put back into the code one at a time,
and each turned exactly the right test red.  A green test is not
evidence; a test that has been seen to go red is.

## Alternatives considered

**Keep the rules in comments and rely on review.**  This is what was
there, and it is what failed three times over.  A comment is read by
whoever is already thinking about the thing it describes; a scan is read
by everybody, on every commit, including the contributor who has never
heard of the rule.

**Check the consequences, the way `test_dark_mode.py` does.**  Rejected
as the *only* mechanism, for the reason above: it passes while the rule
is broken.  It stays as what it is — a set of assertions about specific
outcomes that are too specific to scan for — and the scans sit beside it
rather than replacing it.

**Lint the CSS with an off-the-shelf plugin.**  Rejected: it adds a
dependency and a build step to enforce four rules that are forty lines of
Python, and the app already has the pattern working for emoji.  A rule
the repo can read is worth more than a rule a tool enforces.

**Scan the JavaScript for colour literals too.**  Deliberately not done.
The launcher injects its boot-failure styles as a string, with hardcoded
colours, because the bundle whose CSS cannot be trusted to render an
error is the bundle that failed to load.  Those literals are correct and
the scan would have to be weakened to allow them, so the colour scan
reads `.css` files and Vue `<style>` blocks and leaves the scripts
alone.  The cost is that a hardcoded colour in JavaScript slips past;
the cost of the alternative is a gate that cries wolf.

## Consequences

* A physical property, an undeclared token or a bare colour in a rule
  fails the suite with a message naming the file, the line and the
  logical form to use instead.
* The rules are now stated twice — once in the comment that explains
  them, once in the test that enforces them — and the test is the one
  that survives a contributor who has not read the comment.
* `tests/test_icons.py` keeps the emoji scan and is not duplicated here.
  If the three scans are ever consolidated, that is a refactor to do on
  purpose rather than by accident.
* The next front-end rule the app adopts has a home to be enforced in,
  which is the actual point: the paperclip was not the last emoji because
  somebody decided to allow it, it was the last one because somebody
  finally wrote the check down.

## See also

* [ADR-0017](0017-pure-logic-does-not-live-in-a-browser-bundle.md) — the
  other rule this pass had to enforce in a second place, and the reason
  the launcher bundle is where untested logic could hide.
* `tests/test_icons.py` — the pattern this copies, and the incident that
  produced it.
* `tests/test_dark_mode.py` — the consequence-level assertions these
  scans sit beside.
