// The recent questions sent with a turn.
//
// The rule under test: a follow-up question is only understandable as a
// follow-up if the assistant is told what was asked before, and the list
// is capped so that it stays a convenience rather than a history.

import assert from "node:assert";
import {
	MAX_RECENT_QUESTIONS,
	addQuestion,
	removeQuestion,
	renderRecentQuestions,
	replaceQuestion,
} from "./recent-questions.mjs";

// A question is added to the list.
{
	const asked = addQuestion([], "which sales orders are open?");
	assert.deepEqual(asked, ["which sales orders are open?"]);
}

// The questions accumulate, oldest first.
{
	let asked = [];
	asked = addQuestion(asked, "first");
	asked = addQuestion(asked, "second");
	assert.deepEqual(asked, ["first", "second"]);
}

// The list is capped, and what is dropped is the oldest.
{
	let asked = [];
	for (let index = 0; index < MAX_RECENT_QUESTIONS + 5; index += 1) {
		asked = addQuestion(asked, `question ${index}`);
	}
	assert.equal(asked.length, MAX_RECENT_QUESTIONS);
	assert.equal(asked[0], `question ${5}`);
	assert.equal(asked[asked.length - 1], `question ${MAX_RECENT_QUESTIONS + 4}`);
}

// A blank question is not a question.
{
	assert.deepEqual(addQuestion([], ""), []);
	assert.deepEqual(addQuestion([], "   "), []);
	assert.deepEqual(addQuestion([], null), []);
	assert.deepEqual(addQuestion(["kept"], ""), ["kept"]);
}

// The questions are rendered as one line, because the page context is
// carried as lines and a question that carries a newline would be two.
{
	const asked = addQuestion(addQuestion([], "first\nquestion"), "second");
	assert.equal(renderRecentQuestions(asked), "first question | second");
}

// No questions means no line.
{
	assert.equal(renderRecentQuestions([]), "");
	assert.equal(renderRecentQuestions(null), "");
	assert.equal(renderRecentQuestions(["", "  "]), "");
}

// An edited question takes the replaced one's place, and only there.
{
	const asked = addQuestion(addQuestion([], "first"), "second");
	assert.deepEqual(replaceQuestion(asked, "first", "first, edited"), [
		"first, edited",
		"second",
	]);
}

// A question that is not in the list leaves the list alone.
{
	const asked = addQuestion(addQuestion([], "first"), "second");
	assert.deepEqual(replaceQuestion(asked, "not here", "edited"), ["first", "second"]);
}

// The swap reads the same one line the list stores: a question that was
// carried with a newline was added collapsed, and the edit collapses too.
{
	const asked = addQuestion([], "first question");
	assert.deepEqual(replaceQuestion(asked, "first\nquestion", "second\nquestion"), [
		"second question",
	]);
}

// A blank replacement or a blank original is no swap.
{
	const asked = addQuestion([], "first");
	assert.deepEqual(replaceQuestion(asked, "first", "   "), ["first"]);
	assert.deepEqual(replaceQuestion(asked, "", "second"), ["first"]);
	assert.deepEqual(replaceQuestion(null, "first", "second"), []);
}

// Taking the current question out is what leaves the *rest* of the list
// for the prompt to carry — the question itself is carried as the
// question, not as its own history.
{
	const asked = addQuestion(addQuestion([], "first"), "second");
	assert.deepEqual(removeQuestion(asked, "second"), ["first"]);
	assert.deepEqual(removeQuestion(asked, "not here"), ["first", "second"]);
	assert.deepEqual(removeQuestion(asked, ""), ["first", "second"]);
}

console.log("recent-questions: all assertions passed");
