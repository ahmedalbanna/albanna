// The focus trap's rules, read under plain node with fake elements.
//
// The trap is a behaviour about *order* and *membership*: which stops
// exist, which do not, where the cycle wraps.  None of that needs a
// real browser — the fakes carry only the properties the module reads.

import assert from "node:assert";
import {
	DOCK_OFF_QUERY,
	focusables,
	isOverlay,
	nextFocusable,
} from "./focus-trap.mjs";

/** A fake element with just the properties the trap reads. */
function el(name, { disabled = false, hidden = false, offsetParent = {}, tabindex = null } = {}) {
	return {
		name,
		disabled,
		hidden,
		offsetParent,
		getAttribute: (attr) =>
			attr === "aria-disabled" || attr === "aria-hidden"
				? null
				: attr === "tabindex"
					? tabindex
					: null,
	};
}

/** A fake container whose querySelectorAll answers with a fixed list. */
function container(list) {
	return { querySelectorAll: () => list };
}

function test_the_dock_off_query_names_the_css_breakpoint() {
	assert.equal(DOCK_OFF_QUERY, "(max-width: 991px)");
}

function test_a_floating_panel_is_an_overlay_at_any_width() {
	assert.equal(isOverlay("floating", false), true);
}

function test_a_docked_panel_is_an_overlay_on_a_narrow_screen() {
	assert.equal(isOverlay("bottom-right", true), true);
	assert.equal(isOverlay("bottom-left", true), true);
}

function test_a_docked_panel_on_a_wide_screen_is_a_column_not_an_overlay() {
	assert.equal(isOverlay("bottom-right", false), false);
	assert.equal(isOverlay("bottom-left", false), false);
}

function test_a_disabled_button_is_not_a_stop() {
	const active = el("active");
	const stops = focusables(container([el("dead", { disabled: true }), active]));
	assert.deepEqual(stops, [active]);
}

function test_a_hidden_button_is_not_a_stop() {
	const active = el("active");
	const stops = focusables(container([el("gone", { hidden: true }), active]));
	assert.deepEqual(stops, [active]);
}

function test_a_display_none_button_is_not_a_stop() {
	const active = el("active");
	const stops = focusables(
		container([el("collapsed", { offsetParent: null }), active]),
	);
	assert.deepEqual(stops, [active]);
}

function test_an_aria_hidden_button_is_not_a_stop() {
	const gone = el("gone");
	gone.getAttribute = (attr) => (attr === "aria-hidden" ? "true" : null);
	const active = el("active");
	const stops = focusables(container([gone, active]));
	assert.deepEqual(stops, [active]);
}

function test_forward_tab_wraps_from_the_last_stop_to_the_first() {
	const first = el("first");
	const last = el("last");
	const panel = container([first, el("middle"), last]);
	assert.equal(nextFocusable(panel, last, false), first);
}

function test_backward_tab_wraps_from_the_first_stop_to_the_last() {
	const first = el("first");
	const last = el("last");
	const panel = container([first, el("middle"), last]);
	assert.equal(nextFocusable(panel, first, true), last);
}

function test_tab_steps_through_the_stops_in_order() {
	const first = el("first");
	const middle = el("middle");
	const last = el("last");
	const panel = container([first, middle, last]);
	assert.equal(nextFocusable(panel, first, false), middle);
	assert.equal(nextFocusable(panel, middle, false), last);
	assert.equal(nextFocusable(panel, middle, true), first);
}

function test_tab_into_a_panel_whose_focus_is_outside_the_cycle() {
	const first = el("first");
	const last = el("last");
	const panel = container([first, last]);
	const outsider = el("outside");
	assert.equal(nextFocusable(panel, outsider, false), first);
	assert.equal(nextFocusable(panel, outsider, true), last);
}

function test_an_empty_panel_refuses_the_trap() {
	assert.equal(nextFocusable(container([]), el("current"), false), null);
}

const tests = [
	test_the_dock_off_query_names_the_css_breakpoint,
	test_a_floating_panel_is_an_overlay_at_any_width,
	test_a_docked_panel_is_an_overlay_on_a_narrow_screen,
	test_a_docked_panel_on_a_wide_screen_is_a_column_not_an_overlay,
	test_a_disabled_button_is_not_a_stop,
	test_a_hidden_button_is_not_a_stop,
	test_a_display_none_button_is_not_a_stop,
	test_an_aria_hidden_button_is_not_a_stop,
	test_forward_tab_wraps_from_the_last_stop_to_the_first,
	test_backward_tab_wraps_from_the_first_stop_to_the_last,
	test_tab_steps_through_the_stops_in_order,
	test_tab_into_a_panel_whose_focus_is_outside_the_cycle,
	test_an_empty_panel_refuses_the_trap,
];

for (const test of tests) {
	test();
}
console.log(`focus-trap: ${tests.length} tests passed`);
