// The turn transport's stopping behaviour.
//
// The module is browser-only — it talks to the Desk — so the two things it
// reaches for are stubbed here: the Desk's `__`, and the Desk's `call`.
//
// What is being checked is the one promise the transport makes to the
// panel: a turn that is stopped *stops*.  It resolves, it does not leave
// the panel waiting, and it does not go on polling a server that the
// reader has already walked away from.

import assert from "node:assert";
import { runTurn } from "./turn.mjs";

// The Desk's translation function.
global.__ = (text) => text;

let asked = null;
let answered = null;

global.window = {
	frappe: {
		call: async ({ method, args }) => {
			asked = { method, args };
			if (method === "albanna.api.chat.ask_stream") {
				return { message: { status: "queued", stream_id: "stream-1" } };
			}
			return { message: { status: "ok" } };
		},
		realtime: {
			on: (event, handler) => {
				answered = handler;
			},
			off: () => {
				answered = null;
			},
		},
	},
	setTimeout: (fn, ms) => setTimeout(fn, ms),
	clearTimeout: (id) => clearTimeout(id),
	setInterval: (fn, ms) => setInterval(fn, ms),
	clearInterval: (id) => clearInterval(id),
};

// A turn that was stopped before it started never reaches the server.
{
	asked = null;
	const controller = new AbortController();
	controller.abort();

	const result = await runTurn({
		question: "which orders are open?",
		conversationId: "",
		page: "erpnext/sales-order",
		pageContext: null,
		signal: controller.signal,
	});

	assert.equal(result.status, "aborted");
	assert.equal(asked, null, "a stopped turn must not be queued");
}

// A turn that is stopped while it is running resolves as stopped.
{
	asked = null;
	const controller = new AbortController();

	const pending = runTurn({
		question: "which orders are open?",
		conversationId: "",
		page: "erpnext/sales-order",
		pageContext: null,
		signal: controller.signal,
	});

	// The stop arrives while the request is still in flight — which is
	// exactly the race a reader hits by pressing Stop the moment the
	// button changes.
	controller.abort();

	const result = await pending;
	assert.equal(result.status, "aborted");
	assert.ok(asked, "the turn was queued before it was stopped");
}

// A turn that is not stopped still finishes, and the socket's answer is
// what ends it.
{
	asked = null;
	answered = null;

	const pending = runTurn({
		question: "which orders are open?",
		conversationId: "",
		page: "erpnext/sales-order",
		pageContext: null,
	});

	// The socket delivers the finished answer.
	await new Promise((resolve) => setTimeout(resolve, 10));
	answered({ event: "done", stream_id: "stream-1", result: { status: "ok", reply: "24" } });

	const result = await pending;
	assert.equal(result.status, "ok");
	assert.equal(result.reply, "24");
}

console.log("turn: all assertions passed");

// The cadence of the guarantee: how long the next poll waits.
//
// Extracted as a pure function because the *wait itself* is browser-only,
// but the cadence is business logic: how often may a browser knock on the
// server while a turn is running.
import { nextPollDelay } from "./turn.mjs";

// A quiet socket ramps: the first idle poll keeps the old cadence, and
// each further idle poll waits longer.
{
	const t = 0;
	assert.equal(
		nextPollDelay({ lastEventAt: 0, idlePolls: 0 }, t),
		1500,
		"the first idle poll keeps the old rhythm",
	);
	assert.equal(
		nextPollDelay({ lastEventAt: 0, idlePolls: 1 }, t),
		2400,
		"the second waits longer",
	);
	assert.equal(nextPollDelay({ lastEventAt: 0, idlePolls: 2 }, t), 3840);
	assert.equal(
		nextPollDelay({ lastEventAt: 0, idlePolls: 5 }, t),
		9000,
		"by the sixth idle poll the cap holds",
	);
	assert.equal(
		nextPollDelay({ lastEventAt: 0, idlePolls: 50 }, t),
		9000,
		"it never grows past the cap",
	);
}

// A socket that has spoken recently has proven the transport works, and
// the poll slows right down — every idle poll it has run notwithstanding.
// The times are real clock times: a busy morning, not the epoch.
{
	const t = 1735000000000;
	assert.equal(nextPollDelay({ lastEventAt: t - 100, idlePolls: 0 }, t), 12000);
	assert.equal(
		nextPollDelay({ lastEventAt: t - 7900, idlePolls: 9 }, t),
		12000,
		"recent counts even after many idle polls",
	);
	// And an event older than the window falls back to the ramp.
	assert.equal(
		nextPollDelay({ lastEventAt: t - 8000, idlePolls: 0 }, t),
		1500,
		"a stale event does not count as alive",
	);
}

// A turn with no idea what the socket is doing also ramps, from the start.
{
	assert.equal(nextPollDelay({}, 0), 1500);
	assert.equal(nextPollDelay({}, 0), 1500);
}
