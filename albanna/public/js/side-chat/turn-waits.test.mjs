// Which waits belong to which thread.
//
// The bug this file exists to prevent: a wait of another thread counted
// as this thread's.  The symptom is a Stop button that vanishes while a
// turn is still streaming, and a turn that ends in thread A clearing the
// activity line of thread B.

import assert from "node:assert";
import { waitsOfConversation } from "./turn-waits.mjs";

/** The panel's waits, as it keeps them. */
function waits(...entries) {
	return entries.map(([streamId, waiting]) => [streamId, waiting]);
}

const firstQuestion = { controller: {}, conversation: "" };
const threadA = { controller: {}, conversation: "6bp8e4nplp" };
const threadB = { controller: {}, conversation: "other-thread" };

const all = waits(["s1", firstQuestion], ["s2", threadA], ["s3", threadB]);

// The waits of the thread being read, and only those.
{
	const here = waitsOfConversation(all, "6bp8e4nplp");
	assert.deepEqual(
		here.map((wait) => wait.streamId),
		["s2"],
		"the thread's own turns, and no other thread's",
	);
	assert.equal(here[0].conversation, "6bp8e4nplp");
}

// A reader with no thread yet: a first question's turn has no id.
{
	const here = waitsOfConversation(all, "");
	assert.deepEqual(
		here.map((wait) => wait.streamId),
		["s1"],
		"an empty id means the thread being shown, not every thread",
	);
}

// A thread with nothing running is an empty list, not everything.
{
	assert.deepEqual(waitsOfConversation(all, "nobody"), []);
	assert.deepEqual(waitsOfConversation([], "6bp8e4nplp"), []);
}

console.log("turn-waits: all assertions passed");
