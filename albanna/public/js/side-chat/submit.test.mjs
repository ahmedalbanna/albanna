import assert from "node:assert";
import { submitDecision } from "./submit.mjs";

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