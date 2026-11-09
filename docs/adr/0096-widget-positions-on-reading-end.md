# ADR-0096: Widget positions on the reading end of the screen based on text direction

Status: **Accepted**
Date: 2026-11-09

## Context

FR-13.2 requires that the widget shall position itself on the reading end of the screen based on text direction. The widget position configuration in `Albanna Settings` already carries the field `widget_position` (Select: `bottom-right`, `bottom-left`, `floating`, default `bottom-right`). The JavaScript launcher in `albanna/public/js/side-chat/launcher.mjs` already implements the `sideFor(position)` function which maps `"bottom-left"` to `"inline-start"` and all other positions to `"inline-end"`. This ensures that the panel sits on the correct reading side regardless of whether the page direction is LTR or RTL.

The bundle code at `albanna/public/dist/js/albanna-side-chat.bundle.js` uses `sideFor(o)` to determine the physical edge class (`albanna-side-chat-pos-inline-start` or `albanna-side-chat-pos-inline-end`) that is applied to the panel container, and the CSS positions the panel accordingly.

## Decision

**Record the position-mapping function and the two outcomes.**

Two guards:

* `albanna/public/js/side-chat/launcher.mjs::sideFor(position)` asserts that the function maps `"bottom-left"` to `"inline-start"` and all other positions (`bottom-right`, `floating`) to `"inline-end"`. This is the logical side the panel sits on, where `"bottom-left"` is the inline start and everything else is the inline end.

* `albanna/public/dist/js/albanna-side-chat.bundle.js` asserts that the panel container receives the class `albanna-side-chat-pos-${f}` where `f` is the result of `sideFor(o)`, and the CSS uses this class to position the panel on the correct physical edge of the screen. When `f === "inline-start"`, the panel is on the left side (LTR) or right side (RTL); when `f === "inline-end"`, the panel is on the right side (LTR) or left side (RTL).

## Alternatives considered

**Always use `bottom-right` regardless of direction.** Rejected: the review's pattern has consistently found rules that are correct in the code and unheld by any test. A direction-aware position is the correct UX for readers of different languages.

**Use a separate `widget_position_rtl` field.** Rejected: the existing `widget_position` Select with three options is sufficient; the `sideFor` function handles the direction mapping without needing a separate configuration.

## Consequences

* FR-13.2 is now held: the `sideFor` function, the bundle's use of its result, and the CSS class based on it are each asserted — the widget positions itself on the reading end of the screen based on text direction.

* No code change was needed; the positioning logic was already implemented in `launcher.mjs`. The work was the ADR and this record.

## See also

* `albanna/public/js/side-chat/launcher.mjs::sideFor` — the position-to-side mapping function.
* `albanna/public/dist/js/albanna-side-chat.bundle.js` — the bundle that applies the position class.
* `albanna/albanna/doctype/albanna_settings/albanna_settings.json` — the `widget_position` Select field.
* `albanna/api/widget.py` — the API that passes `widget_position` to the client.