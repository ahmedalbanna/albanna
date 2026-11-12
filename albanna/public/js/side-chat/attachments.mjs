// The rules for an attachment, before the bytes leave the browser, and
// the shape an attachment takes on its way.
//
// The rule is here and not in the composer because it *is* a rule, and a
// rule that lives in a component is a rule nobody can test: this file is
// read by plain node, with no Vue and no Desk.  The shape is here for
// the same reason, and because two files use it: the composer builds an
// attachment and the panel reads it.
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
 * The type a file is, whatever name the browser called it by.
 *
 * The browser reports the type the operating system files the document
 * under, and the two do not always agree: on a Windows install a CSV is
 * registered as ``application/vnd.ms-excel``, so a reader attaching the
 * month's orders hands over a file whose claimed type is on no list —
 * although the site attaches it.  The file's own name is the second
 * witness: the published types carry the other names they arrive
 * claiming and the extension they mean, so the browser resolves the
 * claim through those rather than keeping a list of its own.
 *
 * @param {{type?: string, name?: string}} file the file the reader chose
 * @param {{mime?: string, aliases?: string[], extension?: string}[]} types
 *   the site's published types
 * @returns {string} the canonical type, or the claim unchanged when
 *   nothing published answers to it — the caller's own check refuses
 *   that, and this function invents nothing
 */
export function canonicalType(file, types = []) {
	const claimed = String((file && file.type) || "");
	for (const entry of types || []) {
		const mime = String((entry && entry.mime) || "");
		if (!mime) continue;
		if (claimed === mime) return mime;
		for (const alias of (entry && entry.aliases) || []) {
			if (claimed === alias) return mime;
		}
	}

	const name = String((file && file.name) || "");
	const dot = name.lastIndexOf(".");
	const extension = dot > -1 ? name.slice(dot).toLowerCase() : "";
	if (extension) {
		for (const entry of types || []) {
			if (extension === String((entry && entry.extension) || "").toLowerCase()) {
				return String((entry && entry.mime) || "");
			}
		}
	}
	return claimed;
}

/**
 * What a file picker's ``accept`` filter carries.
 *
 * The canonical types alone are not the whole rule: a picker filtering
 * on ``text/csv`` never shows a CSV on a Windows install, because the
 * system files that document under ``application/vnd.ms-excel``.  The
 * published aliases and extensions travel with the types, so the picker
 * shows every file the rule accepts and nothing it refuses.
 *
 * @param {{mime?: string, aliases?: string[], extension?: string}[]} types
 *   the site's published types
 * @returns {string} the accept value, or ``""`` when nothing was given
 */
export function acceptFor(types = []) {
	const accepted = [];
	for (const entry of types || []) {
		if (!entry) continue;
		if (entry.mime) accepted.push(entry.mime);
		for (const alias of entry.aliases || []) if (alias) accepted.push(alias);
		if (entry.extension) accepted.push(entry.extension);
	}
	return accepted.join(",");
}

/**
 * A data URL that claims the type the file resolved to.
 *
 * The reader builds the URL with ``FileReader``, which writes the type
 * the browser claimed — the very claim the resolution corrected.  A URL
 * carrying the alias would be refused at the server's door even though
 * the browser has already agreed the file is one it may attach, so the
 * header is rewritten to the canonical name before the bytes travel.
 * The payload is untouched.
 *
 * @param {string} dataUrl the URL the reader built
 * @param {string} mime the canonical type
 * @returns {string} the URL claiming the canonical type
 */
export function withType(dataUrl, mime) {
	if (!mime || !dataUrl || !dataUrl.startsWith("data:")) return dataUrl;
	const semi = dataUrl.indexOf(";");
	const comma = dataUrl.indexOf(",");
	const cut = semi > -1 && (comma === -1 || semi < comma) ? semi : comma;
	if (cut === -1) return dataUrl;
	return "data:" + mime + dataUrl.slice(cut);
}

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

/**
 * One attachment, as the composer holds it and the panel sends it.
 *
 * The six fields are the attachment: the bytes the model reads, the name
 * the reader recognises, the type the site checks, the size the reader
 * is shown, the address the file was stored under, and whether it was.
 *
 * @param {{dataUrl?: string, name?: string, type?: string, size?: number,
 *          fileUrl?: string, stored?: boolean}} parts the attachment's parts
 * @returns {object} the attachment
 */
export function makeAttachment(parts = {}) {
	return {
		dataUrl: parts.dataUrl || "",
		name: parts.name || "",
		type: parts.type || "",
		size: Number(parts.size || 0),
		fileUrl: parts.fileUrl || "",
		stored: parts.stored !== false,
	};
}

/**
 * Store every file, and write the list of them once.
 *
 * The list is written once, at the end, with every file that was stored.
 * Writing it after each file lets a later upload overwrite an earlier
 * one, and a reader who dropped three pictures finds one of them gone.
 *
 * @param {Array} files the files the reader chose
 * @param {(file: *) => Promise<object|null>} store the store to use
 * @param {(added: object[]) => void} write the one write of the list
 * @returns {Promise<object[]>} the attachments that were stored, in order
 */
export async function storeAll(files, store, write) {
	const added = [];
	for (const file of files) {
		const entry = await store(file);
		if (entry) added.push(entry);
	}
	if (added.length) write(added);
	return added;
}

/**
 * What a turn carries for its attachments: the bytes, and the addresses
 * they were stored under.
 *
 * The two lists are parallel: the address at one place is the address of
 * the bytes at the same place.  The server relies on that to reuse the
 * file instead of writing the same bytes twice, so the two are built
 * together and never apart.
 *
 * @param {object[]} files the attachments
 * @returns {{attachments: string[], attachmentUrls: string[]}} what the turn carries
 */
export function turnAttachments(files) {
	return {
		attachments: files.map((file) => file.dataUrl || ""),
		attachmentUrls: files.map((file) => file.fileUrl || ""),
	};
}
