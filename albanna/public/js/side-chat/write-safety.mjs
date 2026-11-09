// What counts as a destructive write, and what it costs.
//
// The confirmation card is the widget saying *this one changes data*. Some
// of those are recoverable and some are not, and the reader deserves to
// know which before they press the button — a document that is cancelled
// can be amended, and a document that is deleted cannot be brought back
// from here.
//
// This was a bare comparison in the panel, tested by nobody. That is the
// kind of line that stays wrong: a tool added to the manifest tomorrow
// would delete data without the card saying so, and nothing would fail.
// So the list is a list, with a test that names every tool the manifest
// carries and says whether it is on it.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/**
 * Whether a tool may take something away that cannot be put back.
 *
 * @param {string} toolName the tool the model called
 * @returns {boolean} true when the write is destructive
 */
export function isDestructiveTool(toolName) {
	return toolName === "cancel_doc" || toolName === "delete_doc";
}

/**
 * What the reader is told the destructive write will do.
 *
 * A sentence only for the destructive ones: a card that warns about a
 * write that is recoverable is a card the reader learns to read past.
 *
 * @param {string} toolName the tool the model called
 * @returns {string} the sentence, or nothing to show
 */
export function destructiveConsequence(toolName) {
	if (toolName === "delete_doc") {
		return __("This removes the document. It cannot be undone from here.");
	}
	if (toolName === "cancel_doc") {
		return __("This cancels the submitted document.");
	}
	return "";
}

/**
 * The value a diff row shows, when the field had nothing in it.
 *
 * A field that was empty and now is not is the commonest diff there is,
 * and an empty cell does not say "nothing was here" — it says "broken".
 * The dash is the mark every diff the reader has seen uses for it.  A
 * real zero and a real "false" are values: only null, undefined and the
 * empty string count as nothing, so a rate of 0 still reads as 0.
 *
 * @param {*} value the value the field carried
 * @returns {string} the value to show
 */
export function diffValue(value) {
	if (value === null || value === undefined || value === "") {
		return "—";
	}
	return String(value);
}
