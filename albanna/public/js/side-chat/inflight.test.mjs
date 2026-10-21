// The turn that is in flight, remembered across a reload.
//
// The rule under test: a reader who reloads during a turn finds the
// turn again — and only the turn of the page they are on.

import assert from "node:assert";
import {
	INFLIGHT_KEY,
	INFLIGHT_TTL_MS,
	clearInflight,
	loadInflight,
	saveInflight,
} from "./inflight.mjs";

/** A storage that keeps what it is given, like a browser's. */
function memoryStorage(initial) {
	const data = new Map(Object.entries(initial || {}));
	return {
		getItem: (key) => (data.has(key) ? data.get(key) : null),
		setItem: (key, value) => data.set(key, value),
		removeItem: (key) => data.delete(key),
		data,
	};
}

const turn = {
	stream_id: "abc123",
	conversation_id: "6bp8e4nplp",
	page: "List/Sales Order/List",
	question: "كم عدد أوامر البيع؟",
};

// A turn is written down and read back.
{
	const storage = memoryStorage();
	assert.equal(saveInflight(turn, storage), true);

	const entry = loadInflight(storage);
	assert.equal(entry.stream_id, "abc123");
	assert.equal(entry.conversation_id, "6bp8e4nplp");
	assert.equal(entry.page, "List/Sales Order/List");
	assert.equal(entry.question, "كم عدد أوامر البيع؟");
	assert.ok(entry.started_at, "the entry says when it was written");
}

// Nothing written means nothing to read.
{
	assert.equal(loadInflight(memoryStorage()), null);
	assert.equal(loadInflight(memoryStorage({ [INFLIGHT_KEY]: "not json" })), null);
	assert.equal(loadInflight(memoryStorage({ [INFLIGHT_KEY]: "{}" })), null);
}

// A turn that has been there too long is not a turn any more.
{
	const storage = memoryStorage({
		[INFLIGHT_KEY]: JSON.stringify({
			...turn,
			started_at: Date.now() - INFLIGHT_TTL_MS - 1000,
		}),
	});
	assert.equal(loadInflight(storage), null);
	assert.equal(storage.getItem(INFLIGHT_KEY), null, "and it is forgotten");
}

// A turn that is still within its time is read.
{
	const storage = memoryStorage({
		[INFLIGHT_KEY]: JSON.stringify({ ...turn, started_at: Date.now() - 1000 }),
	});
	assert.equal(loadInflight(storage).stream_id, "abc123");
}

// A turn can be forgotten.
{
	const storage = memoryStorage();
	saveInflight(turn, storage);
	clearInflight(storage);
	assert.equal(loadInflight(storage), null);
}

// A turn with no stream is not a turn.
{
	const storage = memoryStorage();
	assert.equal(saveInflight({ question: "no stream" }, storage), false);
	assert.equal(loadInflight(storage), null);
}

// A storage that refuses is a storage that cannot be asked to remember.
{
	const broken = {
		getItem: () => null,
		setItem: () => {
			throw new Error("no");
		},
		removeItem: () => {
			throw new Error("no");
		},
	};
	assert.equal(saveInflight(turn, broken), false);
	assert.equal(loadInflight(broken), null);
	clearInflight(broken);
}

console.log("inflight: all assertions passed");
