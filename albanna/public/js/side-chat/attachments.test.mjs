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
const TYPES = [
	"image/png",
	"image/jpeg",
	"image/webp",
	"image/gif",
	"application/pdf",
];

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
	const result = checkAttachment(
		{ type: "image/png", size: 5000 },
		{ ...RULES, maxBytes: 4096 },
	);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_SIZE);
}

// A file exactly on the ceiling may be attached.
{
	const result = checkAttachment(
		{ type: "image/png", size: 4096 },
		{ ...RULES, maxBytes: 4096 },
	);
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
	const result = checkAttachment(
		{ type: "image/gif", size: 10 },
		{ types: ["image/png"] },
	);
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

// -- the shape of an attachment -----------------------------------------

// An attachment carries the bytes, the name, the type, the size and the
// address it was stored under.
{
	const file = makeAttachment({
		dataUrl: "data:image/png;base64,AAAA",
		name: "a.png",
		type: "image/png",
		size: 12,
		fileUrl: "/private/files/a.png",
	});
	assert.deepEqual(file, {
		dataUrl: "data:image/png;base64,AAAA",
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
		"dataUrl",
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
	assert.deepEqual(added.map((entry) => entry.name), ["a.png", "c.pdf"]);
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
	const added = await storeAll([{ name: "a" }], async () => null, (entries) =>
		written.push(entries),
	);
	assert.deepEqual(added, []);
	assert.equal(written.length, 0);
}

// -- what a turn carries -------------------------------------------------

// The bytes and the addresses are parallel: the address at one place is
// the address of the bytes at the same place.
{
	const files = [
		makeAttachment({ dataUrl: "data:image/png;base64,AAAA", fileUrl: "/private/files/a.png" }),
		makeAttachment({ dataUrl: "data:image/png;base64,BBBB", fileUrl: "/private/files/b.png" }),
	];
	const { images, imageUrls } = turnAttachments(files);
	assert.deepEqual(images, [
		"data:image/png;base64,AAAA",
		"data:image/png;base64,BBBB",
	]);
	assert.deepEqual(imageUrls, ["/private/files/a.png", "/private/files/b.png"]);
}

// A question with no attachments carries none.
{
	const { images, imageUrls } = turnAttachments([]);
	assert.deepEqual(images, []);
	assert.deepEqual(imageUrls, []);
}

console.log("attachments: all assertions passed");
