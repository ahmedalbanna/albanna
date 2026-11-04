// The empty state's suggested questions.
//
// The widget's whole claim is that it knows what the user is looking at,
// and an empty panel that offers "Which Sales Orders are still open?" on
// an HR page is a panel that does not.  So the suggestions follow the
// page: a form gets questions about *that* document, a list gets questions
// about the list the reader is looking at, a report gets questions about the
// report.  Only when there is nothing to anchor on do we fall back to the
// generic ones.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

// `__` is Frappe's translator in the browser.  Under node (the tests) it
// is not defined, so a small stand-in keeps the module runnable: it does
// the same `{0}` substitution Frappe does, and leaves the string alone
// when there is nothing to substitute.  The call sites below are written as
// `__("...")` on purpose, so the translation check can see them.
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
 * The kind of empty state the page calls for.
 *
 * @param {{view?: string, doctype?: string, name?: string, report?: string}} context
 * @returns {"form" | "list" | "report" | "generic"} the set to show
 */
export function exampleSet(context) {
	const page = context || {};
	if (page.view === "form" && page.doctype) return "form";
	if (page.report) return "report";
	// A list is a route whose last segment is "List" and which carries a
	// doctype.  `resolveContext` sets `view` to the route for non-forms,
	// so we lean on the doctype being present instead.
	if (page.doctype && !page.name) return "list";
	return "generic";
}

/**
 * The document the empty state is asking about, if any.
 *
 * @param {{doctype?: string, name?: string}} context
 * @returns {{doctype: string, name: string} | null}
 */
export function openDocumentFrom(context) {
	const page = context || {};
	if (!page.doctype || !page.name) return null;
	return { doctype: page.doctype, name: page.name };
}

/**
 * The questions the empty state offers, for a given page.
 *
 * With a document open, the questions are about *that* document — a
 * reader with a Sales Order open wants to know about the Sales Order in
 * front of them, not about sales orders in general.  Without one, they
 * are the questions people actually ask of a site.
 *
 * They are asked as questions rather than described, because a suggestion
 * the reader has to translate into a question is a suggestion that costs
 * more than it gives.
 *
 * @param {{view?: string, doctype?: string, name?: string, report?: string}} context
 * @param {number|null} count how many rows the list shows, if any
 * @param {string} party the party on a brand-new document, if any
 * @returns {string[]} the suggested questions
 */
export function examplesFor(context, count, party) {
	const ctx = context || {};
	const set = exampleSet(ctx);

	if (set === "form") {
		const document = openDocumentFrom(ctx);
		if (document && document.doctype === "Issue") {
			return [
				__("What is the customer asking for?"),
				__("What has already been done?"),
				__("What is still open?"),
			];
		}
		if (document) {
			return [
				__("Summarise this {0}", [document.doctype]),
				__("What is the status of this {0}?", [document.doctype]),
				__("What is the total of this {0}?", [document.doctype]),
			];
		}
		// A brand-new document: offer to seed it from the last similar one.
		if (party && ctx.doctype) {
			return [
				__("Copy this {0} from the last one for {1}", [ctx.doctype, party]),
				__("What fields are required for this {0}?", [ctx.doctype]),
			];
		}
		if (ctx.doctype) {
			return [__("What fields are required for this {0}?", [ctx.doctype])];
		}
		return [];
	}

	if (set === "list" && ctx.doctype) {
		if (ctx.doctype === "Issue") {
			return [
				__("What is the customer asking for?"),
				__("What has already been done?"),
				__("What is still open?"),
				__("Show my open tickets"),
			];
		}
		if (count === 0) {
			return [__("Create a {0}", [ctx.doctype])];
		}
		return [
			__("How many {0} are there?", [ctx.doctype]),
			__("Which {0} are still open?", [ctx.doctype]),
			__("What is the total value of these {0}?", [ctx.doctype]),
		];
	}

	if (set === "report" && ctx.report) {
		return [
			__("Summarise this report"),
			__("What are the totals in this report?"),
			__("Which rows stand out?"),
		];
	}

	// Generic fallback: support-shaped, and "my" is never used — the
	// assistant has no way to know who "my" is, so it answers with every
	// open ticket and calls them the reader's.
	return [
		__("How many open Issues are there?"),
		__("Which Issues are still open?"),
		__("How many customers are there?"),
	];
}
