// The panel's focus trap.
//
// The panel is two different things depending on how it is shown: a
// column beside the Desk (docked, on a wide screen) or a surface over
// it (floating by configuration, or docked on a narrow screen, where
// the dock is disabled and the panel floats full-height).  A column's
// neighbour is active content — a trap there would strand the keyboard
// user out of the very Desk the answer is about.  An overlay's behind
// is *not* active: Tab walking out of it lands in content a sighted
// reader cannot see the panel leaving, so the reader is lost.
//
// So the trap answers one question first — is this panel, right now, an
// overlay? — and only when it is does Tab cycle inside it.
//
// Pure: no `frappe`, no Vue.  The DOM parts take the elements they are
// given, so the tests can hand them fakes.

/** The viewport where the dock disables and a docked panel floats. */
export const DOCK_OFF_QUERY = "(max-width: 991px)";

/**
 * Whether the panel is being shown *over* the Desk right now.
 *
 * @param {string} position the configured position
 * @param {boolean} narrow whether the dock-off media query matches
 * @returns {boolean} true when the panel is an overlay
 */
export function isOverlay(position, narrow) {
	return position === "floating" || Boolean(narrow);
}

/**
 * The elements inside *container* Tab would stop at, in order.
 *
 * A button the panel has disabled and a thing the browser has hidden
 * are not stops — a trap that cycled into a disabled button is a trap
 * that swallows a keypress.
 *
 * @param {Element} container the panel
 * @returns {Element[]} the stops, in Tab order
 */
export function focusables(container) {
	const stops = container.querySelectorAll(
		[
			"a[href]",
			"button:not(:disabled)",
			"input:not(:disabled)",
			"select:not(:disabled)",
			"textarea:not(:disabled)",
			"[tabindex]:not([tabindex='-1'])",
		].join(","),
	);
	return Array.from(stops).filter((element) => {
		if (element.disabled || element.getAttribute("aria-disabled") === "true") return false;
		if (element.hidden || element.getAttribute("aria-hidden") === "true") return false;
		// An element whose subtree the panel hid by display: none has no
		// boxes, and Tab does not stop at it.  `offsetParent` answers
		// exactly that — null when nothing of the element is laid out.
		return element.offsetParent !== null;
	});
}

/**
 * The element Tab should land on, or null when the trap does not apply.
 *
 * The caller focuses what comes back.  A panel with no stops — an
 * empty transcript, a drawer still loading — returns null, and the
 * keypress falls through to the browser, which does nothing with it
 * either.
 *
 * @param {Element} container the panel
 * @param {Element} current the element the focus is on now
 * @param {boolean} backward Shift+Tab
 * @returns {Element|null} the next stop
 */
export function nextFocusable(container, current, backward) {
	const stops = focusables(container);
	if (!stops.length) return null;
	const index = stops.indexOf(current);
	if (index === -1) {
		// The focus is not on a stop — say, on the panel itself.  Enter
		// the cycle at the end the reader is heading for.
		return backward ? stops[stops.length - 1] : stops[0];
	}
	const next = index + (backward ? -1 : 1);
	if (next < 0) return stops[stops.length - 1];
	if (next >= stops.length) return stops[0];
	return stops[next];
}
