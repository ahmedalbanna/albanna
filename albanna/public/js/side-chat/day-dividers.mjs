// The day dividers of the transcript.
//
// A thread that ran across several days is one story the reader read over
// several sittings, and the place one sitting ended and the next began is
// worth a line: a hairline with the day on it, before the first message
// of each calendar day.  "Today" and "Yesterday" are words; a day further
// back is a date, because "3 days ago" is arithmetic the reader should
// not have to do.
//
// The day is the *reader's* calendar day: the message carries an epoch,
// and midnight is drawn where the reader's own clock draws it.  The same
// thread opened in another timezone divides at another line — which is
// the point, not a bug.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

import { currentLocale, toDate } from "./format.mjs";

// `__` is Frappe's translator in the browser.  Under node (the tests) it
// is not defined, so a small stand-in keeps the module runnable.
function __(text, args) {
	const fn =
		typeof globalThis !== "undefined" && typeof globalThis.__ === "function"
			? globalThis.__
			: null;
	if (fn) return fn(text, args);
	if (Array.isArray(args)) {
		return String(text).replace(/\{(\d+)\}/g, (_, i) => {
			const value = args[Number(i)];
			return value === undefined || value === null ? "" : String(value);
		});
	}
	return String(text);
}

/**
 * Whether the message at `index` opens a new calendar day.
 *
 * The first message of the transcript opens a divider — the reader should
 * know which day they are reading into even when the day began behind the
 * window, and when the earlier page arrives the divider moves down to the
 * real boundary on its own, because the answer is computed from the
 * messages, not remembered from a render.
 *
 * A message whose moment cannot be read opens nothing: a divider that
 * names no day is noise, and a message that carries no timestamp is
 * usually the turn still being written.
 *
 * @param {object[]} messages the transcript, in order
 * @param {number} index the message's position
 * @returns {boolean} true when a divider belongs above the message
 */
export function isDayStart(messages, index) {
	if (!Array.isArray(messages) || index < 0 || index >= messages.length) return false;
	const day = calendarDay(messages[index]);
	if (!day) return false;
	if (index === 0) return true;
	const previous = calendarDay(messages[index - 1]);
	if (!previous) return false;
	return day !== previous;
}

/**
 * The day a divider names.
 *
 * "Today" and "Yesterday" are translated words — the same catalogue the
 * rest of the panel reads, so an Arabic interface gets "اليوم" and "أمس".
 * A day further back is a date in the reader's language, with the year
 * named only when the day is not in the current year: "Nov 3" and
 * "Nov 3, 2025" both say which day, and the second says it once when it
 * has to.
 *
 * @param {number|string|Date} at the message's moment, epoch seconds or a
 *   timestamp
 * @param {number} [now] the moment to judge it against, epoch
 *   milliseconds — passed by the tests, defaulted to the clock
 * @returns {string} the label, or an empty string when the moment cannot
 *   be read
 */
export function dayLabel(at, now = Date.now()) {
	const date = toDate(at);
	if (!date) return "";

	const days = daysApart(date, new Date(now));
	if (days === 0) return __("Today");
	if (days === 1) return __("Yesterday");

	const thisYear = new Date(now).getFullYear();
	if (date.getFullYear() === thisYear) return dayFormatter().format(date);
	return yearFormatter().format(date);
}

/**
 * The message's calendar day, as a number that compares.
 *
 * Midnight to midnight, in the reader's own zone: the epoch is read into
 * a `Date`, and the hours are cut off.  A message that carries no
 * readable moment has no day.
 *
 * @param {object} message the message
 * @returns {number|null} the day as its local midnight, or null
 */
function calendarDay(message) {
	if (!message) return null;
	const date = toDate(message.at);
	if (!date) return null;
	return startOfDay(date).getTime();
}

/**
 * A moment, cut down to its local midnight.
 *
 * @param {Date} date the moment
 * @returns {Date} the midnight that starts its day
 */
function startOfDay(date) {
	return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/**
 * How many midnights lie between two moments.
 *
 * Counting between midnights is what makes "Yesterday" mean yesterday: a
 * message at 23:59 and the clock at 00:01 are one day apart, and a
 * message an hour ago and the clock the other side of midnight are not
 * "today".  The rounding absorbs the hours a daylight-saving change
 * adds or takes from a day — a 23- or 25-hour day is still one day.
 *
 * @param {Date} date the message's moment
 * @param {Date} now the moment to judge it against
 * @returns {number} the midnights between them
 */
function daysApart(date, now) {
	const from = startOfDay(date).getTime();
	const to = startOfDay(now).getTime();
	return Math.round((to - from) / 86400000);
}

/**
 * The date formatters, by locale.
 *
 * The same rule the clock follows (see `format.mjs`): building an
 * `Intl.DateTimeFormat` resolves the locale's data, and the panel
 * re-renders on every token, so a formatter is built once per locale and
 * kept.
 */
const dayFormatters = new Map();
const yearFormatters = new Map();

function dayFormatter() {
	const locale = currentLocale();
	if (dayFormatters.has(locale)) return dayFormatters.get(locale);
	let formatter = null;
	try {
		formatter = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" });
	} catch {
		formatter = null;
	}
	dayFormatters.set(locale, formatter);
	return formatter;
}

function yearFormatter() {
	const locale = currentLocale();
	if (yearFormatters.has(locale)) return yearFormatters.get(locale);
	let formatter = null;
	try {
		formatter = new Intl.DateTimeFormat(locale, {
			month: "short",
			day: "numeric",
			year: "numeric",
		});
	} catch {
		formatter = null;
	}
	yearFormatters.set(locale, formatter);
	return formatter;
}
