// Albanna: an "Ask Albanna" affordance on Frappe error dialogs.
//
// When a Frappe dialog reports an error (a red msgprint, or a dialog whose
// title says "Error"), the person reading it has a concrete, high-intent
// question: "why did this fail?".  This script puts an "Ask Albanna" button
// on that dialog, which opens the panel with the error text and the doctype
// pre-filled as the first question.
//
// It does not run when chat access is denied: the launcher is the gate, and
// if it did not render, `window.albannaSideChat` is absent.
//
// The dialog is found by watching the document, because Frappe builds it
// asynchronously and there is no event that announces "an error dialog
// just appeared".
//
// Three things about Frappe's dialogs decide how this is written, and each
// of them was found by looking at a real one:
//
//   1. **The red indicator is the mark of an error, not the title.**  A
//      title says "Error" on an English desk and says something else on an
//      Arabic one, and the desk's language is not the app's to assume.  The
//      indicator is Frappe's own class (`.indicator.red` in v16,
//      `.indicator-red` before it), and it says the same thing in every
//      language.
//   2. **The footer is hidden.**  Frappe hides the footer of a message with
//      no primary action, so a button in that footer is a button nobody
//      can press.  The footer is shown when the button is added.
//   3. **The dialog arrives before its footer does.**  So a dialog that
//      cannot be given a button yet is not marked as done: it is left
//      unmarked, and the observer tries again when the footer lands.

(function () {
	"use strict";

	const BUTTON_CLASS = "albanna-error-ask";

	/* The marks of an error dialog, in the versions this runs on.  The
	 * indicator is the reliable one — it is Frappe's own class and it does
	 * not depend on the desk's language. */
	const ERROR_MARKS = ".indicator.red, .indicator-red, .text-danger, [data-indicator='red']";

	function isChatAvailable() {
		return !!(window.albannaSideChat && typeof window.albannaSideChat.ask === "function");
	}

	function alreadyHasButton(dialog) {
		return !!dialog.querySelector("." + BUTTON_CLASS);
	}

	function isErrorDialog(dialog) {
		if (!dialog || dialog.nodeType !== 1) return false;
		if (alreadyHasButton(dialog)) return false;

		const text = (dialog.textContent || "").trim();
		if (text.length < 4) return false;

		if (dialog.querySelector(ERROR_MARKS)) return true;

		// The title, for a desk that says so in English.
		const title = dialog.querySelector(".modal-title, .msgprint-title, h4, h5");
		const titleText = ((title && title.textContent) || "").toLowerCase();
		return titleText.includes("error");
	}

	function errorText(dialog) {
		const body = dialog.querySelector(".modal-body, .msgprint-text, .frappe-control");
		const text = (body && body.textContent) || dialog.textContent || "";
		return String(text).replace(/\s+/g, " ").trim().slice(0, 1500);
	}

	function doctypeFromDialog(dialog) {
		try {
			if (window.cur_frm && window.cur_frm.doctype) return window.cur_frm.doctype;
		} catch (error) {
			// No form is open; the error text will have to carry the
			// context on its own.
		}
		return "";
	}

	function injectButton(dialog) {
		if (!isChatAvailable()) return;
		if (alreadyHasButton(dialog)) return;

		const footer = dialog.querySelector(".modal-footer") || dialog.querySelector(".msgprint-footer");
		if (!footer) {
			// The dialog has not been finished yet.  It is deliberately not
			// marked as done: the observer will see the footer when it
			// arrives, and the button goes in then.
			return;
		}

		const button = document.createElement("button");
		button.type = "button";
		button.className = "btn btn-sm btn-default " + BUTTON_CLASS;
		button.textContent = __("Ask Albanna about this error");
		button.addEventListener("click", function () {
			const text = errorText(dialog);
			const doctype = doctypeFromDialog(dialog);
			const question = doctype
				? __("Why did this error happen on {0}? {1}", [doctype, text])
				: __("Why did this error happen? {0}", [text]);
			// Close the dialog first so the panel is not hidden behind it.
			try {
				const close = dialog.querySelector(".btn-modal-close, .close, [data-dismiss='modal']");
				if (close) close.click();
			} catch (error) {
				// The dialog may not be closable; opening the panel anyway
				// is better than refusing to help.
			}
			window.albannaSideChat.ask(question);
		});

		const slot = footer.querySelector(".custom-actions") || footer;
		slot.appendChild(button);

		// A footer that is hidden hides the button with it.
		if (footer.classList.contains("hide")) footer.classList.remove("hide");
	}

	function scan(root) {
		if (!root || root.nodeType !== 1) return;

		// The dialog itself.
		if (isErrorDialog(root)) injectButton(root);

		// Descendants.
		const dialogs = root.querySelectorAll
			? root.querySelectorAll(".modal, .modal-dialog, .msgprint-dialog")
			: [];
		for (let i = 0; i < dialogs.length; i++) {
			if (isErrorDialog(dialogs[i])) injectButton(dialogs[i]);
		}

		// The dialog that owns what was just added.  A dialog arrives
		// before its footer does, so the footer landing is the moment the
		// button can be added — and the footer knows its dialog.
		const owner = root.closest ? root.closest(".modal, .modal-dialog") : null;
		if (owner && isErrorDialog(owner)) injectButton(owner);
	}

	let scheduled = false;
	function scheduleScan() {
		if (scheduled) return;
		scheduled = true;
		window.setTimeout(function () {
			scheduled = false;
			scan(document.body);
		}, 0);
	}

	if (typeof MutationObserver !== "undefined") {
		const observer = new MutationObserver(function (mutations) {
			for (let i = 0; i < mutations.length; i++) {
				const m = mutations[i];
				for (let j = 0; j < m.addedNodes.length; j++) {
					scan(m.addedNodes[j]);
				}
			}
		});
		if (document.body) {
			observer.observe(document.body, { childList: true, subtree: true });
		} else {
			document.addEventListener("DOMContentLoaded", function () {
				observer.observe(document.body, { childList: true, subtree: true });
			});
		}
	}

	// Initial scan for dialogs already on the page.
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", scheduleScan, { once: true });
	} else {
		scheduleScan();
	}
})();
