// The rules for sending a question from the composer.
//
// The rule is here and not in the composer because it *is* a rule, and a
// rule that lives in a component is a rule nobody can test: this file is
// read by plain node, with no Vue and no Desk.  The composer calls it and
// does the side effects (clearing the box, stopping the microphone) only
// when it says the question may go.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

// `__` is Frappe's translator in the browser.  Under node (the tests) it
// is not defined, so a small stand-in keeps the module runnable.
function __(text, args) {
	const fn =
		typeof globalThis !== "undefined" && typeof globalThis.__ === "function"
			? globalThis.__
			: null;
	if (fn) return fn(text, args);
	if (Array.isArray(args)) {
		return String(text).replace(/\{(\d+)\}/g, (_, i) => {
			const value = args[Number(i)];
			return value === undefined || value === null ? "" : String(value);
		});
	}
	return String(text);
}

/** The longest question that may be sent, in characters.
 *
 * The two neighbouring fields are capped — the conversation title at
 * 120, the recent-questions list at 300 — and both are *display*
 * fields.  The question is the primary input, and it is the one place a
 * reader legitimately pastes something long: a stack trace, a list of
 * invoice numbers, a query.  A cap that refuses a pasted stack trace is
 * a cap that gets worked around by pasting less and asking worse
 * questions.
 *
 * 4000 is roughly a thousand tokens: room for one stack trace, and
 * small enough that a runaway paste cannot quietly eat the turn's whole
 * context.  The server enforces the same number, because the composer
 * is one client and the endpoint is the door. */
export const MAX_QUESTION_LENGTH = 4000;

/**
 * Whether a question may be sent, and the question that would be sent.
 *
 * The rules, in order:
 *   - while a turn is running, or chat is not allowed, nothing is sent
 *     (the primary key stops instead);
 *   - an empty question with no attachment is refused;
 *   - a question over the ceiling is refused, with its length, because
 *     a refusal the reader cannot act on is a refusal that fails;
 *   - otherwise the trimmed question is sent.
 *
 * @param {{modelValue?: string, files?: any[], busy?: boolean, canChat?: boolean}} input
 * @returns {{ok: boolean, question: string, reason: string, length: number}}
 */
export function submitDecision(input) {
	const data = input || {};
	if (data.busy) {
		return { ok: false, question: "", reason: "busy", length: 0 };
	}
	if (!data.canChat) {
		return { ok: false, question: "", reason: "no-chat", length: 0 };
	}
	const question = String(data.modelValue || "").trim();
	const hasFile = Array.isArray(data.files) && data.files.length > 0;
	if (!question && !hasFile) {
		return { ok: false, question: "", reason: "empty", length: 0 };
	}
	// The length is the *trimmed* length: leading whitespace is not part
	// of the question, and a reader who pasted with an indent should not
	// be charged for it.
	if (question.length > MAX_QUESTION_LENGTH) {
		return {
			ok: false,
			question: "",
			reason: "too-long",
			length: question.length,
		};
	}
	return { ok: true, question, reason: "", length: question.length };
}