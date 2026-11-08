// The notices the panel can show.
//
// Two rules, and both are about a sentence the reader sees once.
//
// A key the panel holds has a sentence, and a key it does not has none —
// a notice with no sentence is a notice the panel cannot show, so it says
// nothing rather than showing a key. And every sentence is the reader's:
// the state holds a key, never a sentence, because the reader's language
// can change under a notice that was already shown.

import assert from "node:assert/strict";
import { noticeText } from "./notices.mjs";

global.__ = (text) => text;

// The keys the panel actually puts in the state, and nothing else. A key
// added to the state machine and not here is a notice that shows nothing.
const KEYS = [
	"stopped",
	"moved",
	"no-table",
	"copy-failed",
	"copy-answer-failed",
	"deleted",
	"reverted",
	"cancelled",
	"conversation-deleted",
	"started",
	"removed",
	"attachments-dropped",
	"dry-run",
	"escalated",
	"undone",
];

for (const key of KEYS) {
	const sentence = noticeText(key);
	assert.ok(sentence.length > 0, `${key} has no sentence`);
	// A sentence, not a key: the reader is not shown the state machine's
	// own vocabulary.
	assert.notEqual(sentence, key, `${key} renders as its own key`);
}

// The keys are distinct sentences. Two notices that read the same are two
// notices the reader cannot tell apart.
const sentences = KEYS.map((key) => noticeText(key));
assert.equal(new Set(sentences).size, KEYS.length, "two notices read the same");

// A key the panel does not hold is not a notice, and shows nothing.
assert.equal(noticeText(""), "");
assert.equal(noticeText("no-such-notice"), "");
assert.equal(noticeText(undefined), "");
assert.equal(noticeText(null), "");

console.log("notices: all assertions passed");
