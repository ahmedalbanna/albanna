// The chat access decision, and the button that depends on it.
//
// The rule under test: the "Ask Albanna" button on a form appears only
// for a reader the launcher has said may use the chat.
//
// It used to appear for everybody.  The launcher decided whether the
// widget existed, and the button assumed — so a reader who may not chat
// was given a button that opened nothing, and clicking it did nothing at
// all.  That is the bug this file exists to hold shut.
//
// The three parts are the three facts the fix rests on:
//
//   1. the decision is published, and published for both answers;
//   2. a reader who may not chat is given no button;
//   3. a reader who may chat is given one — even when the answer arrives
//      after the form has already been drawn.

import assert from "node:assert";

import {
	ACCESS_EVENT,
	ACCESS_GLOBAL,
	chatAllowed,
	onAccessDecision,
	publishAccess,
} from "./access.mjs";

/** A document that dispatches events to the listeners registered on it. */
function fakeDocument() {
	const listeners = new Map();
	return {
		addEventListener(type, handler) {
			if (!listeners.has(type)) listeners.set(type, []);
			listeners.get(type).push(handler);
		},
		removeEventListener(type, handler) {
			const list = listeners.get(type) || [];
			const index = list.indexOf(handler);
			if (index >= 0) list.splice(index, 1);
		},
		dispatchEvent(event) {
			for (const handler of listeners.get(event.type) || []) handler(event);
		},
	};
}

/** A form that records the custom buttons put on its toolbar. */
function fakeForm() {
	const buttons = [];
	return {
		buttons,
		custom_buttons: {},
		add_custom_button(label, handler) {
			buttons.push({ label, handler });
			this.custom_buttons[label] = handler;
		},
	};
}

/** A window that runs its timeouts at once, so the test does not wait. */
function fakeWindow() {
	return {
		cur_frm: null,
		setTimeout(fn) {
			fn();
		},
	};
}

// -- the decision itself ---------------------------------------------------

{
	const win = fakeWindow();
	const doc = fakeDocument();
	const env = { window: win, document: doc };

	// Before the launcher has answered, there is nothing to offer.
	assert.equal(chatAllowed(env), false);

	const decision = publishAccess({ visible: true, chat_access: true }, env);
	assert.equal(decision.visible, true);
	assert.equal(decision.chat_access, true);
	assert.equal(win[ACCESS_GLOBAL].visible, true);
	assert.equal(chatAllowed(env), true);

	// A refusal is published too, and it is a refusal.
	publishAccess({ visible: false, chat_access: false }, env);
	assert.equal(chatAllowed(env), false);

	// So is an answer that never arrived.
	publishAccess(null, env);
	assert.equal(chatAllowed(env), false);
}

// -- the announcement ------------------------------------------------------

{
	const win = fakeWindow();
	const doc = fakeDocument();
	const env = { window: win, document: doc };

	const seen = [];
	onAccessDecision((decision) => seen.push(decision), env);

	publishAccess({ visible: true, chat_access: true }, env);

	assert.equal(seen.length, 1);
	assert.equal(seen[0].visible, true);
	assert.equal(seen[0].chat_access, true);
	assert.equal(ACCESS_EVENT, "albanna:access");
}

// -- the button on a form --------------------------------------------------

/**
 * Load the form-button bundle against a fresh page.
 *
 * The bundle is loaded with a query string so that each scenario gets
 * its own copy: a module is evaluated once per URL, and the second
 * scenario would otherwise find the first one's page.
 */
async function loadFormButton({ decision = null, form = null } = {}) {
	const win = fakeWindow();
	const doc = fakeDocument();
	globalThis.window = win;
	globalThis.document = doc;

	if (form) win.cur_frm = form;
	if (decision) publishAccess(decision, { window: win, document: doc });

	await import(`../albanna-form-button.bundle.js?scenario=${Math.random()}`);
	return { win, doc, form: win.cur_frm };
}

// A reader who may not chat is given no button.
{
	const form = fakeForm();
	await loadFormButton({ decision: { visible: false, chat_access: false }, form });

	assert.equal(form.buttons.length, 0);
}

// A reader who may chat is given one.
{
	const form = fakeForm();
	await loadFormButton({ decision: { visible: true, chat_access: true }, form });

	assert.equal(form.buttons.length, 1);
	assert.equal(form.buttons[0].label, "Ask Albanna");
}

// The answer may arrive after the form has been drawn: the button is
// added then, because the reader who may chat must not be the one left
// without it.
{
	const form = fakeForm();
	const { win, doc } = await loadFormButton({ form });

	assert.equal(form.buttons.length, 0, "no button before the answer");

	publishAccess({ visible: true, chat_access: true }, { window: win, document: doc });

	assert.equal(form.buttons.length, 1, "the button arrives with the answer");
}

// An answer that never arrives leaves the reader without a button.
{
	const form = fakeForm();
	await loadFormButton({ form });

	assert.equal(form.buttons.length, 0);
}
