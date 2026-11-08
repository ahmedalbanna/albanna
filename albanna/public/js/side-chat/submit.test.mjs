import assert from "node:assert";
import { MAX_QUESTION_LENGTH, submitDecision } from "./submit.mjs";

// An empty question with no file is refused.
{
	const d = submitDecision({ modelValue: "   ", files: [], busy: false, canChat: true });
	assert.equal(d.ok, false);
	assert.equal(d.reason, "empty");
}

// A question with text is sent, trimmed.
{
	const d = submitDecision({ modelValue: "  hello  ", files: [], busy: false, canChat: true });
	assert.equal(d.ok, true);
	assert.equal(d.question, "hello");
}

// An empty question with an attached file is allowed.
{
	const d = submitDecision({ modelValue: "", files: [{ name: "a.png" }], busy: false, canChat: true });
	assert.equal(d.ok, true);
	assert.equal(d.question, "");
}

// While busy, nothing is sent.
{
	const d = submitDecision({ modelValue: "hi", files: [], busy: true, canChat: true });
	assert.equal(d.ok, false);
	assert.equal(d.reason, "busy");
}

// Without chat access, nothing is sent.
{
	const d = submitDecision({ modelValue: "hi", files: [], busy: false, canChat: false });
	assert.equal(d.ok, false);
	assert.equal(d.reason, "no-chat");
}

// A question at the ceiling is sent.
{
	const d = submitDecision({
		modelValue: "a".repeat(MAX_QUESTION_LENGTH),
		files: [],
		busy: false,
		canChat: true,
	});
	assert.equal(d.ok, true);
	assert.equal(d.question.length, MAX_QUESTION_LENGTH);
}

// A question over the ceiling is refused, and the refusal names its
// length: a reader told only "too long" cannot tell how much to cut.
{
	const d = submitDecision({
		modelValue: "a".repeat(MAX_QUESTION_LENGTH + 1),
		files: [],
		busy: false,
		canChat: true,
	});
	assert.equal(d.ok, false);
	assert.equal(d.reason, "too-long");
	assert.equal(d.length, MAX_QUESTION_LENGTH + 1);
}

// The length is the trimmed length: an indent is not part of the
// question, and a reader who pasted with one should not be charged.
{
	const d = submitDecision({
		modelValue: "  " + "a".repeat(MAX_QUESTION_LENGTH) + "  ",
		files: [],
		busy: false,
		canChat: true,
	});
	assert.equal(d.ok, true);
	assert.equal(d.length, MAX_QUESTION_LENGTH);
}

// An over-long question with a file attached is still refused: the file
// is not a licence to send an unbounded question.
{
	const d = submitDecision({
		modelValue: "a".repeat(MAX_QUESTION_LENGTH + 1),
		files: [{ name: "a.png" }],
		busy: false,
		canChat: true,
	});
	assert.equal(d.ok, false);
	assert.equal(d.reason, "too-long");
}