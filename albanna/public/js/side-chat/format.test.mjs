// The clocks the activity line reads.
//
// The rule under test: a turn that is alive can be seen being alive.  The
// line says what is happening, and after a few seconds of silence it says
// for how long — the gap between two tool calls stops looking like a turn
// that died.

import assert from "node:assert/strict";
import { activityText, elapsedSeconds, middleTruncate } from "./format.mjs";

global.__ = (text, args) => {
	if (Array.isArray(args)) {
		return args.reduce((out, value, index) => out.split(`{${index}}`).join(value), text);
	}
	return text;
};

// -- the seconds --------------------------------------------------------

const NOW = 1_700_000_000_000; // epoch ms

// Epoch seconds are the shape the message carries.
assert.equal(elapsedSeconds(NOW / 1000 - 12, NOW), 12);

// A started moment after "now" reads as zero, not as negative.
assert.equal(elapsedSeconds(NOW / 1000 + 30, NOW), 0);

// The shapes the server's timestamps arrive in.
assert.equal(elapsedSeconds(new Date(NOW - 5000), NOW), 5);
assert.equal(
	elapsedSeconds(new Date(NOW - 5000).toISOString().replace("T", " ").slice(0, 19), NOW) >= 4,
	true,
);

// Unreadable ends cost nothing: the line keeps its label.
assert.equal(elapsedSeconds(null, NOW), 0);
assert.equal(elapsedSeconds(NOW / 1000, undefined), 0);
assert.equal(elapsedSeconds(NOW / 1000, Number.NaN), 0);

// -- the line -----------------------------------------------------------

// Under the threshold: the label, and only the label.
assert.equal(activityText("Searching Sales Order", NOW / 1000 - 4, NOW), "Searching Sales Order");
assert.equal(activityText("Searching Sales Order", NOW / 1000, NOW), "Searching Sales Order");

// Past it: the label, and the ticking tail.
assert.equal(activityText("Searching Sales Order", NOW / 1000 - 12, NOW), "Searching Sales Order · 12s");
assert.equal(activityText("Thinking", NOW / 1000 - 65, NOW), "Thinking · 65s");

// The threshold itself: five seconds is the first second the tail shows.
assert.equal(activityText("Thinking", NOW / 1000 - 5, NOW), "Thinking · 5s");
assert.equal(activityText("Thinking", NOW / 1000 - 4, NOW, 5), "Thinking");

// No label, no line — an empty activity must not print "· 12s".
assert.equal(activityText("", NOW / 1000 - 12, NOW), "");
assert.equal(activityText(null, NOW / 1000 - 12, NOW), "");

// A threshold of zero shows the tail from the first second.
assert.equal(activityText("Thinking", NOW / 1000 - 2, NOW, 0), "Thinking · 2s");

// -- the middle cut -----------------------------------------------------

// Short names go whole.
assert.equal(middleTruncate("orders.csv"), "orders.csv");
assert.equal(middleTruncate("a".repeat(24)), "a".repeat(24));
assert.equal(middleTruncate(""), "");

// A long name keeps its front and its back — the back is where the
// extension lives, and the reader is sending the file *as* that type.
{
	const name = "quarterly-financial-report-2026-11.xlsx";
	const cut = middleTruncate(name);
	assert.equal(cut.length, 24);
	assert.ok(cut.startsWith("quarterly-fin"));
	assert.ok(cut.endsWith(".xlsx"));
	assert.ok(cut.includes("…"));
}

// A cut always yields at most `max` characters and never an empty head.
assert.equal(middleTruncate("x".repeat(25), 24, 8), `${"x".repeat(15)}…${"x".repeat(8)}`);
assert.equal(middleTruncate("abcdefgh", 3, 100).startsWith("a"), true);

console.log("format: all assertions passed");
