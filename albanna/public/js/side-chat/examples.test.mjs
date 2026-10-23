// The empty state's suggestions follow the page.
//
// A form asks about that document, a list asks about that list, a report
// asks about that report, and only a page with nothing to anchor on falls
// back to the generic questions.

import assert from "node:assert";
import { exampleSet, openDocumentFrom } from "./examples.mjs";

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
