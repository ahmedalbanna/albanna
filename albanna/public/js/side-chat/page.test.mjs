// The Desk's route event.
//
// The widget has to hear the Desk say that the page changed.  It heard
// the wrong thing for a long time: it listened for "route-change", which
// the Desk never fires, so the page the widget thought it was on was
// frozen at the page it had been *opened* on.
//
// The Desk fires "change".  This test holds the widget to it.

import assert from "node:assert";
import { ROUTE_EVENT, watchRoute } from "./page.mjs";

/** The event the Desk's router fires.  Frappe's own code listens for it. */
const DESK_EVENT = "change";

function fakeRouter() {
	const handlers = {};
	return {
		handlers,
		on(event, handler) {
			handlers[event] = handlers[event] || [];
			handlers[event].push(handler);
		},
		off(event, handler) {
			const list = handlers[event] || [];
			const index = list.indexOf(handler);
			if (index >= 0) list.splice(index, 1);
		},
		fire(event) {
			for (const handler of (handlers[event] || []).slice()) handler();
		},
	};
}

let router = null;
global.window = {
	get frappe() {
		return { router };
	},
};

// The widget must listen for the event the Desk fires.
assert.equal(ROUTE_EVENT, DESK_EVENT, "the widget must listen for the Desk's event");

// It must hear the Desk say that the page changed.
{
	router = fakeRouter();
	let changes = 0;
	const unwatch = watchRoute(() => {
		changes += 1;
	});

	router.fire(DESK_EVENT);
	assert.equal(changes, 1, "the widget must hear the Desk's route change");

	// And it must hear nothing else.  An event the Desk does not fire is
	// an event that never arrives, and a widget that waits for one waits
	// for ever.
	router.fire("route-change");
	assert.equal(changes, 1, "the widget must not wait for an event the Desk never fires");

	unwatch();
	router.fire(DESK_EVENT);
	assert.equal(changes, 1, "unwatching must stop the notifications");
}

// A Desk without a router is still a Desk, and the widget must not
// throw when there is nothing to watch.
{
	router = null;
	let watched = false;
	const unwatch = watchRoute(() => {
		watched = true;
	});

	assert.equal(typeof unwatch, "function", "watching must always return an unwatch");
	unwatch();
	assert.equal(watched, false);
}

console.log("page: all assertions passed");
