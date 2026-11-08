<script setup>
/**
 * The composer: the question box, the send button, and the hint.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { checkAttachment, makeAttachment, REFUSED_SIZE, storeAll } from "./attachments.mjs";
import { serverMessage } from "./errors.mjs";
import { MAX_SESSION_MS, mergeTranscript, readResults, voiceErrorText } from "./voice.mjs";
import { submitDecision } from "./submit.mjs";

const props = defineProps({
	modelValue: { type: String, default: "" },
	busy: { type: Boolean, default: false },
	canChat: { type: Boolean, default: false },
	//: The attachments the reader has chosen for this question.  Each is
	//: an attachment as ``attachments.mjs`` builds it: the bytes the model
	//: reads, the name the reader recognises, the type the site checks, the
	//: size the reader is shown, the address the file was stored under, and
	//: whether it was.
	files: { type: Array, default: () => [] },
	imageSupport: { type: Boolean, default: false },
	maxImageSizeKb: { type: Number, default: 0 },
	//: The types the site attaches, as the site publishes them: a list of
	//: ``{ mime, name }``.  The browser keeps no copy of its own — a
	//: browser that accepts a file the server would refuse is a reader
	//: who waited for an upload that was going to be refused.
	attachableTypes: { type: Array, default: () => [] },
});

const emit = defineEmits(["update:modelValue", "update:files", "send", "stop"]);

const inputEl = ref(null);
const fileInput = ref(null);

//: The types the site takes, as the browser sends them.
const attachableMimes = computed(() => props.attachableTypes.map((type) => type.mime));

//: The names the site calls those types by, for the refusal that names
//: them.  They are the site's names and not the browser's: a sentence
//: that named types of its own would be a sentence that could name types
//: the site no longer takes.
const attachableNames = computed(() => props.attachableTypes.map((type) => type.name));

const speechSupported = ref(
	typeof window !== "undefined" && !!(window.SpeechRecognition || window.webkitSpeechRecognition),
);
const listening = ref(false);
let recognition = null;
// A transcript that arrives after the question has been sent belongs to a
// turn that has already gone; it must not write itself back into the
// composer.  A reader who saw their question reappear after sending it
// would believe the send had failed.
let ignoreTranscript = false;
let sessionTimer = null;

/**
 * Close the microphone.
 *
 * @param {boolean} keepTranscript whether the last words are still
 *   wanted — a deliberate stop keeps them, an abandonment does not
 */
function stopVoice(keepTranscript = true) {
	if (sessionTimer) {
		clearTimeout(sessionTimer);
		sessionTimer = null;
	}
	if (!recognition) {
		listening.value = false;
		return;
	}
	try {
		if (keepTranscript) recognition.stop();
		else recognition.abort();
	} catch (error) {
		// It had already stopped.
	}
	if (!keepTranscript) {
		recognition = null;
		listening.value = false;
	}
}

function toggleVoice() {
	if (!speechSupported.value || props.busy || !props.canChat) return;
	if (listening.value) {
		stopVoice(true);
		return;
	}
	const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
	// A session that never ended must not be started twice: `start()` on a
	// running recogniser throws, and the microphone would stay open behind a
	// button that says it is closed.
	stopVoice(false);

	const session = new Ctor();
	recognition = session;
	// Long questions are the point of a dictation.  A session that ends at
	// the first pause cuts the sentence in half.
	session.continuous = true;
	session.interimResults = true;
	session.lang = (window.frappe && window.frappe.boot && window.frappe.boot.lang) || "en-US";
	ignoreTranscript = false;

	let finalText = props.modelValue || "";
	let nextFinal = 0;
	let lastEmitted = props.modelValue || "";

	session.onresult = (event) => {
		const read = readResults(event.results, event.resultIndex, nextFinal);
		nextFinal = read.nextFinal;
		if (read.finals.length) {
			finalText = [finalText, read.finals.join(" ")].filter(Boolean).join(" ");
		}
		const spoken = [finalText, read.interim].filter(Boolean).join(" ");
		lastEmitted = mergeTranscript({
			spoken,
			current: props.modelValue,
			lastEmitted,
		});
		emit("update:modelValue", lastEmitted);
	};
	session.onend = () => {
		listening.value = false;
		recognition = null;
		if (sessionTimer) {
			clearTimeout(sessionTimer);
			sessionTimer = null;
		}
		if (ignoreTranscript) return;
		// The reader may have typed alongside the dictation — a
		// correction, a second sentence — and that text is theirs, not
		// the browser's.  The merge is run *again* here rather than
		// reusing what onresult last emitted, because the reader may have
		// typed after the last result event: a deliberate stop is one of
		// the ways a session ends, and "dictate, correct, click stop" is
		// the ordinary shape of using it.  Reusing lastEmitted there
		// would drop the correction; emitting finalText would drop
		// everything typed since the session began.
		emit(
			"update:modelValue",
			mergeTranscript({
				spoken: finalText,
				current: props.modelValue,
				lastEmitted,
			}).trim(),
		);
	};
	session.onerror = (event) => {
		listening.value = false;
		const message = voiceErrorText(event && event.error, __);
		if (message) noticeText.value = message;
	};

	listening.value = true;
	try {
		session.start();
		// A microphone left open is one of the things a reader does not
		// expect, so one session has a life of its own.
		sessionTimer = setTimeout(() => stopVoice(true), MAX_SESSION_MS);
	} catch (error) {
		stopVoice(false);
	}
}

// The microphone does not outlive the panel: a reader who closes the
// widget, or switches to the conversations, must not leave it open.
onBeforeUnmount(() => stopVoice(false));

// A turn that has started is a turn that has the question.  The
// microphone is closed for it, and its transcript is not allowed back.
watch(
	() => props.busy,
	(busy) => {
		if (!busy) return;
		ignoreTranscript = true;
		stopVoice(false);
	},
);

const MAX_HEIGHT = 140;

function resize() {
	const el = inputEl.value;
	if (!el) return;
	el.style.height = "auto";
	el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

watch(
	() => props.modelValue,
	() => nextTick(resize),
);
onMounted(resize);

function onKeydown(event) {
	if (event.key === "Enter" && !event.shiftKey) {
		event.preventDefault();
		// Enter sends when idle and stops when busy — exactly what the
		// button beside the field does.  The key and the button must not
		// disagree about what the primary key does: a reader who types a
		// follow-up while a turn runs and presses Enter gets feedback
		// (a stop) instead of silence.
		onAction();
	}
}

function submit() {
	noticeText.value = "";
	const decision = submitDecision({
		modelValue: props.modelValue,
		files: props.files,
		busy: props.busy,
		canChat: props.canChat,
	});
	if (!decision.ok) return;
	const question = decision.question;
	// The question is on its way.  Whatever the microphone says now belongs
	// to a turn that has already been sent, so it is closed and its
	// transcript is not allowed back into the composer.
	ignoreTranscript = true;
	stopVoice(false);
	emit("update:modelValue", "");
	emit("send", question);
}

function onAction() {
	if (props.busy) {
		emit("stop");
		return;
	}
	submit();
}

const noticeText = ref("");
const uploading = ref(false);
// Whether a file is being dragged over the composer's field.  The field
// is the drop target, and without a visible affordance the reader cannot
// tell where to aim — especially since a drop that misses it navigates
// the whole Desk away.
const dragOver = ref(false);
let dragCounter = 0;
//: How many uploads are in flight.  A reader who drops three files has
//: three uploads, and the flag must not clear when the first one ends
//: while the other two are still going.
let uploadsInFlight = 0;

/**
 * A file pasted into the question box.
 *
 * The browser puts a pasted picture into the paste event as a file, so
 * the ordinary Ctrl+V reaches here without anything special.
 */
async function onPaste(event) {
	const items = event.clipboardData && event.clipboardData.items;
	if (!items) return;
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		// A pasted *file* is a file the reader wants attached, and the
		// rule decides whether it may be — the same rule the picker and
		// the drop use, so a file refused in one of them is refused in
		// all of them.  A pasted *text* is a different thing: the
		// browser puts it in the question box as text, which is what the
		// reader meant.
		if (item.kind !== "file") continue;
		const file = item.getAsFile();
		if (!file) continue;
		event.preventDefault();
		await attachFiles([file]);
		return;
	}
}

/**
 * Files dropped on the question box.
 *
 * Every dropped file is attached: the composer takes a list, and a
 * reader who drops three pictures means three pictures.
 */
async function onDrop(event) {
	event.preventDefault();
	dragCounter = 0;
	dragOver.value = false;
	noticeText.value = "";
	const files = event.dataTransfer && event.dataTransfer.files;
	if (!files || !files.length) return;
	await attachFiles(Array.from(files));
}

function onDragEnter(event) {
	event.preventDefault();
	dragCounter += 1;
	dragOver.value = true;
}

function onDragLeave(event) {
	event.preventDefault();
	dragCounter = Math.max(0, dragCounter - 1);
	if (dragCounter === 0) dragOver.value = false;
}

function onDragOver(event) {
	event.preventDefault();
}

function removeFile(index) {
	noticeText.value = "";
	emit(
		"update:files",
		props.files.filter((_, i) => i !== index),
	);
}

/**
 * Open the file picker.
 *
 * The paperclip goes straight to the browser's own picker: the reader
 * has said they want to attach something, and asking them again — with
 * a card, a destination and three choices — is a second question
 * between the reader and the thing they meant to do.
 */
function openFilePicker() {
	if (!props.canChat) return;
	noticeText.value = "";
	if (fileInput.value) fileInput.value.click();
}

/**
 * Read a file into a data URL.
 *
 * The bytes travel with the turn, because that is what a vision-capable
 * provider can read, and the same bytes are stored as a Frappe File so
 * the picture outlives the request.
 *
 * @param {File} file the file the reader chose
 * @returns {Promise<string>} the data URL
 */
function readAsDataUrl(file) {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = () => reject(new Error(__("The file could not be read.")));
		reader.readAsDataURL(file);
	});
}

/**
 * Store one attached file as a private Frappe File, and return it.
 *
 * The file is stored right away, so it lands under Home/Albanna before
 * the turn is sent: the same bytes still travel with the turn as a data
 * URL for the model, and the stored address is what the reader can
 * later set on a document.
 *
 * The file is *not* added to the composer's list here.  The list is the
 * caller's to write, once, with every file it managed to store — see
 * {@link attachFiles}.
 *
 * @param {File} file the file the reader chose
 * @returns {Promise<object|null>} the attachment, or null when it was refused
 */
async function storeFile(file) {
	if (!props.imageSupport || !props.attachableTypes.length) {
		// The site has not said which files it takes, so there is no file
		// this browser may attach.  The sentence is the site's own: from
		// the reader's side, a site that cannot attach is a site where
		// attachments are not enabled.
		noticeText.value = __("Image attachments are not enabled on this site.");
		return null;
	}
	const maxBytes = props.maxImageSizeKb > 0 ? props.maxImageSizeKb * 1024 : 0;
	const refusal = checkAttachment(file, { types: attachableMimes.value, maxBytes });
	if (!refusal.ok) {
		noticeText.value =
			refusal.reason === REFUSED_SIZE
				? __("The file is larger than {0} KB.", [props.maxImageSizeKb])
				: __("Only {0} files can be attached.", [attachableNames.value.join(", ")]);
		return null;
	}

	noticeText.value = "";
	uploadsInFlight += 1;
	uploading.value = true;

	try {
		const dataUrl = await readAsDataUrl(file);
		const result = await window.frappe.call({
			method: "albanna.api.widget.upload_file",
			args: { file_data_url: dataUrl },
			silent: true,
		});
		const message = result && result.message;
		const fileUrl = message && message.file_url;
		if (!fileUrl) throw new Error(__("The file could not be stored."));

		return makeAttachment({
			dataUrl,
			name: file.name || __("Attached file"),
			type: file.type || "",
			size: file.size || 0,
			fileUrl,
			stored: true,
		});
	} catch (error) {
		noticeText.value = serverMessage(error) || __("The file could not be stored.");
		return null;
	} finally {
		uploadsInFlight -= 1;
		uploading.value = uploadsInFlight > 0;
	}
}

/**
 * Attach a list of files.
 *
 * The composer's own list is read once, at the end, and every file that
 * was stored is added to it in one go.  A file that refused is left
 * out, and the reason it refused is on the notice beside the chips.
 *
 * Each upload finishes at its own time, and each one adds to the *same*
 * list: writing the list after every file would let the second upload
 * overwrite the first, and a reader who dropped three pictures would
 * find one of them gone.
 *
 * @param {File[]} fileList the files the reader chose
 */
async function attachFiles(fileList) {
	const added = await storeAll(fileList, storeFile, (entries) => {
		// The composer's own list is read once, here, and written once,
		// with every file that was stored.
		emit("update:files", [...props.files, ...entries]);
	});
	if (!added.length) return;
	// The reader has attached their files and is about to ask about
	// them, so the question box is where the cursor belongs.
	nextTick(() => {
		if (inputEl.value) inputEl.value.focus();
	});
}

async function onChooseFile() {
	const file = fileInput.value && fileInput.value.files && fileInput.value.files[0];
	if (file) await attachFiles([file]);
	// The input's own value, not the ref's: the ref is the element, and
	// emptying the ref would leave the button with nothing to open.
	if (fileInput.value) fileInput.value.value = "";
}
</script>

<template>
	<div class="albanna-chat__composer">
		<div v-if="files.length || uploading || noticeText" class="albanna-chat__attach-chips">
			<span v-if="noticeText" class="albanna-chat__attach-notice">{{ noticeText }}</span>
			<span
				v-for="(file, index) in files"
				:key="index"
				class="albanna-chat__attach-chip"
				:class="{ 'albanna-chat__attach-chip--stored': file.stored }"
			>
				<span
					class="albanna-chat__attach-chip-icon"
					:class="{
						'albanna-chat__attach-chip-icon--attachments': file.type.startsWith('image/'),
					}"
					aria-hidden="true"
				>
					<svg
						v-if="file.type.startsWith('image/')"
						width="12"
						height="12"
						viewBox="0 0 24 24"
						fill="none"
					>
						<rect
							x="3"
							y="3"
							width="18"
							height="18"
							rx="2"
							ry="2"
							stroke="currentColor"
							stroke-width="2"
						/>
						<circle cx="8.5" cy="8.5" r="1.5" stroke="currentColor" stroke-width="2" />
						<path
							d="M21 15l-5-5L5 21"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
					<svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none">
						<path
							d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
							stroke="currentColor"
							stroke-width="2"
							stroke-linejoin="round"
						/>
						<polyline
							points="14 2 14 8 20 8"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</span>
				<span class="albanna-chat__attach-chip-name">{{
					file.name.length > 24 ? file.name.slice(0, 24) + "…" : file.name
				}}</span>
				<span class="albanna-chat__attach-chip-size"
					>{{ (file.size / 1024).toFixed(1) }} KB</span
				>
				<span
					v-if="file.stored"
					class="albanna-chat__attach-chip-stored"
					aria-hidden="true"
				>
					<svg width="10" height="10" viewBox="0 0 24 24" fill="none">
						<polyline
							points="20 6 9 17 4 12"
							stroke="currentColor"
							stroke-width="3"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
				</span>
				<button
					type="button"
					class="albanna-chat__attach-chip-remove"
					:aria-label="__('Remove attachment')"
					@click="removeFile(index)"
				>
					×
				</button>
			</span>
			<span v-if="uploading" class="albanna-chat__attach-uploading">{{
				__("Uploading…")
			}}</span>
		</div>
		<div
			class="albanna-chat__field"
			:class="{ 'albanna-chat__field--dragover': dragOver }"
			@drop="onDrop"
			@dragover="onDragOver"
			@dragenter="onDragEnter"
			@dragleave="onDragLeave"
		>
			<textarea
				ref="inputEl"
				class="albanna-chat__input"
				rows="1"
				:value="modelValue"
				:placeholder="__('Ask about your data…')"
				:disabled="!canChat"
				:aria-label="__('Your question')"
				aria-describedby="albanna-chat__hint"
				@input="emit('update:modelValue', $event.target.value)"
				@keydown="onKeydown"
				@paste="onPaste"
			></textarea>
			<button
				v-if="speechSupported"
				type="button"
				class="albanna-chat__voice"
				:class="{ 'albanna-chat__voice--listening': listening }"
				:disabled="!canChat || busy"
				:aria-label="listening ? __('Stop listening') : __('Voice input')"
				:title="listening ? __('Stop listening') : __('Voice input')"
				@click="toggleVoice"
			>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
					<path
						d="M19 10v2a7 7 0 0 1-14 0v-2"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
					<line
						x1="12"
						y1="19"
						x2="12"
						y2="23"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
					/>
					<line
						x1="8"
						y1="23"
						x2="16"
						y2="23"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
					/>
				</svg>
			</button>
			<!-- The attachment button.  It is a peer of the microphone and
			     the send button: a round, quiet mark that says what it
			     does.  It goes straight to the browser's own picker —
			     the reader has said they want to attach something, and
			     a second question between them and that is a second
			     question too many. -->
			<button
				v-if="imageSupport"
				type="button"
				class="albanna-chat__attach"
				:class="{ 'albanna-chat__attach--filled': files.length }"
				:disabled="!canChat"
				:aria-label="__('Attach file')"
				:title="__('Attach file')"
				@click="openFilePicker"
			>
				<svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
				</svg>
				<!-- The count of what is attached.  It is decoration: the
				     chips above the composer already name every file, so
				     the number here is for the eye and not for a screen
				     reader. -->
				<span v-if="files.length" class="albanna-chat__attach-count" aria-hidden="true">{{
					files.length
				}}</span>
			</button>
			<input
				ref="fileInput"
				type="file"
				:accept="attachableMimes.join(',')"
				class="albanna-chat__file-input"
				@change="onChooseFile"
			/>
			<button
				type="button"
				class="albanna-chat__send"
				:class="{ 'albanna-chat__send--stop': busy }"
				:disabled="!busy && (!canChat || (!modelValue.trim() && !props.files.length))"
				:aria-label="busy ? __('Stop') : __('Send')"
				:title="busy ? __('Stop') : __('Send')"
				@click="onAction"
			>
				<svg
					v-if="!busy"
					width="15"
					height="15"
					viewBox="0 0 24 24"
					fill="none"
					aria-hidden="true"
				>
					<path
						d="M12 19V5m0 0-6 6m6-6 6 6"
						stroke="currentColor"
						stroke-width="2.2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
				</svg>
				<svg
					v-else
					width="12"
					height="12"
					viewBox="0 0 24 24"
					fill="currentColor"
					aria-hidden="true"
				>
					<rect x="5" y="5" width="14" height="14" rx="2" />
				</svg>
			</button>
		</div>
		<p id="albanna-chat__hint" class="albanna-chat__hint">
			{{ __("Enter to send or stop · Shift+Enter for a new line") }}
		</p>
	</div>
</template>
