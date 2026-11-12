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
 * The seconds something has been running.
 *
 * The turn's answer carries the moment it started (the same epoch the
 * clock line was built from, or the server's creation timestamp when the
 * thread was opened again); the panel has one clock ticking every
 * second, and the difference is the count.
 *
 * @param {number|string|Date} startedAt the moment it started, as
 *   `toDate` reads them
 * @param {number} nowMs the current moment, in epoch milliseconds
 * @returns {number} whole elapsed seconds, 0 when either end is unreadable
 */
export function elapsedSeconds(startedAt, nowMs) {
	const date = toDate(startedAt);
	if (!date || !Number.isFinite(nowMs)) return 0;
	const seconds = Math.floor((nowMs - date.getTime()) / 1000);
	return seconds > 0 ? seconds : 0;
}

/**
 * The activity line's text: what is happening, and for how long.
 *
 * The line already says what the assistant is doing — "Searching Sales
 * Order".  What it cannot say is that it is *still* doing it: a call that
 * runs a long report looks, for a minute, exactly like a turn that died.
 * The elapsed seconds close that gap — after a few seconds the line grows
 * a ticking tail, and a turn that is alive can be seen being alive.
 *
 * Before the threshold the line stays as it is: a counter on a two-second
 * answer is noise, and the reader who has not waited does not need to be
 * told they have not waited long.
 *
 * @param {string} label what is happening, in the reader's language
 * @param {number|string|Date} startedAt the moment the turn started
 * @param {number} nowMs the current moment, in epoch milliseconds
 * @param {number} [showFrom] the seconds after which the tail appears
 * @returns {string} the line's text, empty when there is nothing to say
 */
export function activityText(label, startedAt, nowMs, showFrom = 5) {
	const text = String(label || "").trim();
	if (!text) return "";
	const seconds = elapsedSeconds(startedAt, nowMs);
	if (seconds < showFrom) return text;
	return `${text} · ${__("{0}s", [seconds])}`;
}

/**
 * A long name, cut in the middle so both of its ends survive.
 *
 * A file's name carries its meaning at both ends: the front says what it
 * is ("quarterly-report") and the back says what it is *read by*
 * (".csv").  A cut at the end — the browser's own ellipsis, and the
 * composer's own slice — hides the second end, and a chip that reads
 * "quarterly-financial-report-2026…" leaves the reader guessing whether
 * they are sending the sheet or the export of it.  The cut in the middle
 * keeps both ends and drops the middle, which is the part that repeats.
 *
 * @param {string} text the name
 * @param {number} [max] the longest name shown whole
 * @param {number} [tail] how many characters of the end survive
 * @returns {string} the name, whole or cut in the middle
 */
export function middleTruncate(text, max = 24, tail = 8) {
	const value = String(text || "");
	if (value.length <= max) return value;
	const head = Math.max(1, max - tail - 1);
	return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
