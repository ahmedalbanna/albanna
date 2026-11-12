// The notices the panel can show, in the reader's language.
//
// A notice is the panel saying something in passing: the turn was
// stopped, the answer was cut off, nothing was saved because it was a dry
// run. Each is a sentence the reader reads once, in their own language.
//
// The state holds a *key*, not a sentence. The state machine is pure and
// has no language of its own, and the reader's language can change under
// a notice that was already shown — a sentence stored once would be the
// wrong language the next morning. So the key is stored and the sentence
// is drawn from it at the moment it is shown.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/**
 * The notices the panel can show, in the reader's language.
 *
 * @param {string} notice the key
 * @returns {string} the sentence
 */
export function noticeText(notice) {
	switch (notice) {
		case "stopped":
			return __("Stopped.");
		case "no-table":
			return __("There is no table to copy.");
		case "table-copied":
			return __("The table was copied.");
		case "copy-failed":
			return __("The table could not be copied.");
		case "copy-answer-failed":
			return __("The answer could not be copied.");
		case "deleted":
			return __("The document was deleted.");
		case "reverted":
			return __("The change was reverted.");
		case "cancelled":
			return __("The submission was cancelled.");
		case "conversation-deleted":
			return __("The conversation was deleted.");
		case "started":
			return __("A new conversation was started.");
		case "removed":
			return __("The question and its answer were removed.");
		case "attachments-dropped":
			return __("This model cannot see attachments; the attachment was ignored.");
		case "dry-run":
			return __("Dry run — nothing was saved.");
		case "escalated":
			return __("Escalated to support.");
		case "undone":
			return __("The turn was undone.");
		default:
			return "";
	}
}
