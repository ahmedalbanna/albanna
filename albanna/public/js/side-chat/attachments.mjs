// The rules for an attachment, before the bytes leave the browser.
//
// The rule is here and not in the composer because it *is* a rule, and a
// rule that lives in a component is a rule nobody can test: this file is
// read by plain node, with no Vue and no Desk.
//
// The list is the server's list.  A browser that accepts an SVG and a
// server that refuses it is a reader who chose a file, waited for the
// upload, and was then told the file they chose could not be attached.

/**
 * The types an attachment may carry.
 *
 * Five, and no more.  An SVG is an image and cannot be here: it
 * executes as HTML in a browser.  A PDF is not an image and can: a
 * reader attaches the invoice they were asked about.
 */
export const ATTACHABLE_TYPES = [
	"image/png",
	"image/jpeg",
	"image/webp",
	"image/gif",
	"application/pdf",
];

/** The file is not one of the types that may be attached. */
export const REFUSED_TYPE = "type";

/** The file is over the site's ceiling. */
export const REFUSED_SIZE = "size";

/**
 * May this file be attached?
 *
 * @param {{type?: string, size?: number}} file the file the reader chose
 * @param {{types?: string[], maxBytes?: number}} rules the site's rules —
 *   the types that may be attached, and the ceiling in bytes.  A ceiling
 *   of zero means no ceiling.
 * @returns {{ok: boolean, reason: string}} whether it may be attached, and
 *   why it may not
 */
export function checkAttachment(file, rules = {}) {
	const types = rules.types || ATTACHABLE_TYPES;
	const maxBytes = Number(rules.maxBytes || 0);
	const type = String((file && file.type) || "");

	if (!types.includes(type)) {
		return { ok: false, reason: REFUSED_TYPE };
	}

	const size = Number((file && file.size) || 0);
	if (maxBytes && size > maxBytes) {
		return { ok: false, reason: REFUSED_SIZE };
	}

	return { ok: true, reason: "" };
}
