<script setup>
/**
 * Albanna side chat — the assistant panel.
 *
 * Mounted by the launcher into the panel the launcher placed on the page.
 * The launcher owns *whether* the widget exists; this component owns
 * everything inside it.
 *
 * What it does:
 *
 *  - follows the page the user is looking at, so the assistant knows what
 *    "this invoice" means;
 *  - runs a turn through the server, which does the model call and the tool
 *    calls — there is no mock path here, so a caller who may not chat is
 *    refused rather than shown a fabricated answer;
 *  - shows the turn as it happens: the tokens as they arrive, and each tool
 *    call as it starts and finishes.
 *
 * A conversation belongs to a page.  Moving to another page starts another
 * thread, because the context behind the two is different and a thread that
 * spans both would answer the second question with the first one's context.
 *
 * The panel has two views: the transcript, and the list of the caller's
 * conversations.  The list is not a second floating panel — the widget is
 * already a column of the Desk, and a drawer floating over it would be a
 * second floating thing on a page that has one.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import Composer from "./Composer.vue";
import ConversationDrawer from "./ConversationDrawer.vue";
import { pageIdentity, resolveContext } from "./context.mjs";
import { clockTime } from "./format.mjs";
import { hasTable, renderMarkdown, tableAsTsv } from "./markdown.js";
import { watchRoute } from "./page.mjs";
import { addQuestion, renderRecentQuestions } from "./recent-questions.mjs";
import { takeRetryQuestion } from "./retry.mjs";
import { clearInflight, loadInflight, saveInflight } from "./inflight.mjs";
import { mergeOlder, oldestIdx, olderRequest, windowRequest } from "./window.mjs";
import {
	beginTurn,
	canSend,
	canStop,
	clearTranscript,
	dismiss,
	endTurn,
	failTurn,
	initialState,
	isBusy,
	setActivity,
	stopTurn,
} from "./state.mjs";
import { call, runTurn, waitForTurn } from "./turn.mjs";

const props = defineProps({
	/** The options payload, already resolved by the launcher. */
	config: { type: Object, default: () => ({}) },
	/** Called when the user closes the panel from inside it. */
	onClose: { type: Function, default: () => {} },
	/** Called with the page description whenever it changes. */
	onContext: { type: Function, default: () => {} },
});

/**
 * The turn's state.
 *
 * It is a state machine, in `state.mjs`, because the states of a turn
 * are the part of this widget a reader can see being wrong: a turn that
 * is "running" and has already finished, a stop button that stops
 * nothing, an error that hides a message.  The component is a view over
 * it.
 */
const state = reactive(initialState());

const draft = ref("");
const conversationId = ref("");
const transcriptEl = ref(null);
/** What a screen reader is told, once a turn is over. */
const announcement = ref("");
/** Whether the transcript is pinned to the bottom. */
const followBottom = ref(true);
const showScrollButton = ref(false);
/** The message whose answer was just copied, if any. */
const copiedId = ref("");
/** The message whose table was just copied, if any. */
const copiedTableId = ref("");

/** "chat" shows the transcript; "history" shows the list of conversations. */
const view = ref("chat");
const conversations = ref([]);
const historyLoading = ref(false);

let messageCounter = 0;
/** The page's identity, as a ref so that the examples follow the page. */
const currentPage = ref("");

/**
 * Whether older messages are behind the window on the screen.
 *
 * The panel draws a window of the conversation — the newest fifty
 * messages — and the rest is one click away.  The reader's history is
 * not hidden; it is simply not drawn until it is asked for.
 */
const hasOlder = ref(false);

/** Whether the older page is being fetched. */
const loadingOlder = ref(false);

/** The controller of the turn in flight, so that it can be stopped. */
const abortController = ref(null);

/**
 * The questions the reader has asked, oldest first.
 *
 * They are sent with the turn so that a follow-up can be understood as a
 * follow-up: a reader who asks "which orders are open?" and then "and what
 * are they worth?" means the second question to continue the first, and the
 * assistant cannot know that unless it is told.
 *
 * It is not called `asked`, because that is the question *message* — a
 * different thing, and two things with one name in one file is a bug
 * waiting for a quiet afternoon.
 */
const recentQuestions = ref([]);

/** Stops the panel hearing the Desk's route. */
let unwatch = () => {};

const locked = computed(() => props.config.locked === true);
const canChat = computed(() => props.config.chat_access === true && !locked.value);

/** Is a turn in flight? */
const busy = computed(() => isBusy(state));
/** May the reader ask a question? */
const maySend = computed(() => canSend(state) && canChat.value);
/** May the reader stop the turn? */
const mayStop = computed(() => canStop(state) && canChat.value);

/**
 * The document the widget is looking at, if it is looking at one.
 *
 * A *form* is a document, and the document's name and type are known
 * exactly.  A list is a route, and the route's last segment is a slug
 * rather than a name — "erpnext/sales-order" is not "Sales Order" — so
 * a list is not named here.  Better to say nothing than to say a slug.
 */
const openDocument = computed(() => {
	// `currentPage` is read so that this is recomputed when the page
	// changes: `resolveContext` reads globals that Vue cannot see.
	const page = currentPage.value;
	if (!page) return null;

	const context = resolveContext();
	if (!context.doctype || !context.name) return null;
	return { doctype: context.doctype, name: context.name };
});

/**
 * What the empty state says it is asking about.
 *
 * The widget's whole claim is that it knows what page you are looking
 * at, and an empty panel that says nothing about it makes the reader
 * wonder whether it does.
 */
const pageContext = computed(() => {
	const document = openDocument.value;
	if (!document) return "";
	return __("Asking about {0} {1}", [document.doctype, document.name]);
});

/**
 * The questions the empty state offers.
 *
 * With a document open, the questions are about *that* document — a
 * reader with a Sales Order open wants to know about the Sales Order in
 * front of them, not about sales orders in general.  Without one, they
 * are the questions people actually ask of a site.
 *
 * They are asked as questions rather than described, because a suggestion
 * the reader has to translate into a question is a suggestion that costs
 * more than it gives.
 */
const examples = computed(() => {
	const document = openDocument.value;
	if (document) {
		return [
			__("Summarise this {0}", [document.doctype]),
			__("What is the status of this {0}?", [document.doctype]),
			__("What is the total of this {0}?", [document.doctype]),
		];
	}

	return [
		__("Which Sales Orders are still open?"),
		__("What is the total value of open orders?"),
		__("How many customers are there?"),
	];
});

function nextId() {
	messageCounter += 1;
	return `m${messageCounter}`;
}

/**
 * A message, as a reactive object.
 *
 * The messages live in a `ref`, so the array is reactive — but a *plain*
 * object pushed into it is not.  Vue hands the template a proxy of it,
 * and a mutation of the plain object bypasses that proxy, so nothing
 * re-renders.  The tokens would arrive, be appended to an object nobody
 * is watching, and appear all at once when the turn ended and something
 * else changed.  This is why the message is made reactive *before* it is
 * pushed: the streaming is the feature, and it has to be seen.
 */
function makeMessage(role, content, at) {
	const message = reactive({
		id: nextId(),
		role,
		content: "",
		html: "",
		tools: [],
		// The documents the assistant read, each a `{name, url}` pair.  A
		// name in the answer is a link when it is one of these, and only
		// then.
		documents: [],
		pending: false,
		// When it was said, formatted once.  A message the panel is
		// showing now is stamped with the reader's clock; a message from a
		// conversation that was opened comes with the server's.
		//
		// It is formatted *here* and not in the template, because the
		// template renders every message on every change — and a render
		// happens on every token.  Building a date formatter costs half a
		// millisecond, so a formatter per message per token is a
		// millisecond and a half of work per token, for a clock.
		time: "",
		// Whether the answer holds a table that can be taken away.
		hasTable: false,
		// What the turn's tool calls did, in one line.
		summary: "",
	});
	message.time = clockTime(at || Date.now() / 1000);
	setContent(message, content || "");
	return message;
}

/**
 * Set a message's text, and its rendered HTML with it.
 *
 * The HTML is kept on the message rather than rendered in the template
 * because the template renders *every* message on every change.  A token
 * arriving re-renders the panel, and with a conversation of any length
 * that is the whole transcript's markdown, parsed again and again, for
 * one word.  The parsing is the expensive part, so it is done once per
 * message and only for the message that actually changed.
 *
 * @param {object} message the message
 * @param {string} text the new text
 */
function setContent(message, text) {
	message.content = text;
	refresh(message);
}

/**
 * Write everything about a message that is *derived* from it.
 *
 * One place, so that a message cannot be half-updated: the summary was
 * computed when the tool calls changed and nowhere else, so a conversation
 * opened again showed its tool calls with no line above them.
 *
 * @param {object} message the message
 */
function refresh(message) {
	message.html = renderMarkdown(message.content, message.documents);
	// An answer can gain a table as it streams, so this is not a
	// once-and-for-all thing.
	message.hasTable = hasTable(message.content);
	message.summary = toolSummary(message);
}

/**
 * A message the server sent, with the documents its calls looked at.
 *
 * The documents are stored with the tool calls, so that a conversation
 * opened again links to the same documents the answer names — the same
 * links the live answer had.
 *
 * @param {object} message the message, as the server sent it
 * @returns {object} the message, ready to show
 */
function messageFromServer(message) {
	const item = makeMessage(message.role, message.content, message.creation_ts);
	// The row's own name, so that this message can be addressed: a turn
	// is removed by naming it, and a name does not shift when the
	// conversation grows.
	item.name = message.name || "";
	// The stored index, which is how the panel asks for the page of
	// messages behind this one.  A message that has not been stored yet
	// has no index, and it is the newest one.
	item.idx = Number(message.idx) || 0;
	item.tools = message.tools || [];

	for (const tool of item.tools) {
		tool.documents = (tool.documents || []).map(documentLink).filter(Boolean);
	}
	item.documents = item.tools
		.flatMap((tool) => tool.documents || [])
		.filter(
			(document, index, all) =>
				all.findIndex((other) => other.name === document.name) === index,
		);

	setContent(item, item.content);
	return item;
}

/**
 * The Desk's own link to a document.
 *
 * It is the link the Desk's list view makes, so that a name in an answer
 * opens the same thing a name in a list opens.
 *
 * @param {object} document the document, as the server named it
 * @returns {object} the document, with its url
 */
function documentLink(document) {
	const name = String(document.name || "").trim();
	if (!name) return null;

	const doctype = String(document.doctype || "").trim();
	const slug =
		doctype && window.frappe && window.frappe.router
			? window.frappe.router.slug(doctype)
			: doctype.toLowerCase().replace(/ /g, "-");

	return {
		name,
		url: `/app/${encodeURIComponent(slug)}/${encodeURIComponent(name)}`,
	};
}

function scrollToBottom(force = false) {
	// The reader who has scrolled up to read something is not dragged back
	// down by the next token.
	if (!force && !followBottom.value) return;
	nextTick(() => {
		const el = transcriptEl.value;
		if (el) el.scrollTop = el.scrollHeight;
	});
}

function onTranscriptScroll() {
	const el = transcriptEl.value;
	if (!el) return;
	const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
	followBottom.value = atBottom;
	showScrollButton.value = !atBottom && state.messages.length > 0;
}

function jumpToBottom() {
	followBottom.value = true;
	showScrollButton.value = false;
	scrollToBottom(true);
}

function onContextChanged(context) {
	currentPage.value = pageIdentity();
	props.onContext(context);
}

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
function statusLabel(code) {
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
function describeTool(name, toolArguments) {
	const label = toolLabel(name);
	const doctype = String((toolArguments && toolArguments.doctype) || "").trim();
	// What is being looked at, not only how: "Searching Sales Order" tells
	// the reader the question is being answered against the right thing.
	if (!doctype) return label;
	return `${label} ${doctype}`;
}

function toolLabel(name) {
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
function toolSummary(message) {
	const tools = message.tools || [];
	if (!tools.length) return "";
	const distinct = new Set(tools.map((tool) => tool.name)).size;
	return __("Tools used: {0} · Calls: {1}", [distinct, tools.length]);
}

/**
 * When a message was said.
 *
 * @param {object} message the message
 * @returns {string} the time of day
 */
/**
 * The notices the panel can show, in the reader's language.
 *
 * The state holds a *key*, not a sentence: the state machine is pure and
 * has no language of its own, and the reader's language can change under
 * a notice that was already shown.
 *
 * @param {string} notice the key
 * @returns {string} the sentence
 */
function noticeText(notice) {
	switch (notice) {
		case "stopped":
			return __("Stopped.");
		case "moved":
			return __("You moved to another page, so the turn was stopped.");
		case "no-table":
			return __("There is no table to copy.");
		case "copy-failed":
			return __("The table could not be copied.");
		case "deleted":
			return __("The conversation was deleted.");
		case "started":
			return __("A new conversation was started.");
		case "removed":
			return __("The question and its answer were removed.");
		default:
			return "";
	}
}

/**
 * Pick up a turn that was running when the page was reloaded.
 *
 * The worker is still working and the answer is parked in the cache;
 * all that was lost is the browser's memory of the stream.  So the
 * stream is read back and the turn is waited for again.
 *
 * The turn belongs to the thread of the page it was asked on, so it is
 * only picked up on that page.
 */
async function resumeInflight() {
	const entry = loadInflight();
	if (!entry || !entry.stream_id) return;

	if (entry.page && entry.page !== currentPage.value) {
		// The turn belongs to another page's thread, and this panel is
		// about this one.
		clearInflight();
		return;
	}

	const question = String(entry.question || "");
	const asked = makeMessage("user", question);
	const answer = makeMessage("assistant", "");
	answer.pending = true;

	beginTurn(state, question, asked, answer);
	setActivity(state, __("Thinking"));
	scrollToBottom(true);

	const controller = new AbortController();
	abortController.value = controller;

	try {
		const result = await waitForTurn(entry.stream_id, {
			signal: controller.signal,
			onEvent: (event) => handleTurnEvent(answer, event),
		});
		applyTurnResult(result, asked, answer);
	} catch (failure) {
		failTurn(state, answer, String((failure && failure.message) || failure));
		removeMessage(answer);
	} finally {
		clearInflight();
	}
}

/**
 * Show what a turn is doing, as it does it.
 *
 * @param {object} answer the answer message
 * @param {object} event the progress event
 */
function handleTurnEvent(answer, event) {
	if (event.event === "token") {
		setContent(answer, answer.content + event.text);
		scrollToBottom();
		return;
	}
	if (event.event === "tool_start") {
		answer.tools.push({ name: event.name, ok: null, summary: "" });
		refresh(answer);
		setActivity(state, describeTool(event.name, event.arguments));
		scrollToBottom();
		return;
	}
	if (event.event === "tool_done") {
		const pending = answer.tools.find((tool) => tool.ok === null && tool.name === event.name);
		if (pending) {
			pending.ok = event.ok !== false;
			pending.summary = event.summary || "";
		}
		refresh(answer);

		// The documents the call looked at.  They become links in the
		// answer, so that the answer is a doorway into the Desk and not
		// only a description of it.
		const documents = (event.documents || []).map(documentLink).filter(Boolean);
		if (documents.length) {
			const known = new Set(answer.documents.map((entry) => entry.name));
			const fresh = documents.filter((entry) => !known.has(entry.name));
			if (fresh.length) {
				answer.documents.push(...fresh);
				// The answer may already have streamed past a name that
				// is only now known, so the text is rendered again.
				setContent(answer, answer.content);
			}
		}
		scrollToBottom();
		return;
	}
	if (event.event === "status") {
		setActivity(state, statusLabel(event.code) || event.text || state.activity);
	}
}

/**
 * Show how a turn ended.
 *
 * @param {object} result the turn's final payload
 * @param {object} asked the question message
 * @param {object} answer the answer message
 */
function applyTurnResult(result, asked, answer) {
	if (result && result.conversation_id) {
		conversationId.value = result.conversation_id;
	}

	// The server says which rows it wrote, so that the question and the
	// answer can be addressed later — a turn the reader wants gone is
	// removed by naming it.
	if (result && result.written && result.written.length) {
		for (const row of result.written) {
			if (row.role === "user") asked.name = row.name;
			if (row.role === "assistant") answer.name = row.name;
		}
	}

	if (result && result.status === "aborted") {
		// The turn was stopped at the reader's request.  Whatever
		// arrived is kept — it is the truth so far — and the worker
		// finishes on its own, so the answer is in the conversation
		// when they come back to it.
		stopTurn(state, answer);
		// A notice that is already there is more specific than this one
		// — "you moved to another page" says more than "stopped".
		if (!state.notice) state.notice = "stopped";
	} else if (result && result.status === "error") {
		failTurn(state, answer, result.error || __("Something went wrong."));
		if (!answer.content) {
			removeMessage(answer);
		}
	} else if (result && result.reply) {
		// The server's answer is the truth.  The streamed text was the
		// live preview, and a preview that lost a fragment is worse than
		// no preview: it is a wrong answer that looks complete.
		setContent(answer, result.reply);
		endTurn(state, answer);
	} else {
		// A turn that ended without an answer and without an error is
		// still over.
		failTurn(state, answer, __("Something went wrong."));
	}

	if (answer.content) {
		announcement.value = answer.content;
	}
}

/**
 * Ask a question, starting a turn.
 *
 * @param {string} question the question
 */
async function send(question) {
	const text = String(question || draft.value || "").trim();
	if (!text || !maySend.value) return;

	draft.value = "";
	followBottom.value = true;
	showScrollButton.value = false;

	const asked = makeMessage("user", text);
	const answer = makeMessage("assistant", "");
	answer.pending = true;

	beginTurn(state, text, asked, answer);
	setActivity(state, __("Thinking"));
	scrollToBottom(true);

	/* The page is read *now*, not from a cache.
	 *
	 * The panel keeps the page it is showing, but the question is being
	 * asked about the page the reader is looking at at this moment.  A
	 * cached page is a cache; the context is a fact, and a fact is read
	 * when it is needed.  So a route event that was missed costs the
	 * panel its label and not the assistant its question. */
	const context = resolveContext();
	const page = pageIdentity();

	/* The questions asked *before* this one.
	 *
	 * The current question is the question, and repeating it in the
	 * context would take the room that the questions before it need.  So
	 * the list is rendered first and the question is added to it after. */
	const recent = renderRecentQuestions(recentQuestions.value);
	recentQuestions.value = addQuestion(recentQuestions.value, text);

	const controller = new AbortController();
	abortController.value = controller;

	try {
		const result = await runTurn({
			question: text,
			conversationId: conversationId.value,
			page: page,
			pageContext: {
				route: context.route,
				view: context.view,
				doctype: context.doctype,
				name: context.name,
				title: context.title,
				// The list the reader is looking at: the filters they
				// applied and the rows the list shows.  Without them the
				// assistant answers about the whole table rather than
				// about the table on the screen.
				filters: context.filters,
				rows: context.rows,
				selection: context.selection,
				// What the reader has asked lately, so that a follow-up
				// reads as a follow-up.
				recent_questions: recent,
			},
			signal: controller.signal,
			onEvent: (event) => handleTurnEvent(answer, event),
			// The turn's address on the server, written down so that a
			// reader who reloads during the turn finds it again.
			onQueued: (streamId) => {
				saveInflight({
					stream_id: streamId,
					conversation_id: conversationId.value,
					page,
					question: text,
				});
			},
		});

		applyTurnResult(result, asked, answer);
	} catch (failure) {
		failTurn(
			state,
			answer,
			String((failure && failure.message) || failure || __("Something went wrong.")),
		);
		removeMessage(answer);
	} finally {
		answer.pending = false;
		abortController.value = null;
		clearInflight();
		scrollToBottom();
	}
}

/**
 * Show the page of messages behind the window.
 *
 * The reader asked for the older messages, so the older messages are
 * what they get to see — and the view stays where it was, because the
 * content that was on screen has moved down by the height of the page
 * that was added above it.
 */
async function loadEarlier() {
	if (loadingOlder.value || !hasOlder.value || !conversationId.value) return;
	loadingOlder.value = true;

	const el = transcriptEl.value;
	const before = el ? el.scrollHeight : 0;

	try {
		const result = await call("albanna.api.conversations.open_conversation", {
			conversation: conversationId.value,
			...olderRequest(oldestIdx(state.messages)),
		});
		const older = (result.messages || []).map((message) => messageFromServer(message));
		state.messages = mergeOlder(state.messages, older);
		hasOlder.value = !!(result && result.has_more);

		// The messages that were on screen have moved down; the scroll
		// moves with them, so the reader is looking at the same thing.
		await nextTick();
		if (el) el.scrollTop += el.scrollHeight - before;
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not load the earlier messages."),
		);
	} finally {
		loadingOlder.value = false;
	}
}

/**
 * Remember the questions of a thread that was just opened.
 *
 * They are the reader's recent questions — the ones that explain the
 * question they are about to ask — and a thread that was opened a moment
 * ago is still the thread the reader is in.
 *
 * @param {object[]} messages the loaded messages
 */
function rememberQuestions(messages) {
	const questions = (messages || [])
		.filter((message) => message.role === "user")
		.map((message) => message.content);
	recentQuestions.value = questions.reduce((list, question) => addQuestion(list, question), []);
}

/**
 * Take a message out of the transcript.
 *
 * @param {object} message the message
 */
function removeMessage(message) {
	const index = state.messages.findIndex((entry) => entry.id === message.id);
	if (index >= 0) state.messages.splice(index, 1);
}

/**
 * Stop the turn in flight.
 *
 * The turn is not cancelled on the server — the worker finishes it, and the
 * answer it produces is kept in the conversation.  What is stopped is the
 * *waiting*: a reader who has decided they do not want the answer any more
 * should not have to watch the rest of it arrive.
 */
function stop() {
	if (!mayStop.value || !abortController.value) return;
	abortController.value.abort();
}

function retry() {
	const question = state.asked;
	if (!question) return;

	// The failed attempt goes, whole: the question that failed and the
	// answer that failed with it.  A retry is one attempt, not two, and a
	// transcript that shows the same question twice leaves the reader
	// looking at two answers and not knowing which one is the answer.
	takeRetryQuestion(state.messages, question);
	send(question);
}

/**
 * Ask one of the suggestions.
 *
 * @param {string} question the suggestion
 */
function ask(question) {
	if (busy.value || !canChat.value) return;
	send(question);
}

/**
 * Copy the table in an answer, as data.
 *
 * A table in an answer is data, and data goes into a spreadsheet.  The
 * tabs are what a spreadsheet expects, so the paste lands as a table and
 * not as a column of text.
 *
 * @param {object} message the message
 */
async function copyTable(message) {
	const text = tableAsTsv(message.content);
	if (!text) {
		state.notice = "no-table";
		return;
	}
	try {
		await navigator.clipboard.writeText(text);
		copiedTableId.value = message.id;
		window.setTimeout(() => {
			if (copiedTableId.value === message.id) copiedTableId.value = "";
		}, 1600);
	} catch (failure) {
		state.notice = "copy-failed";
	}
}

/**
 * Copy an answer.
 *
 * @param {object} message the message
 */
async function copyAnswer(message) {
	const text = message.content || "";
	if (!text) return;
	try {
		await navigator.clipboard.writeText(text);
		copiedId.value = message.id;
		window.setTimeout(() => {
			if (copiedId.value === message.id) copiedId.value = "";
		}, 1600);
	} catch (failure) {
		state.notice = "copy-failed";
	}
}

// -- the conversation list ------------------------------------------------

async function showHistory() {
	view.value = "history";
	historyLoading.value = true;
	try {
		const result = await call("albanna.api.conversations.list_conversations", {});
		conversations.value = result.conversations || [];
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not load the conversations."),
		);
	} finally {
		historyLoading.value = false;
	}
}

function showTranscript() {
	view.value = "chat";
}

/**
 * Open a conversation.
 *
 * @param {object} conversation the conversation
 */
async function openConversation(conversation) {
	state.error = "";
	try {
		const result = await call("albanna.api.conversations.open_conversation", {
			conversation: conversation.name,
			...windowRequest(),
		});
		conversationId.value = conversation.name;
		state.messages = (result.messages || []).map((message) => {
			return messageFromServer(message);
		});
		rememberQuestions(state.messages);
		hasOlder.value = !!(result && result.has_more);
		view.value = "chat";
		followBottom.value = true;
		scrollToBottom(true);
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not open that conversation."),
		);
	}
}

/**
 * Rename a conversation.
 *
 * @param {string} name the conversation
 * @param {string} title the new title
 */
async function renameConversation(name, title) {
	try {
		await call("albanna.api.conversations.rename_conversation", { conversation: name, title });
		const item = conversations.value.find((conversation) => conversation.name === name);
		if (item) item.title = title;
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not rename that conversation."),
		);
	}
}

/**
 * Remove a turn: the question asked, and the answer that followed it.
 *
 * A turn is two rows and they go together — an answer with no question is
 * not a conversation — so the question is what the reader points at.
 *
 * The reader is asked first.  A thread cannot be recovered, and one click
 * is not a decision.
 *
 * @param {object} message the question
 */
function removeTurn(message) {
	if (!message || !message.name) return;

	const question = __("Remove this question and the answer it brought?");
	const confirm = window.frappe && window.frappe.confirm;
	if (typeof confirm === "function") {
		confirm(question, () => deleteTurn(message));
		return;
	}
	if (window.confirm(question)) {
		deleteTurn(message);
	}
}

/**
 * Remove a turn from the conversation.
 *
 * The server answers with the transcript as it is now, because a removal
 * moves everything after it: the reader should not have to ask twice to
 * find out what the thread looks like.
 *
 * @param {object} message the question
 */
async function deleteTurn(message) {
	try {
		const result = await call("albanna.api.conversations.delete_turn", {
			conversation: conversationId.value,
			message: message.name,
		});
		const rows = (result && result.messages) || [];
		state.messages = rows.map(messageFromServer);
		hasOlder.value = !!(result && result.has_more);
		state.notice = "removed";
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Something went wrong."),
		);
	}
}

/**
 * Delete a conversation, after asking.
 *
 * A conversation is a thread of questions and answers that cannot be
 * recovered, and the button that deletes it is a small icon next to a
 * list of things the reader may want to keep.  One click is not a decision.
 *
 * @param {object} conversation the conversation
 */
function removeConversation(conversation) {
	const title = conversation.title || __("New conversation");
	const message = __("Delete the conversation “{0}”? This cannot be undone.", [title]);

	const confirm = window.frappe && window.frappe.confirm;
	if (typeof confirm === "function") {
		confirm(message, () => deleteConversation(conversation));
		return;
	}
	if (window.confirm(message)) {
		deleteConversation(conversation);
	}
}

/**
 * Delete a conversation.
 *
 * @param {object} conversation the conversation
 */
async function deleteConversation(conversation) {
	try {
		await call("albanna.api.conversations.delete_conversation", {
			conversation: conversation.name,
		});
		conversations.value = conversations.value.filter((item) => item.name !== conversation.name);
		if (conversationId.value === conversation.name) {
			// The panel is emptied, and no new conversation is made: the
			// next question starts one, and a conversation made here and
			// never used is an empty row in the drawer's list.
			conversationId.value = "";
			state.messages = [];
			view.value = "chat";
			state.notice = "deleted";
		}
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not delete that conversation."),
		);
	}
}

/**
 * Start a new conversation on this page.
 *
 * The server is asked for it, because a "new" conversation that only
 * existed in the browser would be the old one: the server resolves a
 * page's conversation by page, so a turn with no conversation id lands
 * back in the thread the reader was trying to leave.
 */
async function newConversation() {
	state.error = "";
	try {
		const result = await call("albanna.api.conversations.new_conversation", {
			page: currentPage.value,
		});
		conversationId.value = result.conversation || "";
		state.messages = [];
		recentQuestions.value = [];
		view.value = "chat";
		state.notice = "started";
		scrollToBottom(true);
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not start a new conversation."),
		);
	}
}

/**
 * Load the page's thread into the panel.
 *
 * The server resolves a page's conversation *by page*, so the thread the
 * assistant will answer in is the page's thread.  A panel that showed an
 * empty transcript on a page with a thread on it would be telling the
 * reader one thing and the assistant another — and the reader would not
 * know which of them was right.
 *
 * A page with no thread is a page with nothing to show, which is an
 * answer and not a failure.
 */
async function loadPageConversation() {
	const page = currentPage.value;
	try {
		const result = await call("albanna.api.conversations.conversation_for_page", {
			page,
			...windowRequest(),
		});
		// The page may have changed while the answer was in flight.
		if (!result || page !== currentPage.value) return;

		if (!result.conversation) {
			state.messages = [];
			conversationId.value = "";
			hasOlder.value = false;
			return;
		}

		conversationId.value = result.conversation;
		state.messages = (result.messages || []).map((message) => {
			return messageFromServer(message);
		});
		rememberQuestions(state.messages);
		hasOlder.value = !!(result && result.has_more);
		followBottom.value = true;
		scrollToBottom(true);
	} catch (failure) {
		// The panel still works without it: the reader can ask, and the
		// answer will join whatever thread the server picks.
	}
}

/**
 * The reader has moved to another page.
 *
 * A different page is a different thread.  The transcript is cleared
 * rather than kept, because an answer about the previous page would be
 * read as an answer about this one.
 *
 * A turn in flight is stopped with it.  The answer would be about the
 * page the reader has just left, and it belongs to that page's thread —
 * so the work goes on where it belongs, and the panel says what it did.
 */
function onRouteChange() {
	const context = resolveContext();
	const identity = pageIdentity();
	if (identity === currentPage.value) return;

	const stopped = clearTranscript(state);
	if (stopped) {
		state.notice = "moved";
		if (abortController.value) abortController.value.abort();
	}

	conversationId.value = "";
	currentPage.value = identity;
	props.onContext(context);
	loadPageConversation();
}

onMounted(() => {
	const context = resolveContext();
	onContextChanged(context);

	// The page's thread first, and then any turn that was running when
	// this page was last loaded: the question of a turn that is still in
	// flight is not stored yet, so it has to be put back on top of the
	// thread it belongs to.
	loadPageConversation().then(() => resumeInflight());

	// The Desk says the page changed with "change".  It does not say it
	// with "route-change" — that event does not exist — and a listener
	// for an event that never fires is a listener that never fires.
	// `page.mjs` holds the name, and `page.test.mjs` holds it to account.
	unwatch = watchRoute(onRouteChange);
});

onBeforeUnmount(() => {
	// A turn in flight is left to finish on the server, but this panel is
	// no longer waiting for it.
	if (abortController.value) abortController.value.abort();

	if (unwatch) unwatch();
});
</script>

<template>
	<div class="albanna-chat">
		<header class="albanna-chat__header">
			<div class="albanna-chat__heading">
				<span class="albanna-chat__title">{{
					view === "history" ? __("Conversations") : __("Albanna")
				}}</span>
				<span class="albanna-chat__subtitle">{{
					view === "history"
						? __("Your questions and answers")
						: __("Ask about this site")
				}}</span>
			</div>

			<div class="albanna-chat__actions">
				<button
					v-if="view === 'history'"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Back to the conversation')"
					:title="__('Back to the conversation')"
					@click="showTranscript"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M19 12H5m0 0 6-6m-6 6 6 6"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>

				<!-- A new conversation is one click away in both views.  A
				     reader in the middle of a thread who wants a fresh one
				     should not have to go through the list to get it.
				     It is an icon like the two beside it, so that the
				     header is three quiet buttons and not a form.
				     And it is a *plus*, and not a pencil: the pencil is
				     what the list uses for renaming, and one glyph must
				     not mean two things. -->
				<button
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('New conversation')"
					:title="__('New conversation')"
					@click="newConversation"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M12 5v14M5 12h14"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
						/>
					</svg>
				</button>

				<button
					v-if="view === 'chat'"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Conversations')"
					:title="__('Conversations')"
					@click="showHistory"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M3 12a9 9 0 1 0 3-6.7L3 8m0-5v5h5"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
						<path
							d="M12 8v4l3 2"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>

				<button
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Close')"
					:title="__('Close')"
					@click="props.onClose"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M18 6 6 18M6 6l12 12"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
						/>
					</svg>
				</button>
			</div>
		</header>

		<div v-if="locked" class="albanna-chat__locked">
			<p class="albanna-chat__locked-title">
				{{ __("The assistant is not available for your account") }}
			</p>
			<p class="albanna-chat__locked-detail">
				{{
					__(
						"Ask an administrator to add your role to the chat roles in Albanna Settings.",
					)
				}}
			</p>
		</div>

		<ConversationDrawer
			v-else-if="view === 'history'"
			:conversations="conversations"
			:loading="historyLoading"
			:active="conversationId"
			@open="openConversation"
			@rename="renameConversation"
			@remove="removeConversation"
			@back="showTranscript"
		/>

		<div v-else class="albanna-chat__body">
			<!-- The older messages are behind the window, and they are one
			     click away.  The button is *outside* the transcript on
			     purpose: a button inside it would be scrolled into view
			     when the reader clicked it, and the reader would lose
			     their place in the thread they were reading. -->
			<button
				v-if="hasOlder"
				type="button"
				class="albanna-chat__earlier"
				:disabled="loadingOlder"
				@click="loadEarlier"
			>
				{{ loadingOlder ? __("Loading…") : __("Show the earlier messages") }}
			</button>
			<div
				ref="transcriptEl"
				class="albanna-chat__transcript"
				role="log"
				aria-live="off"
				@scroll="onTranscriptScroll"
			>
				<div v-if="!state.messages.length" class="albanna-chat__empty">
					<p class="albanna-chat__empty-title">
						{{ __("Ask a question about this site") }}
					</p>
					<p v-if="pageContext" class="albanna-chat__empty-context">
						{{ pageContext }}
					</p>
					<div class="albanna-chat__examples">
						<button
							v-for="example in examples"
							:key="example"
							type="button"
							class="albanna-chat__example"
							@click="ask(example)"
						>
							{{ example }}
						</button>
					</div>
				</div>

				<div
					v-for="message in state.messages"
					:key="message.id"
					class="albanna-chat__message"
					:class="`albanna-chat__message--${message.role}`"
				>
					<!-- While the turn runs: one line saying what is happening.
					     Afterwards: one line saying what it did, which opens
					     into the list of calls. -->
					<div v-if="message.pending" class="albanna-chat__activity" role="status">
						<span class="albanna-chat__spinner" aria-hidden="true"></span>
						<span class="albanna-chat__activity-text">{{ state.activity }}</span>
					</div>

					<details
						v-else-if="message.tools && message.tools.length"
						class="albanna-chat__tools"
					>
						<summary class="albanna-chat__tools-summary">
							{{ message.summary }}
						</summary>
						<ul class="albanna-chat__tools-list">
							<li
								v-for="(tool, index) in message.tools"
								:key="index"
								class="albanna-chat__tool"
								:class="{ 'albanna-chat__tool--failed': tool.ok === false }"
							>
								<span class="albanna-chat__tool-label">{{
									toolLabel(tool.name)
								}}</span>
								<span class="albanna-chat__tool-name">{{ tool.name }}</span>
								<span v-if="tool.summary" class="albanna-chat__tool-summary">{{
									tool.summary
								}}</span>
								<span v-if="tool.ok === false" class="albanna-chat__tool-failed">
									{{ __("failed") }}
								</span>
							</li>
						</ul>
					</details>

					<!-- The user's own words are shown literally: `{{ }}` escapes
					     them, and a user who types `**` meant a literal `**`. -->
					<div
						v-if="message.role === 'user' && message.content"
						class="albanna-chat__bubble albanna-chat__bubble--plain"
					>
						{{ message.content }}
					</div>
					<!-- The assistant's answer is markdown.  `renderMarkdown`
					     escapes before it builds any markup, so this is safe. -->
					<div
						v-else-if="message.content"
						class="albanna-chat__bubble"
						v-html="message.html"
					></div>

					<div class="albanna-chat__footer">
						<button
							v-if="message.role === 'assistant' && message.content"
							type="button"
							class="albanna-chat__copy"
							:aria-label="__('Copy the answer')"
							:title="__('Copy the answer')"
							@click="copyAnswer(message)"
						>
							<svg
								v-if="copiedId !== message.id"
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								aria-hidden="true"
							>
								<rect
									x="9"
									y="9"
									width="12"
									height="12"
									rx="2"
									stroke="currentColor"
									stroke-width="1.8"
								/>
								<path
									d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"
									stroke="currentColor"
									stroke-width="1.8"
									stroke-linecap="round"
								/>
							</svg>
							<svg
								v-else
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								aria-hidden="true"
							>
								<path
									d="m5 13 4 4L19 7"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
								/>
							</svg>
						</button>
						<button
							v-if="message.role === 'assistant' && message.hasTable"
							type="button"
							class="albanna-chat__copy albanna-chat__copy--table"
							:aria-label="__('Copy the table')"
							:title="__('Copy the table')"
							@click="copyTable(message)"
						>
							{{ copiedTableId === message.id ? __("Copied") : __("Copy table") }}
						</button>
						<button
							v-if="message.role === 'user' && message.name"
							type="button"
							class="albanna-chat__remove"
							:aria-label="__('Remove this turn')"
							:title="__('Remove this turn')"
							@click="removeTurn(message)"
						>
							<svg
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								aria-hidden="true"
							>
								<path
									d="M18 6 6 18M6 6l12 12"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
								/>
							</svg>
						</button>
						<span class="albanna-chat__time">{{ message.time }}</span>
					</div>
				</div>
			</div>

			<button
				v-if="showScrollButton"
				type="button"
				class="albanna-chat__scroll-bottom"
				:aria-label="__('Jump to the latest')"
				:title="__('Jump to the latest')"
				@click="jumpToBottom"
			>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M12 5v14m0 0 6-6m-6 6-6-6"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
				</svg>
			</button>
		</div>

		<!-- The transcript is not a live region: it changes on every token,
		     and a live region that changes that often re-announces the whole
		     answer, again and again.  The answer is announced once, here,
		     when the turn is over. -->
		<p class="albanna-chat__announce" role="status" aria-live="polite">
			{{ announcement }}
		</p>

		<div v-if="state.error" class="albanna-chat__error" role="alert">
			<span class="albanna-chat__error-text">{{ state.error }}</span>
			<button v-if="state.asked" type="button" class="albanna-chat__retry" @click="retry">
				{{ __("Try again") }}
			</button>
			<button
				type="button"
				class="albanna-chat__dismiss"
				:aria-label="__('Dismiss')"
				:title="__('Dismiss')"
				@click="dismiss(state, 'error')"
			>
				<svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M18 6 6 18M6 6l12 12"
						stroke="currentColor"
						stroke-width="2.2"
						stroke-linecap="round"
					/>
				</svg>
			</button>
		</div>

		<!-- The notice is not the error's else-branch: a notice that is
		     hidden by an error is a notice the reader never sees. -->
		<div v-if="state.notice" class="albanna-chat__notice">
			<span class="albanna-chat__notice-text">{{ noticeText(state.notice) }}</span>
			<button
				type="button"
				class="albanna-chat__dismiss"
				:aria-label="__('Dismiss')"
				:title="__('Dismiss')"
				@click="dismiss(state, 'notice')"
			>
				<svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M18 6 6 18M6 6l12 12"
						stroke="currentColor"
						stroke-width="2.2"
						stroke-linecap="round"
					/>
				</svg>
			</button>
		</div>

		<Composer
			v-if="view === 'chat' && !locked"
			v-model="draft"
			:busy="busy"
			:can-chat="canChat"
			@send="send"
			@stop="stop"
		/>
	</div>
</template>
