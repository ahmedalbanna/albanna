// The rules for an attachment, before the bytes leave the browser.
//
// The rule under test: the browser refuses exactly what the server
// refuses, so a reader is told before the upload rather than after it.
//
// The types are the site's, and the site publishes them: the browser is
// told which types the site takes rather than keeping a copy.  A browser
// with a copy is a browser whose copy goes stale, and a stale copy is a
// browser that accepts a file the server refuses.
//
// An SVG is the case that matters.  It is an image, the file picker
// shows it as one, and it cannot be stored: it executes as HTML in a
// browser.  A browser that accepts it and a server that refuses it is
// a reader who chose a file, waited, and was told the file they chose
// could not be attached.

import assert from "node:assert";
import {
	REFUSED_SIZE,
	REFUSED_TYPE,
	checkAttachment,
	makeAttachment,
	storeAll,
	turnAttachments,
} from "./attachments.mjs";

// The types the site publishes.  They arrive with the widget's options.
const TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"];

// The site's rules, as the browser is given them.
const RULES = { types: TYPES };

// A picture of a type the server can store may be attached.
{
	const result = checkAttachment({ type: "image/png", size: 1024 }, RULES);
	assert.equal(result.ok, true);
	assert.equal(result.reason, "");
}

// An SVG is an image and cannot be attached: it executes as HTML.
{
	const result = checkAttachment({ type: "image/svg+xml", size: 1024 }, RULES);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A type the server does not name is refused.
{
	const result = checkAttachment({ type: "text/html", size: 1024 }, RULES);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A file that says nothing about its type is refused.
{
	const result = checkAttachment({ type: "", size: 1024 }, RULES);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A file that says nothing at all is refused, and does not throw.
{
	const result = checkAttachment(undefined, RULES);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A PDF may be attached: a reader attaches the invoice they were asked
// about.
{
	const result = checkAttachment({ type: "application/pdf", size: 1024 }, RULES);
	assert.equal(result.ok, true);
}

// A file over the site's ceiling is refused, and the reason says which.
{
	const result = checkAttachment({ type: "image/png", size: 5000 }, { ...RULES, maxBytes: 4096 });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_SIZE);
}

// A file exactly on the ceiling may be attached.
{
	const result = checkAttachment({ type: "image/png", size: 4096 }, { ...RULES, maxBytes: 4096 });
	assert.equal(result.ok, true);
}

// No ceiling means no ceiling.
{
	const result = checkAttachment(
		{ type: "image/png", size: 10_000_000 },
		{ ...RULES, maxBytes: 0 },
	);
	assert.equal(result.ok, true);
}

// The site may narrow the list.
{
	const result = checkAttachment({ type: "image/gif", size: 10 }, { types: ["image/png"] });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// The site may widen it.
{
	const result = checkAttachment(
		{ type: "image/tiff", size: 10 },
		{ types: [...TYPES, "image/tiff"] },
	);
	assert.equal(result.ok, true);
}

// A site that has not said which types it takes attaches nothing.
//
// The browser has no list of its own to fall back on, so a rule it was
// not told is a rule it does not have.  Guessing here would be guessing
// in the direction of accepting a file the server refuses.
{
	const result = checkAttachment({ type: "image/png", size: 1024 });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// -- the type a file arrives claiming -------------------------------------

import {
	acceptFor,
	canonicalType,
	withType,
} from "./attachments.mjs";

// The site's published types, as the widget's options carry them: each
// with the other names the same file may arrive claiming and the
// extension it means.
const PUBLISHED = [
	{ mime: "image/png", name: "PNG", extension: ".png", aliases: [] },
	{
		mime: "text/csv",
		name: "CSV",
		extension: ".csv",
		aliases: ["application/vnd.ms-excel", "application/msexcel"],
	},
	{ mime: "text/plain", name: "plain text", extension: ".txt", aliases: [] },
];

// A file the browser named canonically keeps its name.
{
	const type = canonicalType({ type: "text/csv", name: "orders.csv" }, PUBLISHED);
	assert.equal(type, "text/csv");
}

// A CSV on a Windows install arrives claiming the name the system files
// the document under — and it resolves to the type the site attaches.
{
	const type = canonicalType(
		{ type: "application/vnd.ms-excel", name: "orders.csv" },
		PUBLISHED,
	);
	assert.equal(type, "text/csv");
}

// The legacy alias resolves the same way.
{
	const type = canonicalType({ type: "application/msexcel", name: "a.csv" }, PUBLISHED);
	assert.equal(type, "text/csv");
}

// A file the browser could not name is named by its own extension.
{
	const type = canonicalType({ type: "", name: "orders.CSV" }, PUBLISHED);
	assert.equal(type, "text/csv");
}

// A claim nothing published answers to passes through unchanged: the
// caller's own check refuses it, and the resolver invents nothing.
{
	const type = canonicalType({ type: "text/html", name: "page.html" }, PUBLISHED);
	assert.equal(type, "text/html");
}

// A file that says nothing at all resolves to nothing.
{
	assert.equal(canonicalType({}, PUBLISHED), "");
	assert.equal(canonicalType(undefined, PUBLISHED), "");
}

// A published list that is not a list resolves to the claim unchanged.
{
	assert.equal(canonicalType({ type: "text/csv", name: "a.csv" }), "text/csv");
}

// -- what a file picker filters on ------------------------------------------

// The accept value carries the types, the aliases and the extensions: a
// filter of the canonical types alone never shows a CSV on a Windows
// install, because the system files that document under another name.
{
	const accept = acceptFor(PUBLISHED);
	assert.equal(
		accept,
		"image/png,.png,text/csv,application/vnd.ms-excel,application/msexcel,.csv,text/plain,.txt",
	);
}

// Nothing published is an empty filter, and nothing throws.
{
	assert.equal(acceptFor([]), "");
	assert.equal(acceptFor(), "");
}

// -- the data URL claims the resolved type ----------------------------------

// A URL built by the reader claims the type the browser reported, which
// is the very claim the resolution corrected.  The header is rewritten;
// the payload is untouched.
{
	const url = withType("data:application/vnd.ms-excel;base64,aGVsbG8=", "text/csv");
	assert.equal(url, "data:text/csv;base64,aGVsbG8=");
}

// A URL that already claims the canonical type is untouched in meaning.
{
	const url = withType("data:text/csv;base64,aGVsbG8=", "text/csv");
	assert.equal(url, "data:text/csv;base64,aGVsbG8=");
}

// A URL with no parameters after the type is rewritten whole.
{
	assert.equal(withType("data:text/csv,a,b", "text/plain"), "data:text/plain,a,b");
}

// A URL that is not a data URL is returned as it is.
{
	assert.equal(withType("", "text/csv"), "");
	assert.equal(withType("not-a-data-url", "text/csv"), "not-a-data-url");
}

// Nothing to claim means the URL is returned as it is.
{
	assert.equal(withType("data:text/csv;base64,aGVsbG8=", ""), "data:text/csv;base64,aGVsbG8=");
}

// -- the shape of an attachment -----------------------------------------

// An attachment carries the name, the type, the size and the address it
// was stored under — and not the bytes, which were read only to be
// uploaded and would sit in the browser's memory for the panel's whole
// life if the composer kept them.
{
	const file = makeAttachment({
		name: "a.png",
		type: "image/png",
		size: 12,
		fileUrl: "/private/files/a.png",
	});
	assert.deepEqual(file, {
		name: "a.png",
		type: "image/png",
		size: 12,
		fileUrl: "/private/files/a.png",
		stored: true,
	});
}

// An attachment with nothing in it still has every field.
{
	const file = makeAttachment();
	assert.deepEqual(Object.keys(file).sort(), [
		"fileUrl",
		"name",
		"size",
		"stored",
		"type",
	]);
}

// -- the list is written once --------------------------------------------

// Three files, one refused: two attachments, in order, and the list is
// written once.
//
// The write is the part that matters.  A list written after each file
// lets a later upload overwrite an earlier one, and a reader who
// dropped three pictures finds one of them gone.
{
	const written = [];
	const store = async (file) => (file.name === "b.txt" ? null : { name: file.name });
	const added = await storeAll(
		[{ name: "a.png" }, { name: "b.txt" }, { name: "c.pdf" }],
		store,
		(entries) => written.push(entries),
	);
	assert.equal(added.length, 2);
	assert.deepEqual(
		added.map((entry) => entry.name),
		["a.png", "c.pdf"],
	);
	assert.equal(written.length, 1);
	assert.deepEqual(written[0], added);
}

// Every file is stored, one after the other: an upload that finished
// late must not overwrite an upload that finished early.
{
	const order = [];
	const store = async (file) => {
		order.push(file.name);
		return { name: file.name };
	};
	await storeAll([{ name: "a" }, { name: "b" }], store, () => {});
	assert.deepEqual(order, ["a", "b"]);
}

// Nothing was stored, so nothing is written.
{
	const written = [];
	const added = await storeAll(
		[{ name: "a" }],
		async () => null,
		(entries) => written.push(entries),
	);
	assert.deepEqual(added, []);
	assert.equal(written.length, 0);
}

// -- what a turn carries -------------------------------------------------

// The turn carries the addresses, and only the addresses: the bytes were
// uploaded before the turn was sent, and a request that sent them again
// would carry every file twice on the wire.
{
	const files = [
		makeAttachment({ fileUrl: "/private/files/a.png" }),
		makeAttachment({ fileUrl: "/private/files/b.png" }),
	];
	const { attachmentUrls } = turnAttachments(files);
	assert.deepEqual(attachmentUrls, ["/private/files/a.png", "/private/files/b.png"]);
}

// A question with no attachments carries none.
{
	const { attachmentUrls } = turnAttachments([]);
	assert.deepEqual(attachmentUrls, []);
}

console.log("attachments: all assertions passed");
