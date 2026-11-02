// The card that arrives through the poll.
//
// The socket is the fast path for progress events, but a socket that
// died mid-confirmation leaves the reader with nothing: the poll was
// reading a marker that said "running" and no card came with it. The
// marker now mirrors the card, and the poll is expected to hand it to
// the panel — shaped like the socket's own `confirm` event, once per
// request id, carrying the server's clock.
//
// What is checked here: the confirm event is forwarded exactly once,
// with the fields the panel's handler reads; a second poll carrying the
// same card forwards nothing new; and the wait keeps running until a
// settled answer arrives.

import assert from "node:assert";
import { waitForTurn } from "./turn.mjs";

global.__ = (text) => text;

// A socket-less client: every progress event must come through the
// poll, and the subscription must be a no-op that was never the point.
global.window = {
	frappe: {
		call: async ({ method, args }) => {
			if (method === "albanna.api.chat.status") {
				statusCalls += 1;
				if (statusCalls === 1) {
					return {
						message: {
							status: "awaiting_approval",
							pending: cardOne,
						},
					};
				}
				if (statusCalls === 2) {
					// The same card again: the poll cadence does not
					// get to redraw it.
					return { message: { status: "awaiting_approval", pending: cardOne } };
				}
				return { message: finalAnswer };
			}
			return { message: { status: "queued", stream_id: "stream-a" } };
		},
		realtime: { on: () => {}, off: () => {} },
	},
	setTimeout: (fn, ms) => setTimeout(fn, ms),
	clearTimeout: (id) => clearTimeout(id),
	setInterval: (fn, ms) => setInterval(fn, ms),
	clearInterval: (id) => clearInterval(id),
};

let statusCalls = 0;
let events = [];

const cardOne = {
	request_id: "req-1",
	name: "create_doc",
	arguments: { doctype: "Bank", data: { bank_name: "X" } },
	preview: "Create Bank: X",
	diff: null,
	window_seconds: 300,
	at: 1700000000000,
};
const finalAnswer = { status: "ok", reply: "the answer" };

const result = await waitForTurn("stream-a", {
	onEvent: (event) => events.push(event),
});

const confirms = events.filter((event) => event.event === "confirm");

assert.strictEqual(confirms.length, 1, "the card is forwarded once, not per poll");
assert.strictEqual(confirms[0].request_id, "req-1");
assert.strictEqual(confirms[0].preview, "Create Bank: X");
assert.strictEqual(confirms[0].window_seconds, 300);
assert.strictEqual(
	confirms[0].at,
	1700000000000,
	"the card counts down from the server's clock, not the poll's",
);
assert.strictEqual(result.status, "ok");
assert.ok(statusCalls >= 3, "the wait kept polling after forwarding the card");

console.log("turn-await: all assertions passed");
