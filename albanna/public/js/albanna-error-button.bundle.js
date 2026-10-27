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

(function () {
	"use strict";

	const BUTTON_CLASS = "albanna-error-ask";
	const PROCESSED = "data-albanna-error-processed";

	function isChatAvailable() {
		return !!(window.albannaSideChat && typeof window.albannaSideChat.ask === "function");
	}

	function isErrorDialog(dialog) {
		if (!dialog || dialog.nodeType !== 1) return false;
		if (dialog.getAttribute(PROCESSED)) return false;
		// Frappe's msgprint dialogs carry the indicator on the title or body.
		const text = (dialog.textContent || "").toLowerCase();
		const title = dialog.querySelector(".modal-title, .msgprint-title, h4, h5");
		const titleText = (title && title.textContent || "").toLowerCase();
		const looksLikeError =
			titleText.includes("error") ||
			dialog.classList.contains("msgprint") ||
			dialog.querySelector(".indicator-red, .text-danger, [data-indicator='red']");
		// Avoid acting on empty or non-error dialogs.
		if (!looksLikeError) return false;
		if (text.trim().length < 4) return false;
		return true;
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
		if (dialog.getAttribute(PROCESSED)) return;
		dialog.setAttribute(PROCESSED, "1");

		const footer =
			dialog.querySelector(".modal-footer") ||
			dialog.querySelector(".msgprint-footer");
		if (!footer) return;

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

		footer.appendChild(button);
	}

	function scan(root) {
		if (!root || root.nodeType !== 1) return;
		// The dialog itself.
		if (isErrorDialog(root)) injectButton(root);
		// Descendants.
		const dialogs = root.querySelectorAll
			? root.querySelectorAll(".modal, .modal-dialog, .msgprint")
			: [];
		for (let i = 0; i < dialogs.length; i++) {
			if (isErrorDialog(dialogs[i])) injectButton(dialogs[i]);
		}
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
