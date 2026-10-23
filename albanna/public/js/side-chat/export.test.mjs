// The transcript, said as Markdown.

import assert from "node:assert";
import { conversationToMarkdown, exportFilename } from "./export.mjs";

const speakers = { reader: "You", assistant: "Albanna" };

// A question and its answer, one turn.
{
	const text = conversationToMarkdown(
		[
			{ role: "user", content: "What is open?" },
			{ role: "assistant", content: "The two orders." },
		],
		speakers,
	);
	assert.equal(
		text,
		"**You:** What is open?\n\n" +
			"**Albanna:**\n\nThe two orders.\n",
		"a turn is the question, a blank line, and the answer",
	);
}

// Tool rows are plumbing, and do not appear.
{
	const text = conversationToMarkdown(
		[
			{ role: "user", content: "the question" },
			{ role: "tool", content: '{"ok": true}' },
			{ role: "assistant", content: "the answer" },
		],
		speakers,
	);
	assert.equal(text, "**You:** the question\n\n**Albanna:**\n\nthe answer\n");
}

// An empty message keeps its speaker line — the shape survives.  The
// trailing separators are trimmed, as the format keeps a single final
// newline rather than a run of blank lines.
{
	const text = conversationToMarkdown(
		[
			{ role: "user", content: "" },
			{ role: "assistant", content: "" },
		],
		speakers,
	);
	assert.equal(text, "**You:** \n\n**Albanna:**\n");
}

// Blank input, harmless.
{
	assert.equal(conversationToMarkdown(null, speakers), "\n");
	assert.equal(conversationToMarkdown([], speakers), "\n");
	assert.equal(conversationToMarkdown([null, undefined], speakers), "\n");
}

// The filename sorts by date and carries the hour.
{
	const name = exportFilename(new Date(2026, 9, 23, 15, 5).getTime());
	assert.equal(name, "albanna-conversation-20261023-1505.md");
}
