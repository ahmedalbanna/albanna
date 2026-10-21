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
