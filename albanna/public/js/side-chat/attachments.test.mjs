// The rules for an attachment, before the bytes leave the browser.
//
// The rule under test: the browser refuses exactly what the server
// refuses, so a reader is told before the upload rather than after it.
//
// An SVG is the case that matters.  It is an image, the file picker
// shows it as one, and it cannot be stored: it executes as HTML in a
// browser.  A browser that accepts it and a server that refuses it is
// a reader who chose a file, waited, and was told the file they chose
// could not be attached.

import assert from "node:assert";
import {
	ATTACHABLE_TYPES,
	REFUSED_SIZE,
	REFUSED_TYPE,
	checkAttachment,
} from "./attachments.mjs";

// The five types the server can store.
assert.deepEqual(ATTACHABLE_TYPES, [
	"image/png",
	"image/jpeg",
	"image/webp",
	"image/gif",
	"application/pdf",
]);

// A picture of a type the server can store may be attached.
{
	const result = checkAttachment({ type: "image/png", size: 1024 });
	assert.equal(result.ok, true);
	assert.equal(result.reason, "");
}

// An SVG is an image and cannot be attached: it executes as HTML.
{
	const result = checkAttachment({ type: "image/svg+xml", size: 1024 });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A type the server does not name is refused.
{
	const result = checkAttachment({ type: "text/html", size: 1024 });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A file that says nothing about its type is refused.
{
	const result = checkAttachment({ type: "", size: 1024 });
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A file that says nothing at all is refused, and does not throw.
{
	const result = checkAttachment(undefined);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_TYPE);
}

// A PDF may be attached: a reader attaches the invoice they were asked
// about.
{
	const result = checkAttachment({ type: "application/pdf", size: 1024 });
	assert.equal(result.ok, true);
}

// A file over the site's ceiling is refused, and the reason says which.
{
	const result = checkAttachment(
		{ type: "image/png", size: 5000 },
		{ maxBytes: 4096 },
	);
	assert.equal(result.ok, false);
	assert.equal(result.reason, REFUSED_SIZE);
}

// A file exactly on the ceiling may be attached.
{
	const result = checkAttachment(
		{ type: "image/png", size: 4096 },
		{ maxBytes: 4096 },
	);
	assert.equal(result.ok, true);
}

// No ceiling means no ceiling.
{
	const result = checkAttachment(
		{ type: "image/png", size: 10_000_000 },
		{ maxBytes: 0 },
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

console.log("attachments: all assertions passed");
