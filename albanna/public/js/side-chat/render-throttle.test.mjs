// The renders a streamed answer asks for, are coalesced.

import assert from "node:assert";
import { createRenderThrottle } from "./render-throttle.mjs";

/** A scheduler that collects callbacks without ever running them, so a
 * test can count the requests and flush them by hand. */
function fakeClock() {
	const pending = [];
	return {
		pending,
		schedule(fn, ms) {
			pending.push({ fn, ms });
			return pending.length;
		},
		flush(index = 0) {
			const item = pending.splice(index, 1)[0];
			if (item) item.fn();
		},
	};
}

// Fifty tokens arrive while the first render is still pending: exactly
// one render is scheduled, and it is the last one's gap.
{
	const clock = fakeClock();
	const renders = [];
	const request = createRenderThrottle((message) => renders.push(message), clock.schedule);

	for (let index = 0; index < 50; index += 1) {
		request({ content: `token ${index}` });
	}

	assert.equal(clock.pending.length, 1, "one render holds fifty requests");
	assert.equal(clock.pending[0].ms, 66, "at the module's own gap");

	clock.flush();
	assert.equal(renders.length, 1, "one render ran");
	assert.equal(renders[0].content, "token 49", "the last token's message is rendered");
	assert.equal(clock.pending.length, 0, "and nothing else is left to run");
}

// A render scheduled only once reveals the next batch when it finishes.
{
	const clock = fakeClock();
	const renders = [];
	const request = createRenderThrottle((message) => renders.push(message), clock.schedule);

	request({ content: "a" });
	request({ content: "ab" });
	clock.flush();
	assert.deepEqual(renders.map((m) => m.content), ["ab"], "the batch ends with the newest content");

	request({ content: "abc" });
	assert.equal(clock.pending.length, 1, "a request after the flush schedules a fresh render");
	clock.flush();
	assert.deepEqual(renders.map((m) => m.content), ["ab", "abc"]);
}

// A custom gap is honoured, so the panel could slow a heavy answer down
// without touching the logic.
{
	const clock = fakeClock();
	const request = createRenderThrottle(() => {}, clock.schedule, 250);
	request({ content: "x" });
	assert.equal(clock.pending[0].ms, 250);
}

// A token that arrives before any interest in renders is harmless.
{
	const clock = fakeClock();
	const request = createRenderThrottle(() => {}, clock.schedule, 50);
	request({ content: "one" });
	clock.flush();
	assert.equal(clock.pending.length, 0);
}
