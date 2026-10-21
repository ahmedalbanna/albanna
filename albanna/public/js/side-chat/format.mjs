// Formatting helpers for the widget.
//
// The only thing here that is not trivial is the relative time, and it is
// done with `Intl.RelativeTimeFormat` rather than a hand-rolled "2 min
// ago": the formatter follows the browser's locale, so an Arabic interface
// gets "قبل دقيقتين" without a second translation table.

/** The locale the interface is in. */
export function currentLocale() {
	return document.documentElement.lang || window.navigator.language || "en";
}

/**
 * A moment, as "2 minutes ago" / "أمس".
 *
 * The epoch is preferred over the string: the server's timestamps are naive —
 * "2026-10-21 03:20:00", with no timezone — so a browser in a different
 * timezone from the server reads them as a different moment, and a
 * conversation that happened a minute ago reads as "in three hours".
 *
 * @param {number|string|Date} value an epoch in seconds, an ISO timestamp
 *   or a Date
 * @returns {string} the relative time
 */
export function relativeTime(value) {
	if (!value) return "";

	let date;
	if (typeof value === "number") {
		date = new Date(value * 1000);
	} else if (value instanceof Date) {
		date = value;
	} else {
		date = new Date(String(value).replace(" ", "T"));
	}
	if (Number.isNaN(date.getTime())) return "";

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
	const doctype = parts.length > 1 ? parts[1] : parts[0];
	return doctype || "";
}
