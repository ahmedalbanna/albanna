// The write-approval card is only actionable while the wait is open.

import assert from "node:assert";
import { APPROVAL_WINDOW_MS, canDecide, remainingSeconds } from "./approval.mjs";

// A fresh approval may be decided.
{
	const approval = { request_id: "abc", at: 1000 };
	assert.equal(canDecide(approval, 1000), true);
}

// An approval at the very edge of the window is still open.
{
	const approval = { request_id: "abc", at: 1000 };
	assert.equal(canDecide(approval, 1000 + APPROVAL_WINDOW_MS - 1), true);
}

// Once the window passes, it is expired.
{
	const approval = { request_id: "abc", at: 1000 };
	assert.equal(canDecide(approval, 1000 + APPROVAL_WINDOW_MS), false);
}

// An approval with no request id cannot be decided.
{
	assert.equal(canDecide({ at: 1000 }, 1000), false);
	assert.equal(canDecide(null, 1000), false);
}

// An approval with no timestamp cannot be decided.
{
	assert.equal(canDecide({ request_id: "abc" }, 1000), false);
}

// The countdown and the actionable window agree, by construction.
{
	const approval = { request_id: "abc", at: 1000 };
	// Just opened: the full window, rounded up.
	assert.equal(remainingSeconds(approval, 1000), 120);
	// One second in.
	assert.equal(remainingSeconds(approval, 2000), 119);
	// Half a second in still says 120 — it counts the whole first second.
	assert.equal(remainingSeconds(approval, 1500), 120);
	// The last actionable instant still says 1, not 0.
	assert.equal(remainingSeconds(approval, 1000 + APPROVAL_WINDOW_MS - 100), 1);
	// Expired: zero, and the card is not clickable either.
	assert.equal(remainingSeconds(approval, 1000 + APPROVAL_WINDOW_MS), 0);
	assert.equal(canDecide(approval, 1000 + APPROVAL_WINDOW_MS), false);
}

// An unusable approval says 0 seconds rather than a number.
{
	assert.equal(remainingSeconds(null, 1000), 0);
	assert.equal(remainingSeconds({ at: 1000 }, 1000), 0);
}