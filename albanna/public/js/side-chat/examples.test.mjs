// The empty state's suggestions follow the page.
//
// A form asks about that document, a list asks about that list, a report
// asks about that report, and only a page with nothing to anchor on falls
// back to the generic questions.

import assert from "node:assert";
import { exampleSet, openDocumentFrom, examplesFor } from "./examples.mjs";

// A form with a document is a form.
{
	assert.equal(exampleSet({ view: "form", doctype: "Sales Order", name: "SAL-ORD-001" }), "form");
}

// A list carries a doctype but no name.
{
	assert.equal(exampleSet({ view: "List/Sales Order/List", doctype: "Sales Order" }), "list");
}

// A report is a report even without a doctype.
{
	assert.equal(exampleSet({ view: "query-report", report: "General Ledger" }), "report");
}

// A page with nothing to anchor on is generic.
{
	assert.equal(exampleSet({ view: "desk" }), "generic");
	assert.equal(exampleSet({}), "generic");
	assert.equal(exampleSet(null), "generic");
}

// openDocumentFrom returns the document only when both are present.
{
	assert.deepEqual(openDocumentFrom({ doctype: "Sales Order", name: "SAL-ORD-001" }), {
		doctype: "Sales Order",
		name: "SAL-ORD-001",
	});
	assert.equal(openDocumentFrom({ doctype: "Sales Order" }), null);
	assert.equal(openDocumentFrom({}), null);
}

// Issue form.
{
	const result = examplesFor({ view: "form", doctype: "Issue", name: "ISS-0001" }, null, "");
	assert.deepEqual(result, [
		"What is the customer asking for?",
		"What has already been done?",
		"What is still open?",
	]);
}

// Generic form with a document.
{
	const result = examplesFor({ view: "form", doctype: "Sales Order", name: "SAL-ORD-001" }, null, "");
	assert.deepEqual(result, [
		"Summarise this Sales Order",
		"What is the status of this Sales Order?",
		"What is the total of this Sales Order?",
	]);
}

// New document with a party.
{
	const result = examplesFor({ view: "form", doctype: "Sales Order", name: "" }, null, "Acme");
	// name empty => openDocumentFrom null => brand-new branch
	assert.deepEqual(result, [
		"Copy this Sales Order from the last one for Acme",
		"What fields are required for this Sales Order?",
	]);
}

// New document without a party.
{
	const result = examplesFor({ view: "form", doctype: "Sales Order", name: "" }, null, "");
	assert.deepEqual(result, ["What fields are required for this Sales Order?"]);
}

// Issue list.
{
	const result = examplesFor({ view: "List/Issue/List", doctype: "Issue" }, 5, "");
	assert.deepEqual(result, [
		"What is the customer asking for?",
		"What has already been done?",
		"What is still open?",
		"Show my open tickets",
	]);
}

// Empty list (count 0).
{
	const result = examplesFor({ view: "List/Sales Order/List", doctype: "Sales Order" }, 0, "");
	assert.deepEqual(result, ["Create a Sales Order"]);
}

// Generic list.
{
	const result = examplesFor({ view: "List/Sales Order/List", doctype: "Sales Order" }, 5, "");
	assert.deepEqual(result, [
		"How many Sales Order are there?",
		"Which Sales Order are still open?",
		"What is the total value of these Sales Order?",
	]);
}

// Report.
{
	const result = examplesFor({ view: "query-report", report: "General Ledger" }, null, "");
	assert.deepEqual(result, [
		"Summarise this report",
		"What are the totals in this report?",
		"Which rows stand out?",
	]);
}

// Generic fallback.
{
	const result = examplesFor({ view: "desk" }, null, "");
	assert.deepEqual(result, [
		"How many open Issues are there?",
		"Which Issues are still open?",
		"How many customers are there?",
	]);
}
