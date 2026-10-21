// Albanna side chat — the Vue application.
//
// Loaded on demand by the launcher (`albanna-side-chat.bundle.js`) the first
// time the widget is opened, so the framework never reaches a user who does
// not use the assistant.
//
// Exposed as `window.__albanna_side_chat__` so the launcher can mount it
// into the panel it already placed on the page.

import { createApp, h } from "vue";
import SideChatApp from "./side-chat/SideChatApp.vue";

const MOUNT_FLAG = "__albanna_side_chat__";

if (!window[MOUNT_FLAG]) {
	window[MOUNT_FLAG] = {
		/**
		 * Mount the widget into `target`.
		 *
		 * @param {Element|string} target the container the launcher created
		 * @param {{config: object, onClose?: Function, onContext?: Function}} options
		 * @returns {object|null} the Vue app instance, or null on failure
		 */
		mount(target, options = {}) {
			const el = typeof target === "string" ? document.querySelector(target) : target;
			if (!el) {
				console.error("[albanna] mount target not found:", target);
				return null;
			}

			// Props rather than provide: the payload is resolved per mount by
			// the launcher, and a second mount (a re-click after a close) must
			// see the fresh payload rather than a singleton stashed on the
			// app.  Vue's `mount(container, rootProps)` does not exist, so
			// the root is a one-component wrapper that renders the app with
			// them.
			const rootProps = {
				config: options.config || {},
				onClose: options.onClose || (() => {}),
				onContext: options.onContext || (() => {}),
			};

			const app = createApp({
				render: () => h(SideChatApp, rootProps),
			});

			// Vue compiles template expressions to `_ctx.__("...")` when
			// `with` is unavailable, and its render-context proxy does not
			// fall back to the global scope.  So `__` and `frappe` used in a
			// template resolve to `undefined` unless they are on the
			// instance.
			const globals = app.config.globalProperties;
			globals.__ = (text) => (window.__ ? window.__(text) : text);
			globals._ = (text) => (window._ ? window._(text) : text);
			globals.frappe = window.frappe;

			app.mount(el);
			return app;
		},
	};
}
