// What the confirmation card warns about.
//
// The rule under test: the card warns when the write may take something
// away that cannot be put back, and says nothing when it cannot.
//
// The list is the manifest's own, written out. A tool added to the
// manifest tomorrow is not on it, and this test is what says so — a new
// tool that deletes data in silence is the failure this file exists to
// prevent.

import assert from "node:assert/strict";
import { destructiveConsequence, diffValue, isDestructiveTool } from "./write-safety.mjs";

global.__ = (text) => text;

// Every tool the manifest carries, by name.
const MANIFEST = [
	"list_docs",
	"get_doc",
	"get_doctype_meta",
	"run_report",
	"create_doc",
	"update_doc",
	"bulk_update_doc",
	"submit_doc",
	"cancel_doc",
	"amend_doc",
	"delete_doc",
	"ask_question",
];

// -- what is destructive ------------------------------------------------

assert.equal(isDestructiveTool("delete_doc"), true);
assert.equal(isDestructiveTool("cancel_doc"), true);

// Every other tool the manifest carries is not.
for (const tool of MANIFEST) {
	if (tool === "cancel_doc" || tool === "delete_doc") continue;
	assert.equal(isDestructiveTool(tool), false, `${tool} is called destructive`);
}

// A name that is not a tool at all is not a destructive one.
assert.equal(isDestructiveTool(""), false);
assert.equal(isDestructiveTool(undefined), false);
assert.equal(isDestructiveTool("delete_everything"), false);

// amend_doc is not on the list, and that is a decision rather than an
// oversight: amending *cancels* the document it amends and files a new
// one, so a reader who is told only "amended" is not told the old one
// goes away. This asserts today's line, so that changing it is a change
// someone makes on purpose.
assert.equal(isDestructiveTool("amend_doc"), false);

// -- what it costs ------------------------------------------------------

assert.equal(
	destructiveConsequence("delete_doc"),
	"This removes the document. It cannot be undone from here.",
);
assert.equal(destructiveConsequence("cancel_doc"), "This cancels the submitted document.");

// A card that warns about a recoverable write is a card the reader learns
// to read past, so the sentence is only for the destructive ones.
for (const tool of MANIFEST) {
	if (isDestructiveTool(tool)) continue;
	assert.equal(destructiveConsequence(tool), "", `${tool} carries a warning`);
}

// The two sentences are different sentences: "this cannot be undone" and
// "this is cancelled" are different warnings.
assert.notEqual(destructiveConsequence("delete_doc"), destructiveConsequence("cancel_doc"));

// A consequence exists for exactly the tools that are destructive — no
// warning without a destructive tool, and no destructive tool without one.
const warned = MANIFEST.filter((tool) => destructiveConsequence(tool) !== "");
assert.deepEqual(
	warned.sort(),
	["cancel_doc", "delete_doc"],
	"the warning does not match the list",
);

// -- what an empty value shows as ---------------------------------------

// Nothing was there, and now something is: the dash, not a blank cell.
assert.equal(diffValue(null), "—");
assert.equal(diffValue(undefined), "—");
assert.equal(diffValue(""), "—");

// A real zero and a real "false" are values, and they keep their faces:
// a rate of 0 that read as "—" would be a lie in a card about money.
assert.equal(diffValue(0), "0");
assert.equal(diffValue("0"), "0");
assert.equal(diffValue(false), "false");

// A value is shown as it is, stringified for the template.
assert.equal(diffValue("Acme"), "Acme");
assert.equal(diffValue(42), "42");

console.log("write-safety: all assertions passed");
