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
	},
});

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
