// Albanna side chat — the global launcher.
//
// Injected on every Desk page through `hooks.app_include_js`.  This file
// does three things and then gets out of the way:
//
//   1. ask the server whether the widget should render at all,
//   2. put a launcher button and an (empty) panel on the page,
//   3. on the first open, fetch the Vue bundle and mount the real UI into it.
//
// The Vue bundle (`side-chat/ui.bundle.js`) is deliberately NOT in
// `app_include_js`: a global hook is paid on every Desk page load, and the
// framework is ~180 KB.  The launcher is ~4 KB and only fetches the rest
// when somebody actually opens the widget.
//
// The launcher owns *whether* the widget exists and where it sits.  The Vue
// app owns everything inside the panel.  That split is why the widget can
// be rendered in a locked state — a user who may not chat still sees it,
// with the reason, instead of finding that it silently does not exist.

const OPTIONS_ENDPOINT = "albanna.api.widget.options";
// The key is the bundle's name in `frappe.boot.assets_json`.  The build
// flattens `public/js/<dir>/` into `public/dist/js/`, so the key follows the
// *file* name and not the directory it was written in — and a generic name
// like `ui.bundle.js` would collide with any other app's `ui.js` in a
// global map.  The name is therefore distinctive on purpose.
const BUNDLE_KEY = "albanna-side-chat-ui.bundle.js";
const MOUNT_FLAG = "__albanna_side_chat__";
const ROOT_ID = "albanna-side-chat";
const MOUNT_ID = "albanna-side-chat-vue-root";

const LAUNCHER_SVG =
	'<svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
	'<path d="M20 4H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3v3l4-3h9a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2Z" ' +
	'stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>';

function tr(text) {
	if (typeof window.__ === "function") return window.__(text);
	return text;
}

/** Boot-failure styles are injected, not shipped: the bundle that failed to
 * load is the bundle whose CSS cannot be trusted to render the error. */
const BOOT_STYLE_ID = "albanna-side-chat-boot-styles";

function ensureBootStyles() {
	if (document.getElementById(BOOT_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = BOOT_STYLE_ID;
	style.textContent = `
		.albanna-boot-error{padding:18px;max-width:360px;margin:auto;text-align:center;
			color:#941f1f;background:#fff7f7;border:1px solid #eb9091;border-radius:8px;
			font-family:inherit;font-size:13px}
		.albanna-boot-error__title{font-size:14px;font-weight:600;margin-bottom:6px}
		.albanna-boot-error__detail{line-height:1.5}
		.albanna-boot-error__hint{margin-top:6px;font-size:12px;opacity:.85}
		.albanna-boot-error__retry{margin-top:12px}`;
	document.head.appendChild(style);
}

async function fetchWidgetOptions() {
	const call = window.frappe && window.frappe.call;
	if (typeof call !== "function") return null;
	const result = await call({ method: OPTIONS_ENDPOINT, silent: true });
	const message = result && result.message;
	return message && typeof message === "object" ? message : null;
}

function paintBootError(el, config, options) {
	el.innerHTML = `
		<div class="albanna-boot-error" role="alert">
			<div class="albanna-boot-error__title">${tr("The assistant could not start")}</div>
			<div class="albanna-boot-error__detail">${tr("The widget bundle failed to load.")}</div>
			<div class="albanna-boot-error__hint">${tr("Run: bench build --app albanna")}</div>
			<button class="btn btn-primary btn-sm albanna-boot-error__retry" type="button">${tr("Retry")}</button>
		</div>`;
	const retry = el.querySelector(".albanna-boot-error__retry");
	if (retry) {
		retry.addEventListener("click", () => {
			el.innerHTML = "";
			loadBundle(el, config, options);
		});
	}
}

/** Resolve the hashed bundle URL from boot, inject it once, then mount. */
function loadBundle(el, config, options) {
	ensureBootStyles();

	if (window[MOUNT_FLAG]) {
		mount(el, config, options);
		return;
	}

	const assets = (window.frappe.boot && window.frappe.boot.assets_json) || {};
	const url = assets[BUNDLE_KEY];
	if (!url) {
		paintBootError(el, config, options);
		return;
	}

	const script = document.createElement("script");
	script.src = url;
	script.onload = () => mount(el, config, options);
	script.onerror = () => paintBootError(el, config, options);
	document.head.appendChild(script);
}

function mount(el, config, options) {
	const app = window[MOUNT_FLAG];
	if (!app || typeof app.mount !== "function") {
		paintBootError(el, config, options);
		return;
	}
	app.mount(el, { config, onClose: options.onClose, onContext: options.onContext });
}

async function boot() {
	if (!document.body) return;
	if (typeof window.frappe === "undefined") return;
	if (document.getElementById(ROOT_ID)) return;

	let config;
	try {
		config = await fetchWidgetOptions();
	} catch (error) {
		if (window.console && window.console.warn) window.console.warn("albanna: unavailable", error);
		return;
	}
	if (!config || config.visible !== true) return;
	if (document.getElementById(ROOT_ID)) return;

	const isRtl = document.documentElement.dir === "rtl";
	// The widget sits on the *inline* end of the screen: the right in a
	// left-to-right interface, the left in a right-to-left one.
	//
	// The configured position is a physical corner ("bottom-right"), and it
	// is mirrored under RTL — which is the same thing as choosing the
	// inline end, and is why the two are the same rule.  Expressing it as a
	// logical side rather than a physical one is what makes it correct: the
	// build's RTL pass mirrors every `left` and `right` in the stylesheet,
	// so a physical rule written for a right-to-left interface ends up on the
	// wrong side, and a logical one is left alone and resolved by the
	// browser.
	const side =
		(config.position || config.position_default || "bottom-right") === "bottom-left"
			? "inline-start"
			: "inline-end";

	const root = document.createElement("div");
	root.id = ROOT_ID;
	root.className = `albanna-side-chat-pos-${side}`;

	const panel = document.createElement("aside");
	panel.className = "albanna-side-chat-panel";
	panel.setAttribute("role", "dialog");
	panel.setAttribute("aria-label", tr("Albanna assistant"));
	panel.setAttribute("aria-hidden", "true");

	const mountPoint = document.createElement("div");
	mountPoint.id = MOUNT_ID;
	panel.appendChild(mountPoint);

	const launcher = document.createElement("button");
	launcher.className = "albanna-side-chat-launcher";
	launcher.type = "button";
	launcher.setAttribute("aria-label", tr("Albanna assistant"));
	launcher.setAttribute("aria-expanded", "false");
	launcher.innerHTML = LAUNCHER_SVG;

	root.append(panel, launcher);
	document.body.append(root);

	let open = false;
	let loaded = false;
	let lastContext = null;

	/* Side-by-side: while the panel is open the Desk gives up the space
	 * instead of being covered.  The class lives on <body> because a margin
	 * there is the only thing that moves the whole Desk.  It is a margin and
	 * not a padding because Frappe's reset ships `body { padding: 0 !important }`,
	 * which beats any non-important declaration whatever its specificity.
	 *
	 * The side is the *logical* one the panel is on, for the same reason the
	 * position is: the build's RTL pass mirrors physical sides, and a
	 * physical margin would end up on the wrong side of a right-to-left
	 * interface.
	 *
	 * Toggled from exactly one place, `setDock`, so it cannot drift out of
	 * sync with the panel's own visibility. */
	const DOCK_CLASS = {
		"inline-end": "albanna-side-chat-docked-inline-end",
		"inline-start": "albanna-side-chat-docked-inline-start",
	};

	const setDock = (next) => {
		for (const name of Object.values(DOCK_CLASS)) {
			document.body.classList.remove(name);
		}
		if (next) {
			document.body.classList.add(DOCK_CLASS[side]);
		}
	};

	const setOpen = (next) => {
		const wasOpen = open;
		open = next;
		panel.classList.toggle("albanna-side-chat-open", open);
		setDock(open);
		panel.setAttribute("aria-hidden", open ? "false" : "true");
		launcher.setAttribute("aria-expanded", open ? "true" : "false");
		launcher.hidden = open;
		if (open) {
			const ta = panel.querySelector("textarea");
			if (ta) window.setTimeout(() => ta.focus(), 0);
		} else if (wasOpen) {
			// Closing returns focus to the control that opened the panel, so
			// a keyboard user does not lose their place in the Desk.
			launcher.focus();
		}
		if (open && !loaded) {
			loaded = true;
			const options = {
				onClose: () => setOpen(false),
				onContext: (context) => {
					lastContext = context;
				},
			};
			loadBundle(mountPoint, config, options);
		}
	};

	launcher.addEventListener("click", () => setOpen(!open));

	/* The close button in the panel header is the ONLY way to close it.
	 *
	 * There is deliberately no outside-click dismissal and no Escape here.
	 * The panel is a column of the layout rather than a transient surface, so
	 * it behaves like a page the user opened, not like a modal over one.
	 * Clicking the page beside the panel is the user reading the page the
	 * answer is about — the whole point of the dock — and throwing the answer
	 * away because they clicked a field is not a dismissal anyone asked for. */
	window.albannaSideChat = {
		config,
		panel,
		launcher,
		isOpen: () => open,
		open: () => setOpen(true),
		close: () => setOpen(false),
		/** The page description the widget last derived (diagnostics only). */
		getContext: () => lastContext,
	};
}

if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", () => window.setTimeout(boot, 0), { once: true });
} else {
	window.setTimeout(boot, 0);
}
