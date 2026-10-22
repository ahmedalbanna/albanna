// The settings page.
//
// The one thing this page could not do was tell the operator whether the
// provider they had just typed was reachable.  They found out at the first
// question, in front of a user, which is the worst possible moment to find
// out.
//
// The button calls the provider with the smallest question that means
// anything, and reports what happened: the model that answered, how long
// it took, or the reason it did not.

frappe.ui.form.on("Albanna Settings", {
	refresh(frm) {
		const button = frm.fields_dict.test_provider;
		if (!button || !button.$input) return;

		// The form re-renders, so the handler is bound once and not once
		// per refresh.
		button.$input.off("click").on("click", () => test_provider(frm));

		// The ledger is a list of rows, and the operator does not want a
		// list of rows: they want the month's total, and they want to
		// know which model and which user it went to.  It is a custom
		// button rather than a field, because it is a reading and not a
		// setting — and a setting that is never edited does not belong
		// in the form.
		//
		// No group: a group becomes the label of the menu it opens, and
		// the operator would be reading "albanna_usage" instead of
		// "Chat usage".
		frm.remove_custom_button(__("Chat usage"));
		frm.add_custom_button(__("Chat usage"), () => show_usage(frm));
	},
});

/**
 * Show what the chat has cost this month.
 *
 * The numbers are the ledger's, and the ledger says which of them are
 * estimates: a total that looks measured but is not is worse than no
 * total at all.
 */
async function show_usage(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Chat usage"),
		size: "small",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "usage",
			},
		],
		primary_action_label: __("Close"),
		primary_action: () => dialog.hide(),
	});

	dialog.show();
	dialog.set_value("usage", __("Reading the ledger…"));

	try {
		const response = await frappe.call({
			method: "albanna.api.usage.summary",
			args: {},
		});
		const summary = response.message || {};

		if (!summary.turns) {
			dialog.set_value(
				"usage",
				`<p>${frappe.utils.escape_html(__("No turns have been run this month."))}</p>`,
			);
			return;
		}

		dialog.set_value("usage", usage_html(summary));
	} catch (error) {
		dialog.set_value(
			"usage",
			`<p class="text-danger">${frappe.utils.escape_html(
				(error && error.message) || __("Unknown error."),
			)}</p>`,
		);
	}
}

/**
 * The usage, as the dialog shows it.
 *
 * @param {object} summary the summary, as the server sent it
 * @returns {string} the markup
 */
function usage_html(summary) {
	const escape = frappe.utils.escape_html;
	const rows = [];

	rows.push(row(__("Turns"), String(summary.turns || 0)));
	rows.push(
		row(
			__("Tokens"),
			`${Number(summary.tokens || 0).toLocaleString()}${summary.estimated ? " ≈" : ""}`,
		),
	);
	rows.push(row(__("Cost"), `${Number(summary.cost || 0).toFixed(4)}`));
	if (summary.provider_cost) {
		rows.push(row(__("Provider cost"), `${Number(summary.provider_cost || 0).toFixed(8)}`));
	}
	rows.push(row(__("Failed turns"), String(summary.errors || 0)));
	if (summary.budget) {
		rows.push(
			row(
				__("Budget"),
				`${Number(summary.cost || 0).toFixed(4)} / ${Number(summary.budget || 0).toFixed(4)}${
					summary.budget_exceeded ? " ⚠" : ""
				}`,
			),
		);
	}

	let html = `<table class="table table-sm" style="width: 100%"><tbody>${rows.join(
		"",
	)}</tbody></table>`;

	if (summary.uncosted_turns) {
		html += `<p class="text-muted" style="font-size: 12px">${escape(
			__("No price is set, so {0} turn(s) have no known cost.", [summary.uncosted_turns]),
		)}</p>`;
	}

	html += `<p class="text-muted" style="font-size: 12px">${escape(
		__(
			"The cost is the site's own: the tokens the turn used, priced with the price per million tokens in the settings.",
		),
	)}</p>`;

	html += breakdown(__("By model"), summary.by_model);
	html += breakdown(__("By user"), summary.by_user);

	return html;
}

/**
 * One line of the totals.
 */
function row(label, value) {
	return `<tr><td>${frappe.utils.escape_html(
		label,
	)}</td><td style="text-align: end"><b>${frappe.utils.escape_html(value)}</b></td></tr>`;
}

/**
 * A breakdown: what it was, and what it cost.
 */
function breakdown(title, entries) {
	if (!entries || !entries.length) return "";
	const escape = frappe.utils.escape_html;
	const rows = entries
		.map(
			(entry) =>
				`<tr><td>${escape(entry.name)}</td><td>${escape(
					String(entry.turns),
				)}</td><td style="text-align: end">${escape(
					Number(entry.cost || 0).toFixed(4),
				)}</td></tr>`,
		)
		.join("");
	return `<p style="margin: 12px 0 4px"><b>${escape(title)}</b></p>
		<table class="table table-sm" style="width: 100%">
			<thead><tr><th>${escape(__("Name"))}</th><th>${escape(
		__("Turns"),
	)}</th><th style="text-align: end">${escape(__("Cost"))}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
}

async function test_provider(frm) {
	const values = {
		kind: frm.doc.provider_kind || "",
		base_url: frm.doc.base_url || "",
		model: frm.doc.model || "",
		api_key: frm.doc.api_key || "",
		timeout: frm.doc.timeout || 0,
	};

	frappe.dom.freeze(__("Testing…"));
	try {
		const response = await frappe.call({
			method: "albanna.api.provider.test_provider",
			args: values,
			indicator: __("Calling the provider…"),
		});
		const message = response.message || {};

		if (message.status === "ok") {
			frappe.msgprint({
				title: __("The provider answered"),
				message: `<div>
					<div><b>${frappe.utils.escape_html(message.model || "")}</b></div>
					<div>${frappe.utils.escape_html(message.reply || "")}</div>
					<div>${frappe.utils.escape_html(__("Took {0} seconds", [message.seconds]))}</div>
				</div>`,
				indicator: "green",
			});
			return;
		}

		frappe.msgprint({
			title: __("The provider did not answer"),
			message: frappe.utils.escape_html(message.error || __("Unknown error.")),
			indicator: "red",
		});
	} catch (error) {
		frappe.msgprint({
			title: __("The provider could not be called"),
			message: frappe.utils.escape_html((error && error.message) || __("Unknown error.")),
			indicator: "red",
		});
	} finally {
		// The form is unfrozen here and not in the branches above: a
		// branch that threw would otherwise leave the page frozen, and
		// a frozen settings page is a page nobody can close.
		frappe.dom.unfreeze();
	}
}
