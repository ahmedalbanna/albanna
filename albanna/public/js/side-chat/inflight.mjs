// The turn that is in flight, remembered across a reload.
//
// A reader who reloads the Desk during a turn loses the turn from the
// screen: the worker is still working, and the answer is parked in the
// cache, but the browser forgot the stream it was waiting for.  So the
// stream is written down — in the session's storage, which a reload
// keeps and a closed tab does not — and the panel picks it up again
// when the page comes back.
//
// The entry is per *page*: a turn belongs to the thread of the page it
// was asked on, and re-attaching it on another page would put the
// answer in the wrong thread.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/** Where the turn is written down. */
export const INFLIGHT_KEY = "albanna_inflight_turn";

/** How long a turn may be waited for after a reload. */
export const INFLIGHT_TTL_MS = 4 * 60 * 60 * 1000;

/**
 * The storage the entry is written to.
 *
 * @returns {object|null} the session's storage, or null when there is
 *   none
 */
function sessionStorageOrNull() {
	try {
		return typeof sessionStorage !== "undefined" ? sessionStorage : null;
	} catch (error) {
		// A browser that refuses its own storage is a browser that
		// cannot be asked to remember anything.
		return null;
	}
}

/**
 * Write the turn down.
 *
 * @param {object} entry the turn: `stream_id`, `conversation_id`, `page`
 *   and `question`
 * @param {object} [storage] the storage, for the test
 * @returns {boolean} true when it was written
 */
export function saveInflight(entry, storage) {
	const store = storage || sessionStorageOrNull();
	if (!store || !entry || !entry.stream_id) return false;

	try {
		store.setItem(
			INFLIGHT_KEY,
			JSON.stringify({ ...entry, started_at: entry.started_at || Date.now() }),
		);
		return true;
	} catch (error) {
		/* A storage that refuses is a storage that cannot be asked. */
		return false;
	}
}

/**
 * Read the turn back.
 *
 * An entry that has been there too long is not a turn any more: the
 * worker died, or the answer was never coming, and a reader who comes
 * back an hour later should not be shown a turn that ended long ago.
 *
 * @param {object} [storage] the storage, for the test
 * @returns {object|null} the turn, or null when there is none
 */
export function loadInflight(storage) {
	const store = storage || sessionStorageOrNull();
	if (!store) return null;

	try {
		const raw = store.getItem(INFLIGHT_KEY);
		if (!raw) return null;

		const parsed = JSON.parse(raw);
		if (!parsed || !parsed.stream_id) return null;
		if (parsed.started_at && Date.now() - parsed.started_at > INFLIGHT_TTL_MS) {
			store.removeItem(INFLIGHT_KEY);
			return null;
		}
		return parsed;
	} catch (error) {
		return null;
	}
}

/**
 * Forget the turn.
 *
 * @param {object} [storage] the storage, for the test
 */
export function clearInflight(storage) {
	const store = storage || sessionStorageOrNull();
	if (!store) return;

	try {
		store.removeItem(INFLIGHT_KEY);
	} catch (error) {
		/* Nothing to forget if the storage refuses. */
	}
}
