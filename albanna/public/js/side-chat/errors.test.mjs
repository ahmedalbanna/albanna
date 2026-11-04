// The text a server refusal carries, whatever shape it arrives in.
//
// The rule under test: a refusal that says something is shown to the
// reader, in every shape the Desk sends one.  A chat that answers with
// an empty bubble is indistinguishable from a broken one, and the person
// has no way to tell that the assistant was *refused* rather than
// silent.
//
// The unwrapping used to be written twice — once in the turn's module
// and once in the composer — and only one of the two copies had a test.
// These are the tests both copies now share.

import assert from "node:assert";
import { failureText, lastLine, messageText, serverMessage } from "./errors.mjs";

// The Desk's own envelope: the text is in its `message`.
const envelope = (text) => JSON.stringify({ message: text });

// A rejected request whose body is JSON, with the Desk's envelopes in it.
{
	const source = {
		responseJSON: {
			_server_messages: JSON.stringify([envelope("You may not read that.")]),
		},
	};
	assert.equal(serverMessage(source), "You may not read that.");
}

// A body that arrives as text rather than as JSON.
{
	const source = {
		responseText: JSON.stringify({
			_server_messages: JSON.stringify([envelope("Not allowed.")]),
		}),
	};
	assert.equal(serverMessage(source), "Not allowed.");
}

// A body that is not JSON at all says nothing, and does not throw.
{
	assert.equal(serverMessage({ responseText: "not json" }), "");
}

// A refusal that is a list of traceback lines: the last line is the
// message, and the rest is the noise a reader does not need.
{
	const source = {
		responseJSON: {
			exc: JSON.stringify([
				"Traceback (most recent call last):",
				"ValueError: something went wrong",
			]),
		},
	};
	assert.equal(serverMessage(source), "something went wrong");
}

// A traceback that arrives as text rather than as JSON.
{
	const source = {
		responseJSON: { exc: "Traceback (most recent call last):\nValueError: it broke" },
	};
	assert.equal(serverMessage(source), "it broke");
}

// The server's message wins over the traceback: it is what was said on
// purpose, and the traceback is what happened on the way.
{
	const source = {
		responseJSON: {
			_server_messages: JSON.stringify([envelope("The chat is switched off.")]),
			exc: JSON.stringify(["Traceback:", "ValueError: it broke"]),
		},
	};
	assert.equal(serverMessage(source), "The chat is switched off.");
}

// A refusal that says nothing says nothing.
{
	assert.equal(serverMessage(null), "");
	assert.equal(serverMessage({}), "");
	assert.equal(serverMessage({ responseJSON: {} }), "");
}

// The text inside an envelope.
{
	assert.equal(messageText({ message: "No." }), "No.");
}

// The text inside an envelope that arrived as a string.
{
	assert.equal(messageText(envelope("No.")), "No.");
}

// A string that is not JSON is the text itself.
{
	assert.equal(messageText("Not allowed."), "Not allowed.");
}

// A list of envelopes: the first one that says something is the message.
{
	assert.equal(messageText([envelope("No."), envelope("And again.")]), "No.");
}

// An empty list says nothing.
{
	assert.equal(messageText([]), "");
}

// Nothing says nothing.
{
	assert.equal(messageText(null), "");
	assert.equal(messageText(undefined), "");
	assert.equal(messageText({}), "");
}

// The last line of a traceback, without the exception class.
{
	assert.equal(lastLine("Traceback:\nValueError: it broke"), "it broke");
	assert.equal(lastLine("ValueError: it broke"), "it broke");
	assert.equal(lastLine(""), "");
	assert.equal(lastLine(null), "");
}

// What the server said is what the reader is shown.
{
	assert.equal(failureText(new Error("You may not do that.")), "You may not do that.");
	assert.equal(failureText({ message: "It broke." }), "It broke.");
}

// A failure that says nothing is shown the sentence the caller wrote for
// exactly that case -- and not the word "Error".
{
	assert.equal(
		failureText(new Error(""), "Could not rename that conversation."),
		"Could not rename that conversation.",
	);
	assert.equal(
		failureText({}, "Could not rename that conversation."),
		"Could not rename that conversation.",
	);
	assert.equal(
		failureText(null, "Could not rename that conversation."),
		"Could not rename that conversation.",
	);
	assert.equal(
		failureText(undefined, "Could not rename that conversation."),
		"Could not rename that conversation.",
	);
}

// With no sentence of its own, the failure is what there is.
{
	assert.equal(failureText(new Error("")), "Error");
	assert.equal(failureText(null), "");
	assert.equal(failureText(undefined), "");
}

console.log("errors: all assertions passed");
