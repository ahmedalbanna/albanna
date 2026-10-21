// What the widget thinks the page is.
//
// The Desk sets `cur_frm` when a form opens and never clears it when the
// reader walks away from that form — only a *page* view clears it.  So on
// the list they walked to, `cur_frm` still points at the form they walked
// away from.
//
// A widget that trusts it answers about a page the reader has already
// left, and looks perfectly correct while doing it.  So the route is the
// authority, and these are the tests that hold it to being so.

import assert from "node:assert";
import {
	classifyRoute,
	currentRoute,
	describeListFilters,
	pageIdentity,
	renderListFilters,
	resolveContext,
} from "./context.mjs";

/**
 * A Desk, as far as the widget is concerned.
 *
 * @param {object} parts the route, the selection, the open document and
 *   the list view
 */
function desk({ route, frm = null, list = null, selection = "" }) {
	global.window = {
		frappe: { get_route: () => route },
		cur_frm: frm,
		cur_list: list,
		getSelection: () => (selection ? { toString: () => selection } : null),
	};
}

/** A Sales Invoice, open. */
const invoice = {
	doctype: "Sales Invoice",
	doc: { name: "ACC-SINV-2026-00001", customer: "Cafe AGRO" },
};

/** A list view, filtered and counted. */
function listView(doctype, filters, count) {
	return {
		doctype,
		total_count: count,
		get_filters_for_args: () => filters,
	};
}

// The route is joined with slashes, not commas.
{
	desk({ route: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"] });
	assert.equal(currentRoute(), "Form/Sales Invoice/ACC-SINV-2026-00001");
}

// A form: the document is the page, and the open document has its title.
{
	desk({ route: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"], frm: invoice });
	const context = resolveContext();

	assert.equal(context.view, "form");
	assert.equal(context.doctype, "Sales Invoice");
	assert.equal(context.name, "ACC-SINV-2026-00001");
	assert.equal(context.title, "Cafe AGRO", "the title comes from the document");
	assert.equal(pageIdentity(), "form|Sales Invoice|ACC-SINV-2026-00001");
}

// A list — and the form the reader came from is still "open", because the
// Desk never closes it.  The list is the page.  This is the bug: the
// widget used to answer about the Sales Invoice while the reader was
// looking at the Customer list.
{
	desk({ route: ["List", "Customer", "List"], frm: invoice });
	const context = resolveContext();

	assert.equal(context.view, "List/Customer/List");
	assert.equal(context.doctype, "", "a stale form must not name the page");
	assert.equal(context.name, "");
	assert.equal(context.title, "", "a stale form must not describe the page");
	assert.equal(pageIdentity(), "List/Customer/List");
}

// The same list, with nothing left over.
{
	desk({ route: ["List", "Customer", "List"] });
	assert.equal(pageIdentity(), "List/Customer/List");
}

// A workspace.
{
	desk({ route: ["Workspaces", "Buying"] });
	assert.equal(pageIdentity(), "Workspaces/Buying");
}

// A form the reader has just walked to, whose document has not loaded yet,
// and whose *previous* form is still open.  The route names the page; the
// stale document says nothing about it.
{
	desk({ route: ["Form", "Sales Order", "SAL-ORD-0001"], frm: invoice });
	const context = resolveContext();

	assert.equal(context.doctype, "Sales Order");
	assert.equal(context.name, "SAL-ORD-0001");
	assert.equal(context.title, "", "the form that is still open is not this one");
	assert.equal(pageIdentity(), "form|Sales Order|SAL-ORD-0001");
}

// A form whose document was only just saved: the route says "new" and the
// document has its real name.
{
	desk({
		route: ["Form", "Sales Invoice", "new"],
		frm: { doctype: "Sales Invoice", doc: { name: "new-ACC-SINV-2026-00009" } },
	});
	assert.equal(pageIdentity(), "form|Sales Invoice|new-ACC-SINV-2026-00009");
}

// The selection is captured, and clipped.
{
	desk({ route: ["List", "Customer", "List"], selection: "  Café AGRO  " });
	assert.equal(resolveContext().selection, "Café AGRO");
}
{
	desk({ route: ["List", "Customer", "List"], selection: "x".repeat(900) });
	assert.equal(resolveContext().selection.length, 500);
}

// The shape of a form's identity is not changed by any of this.  The
// server scopes conversations by it, and the conversations already on a
// site were scoped by it.
{
	desk({ route: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"], frm: invoice });
	assert.equal(pageIdentity(), "form|Sales Invoice|ACC-SINV-2026-00001");
}

console.log("context: all assertions passed");

// The route says what kind of page this is.
{
	assert.equal(classifyRoute("Form/Sales Invoice/ACC-SINV-2026-00001"), "form");
	assert.equal(classifyRoute("List/Customer/List"), "list");
	assert.equal(classifyRoute("List/Customer/Report"), "other", "a report is not a list");
	assert.equal(classifyRoute("Workspaces/Home"), "other");
	assert.equal(classifyRoute(""), "other");
}

// A list's filters are the ones the reader applied, and the rows are the
// rows the list shows.  Without them the assistant answers about the
// whole table rather than about the table on the screen.
{
	desk({
		route: ["List", "Sales Order", "List"],
		list: listView("Sales Order", [["Sales Order", "status", "=", "To Deliver"]], 24),
	});
	const context = resolveContext();

	assert.equal(context.doctype, "Sales Order");
	assert.equal(context.filters, "status = To Deliver");
	assert.equal(context.rows, 24);
}

// A list view that cannot say what it is filtered by is a list whose
// filters are unknown — not a list with no filters.
{
	desk({
		route: ["List", "Sales Order", "List"],
		list: {
			doctype: "Sales Order",
			total_count: 3,
			get_filters_for_args: () => {
				throw new Error("no filters here");
			},
		},
	});
	const context = resolveContext();

	assert.equal(context.filters, "");
	assert.equal(context.rows, 3);
}

// A list the reader has walked away from must not describe the page.
//
// `cur_list` is cleared when the doctype changes and not otherwise, so
// on the form the reader walked to it still holds the list they walked
// away from — the same trap as `cur_frm`.
{
	desk({
		route: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"],
		frm: invoice,
		list: listView("Customer", [["Customer", "name", "like", "%Cafe%"]], 12),
	});
	const context = resolveContext();

	assert.equal(context.filters, "", "a stale list must not filter the page");
	assert.equal(context.rows, 0);
	assert.equal(context.doctype, "Sales Invoice", "the form still names the page");
}

// A list's identity is its route — the description grows, and a
// conversation scoped by a growing description would be re-scoped every
// time it grows.
{
	desk({
		route: ["List", "Sales Order", "List"],
		list: listView("Sales Order", [["Sales Order", "status", "=", "To Deliver"]], 24),
	});
	const context = resolveContext();

	assert.equal(pageIdentity(context), "List/Sales Order/List");
}

// A form's identity is the document.
{
	desk({ route: ["Form", "Sales Invoice", "ACC-SINV-2026-00001"], frm: invoice });
	assert.equal(pageIdentity(resolveContext()), "form|Sales Invoice|ACC-SINV-2026-00001");
}

// The filters are normalised: a row with no field is dropped, the
// operator defaults to "=", and a value is carried on one line.
{
	const rows = describeListFilters([
		["Sales Order", "status", "=", "To Deliver"],
		["Sales Order", "", "=", "ignored"],
		["Sales Order", "company", "", "Albanna"],
		"not a row",
	]);
	assert.deepEqual(rows, [
		{ field: "status", op: "=", value: "To Deliver" },
		{ field: "company", op: "=", value: "Albanna" },
	]);
	assert.equal(renderListFilters(rows), "status = To Deliver; company = Albanna");
	assert.equal(renderListFilters([]), "");
	assert.equal(renderListFilters(null), "");
}

// The filters are capped, because a list can carry a hundred of them and
// a model does not need them.
{
	const many = [];
	for (let index = 0; index < 40; index += 1) {
		many.push(["Sales Order", `field_${index}`, "=", String(index)]);
	}
	assert.equal(describeListFilters(many).length, 20);
}
