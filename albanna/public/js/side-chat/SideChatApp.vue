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
 *
 * Where things live
 * -----------------
 *
 * The pure, tested logic is deliberately out of this file; what stays
 * here is state, wiring and DOM.  Each concern has its module:
 *
 *  - ``approval.mjs``     — the approval window: is the card decided, expired,
 *                           how long is left (and the same window everywhere);
 *  - ``export.mjs``       — the transcript as a Markdown file;
 *  - ``inflight.mjs``     — a turn in flight across a page reload;
 *  - ``window.mjs``       — which slice of the transcript is shown, older pages;
 *  - ``markdown.js``      — answer rendering, tables, copy formats;
 *  - ``context.mjs``      — the page's identity and its resolvable names;
 *  - ``examples.mjs``     — the empty-state suggestions, per page;
 *  - ``recent-questions.mjs``, ``retry.mjs``, ``page.mjs``, ``format.mjs``
 *                         — recent asks, the retried question, route
 *                           watching, clocks.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowReactive, watch } from "vue";
import Composer from "./Composer.vue";
import ConversationDrawer from "./ConversationDrawer.vue";
import { pageIdentity, resolveContext } from "./context.mjs";
import { exampleSet, openDocumentFrom } from "./examples.mjs";
import { clockTime } from "./format.mjs";
import { conversationToMarkdown, exportFilename } from "./export.mjs";
import { hasTable, renderMarkdown, tableAsCsv, tableAsTsv } from "./markdown.js";
import { watchRoute } from "./page.mjs";
import { addQuestion, renderRecentQuestions } from "./recent-questions.mjs";
import { takeRetryQuestion } from "./retry.mjs";
import { waitsOfConversation, waitsOfPage } from "./turn-waits.mjs";
import { createRenderThrottle, scheduleRender } from "./render-throttle.mjs";
import {
	findInflight,
	removeInflight,
	saveInflight,
	turnsForConversation,
	turnsForPage,
} from "./inflight.mjs";
import { canDecide, remainingSeconds } from "./approval.mjs";
import { mergeOlder, oldestIdx, olderRequest, windowRequest } from "./window.mjs";
import {
	beginTurn,
	clearTranscript,
	dismiss,
	endTurn,
	failTurn,
	IDLE,
	initialState,
	RUNNING,
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
const attachedImage = ref("");
const conversationId = ref("");
const transcriptEl = ref(null);
/** What a screen reader is told, once a turn is over. */
const announcement = ref("");
/** Whether the transcript is pinned to the bottom. */
const followBottom = ref(true);

/** Handler for the "ask" event dispatched by the launcher. */
const askHandler = ref(null);

const TOUR_KEY = "albanna.tour.dismissed";
const showTour = ref(false);
try {
	showTour.value = window.localStorage.getItem(TOUR_KEY) !== "1";
} catch (error) {
	showTour.value = false;
}

function dismissTour() {
	showTour.value = false;
	try {
		window.localStorage.setItem(TOUR_KEY, "1");
	} catch (error) {
		// A browser that will not remember is a browser that will show
		// the tour again; that is the safe failure.
	}
}

const lastAssistantMessage = computed(() => {
	const messages = state.messages;
	for (let i = messages.length - 1; i >= 0; i -= 1) {
		if (messages[i].role === "assistant") return messages[i];
	}
	return null;
});
const showScrollButton = ref(false);
/** The message whose answer was just copied, if any. */
const copiedId = ref("");
/** The message whose table was just copied, if any. */
const copiedTableId = ref("");

/* One clock for every approval card on screen.
 *
 * A timer per card was a timer per card, and two of them disagreed about
 * what "now" was within the same second.  One ticking `now`, read by
 * every card. */
const now = ref(Date.now());
let clockTimer = null;

onMounted(() => {
	clockTimer = setInterval(() => {
		now.value = Date.now();
	}, 1000);
});

/** "chat" shows the transcript; "history" shows the list of conversations. */
const view = ref("chat");
const conversations = ref([]);
const historyLoading = ref(false);
const historyLoadingMore = ref(false);
const historyHasMore = ref(false);
const historyOffset = ref(0);

let messageCounter = 0;
/** The page's identity, as a ref so that the examples follow the page. */
const currentPage = ref("");

/** How many documents the current list page holds, when known. */
const doctypeCount = ref(null);

/** A non-intrusive nudge for the current list page, if any. */
const nudgeMessage = ref("");

watch(
	currentPage,
	async () => {
		const context = resolveContext();
		if (!context || !context.doctype || context.name) {
			doctypeCount.value = null;
			nudgeMessage.value = "";
			return;
		}
		try {
			const result = await call("albanna.api.context.count_doctype", {
				doctype: context.doctype,
			});
			doctypeCount.value =
				result && result.count != null ? result.count : null;
		} catch (failure) {
			doctypeCount.value = null;
		}
		try {
			const result = await call("albanna.api.context.nudge_for_page", {
				doctype: context.doctype,
			});
			nudgeMessage.value = (result && result.message) || "";
		} catch (failure) {
			nudgeMessage.value = "";
		}
	},
);

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

/* The turns being waited for right now, by stream id.
 *
 * One entry per turn — not one per panel — because a reader may have a
 * turn running in more than one thread: they asked, moved to another
 * conversation, and asked again there.  Both turns are running on the
 * server, and the panel waits for whichever thread it is showing.  A
 * turn in another thread keeps its address in the storage (so a reload
 * finds it) but is not waited for here: its events would render into a
 * transcript the reader is not looking at.
 *
 * Each entry is `{controller, conversation, page}`: the abort handle,
 * and which thread the turn belongs to — a conversation's id, or the
 * empty string for the page's own thread before its first question has
 * created it.
 *
 * `shallowReactive`, not `reactive`: the map's own adds and deletes must
 * be seen by the computed that reads it, and its *values* must not be
 * touched — a proxied `AbortController` is a controller whose `abort()`
 * may not reach the signal the wait is listening on. */
const turnWaits = shallowReactive(new Map());

const keydownHandler = ref(null);

/* The approvals waiting for an answer, by stream id.
 *
 * A map of its own, and not a field on the wait above it, for one
 * reason: `shallowReactive` tracks the map's own adds and deletes and
 * nothing inside a value.  Clearing a field on a wait entry would leave
 * the card on screen until something else re-rendered — a card that
 * stays after its decision is taken, which is the same lie in the other
 * direction.  Adding and deleting a *key* is seen.
 *
 * The values are plain data, written once when the write is proposed and
 * never edited: a decision replaces the entry rather than changing it. */
const pendingApprovals = shallowReactive(new Map());

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

/** The waits of the thread the reader is looking at, oldest last. */
const visibleWaits = computed(() => waitsOfConversation([...turnWaits.entries()], conversationId.value));

/** The approvals waiting in the thread being read, oldest last.
 *
 * An approval belongs to the turn that is waiting for it, and a turn
 * belongs to its thread — so the card belongs to the thread too.  A
 * write proposed in another thread is not shown here: its reader is
 * elsewhere, and the card comes back when its thread is opened. */
const visibleApprovals = computed(() => {
	const waiting = [];
	for (const wait of visibleWaits.value) {
		const approval = pendingApprovals.get(wait.streamId);
		if (approval) waiting.push({ streamId: wait.streamId, approval });
	}
	return waiting;
});

/** Is a turn running in the thread being read? */
const busy = computed(() => visibleWaits.value.length > 0);
/** May the reader ask a question? */
const maySend = computed(() => !busy.value && canChat.value);
/** May the reader stop the turn? */
const mayStop = computed(() => busy.value && canChat.value);

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
	// `currentPage` is read so that this is recomputed when the page
	// changes: `resolveContext` reads globals that Vue cannot see.
	const page = currentPage.value;
	const context = resolveContext();
	const set = exampleSet(context);

	if (set === "form") {
		const document = openDocumentFrom(context);
		if (document) {
			return [
				__("Summarise this {0}", [document.doctype]),
				__("What is the status of this {0}?", [document.doctype]),
				__("What is the total of this {0}?", [document.doctype]),
			];
		}
		// A brand-new document: offer to seed it from the last similar one.
		let party = "";
		try {
			const frm = window.cur_frm;
			if (frm && frm.doc) {
				party = frm.doc.customer || frm.doc.supplier || frm.doc.party || "";
			}
		} catch (error) {
			party = "";
		}
		if (party && context.doctype) {
			return [
				__("Copy this {0} from the last one for {1}", [context.doctype, party]),
				__("What fields are required for this {0}?", [context.doctype]),
			];
		}
		return [
			__("What fields are required for this {0}?", [context.doctype]),
		];
	}

	if (set === "list" && context.doctype) {
		if (doctypeCount.value === 0) {
			return [__("Create a {0}", [context.doctype])];
		}
		return [
			__("How many {0} are there?", [context.doctype]),
			__("Which {0} are still open?", [context.doctype]),
			__("What is the total value of these {0}?", [context.doctype]),
		];
	}

	if (set === "report" && context.report) {
		return [
			__("Summarise this report"),
			__("What are the totals in this report?"),
			__("Which rows stand out?"),
		];
	}

	return [
		__("Which Sales Orders are still open?"),
		__("What is the total value of open orders?"),
		__("How many customers are there?"),
	];
});

function openSource(doc) {
	if (!doc || !doc.name) return;
	try {
		if (doc.doctype && window.frappe && typeof window.frappe.set_route === "function") {
			window.frappe.set_route("Form", doc.doctype, doc.name);
			return;
		}
		if (doc.url) {
			window.location.href = doc.url;
		}
	} catch (error) {
		// Navigation is best-effort.
	}
}
function canUndo(message) {
	if (!message || !Array.isArray(message.tools)) return false;
	return message.tools.some((tool) => {
		return (
			(tool.name === "create_doc" || tool.name === "update_doc") &&
			tool.ok !== false
		);
	});
}

async function undoTurn(message) {
	if (!conversationId.value || !message || !message.name) return;
	try {
		const result = await call("albanna.api.conversations.undo_turn", {
			conversation: conversationId.value,
			message: message.name,
		});
		const undone = (result && result.undone) || [];
		if (undone.length) {
			state.notice = "undone";
		} else {
			state.error = String((result && result.status) || __("Nothing to undo."));
		}
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not undo this turn."),
		);
	}
}
const expandedSources = ref(new Set());

function isSourcesExpanded(message) {
	return expandedSources.value.has(message.id);
}

function toggleSources(message) {
	const set = new Set(expandedSources.value);
	if (set.has(message.id)) {
		set.delete(message.id);
	} else {
		set.add(message.id);
	}
	expandedSources.value = set;
}

function sourcesToShow(message) {
	if (!message || !Array.isArray(message.documents)) return [];
	if (isSourcesExpanded(message) || message.documents.length <= 3) {
		return message.documents;
	}
	return message.documents.slice(0, 3);
}
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
		rating: "",
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
		// What the turn cost, in the site's currency.  Null until the
		// turn has finished, so the line is not drawn for a streamed
		// answer that has not landed yet.
		cost: null,
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

/* The renders a streaming answer asks for.
 *
 * Every token mutates the answer's content synchronously — the text is
 * on the message the instant it arrives — and asks for a render through
 * this, so a fast token stream coalesces into one render per frame
 * instead of one full markdown parse per token.  Everything *else* that
 * writes content (a re-render because the documents arrived, a final
 * answer, a reopened conversation) is rare, and renders immediately
 * through setContent.
 *
 * The token's own render is never the last one: applyTurnResult writes
 * the final answer with setContent the moment the turn ends, so nothing
 * waits for a scheduled render that the turn has already outlived. */
const renderStreamed = createRenderThrottle(refresh, scheduleRender);

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
	item.rating = message.rating || "";
	item.image = message.image || "";
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
		doctype,
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
			return __("You moved to another page. The turn is still running — its answer will be in that page's conversation.");
		case "no-table":
			return __("There is no table to copy.");
		case "copy-failed":
			return __("The table could not be copied.");
		case "copy-answer-failed":
			return __("The answer could not be copied.");
		case "deleted":
			return __("The conversation was deleted.");
		case "started":
			return __("A new conversation was started.");
		case "removed":
			return __("The question and its answer were removed.");
		case "truncated":
			return __("The answer was cut off before it was finished.");
		case "image-dropped":
			return __("This model cannot see images; the image was ignored.");
		case "dry-run":
			return __("Dry run — nothing was saved.");
		case "escalated":
			return __("Escalated to support.");
		case "undone":
			return __("The turn was undone.");
		default:
			return "";
	}
}

/**
 * Open a link in the answer in a new tab.
 *
 * The Desk's router captures every click on a link and routes it in the
 * page, so a document the answer names would take the reader *away* from
 * the conversation they were having — and the panel, which follows the
 * page, would show a different thread when they came back.  The Desk
 * makes an exception for a link that says so, but the exception is the
 * Desk's courtesy, and a courtesy is not a contract.
 *
 * So the widget opens its own links: the click is stopped before it
 * reaches the Desk, and the document is opened in a new tab.  The reader
 * keeps the conversation, and the document is still one click away.
 *
 * @param {object} event the click
 */
function onTranscriptClick(event) {
	const link = event.target.closest && event.target.closest("a[href]");
	if (!link) return;

	const href = link.getAttribute("href");
	if (!href || href === "#") return;

	// The Desk's router listens on the body, so the click must not
	// reach it: it would route in the page and open the document here.
	event.preventDefault();
	event.stopPropagation();

	window.open(href, "_blank", "noopener,noreferrer");
}

/**
 * Put the focus in the composer's field.
 */
function focusComposer() {
	nextTick(() => {
		const input = document.querySelector(".albanna-chat__input");
		if (input) input.focus();
	});
}

/**
 * The focus follows the view.
 *
 * The panel is a column of the Desk rather than a modal, so nothing
 * moves the focus for us: a reader who opens the conversation list with
 * the keyboard would find the focus still in the transcript behind it,
 * and every key they press would go there instead.
 */
watch(view, async (next) => {
	if (next === "history") {
		// The drawer moves the focus when its list arrives; there is
		// nothing to focus until then.
		return;
	}
	await nextTick();
	focusComposer();
});

/**
 * Wait for a turn that is already running, and keep the panel honest
 * about it while it runs.
 *
 * This is the one place a turn is *followed* — by `send` through
 * `runTurn`, and by every path that picks a turn up again: a reload, a
 * thread opened from the drawer, the page's thread loaded after a route
 * change.  They differ in where the turn came from and not in what it
 * means to wait for it, so the waiting is written once, here.
 *
 * @param {object} entry the remembered turn
 * @param {object} asked the question message
 * @param {object} answer the answer message
 * @param {object} [approval] the approval this turn is waiting for, when
 *   it is being picked up again after a reload or a return to its thread
 * @returns {Promise<void>} settles when the turn is no longer waited for
 */
function followTurn(entry, asked, answer, approval = null) {
	const controller = new AbortController();
	turnWaits.set(entry.stream_id, {
		controller,
		conversation: entry.conversation_id || "",
		page: entry.page || "",
	});
	// A turn picked up again with an approval still waiting keeps its
	// card: the reader left it mid-decision and is now back.
	if (approval) pendingApprovals.set(entry.stream_id, approval);
	// Set when the wait ends because it was aborted rather than because
	// the turn ended: the two need different cleanups, and only one of
	// them may forget the turn's address.
	let abortedWait = false;
	refreshPhase();

	return waitForTurn(entry.stream_id, {
		signal: controller.signal,
		onEvent: (event) => handleTurnEvent(answer, event, entry.stream_id),
	})
		.then((result) => {
			if (result && result.status === "aborted") {
				abortedWait = true;
				/* The waiting stopped; the work did not.
				 *
				 * A wait is aborted by leaving the thread, leaving the
				 * page, or pressing Stop — and in all three the worker
				 * finishes the turn and the answer lands in the
				 * conversation.  So the address is *kept*: it is what
				 * lets the reader come back to the thread and find the
				 * answer arriving, or already there.  Erasing it here
				 * would turn "unwatched" into "lost", which is exactly
				 * the lie the panel must not tell.
				 *
				 * The *notice* is another matter, and it belongs to the
				 * thread being read: the Stop button is only on that
				 * thread, so only a stop the reader asked for is
				 * acknowledged.  A turn that was left behind says
				 * nothing, because its reader is elsewhere. */
				if (attached(answer)) {
					stopTurn(state, answer);
					if (!state.notice) state.notice = "stopped";
				}
				return;
			}

			applyTurnResult(result, asked, answer);
		})
		.catch((failure) => {
			// A detached answer is not on screen, and its failure is not
			// this thread's failure to report.
			if (attached(answer)) {
				failTurn(state, answer, String((failure && failure.message) || failure));
				removeMessage(answer);
				refreshPhase();
			}
		})
		.finally(() => {
			turnWaits.delete(entry.stream_id);
			// The card goes with the wait: a turn that is no longer
			// waited for has no card to show, in this thread or any
			// other.  (The remembered entry keeps its approval, so
			// picking the turn up again brings the card back.)
			pendingApprovals.delete(entry.stream_id);
			// The address goes when the turn is *over* — answered,
			// failed, or reported lost — and stays while it runs, for
			// the reader who comes back to its thread.
			if (!abortedWait) removeInflight(entry.stream_id);
			answer.pending = false;
			refreshPhase();
			scrollToBottom();
		});
}

/**
 * Put the turns of one thread back on screen, and wait for them.
 *
 * The question and the answer are rebuilt from what was remembered: the
 * question is the reader's own words, and the answer starts empty and
 * fills from the stream — exactly as it did the first time.
 *
 * @param {string} conversationName the thread, empty for the page's own
 *   thread before its first question created it
 */
function attachRunningTurns(conversationName) {
	for (const entry of turnsForConversation(conversationName)) {
		if (turnWaits.has(entry.stream_id)) continue;

		const question = String(entry.question || "");
		const asked = makeMessage("user", question);
		const answer = makeMessage("assistant", "");
		answer.pending = true;

		beginTurn(state, question, asked, answer);
		setActivity(state, __("Thinking"));
		scrollToBottom(true);

		// A turn that was waiting for approval when the page was
		// reloaded is still waiting for it.  The card comes back with
		// the request id it needs, and only if the wait has not already
		// run out — the same window every other part of the card reads,
		// so the card cannot come back saying "waiting" when the worker
		// has already given up.
		if (canDecide(entry.approval, Date.now())) {
			setActivity(state, __("Waiting for your approval…"));
		}

		followTurn(entry, asked, answer, entry.approval);
	}
}

/**
 * The waits of one page.
 *
 * @param {string} page the page identity
 * @returns {Array<{streamId: string, controller: AbortController}>}
 */
function waitsForPage(page) {
	return waitsOfPage([...turnWaits.entries()], page);
}

/**
 * Stop waiting for the turns of the threads the reader is not reading.
 *
 * The work is not cancelled — the worker finishes every turn and the
 * answer lands in its thread on the server.  What stops is the watching:
 * a turn's events belong to its own transcript, and rendering them into
 * a thread the reader has left is noise nobody sees.
 *
 * The address stays remembered, so coming back to the thread picks the
 * turn up again, mid-answer if that is where it is.
 */
function stopOtherWaits() {
	for (const wait of visibleWaits.value) {
		// The thread being read keeps its waits.
		if ((wait.conversation || "") === (conversationId.value || "")) continue;
		wait.controller.abort();
	}
}

/**
 * Bring the turn's phase back in step with the waits.
 *
 * The phase is one turn's state, and there is more than one turn now.
 * It follows the *thread*: running while the thread being read has a
 * wait, idle when it has none.  So it is corrected after every ending —
 * a turn ending in another thread leaves it alone, one turn ending while
 * another of the same thread still runs keeps it running, and the last
 * one ending makes it idle.
 *
 * The corrections run both ways on purpose: the state machine's own
 * transitions (`endTurn`, `stopTurn`, `failTurn`) end *a* turn, and with
 * more than one turn in a thread that is not the same thing as the
 * thread being over.
 */
function refreshPhase() {
	if (visibleWaits.value.length > 0) {
		state.phase = RUNNING;
		return;
	}
	if (state.phase !== IDLE) {
		state.phase = IDLE;
		state.activity = "";
	}
}

/**
 * Put the page's own turns back on screen — the ones asked as the page's
 * *first* question, before the server had a conversation to name.
 *
 * Such a turn is remembered with no conversation id, because the
 * conversation is created by the answer that is still on its way.  It
 * belongs to this page's thread, and to no other: another page's
 * unanswered first question is another page's business.
 */
function attachPageThreadTurns() {
	const own = turnsForPage(currentPage.value).some((entry) => !entry.conversation_id);
	if (own) attachRunningTurns("");
}

/**
 * Pick up the turns that were running when the page was reloaded.
 *
 * The worker is still working and each answer is parked in the cache;
 * all that was lost is the browser's memory of the streams.  So the
 * streams are read back and waited for again — every one of them, each
 * in the thread it belongs to.
 *
 * A turn belongs to the thread of the page it was asked on, so a turn
 * of another page is not picked up here: it belongs to a thread this
 * panel is not showing, and it is picked up when that thread is opened.
 */
function resumeInflight() {
	const wanted = new Set();
	for (const entry of turnsForPage(currentPage.value)) {
		wanted.add(entry.conversation_id || "");
	}

	// The thread being shown, and the page's own thread — a first
	// question's turn is remembered with no conversation id yet, because
	// the conversation is created by the answer.
	for (const conversation of wanted) {
		if (conversation && conversation !== conversationId.value) continue;
		attachRunningTurns(conversation);
	}
	attachPageThreadTurns();
}

/**
 * Show what a turn is doing, as it does it.
 *
 * @param {object} answer the answer message
 * @param {object} event the progress event
 * @param {string} [streamId] the turn the event belongs to
 */
function handleTurnEvent(answer, event, streamId = "") {
	if (event.event === "confirm") {
		// A write is proposed and waits for the reader's approval.  The
		// card is shown in the transcript, so the reader approves a
		// change and not a JSON blob — and the thread keeps its place.
		//
		// The card belongs to the *turn*: it hangs off the turn's wait,
		// so a second write proposed in another thread has a card of
		// its own instead of overwriting this one, and leaving the
		// thread takes this card with it.
		const approval = {
			request_id: event.request_id,
			name: event.name,
			preview: event.preview || event.name || __("a change"),
			diff: event.diff || null,
			at: Date.now(),
			// The server's own deadline, in seconds.  The card counts
			// down from this and stops accepting answers at it — the
			// same deadline the worker is holding, not a second opinion
			// about it.
			window_seconds: event.window_seconds,
			stream_id: streamId,
		};

		/* Write it down *first*, and show it second.
		 *
		 * The order matters for the reader who is in another thread
		 * when the write is proposed: the worker is already waiting,
		 * and the card has to be remembered even though nobody is
		 * looking at it — otherwise coming back to the thread brings
		 * back a turn with no way to answer it, and the write times
		 * out with the reader none the wiser.  Remembered first, the
		 * card is there when they return. */
		const saved = findInflight(streamId);
		if (saved) {
			saveInflight({ ...saved, approval });
		}

		if (!turnWaits.has(streamId)) return;
		pendingApprovals.set(streamId, approval);
		setActivity(state, __("Waiting for your approval…"));
		scrollToBottom();
		return;
	}
	if (event.event === "token") {
		// The text lands on the message at once, so nothing is lost if
		// the render waits for the frame's other tokens; the render
		// reads whatever the content is when it runs.
		answer.content += event.text;
		renderStreamed(answer);
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
/**
 * Whether a message is still part of the transcript being shown.
 *
 * A turn that was running when the reader moved to another thread has
 * an answer that is no longer on screen: it is detached, and everything
 * this module does to *state* — the phase, the activity line, the
 * notice — belongs to the thread being read, not to that one.
 *
 * @param {object} message the message
 * @returns {boolean}
 */
function attached(message) {
	return state.messages.includes(message);
}

/**
 * Apply what a turn ended with.
 *
 * @param {object} result the turn's final payload
 * @param {object} asked the question message
 * @param {object} answer the answer message
 */
function applyTurnResult(result, asked, answer) {
	if (!attached(answer)) {
		// The turn finished in a thread the reader has left.  Its
		// answer is in that thread on the server — where it belongs —
		// and the panel stays where the reader chose to be.  Nothing
		// here may drag them back to it.
		return;
	}

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

		if (result && result.cost != null) {
			answer.cost = result.cost;
		}

		// The answer was cut off at the token ceiling.  It is not wrong
		// — it is unfinished, and the reader is told so, because an
		// answer that looks complete and is not is worse than one that
		// says it was cut.
		if (result.truncated) state.notice = "truncated";
		if (result.dry_run) state.notice = "dry-run";
		if (result.image_dropped) state.notice = "image-dropped";
	} else {
		// A turn that ended without an answer and without an error is
		// still over.
		failTurn(state, answer, __("Something went wrong."));
	}

	// The state machine ended *a* turn; the phase belongs to the thread,
	// and another of its waits may still be running.
	refreshPhase();

	if (answer.content) {
		// A full answer in an aria-live region is read aloud in full,
		// which is not useful.  Announce the outcome, not the text.
		announcement.value =
			result && result.truncated ? __("The answer was cut off.") : __("Answer ready.");
	}
}

/**
 * Approve or reject a write that is waiting in the transcript.
 *
 * @param {string} streamId the turn whose write is waiting
 * @param {string} decision "approve" or "reject"
 */
/**
 * Whether a tool's approval is destructive — cancelling or deleting a
 * document.  Destructive approvals get a danger style and a consequence
 * line so the reader is not asked to confirm a JSON blob.
 *
 * @param {string} toolName the tool that proposed the write
 * @returns {boolean}
 */
function isDestructiveTool(toolName) {
	return toolName === "cancel_doc" || toolName === "delete_doc";
}

/**
 * The consequence line shown on a destructive approval card.
 *
 * @param {string} toolName the tool that proposed the write
 * @returns {string}
 */
function destructiveConsequence(toolName) {
	if (toolName === "delete_doc") {
		return __("This removes the document. It cannot be undone from here.");
	}
	if (toolName === "cancel_doc") {
		return __("This cancels the submitted document.");
	}
	return "";
}

function decideWrite(streamId, decision) {
	const pending = streamId ? pendingApprovals.get(streamId) : null;
	if (!pending) return;

	// The card goes the moment the decision is taken: the worker is
	// acting on it now, and a card that waits for the turn to end says
	// "undecided" about a decision already made.  If the decision fails
	// to reach the worker, the turn says so — an error the reader can
	// read, rather than a card that silently does nothing.
	pendingApprovals.delete(streamId);
	// The remembered entry must not resurrect it either: a reload after
	// the decision must not show a card that was already answered.
	const saved = findInflight(streamId);
	if (saved) saveInflight({ ...saved, approval: null });

	call("albanna.api.chat.confirm_write", {
		request_id: pending.request_id,
		decision,
	}).catch((error) => {
		// The decision did not reach the worker.  The worker will time
		// out on its own, but the reader should not be left thinking
		// their click did nothing.
		state.error = String(
			(error && error.message) || error || __("The approval could not be recorded."),
		);
	});
}

/**
 * Ask a question, starting a turn.
 *
 * @param {string} question the question
 */
async function send(question) {
	const text = String(question || draft.value || "").trim();
	if (!text && !attachedImage.value) return;
	if (!maySend.value) return;

	const image = attachedImage.value || "";
	attachedImage.value = "";

	draft.value = "";
	followBottom.value = true;
	showScrollButton.value = false;

	const asked = makeMessage("user", text);
	if (image) asked.image = image;
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
	// The turn's address, written down by `onQueued` and cleaned up by
	// the `finally`: one turn, one entry, one cleanup.
	let entry = null;
	// How the turn ended, for the same reason: the `finally` needs to
	// know whether the turn is over or merely unwatched, and a `const`
	// inside the `try` is not visible there.
	let result = null;

	try {
		result = await runTurn({
			question: text,
			image: image,
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
				columns: context.columns,
				sort: context.sort,
				report: context.report,
				selection: context.selection,
				// What the reader has asked lately, so that a follow-up
				// reads as a follow-up.
				recent_questions: recent,
			},
			signal: controller.signal,
			onEvent: (event) => handleTurnEvent(answer, event, entry ? entry.stream_id : ""),
			// The turn's address on the server, written down so that a
			// reader who reloads during the turn finds it again — beside
			// the addresses of any other turn still running.
			onQueued: (streamId) => {
				entry = {
					stream_id: streamId,
					conversation_id: conversationId.value,
					page,
					question: text,
				};
				saveInflight(entry);
				turnWaits.set(streamId, {
					controller,
					conversation: conversationId.value || "",
					page,
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
		// This turn cleans up after itself, and only itself: a turn
		// running in another thread keeps both its address and its
		// wait, because the reader may go back to it.
		if (entry) {
			turnWaits.delete(entry.stream_id);
			// An aborted wait is a turn still running: its address stays,
			// so coming back to the thread finds the answer arriving.
			if (!(result && result.status === "aborted")) {
				removeInflight(entry.stream_id);
			}
		}
		refreshPhase();
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
	if (visibleApprovals.value.length) {
		// A write is waiting for the reader.  Stopping is a decision as
		// much as a click is, and it is the same decision: not to run it
		// — for every write this thread is waiting on.
		for (const wait of visibleApprovals.value) {
			decideWrite(wait.streamId, "reject");
		}
		return;
	}
	if (!mayStop.value) return;
	// The waits of the thread being read, and only those: a turn running
	// in another thread is not the reader's to stop from here, and its
	// Stop button is not on this screen.
	for (const wait of visibleWaits.value) {
		wait.controller.abort();
	}
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
 * Download the table in the answer, as a CSV.
 *
 * Copying puts the table on the clipboard, which is where a table goes
 * when it is going into a spreadsheet that is already open.  Sometimes
 * the reader wants the file itself — to attach to something, or to keep.
 *
 * The file is built here, in the browser, because the answer is already
 * here: the table is in the markdown the model wrote, and a round trip
 * to the server would move text that never needed to move.
 *
 * @param {object} message the message
 */
function downloadTable(message) {
	const text = tableAsCsv(message.content);
	if (!text) {
		state.notice = "no-table";
		return;
	}

	try {
		// A byte order mark, so that a spreadsheet opens the Arabic in
		// the right order: without it, the columns are read right to
		// left and the numbers are not numbers.
		const blob = new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" });
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = "table.csv";
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
		URL.revokeObjectURL(url);
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
	let text = message.content || "";
	if (message.documents && message.documents.length) {
		text += "\n\n**Sources:**\n" + message.documents
			.map((doc) => `- ${doc.doctype ? doc.doctype + " " : ""}${doc.name}`)
			.join("\n");
	}
	if (!text) return;
	try {
		if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
			await navigator.clipboard.writeText(text);
		} else {
			fallbackCopy(text);
		}
		copiedId.value = message.id;
		window.setTimeout(() => {
			if (copiedId.value === message.id) copiedId.value = "";
		}, 1600);
	} catch (failure) {
		// Fall back to the legacy path: some Desk contexts (iframes,
		// older browsers) block the async Clipboard API even inside a
		// user gesture.
		try {
			fallbackCopy(text);
			copiedId.value = message.id;
			window.setTimeout(() => {
				if (copiedId.value === message.id) copiedId.value = "";
			}, 1600);
		} catch (error) {
			state.notice = "copy-answer-failed";
		}
	}
}

function fallbackCopy(text) {
	const textarea = document.createElement("textarea");
	textarea.value = text;
	textarea.setAttribute("readonly", "");
	textarea.style.position = "fixed";
	textarea.style.top = "-9999px";
	textarea.style.opacity = "0";
	document.body.appendChild(textarea);
	textarea.select();
	const ok = document.execCommand("copy");
	document.body.removeChild(textarea);
	if (!ok) throw new Error("execCommand failed");
}

// -- the conversation list ------------------------------------------------

const historySearch = ref("");
let searchTimer = null;

async function escalateConversation() {
	if (!conversationId.value) return;
	try {
		const result = await call("albanna.api.conversations.escalate_conversation", {
			conversation: conversationId.value,
		});
		state.notice = "escalated";
		if (result && result.issue) {
			state.error = "";
		}
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not escalate the conversation."),
		);
	}
}

async function showHistory(searchTerm = "") {
	const term = (searchTerm != null ? searchTerm : historySearch.value) || "";
	historySearch.value = term;
	view.value = "history";
	historyLoading.value = true;
	historyOffset.value = 0;
	historyHasMore.value = false;
	try {
		const result = await call("albanna.api.conversations.list_conversations", {
			offset: 0,
			search: term,
		});
		const rows = result.conversations || [];
		conversations.value = rows;
		historyOffset.value = rows.length;
		historyHasMore.value = rows.length >= 30;
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not load the conversations."),
		);
	} finally {
		historyLoading.value = false;
	}
}

function onHistorySearch(term) {
	historySearch.value = term || "";
	if (searchTimer) clearTimeout(searchTimer);
	searchTimer = setTimeout(() => {
		showHistory(historySearch.value);
	}, 250);
}

async function pinConversation(conversation, pinned) {
	if (!conversation || !conversation.name) return;
	conversation.pinned = !!pinned;
	try {
		await call("albanna.api.conversations.toggle_pin", {
			conversation: conversation.name,
			pinned: pinned ? 1 : 0,
		});
	} catch (failure) {
		conversation.pinned = !pinned;
	}
}

async function loadMoreConversations() {
	if (historyLoadingMore.value || !historyHasMore.value) return;
	historyLoadingMore.value = true;
	try {
		const result = await call("albanna.api.conversations.list_conversations", {
			offset: historyOffset.value,
			search: historySearch.value,
		});
		const rows = result.conversations || [];
		conversations.value = conversations.value.concat(rows);
		historyOffset.value += rows.length;
		historyHasMore.value = rows.length >= 30;
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not load the conversations."),
		);
	} finally {
		historyLoadingMore.value = false;
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

		/* The thread being left stops being waited for — its turns
		 * keep running, and their addresses are remembered — and the
		 * thread just opened picks up any turn of its own that is still
		 * running, mid-answer and all. */
		stopOtherWaits();
		attachRunningTurns(conversation.name);
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
async function regenerateLast() {
	const assistant = lastAssistantMessage.value;
	if (!assistant || !assistant.name || !conversationId.value) return;
	// Find the question that brought this answer.
	let questionMessage = null;
	for (let i = state.messages.length - 1; i >= 0; i -= 1) {
		if (state.messages[i] === assistant) {
			for (let j = i - 1; j >= 0; j -= 1) {
				if (state.messages[j].role === "user") {
					questionMessage = state.messages[j];
					break;
				}
			}
			break;
		}
	}
	const question = questionMessage ? questionMessage.content : "";
	try {
		const result = await call("albanna.api.conversations.delete_turn", {
			conversation: conversationId.value,
			message: assistant.name,
		});
		const messages = (result.messages || []).map(messageFromServer);
		clearTranscript(state);
		for (const message of messages) state.messages.push(message);
		draft.value = question;
	} catch (failure) {
		state.error = String(
			(failure && failure.message) || failure || __("Could not regenerate."),
		);
	}
}

/**
 * Export the transcript as a Markdown file.
 *
 * The *file* is built in :mod:`export.mjs`, where it is testable; the
 * DOM dance of a detached anchor is what stays here.  The speakers are
 * named in the reader's language, because the file is theirs.
 */
function exportConversation() {
	const body = conversationToMarkdown(state.messages, {
		reader: __("You"),
		assistant: __("Albanna"),
	});
	const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = exportFilename(Date.now());
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);
}

/**
 * Rate an answer, as a toggle.
 *
 * Clicking the marked side again clears the rating: the rating is the
 * reader's single opinion of the answer, and two thumbs lit at once is
 * not an opinion, it is noise.  A failure is silent — the rating is a
 * courtesy, and a lost courtesy is not worth a toast over a thread the
 * reader is still reading.
 *
 * @param {object} message the answer, carrying its row name
 * @param {string} rating "up" or "down"
 */
async function rateMessage(message, rating) {
	if (!message || !message.name || !conversationId.value) return;
	const next = message.rating === rating ? "" : rating;
	try {
		await call("albanna.api.conversations.rate_message", {
			conversation: conversationId.value,
			message: message.name,
			rating: next,
		});
		// The server, not the click, is what the answer carries: the
		// rating has to survive a reload, so it is only set here once
		// the row agrees.
		message.rating = next;
	} catch (failure) {
		// Silent, for the reason above.
	}
}

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
	// A conversation is created lazily: the "New" button only clears the
	// thread the panel is showing.  The first question asked in it is what
	// creates the conversation on the server, named after that question.
	// Creating it here would leave an empty, orphaned conversation every
	// time the button is pressed without a question following.
	conversationId.value = "";
	state.messages = [];
	recentQuestions.value = [];
	view.value = "chat";
	state.notice = "started";
	scrollToBottom(true);
	// The thread being left keeps its turns running; the watching
	// stops here, and the new thread is empty of them.
	stopOtherWaits();
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
			// The page's own thread, before its first question created
			// it: a turn asked a moment ago is remembered with no
			// conversation id, and it is still running.
			attachPageThreadTurns();
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
		// A turn of this page's thread that is still running is picked
		// up again: the reader moved to another page and came back, and
		// the answer is still arriving.
		attachRunningTurns(result.conversation);
		attachPageThreadTurns();
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
 * The turns of the page being left stop being waited for.  The answers
 * would be about the page the reader has just left, and they belong to
 * that page's threads — so the work goes on where it belongs, and the
 * panel says what it did.  Their addresses stay remembered: coming back
 * to that page picks each turn up again.
 */
function onRouteChange() {
	const context = resolveContext();
	const identity = pageIdentity();
	if (identity === currentPage.value) return;

	// Every wait of the page being left — the thread on screen and any
	// other thread of this page that is still running — stops being
	// waited for.  The answers belong to those threads, the work goes
	// on, and the addresses are remembered.
	const leaving = waitsForPage(currentPage.value);
	const stopped = clearTranscript(state);
	for (const wait of leaving) {
		wait.controller.abort();
	}
	if (stopped || leaving.length) state.notice = "moved";
	// The waits are aborting, not gone: the phase catches up with them
	// as they settle, and says "running" until they have.
	refreshPhase();

	conversationId.value = "";
	currentPage.value = identity;
	props.onContext(context);
	loadPageConversation();
}

onMounted(() => {
	const context = resolveContext();
	onContextChanged(context);

	/* The focus comes with the panel.
	 *
	 * The launcher tries to focus the panel's field when it opens, but
	 * the panel's field does not exist yet: the widget is a bundle that
	 * is fetched and mounted afterwards, so the launcher's query finds
	 * nothing and the focus is left on a button that has just been
	 * hidden.  A keyboard reader is then stranded — every key they press
	 * goes to the Desk, not to the assistant they opened. */
	focusComposer();

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

	const onAsk = (event) => {
		const question = (event && event.detail) || "";
		if (question) {
			draft.value = question;
			ask(question);
		}
	};
	document.addEventListener("albanna:ask", onAsk);
	askHandler.value = onAsk;
	const askHandler = onAsk;

	// Keyboard: Escape closes the panel, Ctrl/Cmd+K focuses the composer.
	// Both are the affordances a reader expects of a chat panel, and
	// neither should be a mouse-only action.
	const onKeydown = (event) => {
		if (event.key === "Escape") {
			props.onClose();
			return;
		}
		if ((event.ctrlKey || event.metaKey) && (event.key === "k" || event.key === "K")) {
			event.preventDefault();
			focusComposer();
		}
	};
	document.addEventListener("keydown", onKeydown);
	keydownHandler.value = onKeydown;
});

onBeforeUnmount(() => {
	if (clockTimer) clearInterval(clockTimer);

	// Every turn in flight is left to finish on the server — the answers
	// land in their threads — but this panel is no longer waiting for
	// any of them: there is no screen left to show them on, and a wait
	// nobody resolves is a socket subscription and a poll nobody stops.
	for (const wait of visibleWaits.value) {
		wait.controller.abort();
	}

	if (unwatch) unwatch();
	if (keydownHandler.value) document.removeEventListener("keydown", keydownHandler.value);
	if (askHandler.value) document.removeEventListener("albanna:ask", askHandler.value);
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
					v-if="conversationId"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Escalate to support')"
					:title="__('Escalate to support')"
					@click="escalateConversation"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>
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
					v-if="view === 'chat' && lastAssistantMessage"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Regenerate last answer')"
					:title="__('Regenerate last answer')"
					@click="regenerateLast"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M21 12a9 9 0 1 1-3-6.7L21 8m0-5v5h-5"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>

				<button
					v-if="view === 'chat' && state.messages.length"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Export conversation')"
					:title="__('Export conversation')"
					@click="exportConversation"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
						<path
							d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</button>

				<button
					v-if="view === 'chat'"
					type="button"
					class="albanna-chat__icon"
					:aria-label="__('Conversations')"
					:title="__('Conversations')"
					@click="showHistory('')"
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
						"Ask an administrator to grant your account read access to Albanna Conversation.",
					)
				}}
			</p>
		</div>

		<ConversationDrawer
			v-else-if="view === 'history'"
			:conversations="conversations"
			:loading="historyLoading"
			:active="conversationId"
			:has-more="historyHasMore"
			:loading-more="historyLoadingMore"
			:search="historySearch"
			@open="openConversation"
			@rename="renameConversation"
			@remove="removeConversation"
			@back="showTranscript"
			@loadmore="loadMoreConversations"
			@pin="pinConversation"
			@search="onHistorySearch"
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
				@click="onTranscriptClick"
			>
				<div v-if="!state.messages.length" class="albanna-chat__empty">
					<p class="albanna-chat__empty-title">
						{{ __("Ask a question about this site") }}
					</p>
					<p v-if="pageContext" class="albanna-chat__empty-context">
						{{ pageContext }}
					</p>
					<p
						v-if="nudgeMessage"
						class="albanna-chat__nudge"
					>
						{{ nudgeMessage }}
						<button
							type="button"
							class="albanna-chat__nudge-ask"
							@click="ask(nudgeMessage)"
						>
							{{ __("Go") }}
						</button>
					</p>
					<p
						v-if="showTour"
						class="albanna-chat__tour"
					>
						{{ __("Type a question in plain language — the assistant reads this page and answers from the site's own data. Dismiss any time.") }}
						<button
							type="button"
							class="albanna-chat__tour-dismiss"
							@click="dismissTour"
						>
							{{ __("Got it") }}
						</button>
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
						v-if="message.role === 'user' && (message.content || message.image)"
						class="albanna-chat__bubble albanna-chat__bubble--plain"
					>
						<img
							v-if="message.image"
							:src="message.image"
							alt=""
							class="albanna-chat__user-image"
						/>
						<span v-if="message.content">{{ message.content }}</span>
					</div>
					<!-- The assistant's answer is markdown.  `renderMarkdown`
					     escapes before it builds any markup, so this is safe. -->
					<div
						v-else-if="message.content"
						class="albanna-chat__bubble"
						v-html="message.html"
					></div>

					<div
						v-if="message.role === 'assistant' && message.documents && message.documents.length"
						class="albanna-chat__sources"
					>
						<span class="albanna-chat__sources-label">{{ __("Sources") }}:</span>
						<template
							v-for="(doc, index) in sourcesToShow(message)"
							:key="index"
						>
							<button
								type="button"
								class="albanna-chat__source"
								@click="openSource(doc)"
							>
								{{ doc.doctype ? doc.doctype + ' ' + doc.name : doc.name }}
							</button>
						</template>
						<button
							v-if="message.documents.length > 3"
							type="button"
							class="albanna-chat__source-toggle"
							@click="toggleSources(message)"
						>
							{{
								isSourcesExpanded(message)
									? __("See less")
									: __("See more ({0})", [message.documents.length - 3])
							}}
						</button>
					</div>

					<div class="albanna-chat__footer">
						<span
							v-if="message.role === 'assistant' && message.cost != null && message.cost > 0"
							class="albanna-chat__cost"
						>
							{{ __("This turn cost {0}.", [Number(message.cost).toFixed(4)]) }}
						</span>
						<button
							v-if="message.role === 'assistant' && message.content"
							type="button"
							class="albanna-chat__copy"
							:aria-label="__('Copy as Markdown')"
							:title="__('Copy as Markdown')"
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
						<!-- The rating is a toggle behaviour, not two independent
					     buttons: clicking the marked side again clears the
					     rating.  The state is on the *button*, not only in
					     the glyph, so a reader who cannot tell the two
					     thumbs apart still gets the answer in the tooltip
					     and the pressed state in their reader. -->
						<button
							v-if="message.role === 'assistant' && message.name"
							type="button"
							class="albanna-chat__copy"
							:class="{ 'albanna-chat__rating--on': message.rating === 'up' }"
							:aria-label="__('Helpful')"
							:aria-pressed="message.rating === 'up' ? 'true' : 'false'"
							:title="__('Helpful')"
							@click="rateMessage(message, 'up')"
						>
							<svg
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"
							>
								<path d="M7 10v12" />
								<path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
							</svg>
						</button>
						<button
							v-if="message.role === 'assistant' && message.name"
							type="button"
							class="albanna-chat__copy"
							:class="{ 'albanna-chat__rating--on': message.rating === 'down' }"
							:aria-label="__('Not helpful')"
							:aria-pressed="message.rating === 'down' ? 'true' : 'false'"
							:title="__('Not helpful')"
							@click="rateMessage(message, 'down')"
						>
							<svg
								width="13"
								height="13"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"
							>
								<path d="M17 14V2" />
								<path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
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
							v-if="message.role === 'assistant' && message.hasTable"
							type="button"
							class="albanna-chat__copy albanna-chat__copy--table"
							:aria-label="__('Download the table')"
							:title="__('Download the table')"
							@click="downloadTable(message)"
						>
							{{ __("Download") }}
						</button>
						<button
							v-if="message.role === 'assistant' && message.name && canUndo(message)"
							type="button"
							class="albanna-chat__copy"
							:aria-label="__('Undo this turn')"
							:title="__('Undo this turn')"
							@click="undoTurn(message)"
						>
							{{ __("Undo") }}
						</button>

						<button
							v-if="message.role === 'user' && message.name"
							type="button"
							class="albanna-chat__copy"
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

		<!-- A write that is waiting for the reader's approval.  It is a
		     card in the transcript rather than a dialog, so that the
		     reader approves a change and not a JSON blob, and the thread
		     keeps its place.

		     One card per waiting write, each belonging to the turn that
		     proposed it: two writes waiting in this thread are two cards,
		     and neither can be answered by clicking the other.

		     The buttons stop when the server's window runs out, and the
		     card says so.  A card that stays clickable past its deadline
		     accepts an answer nobody is reading any more, and the reader
		     who clicks it gets silence — which reads as the assistant
		     ignoring them. -->
		<div
			v-for="wait in visibleApprovals"
			:key="wait.streamId"
			class="albanna-chat__confirm"
			:class="{ 'albanna-chat__confirm--destructive': isDestructiveTool(wait.approval.name) }"
			role="alertdialog"
			aria-live="assertive"
		>
			<p class="albanna-chat__confirm-preview">{{ wait.approval.preview }}</p>
			<p
				v-if="isDestructiveTool(wait.approval.name)"
				class="albanna-chat__confirm-consequence"
			>
				{{ destructiveConsequence(wait.approval.name) }}
			</p>
			<ul
				v-if="wait.approval.diff && Object.keys(wait.approval.diff).length"
				class="albanna-chat__confirm-diff"
			>
				<li
					v-for="(change, field) in wait.approval.diff"
					:key="field"
					class="albanna-chat__confirm-diff-row"
				>
					<span class="albanna-chat__confirm-diff-field">{{ field }}</span>
					<span class="albanna-chat__confirm-diff-before">{{ change.before }}</span>
					<span class="albanna-chat__confirm-diff-arrow">→</span>
					<span class="albanna-chat__confirm-diff-after">{{ change.after }}</span>
				</li>
			</ul>
			<p v-if="canDecide(wait.approval, now)" class="albanna-chat__confirm-countdown">
				{{ __("Waiting {0}s", [remainingSeconds(wait.approval, now)]) }}
			</p>
			<p v-else class="albanna-chat__confirm-countdown albanna-chat__confirm-countdown--out">
				{{ __("The wait ran out — the change was not made.") }}
			</p>
			<div class="albanna-chat__confirm-actions">
				<button
					type="button"
					class="albanna-chat__confirm-button albanna-chat__confirm-button--confirm"
					:class="{ 'albanna-chat__confirm-button--danger': isDestructiveTool(wait.approval.name) }"
					:disabled="!canDecide(wait.approval, now)"
					@click="decideWrite(wait.streamId, 'approve')"
				>
					{{ __("Confirm") }}
				</button>
				<button
					type="button"
					class="albanna-chat__confirm-button albanna-chat__confirm-button--cancel"
					:disabled="!canDecide(wait.approval, now)"
					@click="decideWrite(wait.streamId, 'reject')"
				>
					{{ __("Cancel") }}
				</button>
			</div>
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
			:image="attachedImage"
			:image-support="config && config.image_support"
			:busy="busy"
			:can-chat="canChat"
			@update:image="attachedImage = $event"
			@send="send"
			@stop="stop"
		/>
	</div>
</template>
