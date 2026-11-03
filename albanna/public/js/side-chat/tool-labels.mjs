// What a tool call is called, in the reader's language.
//
// The transcript shows a tool call as it happens: a line that says what
// the assistant is doing, and a summary at the end that says what it did.
// Both are *labels*, and a label is the reader's business — the tool's
// own name (`list_docs`, `run_report`) is the model's name for it, and it
// is available on demand rather than on the face of the conversation.
//
// This was the panel's own logic until it was tested.  A label that
// reads "Working" for a tool the manifest knows by another name is a
// label nobody notices being wrong, which is the kind that stays wrong;
// and the panel also carries the notices it shows, which are the same
// problem in a longer list.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.  The
// language comes from the page's `__`, as everywhere else in the widget.

/**
 * The status the turn is in, in the reader's language.
 *
 * The server sends a *code*, not a sentence: the turn runs in a worker, and
 * a worker has no user's language to render a label in.  Only the reader
 * has one.
 *
 * @param {string} code the status code
 * @returns {string} the label
 */
export function statusLabel(code) {
	if (code === "thinking") return __("Thinking");
	return "";
}

/**
 * What a tool call is called, in the reader's language.
 *
 * The tool's *name* — `list_docs`, `run_report` — is the model's name for
 * it, and it is not the reader's.  A person wants to know that the
 * assistant is looking something up, not which function it reached for.
 * The name is still available, on demand, in the summary under the
 * answer.
 *
 * @param {string} name the tool's name
 * @returns {string} the label
 */
export function toolLabel(name) {
	switch (name) {
		case "list_docs":
			return __("Searching");
		case "get_doc":
			return __("Reading");
		case "get_doctype_meta":
			return __("Checking fields");
		case "run_report":
			return __("Running a report");
		case "create_doc":
			return __("Creating");
		default:
			return __("Working");
	}
}

/**
 * The label, with what it is being done to.
 *
 * What is being looked at, not only how: "Searching Sales Order" tells
 * the reader the question is being answered against the right thing.
 *
 * @param {string} name the tool's name
 * @param {object} toolArguments the arguments the model called it with
 * @returns {string} the label
 */
export function describeTool(name, toolArguments) {
	const label = toolLabel(name);
	const doctype = String((toolArguments && toolArguments.doctype) || "").trim();
	if (!doctype) return label;
	return `${label} ${doctype}`;
}

/**
 * The one line that says what the turn did.
 *
 * The count is of *distinct* tools and of *calls*, because "3 tools" and
 * "7 calls" are different questions and the reader may want either.  The
 * model's own names are behind the disclosure, for the reader who wants
 * them.
 *
 * @param {object} message the message
 * @returns {string} the summary
 */
export function toolSummary(message) {
	const tools = (message && message.tools) || [];
	if (!tools.length) return "";
	const distinct = new Set(tools.map((tool) => tool.name)).size;
	return __("Tools used: {0} · Calls: {1}", [distinct, tools.length]);
}
