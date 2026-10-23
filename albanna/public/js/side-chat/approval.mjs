// The write-approval card.
//
// A write that waits for the reader does so for two minutes.  After that
// the worker has already recorded a timeout, and a card that still offers
// "Approve" is a card that lies.  So the card is only actionable while
// the wait is still open, and the wall clock that decides that is the
// reader's — the server's clock is not on the reader's screen.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** How long a write waits for the reader, in milliseconds. */
export const APPROVAL_WINDOW_MS = 120000;

/**
 * Whether the card may still be decided.
 *
 * @param {{at?: number}} approval the pending approval
 * @param {number} now the current time, in milliseconds
 * @returns {boolean}
 */
export function canDecide(approval, now) {
	if (!approval || !approval.request_id) return false;
	const at = Number(approval.at);
	if (!Number.isFinite(at)) return false;
	return Number(now) - at < APPROVAL_WINDOW_MS;
}

/**
 * The seconds left on the wait, floored at zero.
 *
 * This is what the card's countdown says.  It agrees with
 * :func:`canDecide` by construction — both read the same window — so the
 * card cannot show "3s left" while refusing to be clicked, or the other
 * way round.
 *
 * @param {{at?: number}} approval the pending approval
 * @param {number} now the current time, in milliseconds
 * @returns {number} whole seconds left, zero when the wait has run out
 */
export function remainingSeconds(approval, now) {
	if (!canDecide(approval, now)) return 0;
	const at = Number(approval.at);
	return Math.max(0, Math.ceil((APPROVAL_WINDOW_MS - (Number(now) - at)) / 1000));
}

/**
 * Whether the wait has run out.
 *
 * @param {{at?: number}} approval the pending approval
 * @param {number} now the current time, in milliseconds
 * @returns {boolean}
 */
export function isExpired(approval, now) {
	return !canDecide(approval, now);
}