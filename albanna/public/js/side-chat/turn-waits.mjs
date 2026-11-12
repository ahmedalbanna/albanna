// Which waits belong to which thread.
//
// A panel waits for the turns of the thread it is showing.  "Which
// thread" sounds like the easy part, and it is the part that is easy to
// get subtly wrong in two ways at once:
//
//   - a turn asked as a reader's *first* question is remembered with no
//     conversation id yet, because the conversation is created by the
//     answer — so "no id" means "the thread being shown", not "no
//     thread";
//   - a turn in another thread must never be treated as this thread's,
//     or its ending clears this thread's Stop button;
//
// and in both the answer is a list, and an empty list is an answer
// ("nothing running here"), not a failure to find something.
//
// Pure: no `frappe`, no DOM, no Vue — so it is tested under plain node,
// which is where a wrong answer here would otherwise only show up as a
// Stop button that vanishes at the wrong moment.

/**
 * The waits of one conversation, newest last.
 *
 * @param {Array<[string, object]>} entries the waits, as the panel keeps
 *   them: `[streamId, {controller, conversation}]`
 * @param {string} conversationId the thread, empty for a reader with no
 *   thread yet — a first question's turn is remembered with no id
 * @returns {Array<{streamId: string, controller: AbortController, conversation: string}>}
 */
export function waitsOfConversation(entries, conversationId) {
	const wanted = conversationId || "";
	return entries
		.filter(([, waiting]) => (waiting.conversation || "") === wanted)
		.map(([streamId, waiting]) => ({ streamId, ...waiting }));
}
