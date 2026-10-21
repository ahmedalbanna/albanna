// What the widget knows about the page the user is looking at.
//
// The Desk is a single-page application, so the page is not a URL — it is
// the current form, the current route, and whatever the user has selected.
// A poll that reads `cur_frm` is wrong twice over: it cannot see a list or
// a report, and `cur_frm` outlives the document it points at.
//
// Everything here is a *description*.  The server re-reads whatever it
// needs and treats the description as untrusted, so a wrong answer here
// costs a slightly less relevant question, never a wrong document.
//
// The selection is captured passively.  The user selected something, and
// that selection is the strongest signal available about what they are
// about to ask.

/** The longest selection that is sent. */
const MAX_SELECTION = 500;

/**
 * The current route, as a string.
 *
 * `frappe.get_route()` returns an array in Frappe v16 (`["Form", "Sales
 * Invoice", "SINV-0001"]`) and a string in some builds.  Left as an array
 * it stringifies with commas wherever it is joined, which makes a page
 * identity that looks like a typo.
 */
export function currentRoute() {
	const route =
		window.frappe && typeof window.frappe.get_route === "function"
			? window.frappe.get_route()
			: "";
	if (Array.isArray(route)) return route.filter(Boolean).join("/");
	return String(route || "");
}

/** The route's identity — the same string, used for scoping a conversation. */
export function pageIdentity() {
	const context = resolveContext();
	return [context.view, context.doctype, context.name].filter(Boolean).join("|");
}

/**
 * Describe the current page.
 *
 * @returns {{view: string, doctype: string, name: string, title: string,
 *   filters: string, selection: string}} the description
 */
export function resolveContext() {
	const frm = window.cur_frm;
	const route = currentRoute();

	let view = route;
	let doctype = "";
	let name = "";
	let title = "";
	let filters = "";

	if (frm && frm.doctype && frm.doc) {
		// A form: the document is the page.
		view = "form";
		doctype = frm.doctype;
		name = frm.doc.name || "";
		title = documentTitle(frm.doc);
	} else {
		// A list, a report, a workspace, a dashboard: the route is the page.
		// The route carries the module and the view ("erpnext/sales-order"),
		// which is enough to scope a conversation and to tell the model where
		// the user is.
		view = route;
	}
	return { view, route, doctype, name, title, filters, selection: currentSelection() };
}

/**
 * A readable title for a document.
 *
 * `doc.title` is null on most ERPNext documents — the field is not a thing
 * ERPNext has — so a title that stops at the name is a title that says
 * nothing.  The party and the amount are what identify a document to a
 * person, so they are used when the title is missing.
 */
function documentTitle(doc) {
	if (doc.title) return doc.title;
	for (const field of ["customer", "supplier", "company", "item_name", "full_name", "subject"]) {
		if (doc[field]) return String(doc[field]);
	}
	return doc.name || "";
}

/**
 * The text the user has selected, if any.
 *
 * @returns {string} the selected text, clipped
 */
export function currentSelection() {
	try {
		const selection = window.getSelection && window.getSelection();
		if (!selection) return "";
		const text = String(selection).trim();
		if (text.length < 3) return "";
		return text.slice(0, MAX_SELECTION);
	} catch (error) {
		return "";
	}
}
