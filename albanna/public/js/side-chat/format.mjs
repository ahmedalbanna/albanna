// Formatting helpers for the widget.
//
// The only thing here that is not trivial is the relative time, and it is
// done with `Intl.RelativeTimeFormat` rather than a hand-rolled "2 min
// ago": the formatter follows the browser's locale, so an Arabic interface
// gets "قبل دقيقتين" without a second translation table.

/** The locale the interface is in. */
export function currentLocale() {
	if (typeof document !== "undefined" && document.documentElement) {
		const lang = document.documentElement.lang;
		if (lang) return lang;
	}
	if (typeof navigator !== "undefined" && navigator.language) {
		return navigator.language;
	}
	return "en";
}

/**
 * A moment, as a `Date`.
 *
 * The epoch is preferred over the string: the server's timestamps are
 * naive — "2026-10-21 03:20:00", with no timezone — so a browser in a
 * different timezone from the server reads them as a different moment, and
 * a conversation that happened a minute ago reads as "in three hours".
 *
 * @param {number|string|Date} value an epoch in seconds, a timestamp or a
 *   Date
 * @returns {Date|null} the moment, or null when it could not be read
 */
function toDate(value) {
	if (!value) return null;

	if (typeof value === "number") {
		return new Date(value * 1000);
	}
	if (value instanceof Date) {
		return value;
	}
	const date = new Date(String(value).replace(" ", "T"));
	if (Number.isNaN(date.getTime())) return null;
	return date;
}

/**
 * A moment, as "2 minutes ago" / "أمس".
 *
 * @param {number|string|Date} value an epoch in seconds, an ISO timestamp
 *   or a Date
 * @returns {string} the relative time
 */
export function relativeTime(value) {
	const date = toDate(value);
	if (!date) return "";

	const seconds = Math.round((date.getTime() - Date.now()) / 1000);
	const units = [
		["year", 60 * 60 * 24 * 365],
		["month", 60 * 60 * 24 * 30],
		["week", 60 * 60 * 24 * 7],
		["day", 60 * 60 * 24],
		["hour", 60 * 60],
		["minute", 60],
		["second", 1],
	];

	const formatter = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
	for (const [unit, size] of units) {
		if (Math.abs(seconds) >= size || unit === "second") {
			return formatter.format(Math.round(seconds / size), unit);
		}
	}
	return "";
}

/**
 * The formatters, by locale.
 *
 * Building an `Intl.DateTimeFormat` costs about half a millisecond — it
 * resolves the locale's data.  The panel formats a time for every
 * message, and the panel re-renders on every token, so a formatter per
 * message per token is a millisecond and a half of work per token, for a
 * clock.  So there is one formatter per locale, and it is kept.
 */
const formatters = new Map();

function timeFormatter() {
	const locale = currentLocale();
	if (formatters.has(locale)) return formatters.get(locale);

	let formatter = null;
	try {
		formatter = new Intl.DateTimeFormat(locale, {
			hour: "2-digit",
			minute: "2-digit",
		});
	} catch (error) {
		// A browser with no locale data still shows the reader something.
		formatter = null;
	}
	formatters.set(locale, formatter);
	return formatter;
}

/**
 * A moment, as the time of day.
 *
 * The reader's locale and the reader's clock: `Intl.DateTimeFormat`
 * formats in the browser's language, so an Arabic interface gets Arabic
 * digits without a second translation table.
 *
 * @param {number|string|Date} value an epoch in seconds, a timestamp or a
 *   Date
 * @returns {string} the time of day, or an empty string
 */
export function clockTime(value) {
	const date = toDate(value);
	if (!date) return "";

	const formatter = timeFormatter();
	if (formatter) {
		try {
			return formatter.format(date);
		} catch (error) {
			// Fall through to the plain time below.
		}
	}
	return date.toTimeString().slice(0, 5);
}

/**
 * The page a conversation belongs to, as a readable phrase.
 *
 * The page identity is `view|doctype|name`; the drawer shows the middle of
 * it, which is the thing a person recognises ("Sales Order").
 *
 * @param {string} page the page identity
 * @returns {string} the readable page
 */
export function readablePage(page) {
	if (!page) return "";

	const parts = String(page).split("|");
	if (parts.length > 1) return parts[1] || "";

	// A list or a workspace: the identity is the route, and the route's
	// last segment is a slug — "erpnext/sales-order" is not a name a
	// person would recognise.  So it is turned into one.
	return titleise(parts[0].split("/").pop() || "");
}

/**
 * A slug, as a name: "sales-order" becomes "Sales Order".
 *
 * @param {string} slug the slug
 * @returns {string} the name
 */
function titleise(slug) {
	return String(slug || "")
		.split(/[-_\s]+/)
		.filter(Boolean)
		.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
		.join(" ");
}
