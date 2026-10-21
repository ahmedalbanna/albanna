// The turn's state, and the transitions between its states.
//
// The state of a turn is the part of the widget that can be wrong in
// ways the reader can see: a turn that is "running" and has already
// finished, a stop button that stops nothing, an error that hides a
// message.  So it is written down once, here, as a state machine, and
// the component is a view over it.
//
// Every function takes the state and changes it.  The state is a plain
// object, so it can be tested without Vue; the component holds it in a
// `reactive`, and a change is then a change on the screen.
//
// The phases are the whole of it.  `busy` and a per-message "pending"
// flag were two answers to one question, and they could disagree; a
// phase is one answer, and the transitions that change it change
// everything that depends on it.

/** No turn is running. */
export const IDLE = "idle";
/** A turn is running. */
export const RUNNING = "running";

/**
 * The state of the widget, before anything has happened.
 *
 * @returns {object} the state
 */
export function initialState() {
	return {
		/** One of IDLE, RUNNING, STOPPING. */
		phase: IDLE,
		/** The transcript. */
		messages: [],
		/** What the assistant is doing right now. */
		activity: "",
		/** Something went wrong. */
		error: "",
		/** Something happened that is not an error. */
		notice: "",
		/** The reader's last question, for a retry. */
		asked: "",
	};
}

/**
 * May the reader ask a question?
 *
 * @param {object} state the state
 * @returns {boolean} true when a question may be sent
 */
export function canSend(state) {
	return state.phase === IDLE;
}

/**
 * May the reader stop the turn?
 *
 * @param {object} state the state
 * @returns {boolean} true when a turn may be stopped
 */
export function canStop(state) {
	return state.phase === RUNNING;
}

/**
 * Is a turn in flight?
 *
 * @param {object} state the state
 * @returns {boolean} true when a turn is running or settling
 */
export function isBusy(state) {
	return state.phase !== IDLE;
}

/**
 * Start a turn.
 *
 * @param {object} state the state
 * @param {string} question the reader's question
 * @param {object} asked the message for the question
 * @param {object} answer the message for the answer
 * @returns {object} the answer message
 */
export function beginTurn(state, question, asked, answer) {
	state.phase = RUNNING;
	state.activity = "";
	state.error = "";
	state.notice = "";
	state.asked = question;
	state.messages.push(asked, answer);
	return answer;
}

/**
 * Say what the assistant is doing.
 *
 * @param {object} state the state
 * @param {string} activity the line to show
 */
export function setActivity(state, activity) {
	state.activity = activity;
}

/**
 * Finish a turn.
 *
 * The answer's *text* is the caller's: it renders the text, and this
 * says that the turn is over.  One owner each.
 *
 * @param {object} state the state
 * @param {object} answer the answer message
 */
export function endTurn(state, answer) {
	answer.pending = false;
	state.phase = IDLE;
	state.activity = "";
}

/**
 * Fail a turn.
 *
 * @param {object} state the state
 * @param {object} answer the answer message, if there is one
 * @param {string} message what went wrong
 */
export function failTurn(state, answer, message) {
	if (answer) answer.pending = false;
	state.phase = IDLE;
	state.activity = "";
	state.error = message;
}

/**
 * Stop a turn at the reader's request.
 *
 * The work finishes on the server; the waiting stops here.  What arrived
 * is kept — it is the truth so far — and the answer is in the
 * conversation when the reader comes back to it.
 *
 * The notice is the caller's: the panel says *why* a turn stopped, and
 * "because you moved to another page" is not the same sentence as
 * "because you asked it to".
 *
 * @param {object} state the state
 * @param {object} answer the answer message, if there is one
 */
export function stopTurn(state, answer) {
	if (answer) answer.pending = false;
	state.phase = IDLE;
	state.activity = "";
}

/**
 * Clear the transcript, because the reader has moved to another page.
 *
 * A turn in flight is stopped first: the answer would be about the page
 * the reader has left, and it belongs to that page's thread.
 *
 * @param {object} state the state
 * @returns {object|null} the answer message of a turn that was stopped
 */
export function clearTranscript(state) {
	let stopped = null;
	if (state.phase !== IDLE) {
		const answer = state.messages[state.messages.length - 1];
		if (answer && answer.pending) stopped = answer;
		stopTurn(state, answer);
	}
	state.messages = [];
	return stopped;
}

/**
 * Put a message away.
 *
 * @param {object} state the state
 * @param {string} channel "error" or "notice"
 */
export function dismiss(state, channel) {
	if (channel === "error") state.error = "";
	if (channel === "notice") state.notice = "";
}
