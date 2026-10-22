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
