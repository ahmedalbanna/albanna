// The turn's state machine.
//
// The state of a turn is the part of the widget a reader can see being
// wrong: a turn that is "running" and has already finished, a stop
// button that stops nothing, an error that hides a message.  So it is
// written down once, as transitions, and tested here — with no Vue, no
// browser and no site.

import assert from "node:assert";
import {
	IDLE,
	RUNNING,
	beginTurn,
	canSend,
	canStop,
	clearTranscript,
	dismiss,
	endTurn,
	failTurn,
	initialState,
	isBusy,
	setActivity,
	stopTurn,
} from "./state.mjs";

function message(role) {
	return { role, content: "", pending: false, tools: [] };
}

// A widget that has not been used is idle, and can be used.
{
	const state = initialState();

	assert.equal(state.phase, IDLE);
	assert.equal(canSend(state), true);
	assert.equal(canStop(state), false);
	assert.equal(isBusy(state), false);
	assert.deepEqual(state.messages, []);
}

// A turn that has begun is running, and cannot be sent again.
{
	const state = initialState();
	const asked = message("user");
	const answer = message("assistant");

	beginTurn(state, "how many orders are open?", asked, answer);

	assert.equal(state.phase, RUNNING);
	assert.equal(canSend(state), false, "a question may not be sent while one is running");
	assert.equal(canStop(state), true, "a running turn may be stopped");
	assert.equal(isBusy(state), true);
	assert.equal(state.messages.length, 2);
	assert.equal(state.asked, "how many orders are open?");
	assert.equal(answer.pending, false, "the answer is not pending until the turn says so");
}

// A turn that has finished is idle again, and the answer is not pending.
{
	const state = initialState();
	const answer = message("assistant");
	answer.pending = true;
	beginTurn(state, "q", message("user"), answer);
	setActivity(state, "Searching Sales Order");

	answer.content = "24 of them";
	endTurn(state, answer);

	assert.equal(state.phase, IDLE);
	assert.equal(canSend(state), true);
	assert.equal(answer.pending, false, "a finished turn is not pending");
	assert.equal(answer.content, "24 of them");
	assert.equal(state.activity, "", "a finished turn is not doing anything");
}

// A turn that failed says so, and is idle again.
{
	const state = initialState();
	const answer = message("assistant");
	answer.pending = true;
	beginTurn(state, "q", message("user"), answer);

	failTurn(state, answer, "the provider did not answer");

	assert.equal(state.phase, IDLE);
	assert.equal(answer.pending, false);
	assert.equal(state.error, "the provider did not answer");
}

// A turn the reader stopped says so, and is idle again.
{
	const state = initialState();
	const answer = message("assistant");
	answer.pending = true;
	beginTurn(state, "q", message("user"), answer);

	stopTurn(state, answer);

	assert.equal(state.phase, IDLE);
	assert.equal(answer.pending, false);
	assert.equal(state.error, "", "a stop is not an error");
}

// A page change clears the transcript — and stops a turn that was running,
// because the answer would be about the page the reader has left.
{
	const state = initialState();
	const answer = message("assistant");
	answer.pending = true;
	beginTurn(state, "q", message("user"), answer);

	const stopped = clearTranscript(state);

	assert.equal(stopped, answer, "the stopped answer is handed back");
	assert.equal(state.messages.length, 0, "the transcript is empty");
	assert.equal(state.phase, IDLE, "the turn is not running any more");
	assert.equal(answer.pending, false);
}

// A page change with nothing running just clears the transcript.
{
	const state = initialState();
	beginTurn(state, "q", message("user"), message("assistant"));
	endTurn(state, state.messages[1]);

	const stopped = clearTranscript(state);

	assert.equal(stopped, null, "nothing was running, so nothing was stopped");
	assert.equal(state.messages.length, 0);
}

// A message can be put away, and the error and the notice are separate
// channels: a notice must not be hidden by an error.
{
	const state = initialState();
	state.error = "the provider did not answer";
	state.notice = "Copied";

	dismiss(state, "notice");
	assert.equal(state.notice, "");
	assert.equal(state.error, "the provider did not answer", "the error is its own channel");

	dismiss(state, "error");
	assert.equal(state.error, "");
}

console.log("state: all assertions passed");
