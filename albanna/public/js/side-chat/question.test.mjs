// The question card's own rules.
//
// Run under plain node:  node albanna/public/js/side-chat/question.test.mjs

import assert from "node:assert/strict";

global.__ = (text, args) => {
	let out = String(text);
	(args || []).forEach((value, index) => {
		out = out.replace(`{${index}}`, String(value));
	});
	return out;
};

const { ANSWERED, canAnswer, answerMessage, questionCard } = await import("./question.mjs");

/* -- the card ---------------------------------------------------------- */

const card = questionCard({
	name: "Q-0001",
	question: "أي عميل تريد؟",
	options: [
		{ label: "عميل نقدي", value: "عميل نقدي" },
		{ label: "أحمد عبدالله", value: "CUST-0002" },
	],
	status: "Pending",
});

assert.equal(card.name, "Q-0001");
assert.equal(card.question, "أي عميل تريد؟");
assert.equal(card.options.length, 2);
assert.equal(card.options[1].value, "CUST-0002");
assert.equal(card.status, "Pending");

/* A card that arrives half-built is a card with no buttons, not a card
   that throws. */
const empty = questionCard(null);
assert.equal(empty.name, "");
assert.deepEqual(empty.options, []);
assert.equal(empty.status, "Pending");

/* An option with no label is not a button. */
const half = questionCard({
	name: "Q-0002",
	options: [
		{ label: "", value: "x" },
		{ label: "ok", value: "y" },
	],
});
assert.equal(half.options.length, 1);
assert.equal(half.options[0].value, "y");

/* -- answering --------------------------------------------------------- */

assert.equal(canAnswer(card), true);
assert.equal(canAnswer(questionCard({ ...card, status: ANSWERED })), false);
assert.equal(canAnswer(questionCard({ ...card, options: [] })), false);
assert.equal(canAnswer(questionCard({ ...card, name: "" })), false);
assert.equal(canAnswer(null), false);

/* The message names the question, so the answer is not a bare string,
   and it carries the option's *value* — the thing the assistant goes on
   to use — rather than the label the reader saw. */
const message = answerMessage(card, card.options[1]);
assert.ok(message.includes("أي عميل تريد؟"));
assert.ok(message.includes("CUST-0002"));
assert.ok(!message.includes("أحمد عبدالله"));

/* An option with no value falls back to its label. */
const bare = answerMessage({ question: "Q?" }, { label: "A" });
assert.ok(bare.includes("A"));

/* A card with no question still carries the answer. */
assert.equal(answerMessage({ question: "" }, { label: "A" }), "A");

/* Nothing chosen, nothing said. */
assert.equal(answerMessage(card, null), "");
assert.equal(answerMessage(card, { label: "" }), "");

console.log("question.test.mjs: all assertions passed");
