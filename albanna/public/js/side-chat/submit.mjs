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

/**
 * Whether a question may be sent, and the question that would be sent.
 *
 * The rules, in order:
 *   - while a turn is running, or chat is not allowed, nothing is sent
 *     (the primary key stops instead);
 *   - an empty question with no attachment is refused;
 *   - otherwise the trimmed question is sent.
 *
 * @param {{modelValue?: string, files?: any[], busy?: boolean, canChat?: boolean}} input
 * @returns {{ok: boolean, question: string, reason: string}}
 */
export function submitDecision(input) {
	const data = input || {};
	if (data.busy) {
		return { ok: false, question: "", reason: "busy" };
	}
	if (!data.canChat) {
		return { ok: false, question: "", reason: "no-chat" };
	}
	const question = String(data.modelValue || "").trim();
	const hasFile = Array.isArray(data.files) && data.files.length > 0;
	if (!question && !hasFile) {
		return { ok: false, question: "", reason: "empty" };
	}
	return { ok: true, question, reason: "" };
}