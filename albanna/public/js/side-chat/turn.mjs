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
//
// The poll is also polite about it: one poll in flight at a time, each
// idle poll waiting longer than the last, and the whole thing slowing
// right down while the socket is visibly delivering — a guarantee that is
// never exercised is not a guarantee, but it does not need to be loud.

/** The socket.io event the server publishes progress on. */
export const STREAM_EVENT = "albanna_chat_progress";

/** The endpoint that starts a turn. */
export const ASK_ENDPOINT = "albanna.api.chat.ask_stream";

/** The endpoint that reads a finished turn back. */
export const STATUS_ENDPOINT = "albanna.api.chat.status";

/** How often to ask whether the turn is done, the first time. */
export const STATUS_POLL_MS = 1500;

/** How much longer each idle poll waits than the one before it.
 *
 * A turn's answer usually arrives over the socket within seconds.  The
 * poll is the delivery *guarantee*, not the transport, so the gap grows
 * — one poll dictating a second of latency was a choice made when the
 * poll was the fast path. */
export const STATUS_POLL_GROWTH = 1.6;

/** The longest a wait between two idle polls grows to. */
export const STATUS_POLL_MAX_MS = 9000;

/** The gap between two polls while the socket is visibly delivering.
 *
 * When events are arriving, the transport is working and a poll is
 * almost redundant — yet a guarantee that is never exercised is not a
 * guarantee, so it still runs, slowly. */
export const STATUS_POLL_MS_WHILE_ALIVE = 12000;

/** How long after a socket event the socket still counts as alive. */
export const SOCKET_ALIVE_WINDOW_MS = 8000;

/** How long to wait before the first poll. */
export const FIRST_POLL_MS = 1200;

/**
 * The gap before the next poll.
 *
 * Three states, read from what the wait itself has seen: the socket has
 * spoken recently (the transport is alive — slow down), the socket has
 * gone quiet or never spoke (poll is the ear — keep the ramp), and the
 * ramp never grows past its cap.
 *
 * @param {object} state what the wait has observed
 * @param {number} state.lastEventAt when the last socket event arrived,
 *   zero if none ever has
 * @param {number} state.idlePolls how many polls have run without a
 *   settled answer
 * @param {number} now the current time, in milliseconds
 * @returns {number} milliseconds to wait before the next poll
 */
export function nextPollDelay({ lastEventAt = 0, idlePolls = 0 }, now) {
	if (lastEventAt > 0 && now - lastEventAt < SOCKET_ALIVE_WINDOW_MS) {
		return STATUS_POLL_MS_WHILE_ALIVE;
	}
	const grown = STATUS_POLL_MS * STATUS_POLL_GROWTH ** Math.max(0, idlePolls);
	return Math.min(Math.round(grown), STATUS_POLL_MAX_MS);
}

/**
 * Call a whitelisted method.
 *
 * `silent: true` on every call: `frappe.call` otherwise raises a modal
 * dialog per server message, and this panel renders its own errors inline.
 *
 * A server-side *refusal* comes back as an exception rather than a message,
 * and `frappe.call` shows it in a dialog.  The panel must show it too: a
 * chat that answers with an empty bubble is indistinguishable from a broken
 * one, and the person has no way to tell that the assistant was *refused*
 * rather than silent.
 *
 * @param {string} method the whitelisted method path
 * @param {object} args the arguments
 * @returns {Promise<object>} the `message` of the response
 */
export async function call(method, args = {}) {
	let result;
	try {
		result = await window.frappe.call({ method, args, silent: true });
	} catch (request) {
		// A server-side *refusal* comes back as a rejected request, and the
		// reason is in the response body.  The panel must show it: a chat
		// that answers with an empty bubble is indistinguishable from a
		// broken one, and the person has no way to tell that the assistant
		// was *refused* rather than silent.
		throw new Error(serverMessage(request) || __("The request could not be completed."));
	}

	const message = result && result.message;
	if (message && typeof message === "object") {
		return message;
	}

	throw new Error(serverMessage(result) || __("The request could not be completed."));
}

/**
 * The text the server refused with, if it said.
 *
 * @param {object} source the rejected request, or the raw response
 * @returns {string} the message, or an empty string
 */
function serverMessage(source) {
	if (!source) return "";

	// A rejected request carries the body as text.
	let body = source.responseJSON;
	if (!body && typeof source.responseText === "string") {
		try {
			body = JSON.parse(source.responseText);
		} catch (error) {
			body = null;
		}
	}
	const payload = body && typeof body === "object" ? body : source;

	const messages = payload._server_messages;
	if (messages) {
		try {
			const text = messageText(JSON.parse(messages));
			if (text) return text;
		} catch (error) {
			// Not JSON: fall through to the traceback.
		}
	}

	const exc = payload.exc;
	if (exc) {
		try {
			const parsed = JSON.parse(exc);
			if (Array.isArray(parsed) && parsed.length) {
				return lastLine(String(parsed[parsed.length - 1]));
			}
		} catch (error) {
			return lastLine(String(exc));
		}
	}

	return "";
}

/**
 * The text inside a server message, whatever shape it arrives in.
 *
 * A server message is an *envelope* — the text is in its `message`, and the
 * rest is how the Desk would present it — and Frappe sends it as a list of
 * envelopes, each of which has been serialised to a string inside the list.
 * So the unwrapping is three levels deep, and each level is handled rather
 * than assumed.
 *
 * @param {*} value the server message
 * @returns {string} the text, or an empty string
 */
function messageText(value) {
	if (!value) return "";

	if (typeof value === "string") {
		const trimmed = value.trim();
		if (trimmed.startsWith("{")) {
			try {
				return messageText(JSON.parse(trimmed));
			} catch (error) {
				return value;
			}
		}
		return value;
	}

	if (Array.isArray(value)) {
		for (const item of value) {
			const text = messageText(item);
			if (text) return text;
		}
		return "";
	}

	if (typeof value === "object" && value.message) {
		return String(value.message);
	}

	return "";
}

/**
 * The last line of a traceback, without the exception class in front of it.
 *
 * @param {string} text the traceback
 * @returns {string} the message
 */
function lastLine(text) {
	const line =
		String(text || "")
			.trim()
			.split("\n")
			.pop() || "";
	return line.replace(/^[A-Za-z_.]*(Error|Exception):\s*/, "");
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
 * @param {function} [options.onQueued] called with the stream id, once
 *   the turn is queued
 * @param {AbortSignal} [options.signal] aborts the *client's* wait
 * @returns {Promise<object>} the final payload
 */
export async function runTurn({
	question,
	image,
	conversationId,
	page,
	pageContext,
	onEvent,
	onQueued,
	signal,
}) {
	if (signal && signal.aborted) {
		return { status: "aborted" };
	}

	const queued = await call(ASK_ENDPOINT, {
		question,
		image: image || "",
		conversation_id: conversationId || "",
		page: page || "",
		page_context: pageContext ? JSON.stringify(pageContext) : "",
	});

	if (queued.status !== "queued" || !queued.stream_id) {
		return queued;
	}

	const streamId = queued.stream_id;

	// The stream id is the turn's address on the server, and the panel
	// writes it down: a reader who reloads the Desk during a turn can
	// find the turn again.
	if (onQueued) onQueued(streamId);

	return waitForTurn(streamId, { onEvent, signal });
}

/**
 * Wait for a turn that is already running.
 *
 * The same wait, for a turn that was queued before the page was
 * reloaded: the socket subscription and the poll are all that is needed
 * to pick a running turn up again.
 *
 * @param {string} streamId the turn's stream id
 * @param {object} [options]
 * @param {function} [options.onEvent] called with each progress event
 * @param {AbortSignal} [options.signal] aborts the *client's* wait
 * @param {string} [options.conversation] the thread the turn belongs to
 * @returns {Promise<object>} the final payload
 */
export function waitForTurn(streamId, { onEvent, signal, conversation = "" } = {}) {
	return new Promise((resolve) => {
		let settled = false;
		let pollTimer = null;
		let pollInFlight = false;
		let lastEventAt = 0;
		let idlePolls = 0;
		let unsubscribeSocket = () => {};

		const finish = (payload) => {
			if (settled) return;
			settled = true;
			unsubscribeSocket();
			if (pollTimer) window.clearTimeout(pollTimer);
			// The abort listener is removed here rather than left on the
			// signal: a signal outlives the turn, and a listener that
			// outlives its turn is a leak the user never sees.
			if (signal && onAbort) signal.removeEventListener("abort", onAbort);
			resolve(payload || { status: "error", error: __("No answer.") });
		};

		/* Stopping a turn is a *client* action.
		 *
		 * The worker keeps running and the answer is still parked in the
		 * cache, so the turn is not lost — it is merely no longer waited
		 * for.  That is the honest shape of it: a server-side cancel would
		 * have to reach into the worker to stop a model call that is
		 * already in flight, and the cost of that is a whole cancellation
		 * channel between the browser and the queue.
		 *
		 * What the user needs is to stop *watching*, and this does that:
		 * the socket subscription is dropped, the poll stops, and the panel
		 * is theirs again. */
		function onAbort() {
			finish({ status: "aborted" });
		}

		unsubscribeSocket = subscribe(streamId, (event) => {
			// When an event arrives, the socket is proven alive: the wait
			// uses that to slow its polls down to the guarantee-only rate.
			lastEventAt = Date.now();
			if (event.event === "done") {
				finish(event.result);
				return;
			}
			if (onEvent) onEvent(event);
		});

		/* The poll is the delivery guarantee.  It is *serialised*: the
		 * next poll is scheduled only when the previous one has finished,
		 * because a queue of unanswered polls piled up behind a slow
		 * response is requests spent on nothing.  And it ramps: each
		 * poll that comes back without an answer waits longer than the
		 * last, so a turn that is thinking hard is polled a few times a
		 * minute, not every second and a half.
		 *
		 * When a socket event arrives the socket is scheduled to slow
		 * right down, since the transport is working and the poll is
		 * only there to guarantee what is already working. */
		async function poll() {
			pollInFlight = true;
			try {
				const payload = await call(STATUS_ENDPOINT, { stream_id: streamId, conversation });
				if (payload && (payload.status === "ok" || payload.status === "error")) {
					finish(payload);
					return;
				}
				idlePolls += 1;
			} catch (error) {
				// A failed poll is not a failed turn; the next one may work.
				idlePolls += 1;
			} finally {
				pollInFlight = false;
				if (!settled) {
					// The delay is read *now*: a socket event that arrived
					// while the request was in flight is included in the
					// judgment, so a working socket slows the next poll.
					pollTimer = window.setTimeout(poll, nextPollDelay({ lastEventAt, idlePolls }, Date.now()));
				}
			}
		}
		pollTimer = window.setTimeout(poll, FIRST_POLL_MS);

		/* The abort listener goes on *last*, and that order matters.
		 *
		 * The signal may have been aborted while the request was in
		 * flight — which is exactly the race a reader hits by pressing
		 * Stop the moment the button changes.  If the listener were
		 * registered before the timers were made, `finish` would run
		 * first, find no timer to clear, and the poll would then be
		 * scheduled *after* the turn was already over: a timer nobody
		 * stops, polling a turn nobody is waiting for. */
		if (signal) {
			signal.addEventListener("abort", onAbort, { once: true });
			if (signal.aborted) onAbort();
		}
	});
}
