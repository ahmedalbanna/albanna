// The live hint's names.
//
// Run under plain node:  node albanna/public/js/side-chat/nudge.test.mjs

import assert from "node:assert/strict";

global.__ = (text, args) => {
	let out = String(text);
	(args || []).forEach((value, index) => {
		out = out.replace(`{${index}}`, String(value));
	});
	return out;
};

const { documentRoute, moreText, namedDocuments, unnamedCount } = await import("./nudge.mjs");

/* -- the route ---------------------------------------------------------- */

/* The Desk's own convention: the DocType's slug, then the document's name.
   The name is percent-encoded, so an Arabic name is a URL the Desk can
   still route to. */
assert.equal(
	documentRoute("Sales Invoice", "ف-2026-0011"),
	"/app/sales-invoice/%D9%81-2026-0011",
);
assert.equal(documentRoute("Purchase Invoice", "PI-0001"), "/app/purchase-invoice/PI-0001");

/* -- the names ---------------------------------------------------------- */

const payload = {
	doctype: "Sales Invoice",
	documents: [
		{ name: "ف-2026-0011", title: "أحمد محمد عبدربه" },
		{ name: "ف-2026-0012", title: "عميل نقدي" },
	],
	more: 1,
};

const named = namedDocuments(payload);
assert.equal(named.length, 2);

/* The label is the name the reader sees in the list, and the document's own
   name travels with it. */
assert.equal(named[0].label, "أحمد محمد عبدربه");
assert.equal(named[0].name, "ف-2026-0011");
assert.equal(named[0].title, "أحمد محمد عبدربه");
assert.equal(named[0].url, "/app/sales-invoice/%D9%81-2026-0011");
assert.equal(named[1].label, "عميل نقدي");

/* A document with no title is labelled by its name — that is what the
   reader would see anyway. */
const untitled = namedDocuments({
	doctype: "Sales Invoice",
	documents: [{ name: "ف-2026-0013", title: "" }],
});
assert.equal(untitled[0].label, "ف-2026-0013");
assert.equal(untitled[0].title, "");

/* A hint that arrives half-built is a hint with no names, not a hint that
   throws. */
assert.deepEqual(namedDocuments(null), []);
assert.deepEqual(namedDocuments({}), []);
assert.deepEqual(namedDocuments({ documents: "not a list" }), []);
assert.deepEqual(namedDocuments({ documents: [null, {}] }), []);

/* -- the rest ----------------------------------------------------------- */

assert.equal(unnamedCount(payload), 1);
assert.equal(unnamedCount({ more: 0 }), 0);
assert.equal(unnamedCount({ more: -3 }), 0);
assert.equal(unnamedCount({}), 0);
assert.equal(unnamedCount(null), 0);

assert.equal(moreText(2), "and 2 more");
assert.equal(moreText(0), "");
assert.equal(moreText(-1), "");

console.log("nudge.test.mjs: all assertions passed");
