// The turn transport.
//
// A turn is not a request that returns an answer — it is a request that
// starts a turn, a stream of progress events, and eventually an answer.
// This module owns all three, and hides the difference between the two
// ways progress can arrive.
//
// The socket is the fast path: the user sees tokens as they are produced
// and each tool call as it starts and finishes.  The poll is the guarantee:
// Frappe's request model cannot stream a response, so the worker also parks
// the finished answer in the cache, and this module reads it back until it
// arrives.  A client whose socket died still gets its answer, because the
// poll does not care about the socket.

/** The socket.io event the server publishes progress on. */
export const STREAM_EVENT = "albanna_chat_progress";

/** The endpoint that starts a turn. */
export const ASK_ENDPOINT = "albanna.api.chat.ask_stream";

/** The endpoint that reads a finished turn back. */
export const STATUS_ENDPOINT = "albanna.api.chat.status";

/** How often to ask whether the turn is done. */
export const STATUS_POLL_MS = 1500;

/** How long to wait before the first poll. */
export const FIRST_POLL_MS = 1200;

/**
 * Call a whitelisted method.
 *
 * `silent: true` on every call: `frappe.call` otherwise raises a modal
 * dialog per server message, and this panel renders its own errors inline.
 *
 * @param {string} method the whitelisted method path
 * @param {object} args the arguments
 * @returns {Promise<object>} the `message` of the response
 */
export async function call(method, args = {}) {
	const result = await window.frappe.call({ method, args, silent: true });
	return (result && result.message) || {};
}

/**
 * Subscribe to the progress events of one turn.
 *
 * Every event carries the stream id, and the socket is site-wide, so the
 * filter is what keeps one user's progress out of another user's browser.
 *
 * @param {string} streamId the turn to listen for
 * @param {function} handler called with each event
 * @returns {function} an unsubscribe function
 */
export function subscribe(streamId, handler) {
	const realtime = window.frappe && window.frappe.realtime;
	if (!realtime || typeof realtime.on !== "function") return () => {};

	const wrapped = (payload) => {
		if (!payload || payload.stream_id !== streamId) return;
		handler(payload);
	};

	realtime.on(STREAM_EVENT, wrapped);
	return () => {
		try {
			realtime.off(STREAM_EVENT, wrapped);
		} catch (error) {
			// A socket that has already gone is not a failure worth raising.
		}
	};
}

/**
 * Run one turn to completion.
 *
 * @param {object} options
 * @param {string} options.question what the user asked
 * @param {string} options.conversationId the thread to continue
 * @param {string} options.page the page identity
 * @param {object} options.pageContext the page description
 * @param {function} options.onEvent called with each progress event
 * @returns {Promise<object>} the final payload
 */
export async function runTurn({ question, conversationId, page, pageContext, onEvent }) {
	const queued = await call(ASK_ENDPOINT, {
		question,
		conversation_id: conversationId || "",
		page: page || "",
		page_context: pageContext ? JSON.stringify(pageContext) : "",
	});

	if (queued.status !== "queued" || !queued.stream_id) {
		return queued;
	}

	const streamId = queued.stream_id;

	return new Promise((resolve) => {
		let settled = false;
		let pollTimer = null;
		let firstPoll = null;
		let unsubscribeSocket = () => {};

		const finish = (payload) => {
			if (settled) return;
			settled = true;
			unsubscribeSocket();
			if (firstPoll) window.clearTimeout(firstPoll);
			if (pollTimer) window.clearInterval(pollTimer);
			resolve(payload || { status: "error", error: "No answer." });
		};

		unsubscribeSocket = subscribe(streamId, (event) => {
			if (event.event === "done") {
				finish(event.result);
				return;
			}
			if (onEvent) onEvent(event);
		});

		// The poll is the delivery guarantee.  It starts a moment after the
		// socket subscription so a fast turn is not asked for twice.
		const poll = async () => {
			try {
				const payload = await call(STATUS_ENDPOINT, { stream_id: streamId });
				if (payload && (payload.status === "ok" || payload.status === "error")) {
					finish(payload);
				}
			} catch (error) {
				// A failed poll is not a failed turn; the next one may work.
			}
		};
		firstPoll = window.setTimeout(() => {
			pollTimer = window.setInterval(poll, STATUS_POLL_MS);
			poll();
		}, FIRST_POLL_MS);
	});
}
