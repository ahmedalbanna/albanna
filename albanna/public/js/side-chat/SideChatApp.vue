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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import ConversationDrawer from "./ConversationDrawer.vue";
import { pageIdentity, resolveContext } from "./context.mjs";
import { renderMarkdown } from "./markdown.js";
import { call } from "./turn.mjs";
import { runTurn } from "./turn.mjs";

const props = defineProps({
	/** The options payload, already resolved by the launcher. */
	config: { type: Object, default: () => ({}) },
	/** Called when the user closes the panel from inside it. */
	onClose: { type: Function, default: () => {} },
	/** Called with the page description whenever it changes. */
	onContext: { type: Function, default: () => {} },
});

const messages = ref([]);
const draft = ref("");
const busy = ref(false);
const status = ref("");
const error = ref("");
const conversationId = ref("");
const transcriptEl = ref(null);
const composerEl = ref(null);

/** "chat" shows the transcript; "history" shows the list of conversations. */
const view = ref("chat");
const conversations = ref([]);
const historyLoading = ref(false);

let messageCounter = 0;
let currentPage = "";

const locked = computed(() => props.config.locked === true);
const canChat = computed(() => props.config.chat_access === true && !locked.value);
const toolNames = computed(() => (props.config.tools || []).join(", "));

function nextId() {
	messageCounter += 1;
	return `m${messageCounter}`;
}

function scrollToBottom() {
	nextTick(() => {
		const el = transcriptEl.value;
		if (el) el.scrollTop = el.scrollHeight;
	});
}

function onContextChanged(context) {
	currentPage = pageIdentity();
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
	const labels = {
		thinking: () => __("Thinking"),
	};
	const label = labels[code];
	return label ? label() : "";
}

function describeTool(name) {
	const labels = {
		list_docs: "Searching",
		get_doc: "Reading",
		get_doctype_meta: "Checking fields",
		run_report: "Running a report",
		create_doc: "Creating",
	};
	return labels[name] || "Working";
}

async function send() {
	const question = draft.value.trim();
	if (!question || busy.value || !canChat.value) return;

	draft.value = "";
	error.value = "";
	busy.value = true;

	messages.value.push({ id: nextId(), role: "user", content: question, tools: [] });
	scrollToBottom();

	const answer = { id: nextId(), role: "assistant", content: "", tools: [] };
	messages.value.push(answer);
	scrollToBottom();

	const context = resolveContext();

	try {
		const result = await runTurn({
			question,
			conversationId: conversationId.value,
			page: currentPage,
			pageContext: {
				route: context.route,
				view: context.view,
				doctype: context.doctype,
				name: context.name,
				title: context.title,
				filters: context.filters,
				selection: context.selection,
			},
			onEvent: (event) => {
				if (event.event === "token") {
					answer.content += event.text;
					scrollToBottom();
					return;
				}
				if (event.event === "tool_start") {
					answer.tools.push({ name: event.name, ok: null });
					scrollToBottom();
					return;
				}
				if (event.event === "tool_done") {
					const pending = answer.tools.find(
						(tool) => tool.ok === null && tool.name === event.name,
					);
					if (pending) pending.ok = event.ok !== false;
					scrollToBottom();
					return;
				}
				if (event.event === "status") {
					status.value = event.code ? statusLabel(event.code) : event.text || "";
				}
			},
		});

		if (result && result.conversation_id) {
			conversationId.value = result.conversation_id;
		}

		if (result && result.status === "error") {
			error.value = result.error || __("Something went wrong.");
			if (!answer.content) {
				messages.value = messages.value.filter((message) => message.id !== answer.id);
			}
		} else if (result && result.reply) {
			// The server's answer is the truth.  The streamed text was the
			// live preview, and a preview that lost a fragment is worse
			// than no preview: it is a wrong answer that looks complete.
			answer.content = result.reply;
		}
	} catch (failure) {
		error.value = String(
			(failure && failure.message) || failure || __("Something went wrong."),
		);
		messages.value = messages.value.filter((message) => message.id !== answer.id);
	} finally {
		busy.value = false;
		status.value = "";
		scrollToBottom();
	}
}

function onKeydown(event) {
	// Enter sends; Shift+Enter is a new line.
	if (event.key === "Enter" && !event.shiftKey) {
		event.preventDefault();
		send();
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
		error.value = String(
			(failure && failure.message) || failure || __("Could not load the conversations."),
		);
	} finally {
		historyLoading.value = false;
	}
}

function showTranscript() {
	view.value = "chat";
}

async function openConversation(conversation) {
	error.value = "";
	try {
		const result = await call("albanna.api.conversations.open_conversation", {
			conversation: conversation.name,
		});
		conversationId.value = conversation.name;
		messages.value = (result.messages || []).map((message) => ({
			id: nextId(),
			role: message.role,
			content: message.content,
			tools: message.tools || [],
		}));
		view.value = "chat";
		scrollToBottom();
	} catch (failure) {
		error.value = String(
			(failure && failure.message) || failure || __("Could not open that conversation."),
		);
	}
}

async function renameConversation(name, title) {
	try {
		await call("albanna.api.conversations.rename_conversation", { conversation: name, title });
		const item = conversations.value.find((conversation) => conversation.name === name);
		if (item) item.title = title;
	} catch (failure) {
		error.value = String(
			(failure && failure.message) || failure || __("Could not rename that conversation."),
		);
	}
}

async function removeConversation(conversation) {
	try {
		await call("albanna.api.conversations.delete_conversation", {
			conversation: conversation.name,
		});
		conversations.value = conversations.value.filter((item) => item.name !== conversation.name);
		if (conversationId.value === conversation.name) {
			newConversation();
		}
	} catch (failure) {
		error.value = String(
			(failure && failure.message) || failure || __("Could not delete that conversation."),
		);
	}
}

function newConversation() {
	messages.value = [];
	conversationId.value = "";
	view.value = "chat";
	scrollToBottom();
}

function onRouteChange() {
	const context = resolveContext();
	const identity = pageIdentity();
	if (identity === currentPage) return;

	// A different page is a different thread.  The transcript is cleared
	// rather than kept, because an answer about the previous page would be
	// read as an answer about this one.
	messages.value = [];
	conversationId.value = "";
	currentPage = identity;
	props.onContext(context);
}

onMounted(() => {
	const context = resolveContext();
	onContextChanged(context);

	try {
		if (
			window.frappe &&
			window.frappe.router &&
			typeof window.frappe.router.on === "function"
		) {
			window.frappe.router.on("route-change", onRouteChange);
		}
	} catch (error) {
		// A Desk without a router event is still a usable Desk.
	}
});

onBeforeUnmount(() => {
	try {
		if (
			window.frappe &&
			window.frappe.router &&
			typeof window.frappe.router.off === "function"
		) {
			window.frappe.router.off("route-change", onRouteChange);
		}
	} catch (error) {
		// Nothing to clean up.
	}
});
</script>

<template>
	<div class="albanna-chat">
		<header class="albanna-chat__header">
			<button
				v-if="view === 'history'"
				type="button"
				class="albanna-chat__close"
				:aria-label="__('Back to the conversation')"
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

			<button
				v-if="view === 'history'"
				type="button"
				class="albanna-chat__new"
				@click="newConversation"
			>
				{{ __("New") }}
			</button>

			<button
				v-else
				type="button"
				class="albanna-chat__close"
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
				class="albanna-chat__close"
				:aria-label="__('Close')"
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

		<div
			v-else
			ref="transcriptEl"
			class="albanna-chat__transcript"
			role="log"
			aria-live="polite"
		>
			<div v-if="!messages.length" class="albanna-chat__empty">
				<p class="albanna-chat__empty-title">{{ __("Ask a question about this site") }}</p>
				<p class="albanna-chat__empty-detail">
					{{
						__(
							"For example: which Sales Orders are still open, or what is customer Acme's balance.",
						)
					}}
				</p>
				<p v-if="toolNames" class="albanna-chat__empty-tools">
					{{ __("Available tools") }}: {{ toolNames }}
				</p>
			</div>

			<div
				v-for="message in messages"
				:key="message.id"
				class="albanna-chat__message"
				:class="`albanna-chat__message--${message.role}`"
			>
				<div v-if="message.tools && message.tools.length" class="albanna-chat__tools">
					<span
						v-for="(tool, index) in message.tools"
						:key="index"
						class="albanna-chat__tool"
						:class="{
							'albanna-chat__tool--running': tool.ok === null,
							'albanna-chat__tool--failed': tool.ok === false,
						}"
					>
						{{ describeTool(tool.name) }} · {{ tool.name }}
					</span>
				</div>
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
					v-html="renderMarkdown(message.content)"
				></div>
			</div>
		</div>

		<div v-if="error" class="albanna-chat__error" role="alert">{{ error }}</div>

		<div v-if="view === 'chat'" class="albanna-chat__composer">
			<textarea
				ref="composerEl"
				v-model="draft"
				class="albanna-chat__input"
				rows="2"
				:placeholder="__('Ask about your data…')"
				:disabled="busy || !canChat"
				:aria-label="__('Your question')"
				@keydown="onKeydown"
			></textarea>
			<button
				type="button"
				class="btn btn-primary albanna-chat__send"
				:disabled="busy || !draft.trim() || !canChat"
				@click="send"
			>
				{{ busy ? status || __("Working…") : __("Send") }}
			</button>
		</div>
	</div>
</template>
