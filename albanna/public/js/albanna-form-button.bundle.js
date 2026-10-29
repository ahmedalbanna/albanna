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
//
// Two facts about Frappe decide how this is written:
//
//   1. The form clears its custom buttons on every refresh
//      (`refresh_header` calls `clear_custom_buttons`).  So the button is
//      re-added whenever the form refreshes, and the check is "is it
//      there now" rather than "did I add it once".
//   2. The form announces its own refresh with the jQuery event
//      `form-refresh` on the document, and the form is its payload.  That
//      is the hook that works on a direct page load: the router's
//      "change" event has already fired by the time this file is parsed,
//      so a listener on it alone never sees the first form.
//
// The router's "change" is still watched, for the SPA case: a route
// change may open a form whose refresh event has not arrived yet.
//
// The third fact is this app's own: the chat is gated, and the gate is
// decided by the server and published by the launcher
// (`side-chat/access.mjs`).  A reader who may not chat was given this
// button anyway, and clicking it did nothing — the launcher had not
// mounted, so there was no panel for it to open.  The button therefore
// waits for the answer: it is added when the widget exists for this
// reader, and not before.

import { chatAllowed, onAccessDecision } from "./side-chat/access.mjs";

(function () {
	"use strict";

	/* The label is written out at the call site, not held in a constant:
	 * the translation checker reads the literal, and a constant would hide
	 * it from the checker — which would leave an English button on an
	 * Arabic desk, with the catalogue claiming the string was unused. */
	function label() {
		return typeof window.__ === "function" ? window.__("Ask Albanna") : "Ask Albanna";
	}

	function mayOfferChat() {
		return chatAllowed({ window, document });
	}

	function addButton(frm) {
		if (!frm || typeof frm.add_custom_button !== "function") return;
		// No widget for this reader means no button: a button that opens
		// nothing is worse than no button, because it looks like a thing
		// that works.
		if (!mayOfferChat()) return;

		const text = label();
		// The form drops its custom buttons on every refresh, so what is
		// asked is whether the button is on the toolbar now — not whether
		// this script has run before.
		if (frm.custom_buttons && frm.custom_buttons[text]) return;

		try {
			frm.add_custom_button(text, function () {
				if (window.albannaSideChat && typeof window.albannaSideChat.open === "function") {
					window.albannaSideChat.open();
				}
			});
		} catch (error) {
			// A form without a toolbar is not a place for a button.
		}
	}

	function watchForms() {
		try {
			if (window.cur_frm) addButton(window.cur_frm);
		} catch (error) {
			// The Desk is not ready yet.
		}
	}

	/* The answer may arrive after the form has been drawn.
	 *
	 * The launcher asks the server, and the server answers in its own
	 * time.  A form that is already on screen when the answer lands has
	 * to be given the button then — otherwise the reader who *may* chat
	 * is the one left without it, which is the same bug wearing the
	 * other hat. */
	onAccessDecision(
		function (decision) {
			if (!decision || decision.visible !== true) return;
			watchForms();
		},
		{ window, document }
	);

	if (window.jQuery) {
		window.jQuery(document).on("form-refresh", function (_event, frm) {
			addButton(frm);
		});
	}

	if (window.frappe && typeof window.frappe.router === "object") {
		window.frappe.router.on("change", function () {
			window.setTimeout(watchForms, 0);
		});
	}

	window.setTimeout(watchForms, 0);
})();
