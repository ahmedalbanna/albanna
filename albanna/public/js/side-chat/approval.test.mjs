// The write-approval card is only actionable while the wait is open.

import assert from "node:assert";
import { APPROVAL_WINDOW_MS, canDecide, isExpired } from "./approval.mjs";

// A fresh approval may be decided.
{
	const approval = { request_id: "abc", at: 1000 };
	assert.equal(canDecide(approval, 1000), true);
	assert.equal(isExpired(approval, 1000), false);
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
	assert.equal(isExpired(approval, 1000 + APPROVAL_WINDOW_MS), true);
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