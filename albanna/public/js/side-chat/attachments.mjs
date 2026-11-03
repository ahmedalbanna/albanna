// The rules for an attachment, before the bytes leave the browser.
//
// The rule is here and not in the composer because it *is* a rule, and a
// rule that lives in a component is a rule nobody can test: this file is
// read by plain node, with no Vue and no Desk.
//
// The list is the server's list, and the server publishes it: the browser
// is told which types the site takes rather than keeping a copy of them.
// A browser that accepts an SVG and a server that refuses it is a reader
// who chose a file, waited for the upload, and was then told the file
// they chose could not be attached.
//
// So this file has no list of its own.  A browser that keeps a copy of
// the server's list is a browser whose copy goes stale the day the
// server's changes, and a stale list is a browser that accepts a file
// the server refuses.

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
 *   of zero means no ceiling.  No types means the site has not said, and
 *   nothing may be attached: a browser that guesses is a browser that
 *   guesses wrong.
 * @returns {{ok: boolean, reason: string}} whether it may be attached, and
 *   why it may not
 */
export function checkAttachment(file, rules = {}) {
	const types = rules.types || [];
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
