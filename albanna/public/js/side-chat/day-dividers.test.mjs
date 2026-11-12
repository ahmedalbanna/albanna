// The day dividers of the transcript.
//
// The rule under test: a divider stands before the first message of each
// calendar day, read on the reader's own clock, and names the day —
// "Today", "Yesterday", or the date, with the year only when the day is
// not in this one.  A message whose moment cannot be read opens nothing.

import assert from "node:assert";
import { dayLabel, isDayStart } from "./day-dividers.mjs";

global.__ = (text) => text;

// A local timestamp: midnight arithmetic is the rule under test, so the
// tests build their moments with the local constructors and pass in any
// timezone the machine has.
function at(year, month, day, hour = 12, minute = 0) {
	return new Date(year, month - 1, day, hour, minute).getTime() / 1000;
}

function message(epochSeconds) {
	return { at: epochSeconds };
}

// The first message of the transcript opens a divider.
{
	assert.equal(isDayStart([message(at(2026, 11, 12))], 0), true);
}

// A day further back opens the window's first message too — the day may
// have begun behind the window, and the divider moves down when the
// earlier page arrives.
{
	const messages = [message(at(2026, 11, 10)), message(at(2026, 11, 12))];
	assert.equal(isDayStart(messages, 0), true);
}

// Messages of the same day open nothing.
{
	const messages = [
		message(at(2026, 11, 12, 9)),
		message(at(2026, 11, 12, 10)),
		message(at(2026, 11, 12, 23, 59)),
	];
	assert.equal(isDayStart(messages, 1), false);
	assert.equal(isDayStart(messages, 2), false);
}

// The midnight boundary is the divider: 23:59 and 00:01 are neighbours
// one day apart.
{
	const messages = [message(at(2026, 11, 11, 23, 59)), message(at(2026, 11, 12, 0, 1))];
	assert.equal(isDayStart(messages, 0), true);
	assert.equal(isDayStart(messages, 1), true);
}

// A daylight-saving day is still one day: the hours it lost or gained do
// not make a second midnight.
{
	// 2026-10-25 is the day several European zones put their clocks back.
	const messages = [message(at(2026, 10, 25, 1)), message(at(2026, 10, 26, 1))];
	assert.equal(isDayStart(messages, 1), true);
}

// A message that carries no readable moment opens nothing.
{
	const messages = [message(at(2026, 11, 12)), { at: 0 }, message(at(2026, 11, 12, 15))];
	assert.equal(isDayStart(messages, 1), false);
	assert.equal(isDayStart(messages, 2), false);
}

// Neither does a message whose neighbour has none — a gap in the
// timestamps is not a day boundary anybody can name.
{
	const messages = [{ at: 0 }, message(at(2026, 11, 12))];
	assert.equal(isDayStart(messages, 1), false);
}

// And the guard rails: no transcript, an index past either end.
{
	assert.equal(isDayStart([], 0), false);
	assert.equal(isDayStart([message(at(2026, 11, 12))], -1), false);
	assert.equal(isDayStart([message(at(2026, 11, 12))], 1), false);
	assert.equal(isDayStart(null, 0), false);
}

const NOW = at(2026, 11, 12, 15).valueOf() * 1000;

// Today, whichever hour it is.
{
	assert.equal(dayLabel(at(2026, 11, 12, 0, 1), NOW.valueOf()), "Today");
	assert.equal(dayLabel(at(2026, 11, 12, 23, 59), NOW.valueOf()), "Today");
}

// Yesterday, by the midnight between, not by the hours.
{
	assert.equal(dayLabel(at(2026, 11, 11, 23, 59), NOW.valueOf()), "Yesterday");
	assert.equal(dayLabel(at(2026, 11, 11, 0, 1), NOW.valueOf()), "Yesterday");
}

// A day further back, in this year, is the date without the year.
{
	assert.equal(dayLabel(at(2026, 3, 5), NOW.valueOf()), "Mar 5");
}

// And in an earlier year, the date with it.
{
	assert.equal(dayLabel(at(2025, 3, 5), NOW.valueOf()), "Mar 5, 2025");
}

// A moment that cannot be read names nothing.
{
	assert.equal(dayLabel(0, NOW.valueOf()), "");
	assert.equal(dayLabel(null, NOW.valueOf()), "");
}

console.log("day-dividers: all assertions passed");
