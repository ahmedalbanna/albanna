// What the widget knows about the page the user is looking at.
//
// The Desk is a single-page application, so the page is not a URL — it is
// the current form, the current route, and whatever the user has selected.
// A poll that reads `cur_frm` is wrong twice over: it cannot see a list or
// a report, and `cur_frm` outlives the document it points at.
//
// So the route is the authority — it is the Desk's own statement of what
// is on the screen — and the open document is consulted only for the
// details the route does not carry, and only when it is the document the
// route names.  The route's shape is unchanged: a form is
// "form|<doctype>|<name>" and everything else is the route itself, so a
// conversation scoped by one page is still found after the change.
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
	const route = currentRoute();
	const parts = route ? route.split("/") : [];

	// The route is the Desk's own statement of what is on the screen, and
	// it is the only statement that is always true.
	//
	// `cur_frm` is not.  The Desk sets it when a form opens and never
	// clears it when the reader walks away from that form — only a *page*
	// view clears it — so on the list they walked to, it still points at
	// the form they walked away from.  A widget that trusts it answers
	// about a page the reader has already left, and looks perfectly
	// correct while doing it.
	//
	// So the route decides, and the open document only supplies the
	// details the route does not carry.
	const onForm = parts[0] === "Form";

	const frm = window.cur_frm;
	let view = route;
	let doctype = "";
	let name = "";
	let title = "";
	let filters = "";

	if (onForm) {
		// A form: the document is the page.
		view = "form";
		doctype = parts[1] || "";
		name = parts[2] || "";

		// The open document has what the route does not: its title, and
		// its real name when it is a document that was only just saved.
		// It is used only when it is the document the route names — a
		// stale form must not describe the page.
		if (frm && frm.doctype && frm.doc && frm.doctype === doctype) {
			title = documentTitle(frm.doc);
			if (frm.doc.name) name = frm.doc.name;
		}
	}
	// A list, a report, a workspace, a dashboard: the route is the page.
	// The route carries the module and the view ("erpnext/sales-order"),
	// which is enough to scope a conversation and to tell the model where
	// the user is.
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
