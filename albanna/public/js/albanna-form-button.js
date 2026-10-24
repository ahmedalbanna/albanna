// Albanna: a small, global affordance on every form.
//
// The side chat is already scoped to the document the reader is looking at
// — its page identity is "form|<doctype>|<name>" — so opening it from a
// form needs no new backend and no new context.  What is missing is a way
// to reach it without hunting for the launcher, and a form is where a
// person is most likely to want it: "ask anything about this record".
//
// The button is added to the form's own toolbar rather than to the side
// panel, because a button that lives on the document it is about is found
// where the question is, and a launcher in the corner is found where the
// question is not.

(function () {
	"use strict";

	function addButton(frm) {
		if (!frm || !frm.add_custom_button) return;
		if (frm.__albanna_button_added) return;
		frm.__albanna_button_added = true;
		try {
			frm.add_custom_button(__("Ask Albanna"), function () {
				if (window.albannaSideChat && typeof window.albannaSideChat.open === "function") {
					window.albannaSideChat.open();
				}
			});
		} catch (error) {
			// A form without a toolbar is not a place for a button.
		}
	}

	function watchForms() {
		// The Desk is a single-page application: a form is not a page
		// load, it is a route change.  So the button is added when the
		// route settles on a form, and again whenever the reader moves to
		// another one.  `cur_frm` is the Desk's own statement of which
		// form is open, and it is the right thing to read here — this is
		// a UI affordance, not a permission decision.
		try {
			if (window.cur_frm) addButton(window.cur_frm);
		} catch (error) {
			// The Desk is not ready yet.
		}
	}

	if (window.frappe && typeof window.frappe.router === "object") {
		// `change` fires on every route change, including the first one.
		window.frappe.router.on("change", function () {
			window.setTimeout(watchForms, 0);
		});
	}

	// A form can be opened without a route change (a new document created
	// in place), so watch for refresh events too.
	if (window.frappe && typeof window.frappe.ui === "object") {
		document.addEventListener("frappe:refresh", watchForms);
	}

	window.setTimeout(watchForms, 0);
})();
