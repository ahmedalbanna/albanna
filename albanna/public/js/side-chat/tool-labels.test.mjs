// The labels a tool call carries, and the notices the panel can show.
//
// A label is the reader's business, so the rule under test is that the
// reader is told what is being done and not which function is doing it —
// and that a tool the manifest knows by another name does not fall
// through to a label nobody notices being wrong.

import assert from "node:assert/strict";
import { describeTool, statusLabel, toolLabel, toolSummary } from "./tool-labels.mjs";

// The page's translation function, as the widget uses it: the string
// itself in this suite, so a label is compared as the string the reader
// would see rather than as whatever the catalogue does to it.
global.__ = (text, args) => {
	if (Array.isArray(args)) {
		return args.reduce((out, value, index) => out.split(`{${index}}`).join(value), text);
	}
	return text;
};

// -- the status ---------------------------------------------------------

assert.equal(statusLabel("thinking"), "Thinking");
assert.equal(statusLabel(""), "");
assert.equal(statusLabel("running"), "");

// -- what the tool is called -------------------------------------------

assert.equal(toolLabel("list_docs"), "Searching");
assert.equal(toolLabel("get_doc"), "Reading");
assert.equal(toolLabel("get_doctype_meta"), "Checking fields");
assert.equal(toolLabel("run_report"), "Running a report");
assert.equal(toolLabel("create_doc"), "Creating");

// A tool with no label of its own reads as "Working" — which is true, and
// is the one label the reader is not misled by.
assert.equal(toolLabel("bulk_update_doc"), "Working");
assert.equal(toolLabel(""), "Working");
assert.equal(toolLabel(undefined), "Working");

// -- what it is being done to ------------------------------------------

assert.equal(describeTool("list_docs", { doctype: "Sales Order" }), "Searching Sales Order");
assert.equal(describeTool("get_doc", { doctype: "Sales Order" }), "Reading Sales Order");

// No doctype is a call that names nothing, and the label stands alone.
assert.equal(describeTool("list_docs", {}), "Searching");
assert.equal(describeTool("list_docs", undefined), "Searching");
assert.equal(describeTool("list_docs", { doctype: "   " }), "Searching");

// -- what the turn did --------------------------------------------------

assert.equal(toolSummary({ tools: [] }), "");
assert.equal(toolSummary({}), "");
assert.equal(toolSummary(undefined), "");

assert.equal(
	toolSummary({ tools: [{ name: "get_doc" }, { name: "run_report" }] }),
	"Tools used: 2 · Calls: 2",
);

// The same tool twice is one tool and two calls: they are different
// questions, and one line that answers both is one line the reader can
// trust for either.
assert.equal(
	toolSummary({ tools: [{ name: "get_doc" }, { name: "get_doc" }] }),
	"Tools used: 1 · Calls: 2",
);

console.log("tool-labels: all assertions passed");
