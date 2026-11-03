<script setup>
/**
 * The composer: the question box, the send button, and the hint.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { MAX_SESSION_MS, mergeTranscript, readResults, voiceErrorText } from "./voice.mjs";

const props = defineProps({
	modelValue: { type: String, default: "" },
	busy: { type: Boolean, default: false },
	canChat: { type: Boolean, default: false },
	//: The attachments the reader has chosen for this question.  Each is
	//: ``{ dataUrl, name, type, size }``; a data URL travels with the turn
	//: and the same file is stored as a Frappe File by the service.
	files: { type: Array, default: () => [] },
	imageSupport: { type: Boolean, default: false },
	maxImageSizeKb: { type: Number, default: 0 },
});

const emit = defineEmits([
	"update:modelValue",
	"update:files",
	"send",
	"stop",
]);

const inputEl = ref(null);
const fileInput = ref(null);

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
		emit("update:modelValue", finalText.trim());
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
		submit();
	}
}

function submit() {
	noticeText.value = "";
	if (props.busy || !props.canChat) return;
	const question = (props.modelValue || "").trim();
	if (!question && !props.files.length) return;
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

const ATTACHABLE_TYPES = ["image/", "application/pdf"];

async function onPaste(event) {
	const items = event.clipboardData && event.clipboardData.items;
	if (!items) return;
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		if (item.kind === "file" && (item.type.startsWith("image/") || item.type === "application/pdf")) {
			const file = item.getAsFile();
			if (file) {
				event.preventDefault();
				await storeFile(file);
				return;
			}
		}
	}
}

function onDrop(event) {
	event.preventDefault();
	noticeText.value = "";
	const files = event.dataTransfer && event.dataTransfer.files;
	if (!files || !files.length) return;
	if (files.length > 1) {
		noticeText.value = __("One file at a time — attaching the first.");
	}
	storeFile(files[0]);
}

function onDragOver(event) {
	event.preventDefault();
}

function removeFile(index) {
	noticeText.value = "";
	emit("update:files", props.files.filter((_, i) => i !== index));
}

function openFilePicker() {
	if (fileInput.value) fileInput.value.click();
}

const showUpload = ref(false);
const uploadPanelEl = ref(null);
const attachButtonEl = ref(null);

function openUpload() {
	if (!props.canChat || props.busy) return;
	showUpload.value = true;
	noticeText.value = "";
	// The panel takes the focus when it opens, so a reader who opened it
	// with the keyboard is *in* it rather than still on the button that
	// opened it.
	nextTick(() => {
		if (uploadPanelEl.value) uploadPanelEl.value.focus();
	});
}

/**
 * Close the upload panel.
 *
 * The focus goes back where it came from — but only when the reader
 * closed the panel *from* the panel.  A reader who clicked somewhere
 * else in the thread has already put their focus there, and taking it
 * back to the paperclip would be the panel grabbing the reader's hands.
 *
 * @param {boolean} restoreFocus whether to hand the focus back
 */
function closeUpload(restoreFocus = true) {
	showUpload.value = false;
	noticeText.value = "";
	if (!restoreFocus) return;
	nextTick(() => {
		if (attachButtonEl.value) attachButtonEl.value.focus();
	});
}

/**
 * A click outside the panel closes it.
 *
 * The panel is a card above the composer, not a modal over the Desk: the
 * reader is choosing where a file goes while still reading the thread,
 * the way the approval card does.  So there is no backdrop to swallow
 * the click, and this is what notices it instead.
 */
function onDocumentPointerDown(event) {
	const panel = uploadPanelEl.value;
	const button = attachButtonEl.value;
	if (panel && panel.contains(event.target)) return;
	if (button && button.contains(event.target)) return;
	closeUpload(false);
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
 * Store one attached file as a private Frappe File right away, so it lands
 * under Home/Albanna before the turn is sent.  The same bytes still travel
 * with the turn as a data URL for the model; the stored URL is what the
 * reader can later set on a document.
 */
async function storeFile(file) {
	if (!props.imageSupport) {
		noticeText.value = __("Image attachments are not enabled on this site.");
		return;
	}
	if (!ATTACHABLE_TYPES.some((t) => file.type.startsWith(t))) {
		noticeText.value = __("Only images and PDFs can be attached.");
		return;
	}
	const max = props.maxImageSizeKb > 0 ? props.maxImageSizeKb * 1024 : 0;
	if (max && file.size > max) {
		noticeText.value = __("The file is larger than {0} KB.", [props.maxImageSizeKb]);
		return;
	}

	showUpload.value = false;
	noticeText.value = "";
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

		const entry = {
			dataUrl,
			name: file.name || __("Attached file"),
			type: file.type || "",
			size: file.size || 0,
			fileUrl,
			stored: true,
		};
		emit("update:files", [...props.files, entry]);
		noticeText.value = "";
		// The reader has attached their file and is about to ask about
		// it, so the question box is where the cursor belongs.
		nextTick(() => {
			if (inputEl.value) inputEl.value.focus();
		});
	} catch (error) {
		noticeText.value = errorMessage(error) || __("The file could not be stored.");
	} finally {
		uploading.value = false;
	}
}

function errorMessage(error) {
	if (!error) return "";
	let body = error.responseJSON;
	if (!body && typeof error.responseText === "string") {
		try {
			body = JSON.parse(error.responseText);
		} catch (failure) {
			body = null;
		}
	}
	const payload = body && typeof body === "object" ? body : error;
	const messages = payload._server_messages;
	if (messages) {
		try {
			const text = messageText(JSON.parse(messages));
			if (text) return text;
		} catch (failure) {
			// Not JSON: fall through to the traceback.
		}
	}
	const exc = payload.exc;
	if (exc) {
		try {
			const parsed = JSON.parse(exc);
			if (Array.isArray(parsed) && parsed.length) {
				return lastLine(String(parsed[parsed.length - 1]));
			}
		} catch (failure) {
			return lastLine(String(exc));
		}
	}
	return "";
}

function messageText(value) {
	if (!value) return "";
	if (typeof value === "string") {
		const trimmed = value.trim();
		if (trimmed.startsWith("{")) {
			try {
				return messageText(JSON.parse(trimmed));
			} catch (failure) {
				return value;
			}
		}
		return value;
	}
	if (Array.isArray(value)) {
		for (const item of value) {
			const text = messageText(item);
			if (text) return text;
		}
		return "";
	}
	if (typeof value === "object" && value.message) {
		return String(value.message);
	}
	return "";
}

function lastLine(text) {
	const line = String(text || "")
		.trim()
		.split("\n")
		.pop() || "";
	return line.replace(/^[A-Za-z_.]*(Error|Exception):\s*/, "");
}

async function onChooseFile() {
	const file = fileInput.value && fileInput.value.files && fileInput.value.files[0];
	if (file) await storeFile(file);
	// The input's own value, not the ref's: the ref is the element, and
	// emptying the ref would leave the button with nothing to open.
	if (fileInput.value) fileInput.value.value = "";
	closeUpload();
}

async function onPasteClipboard() {
	try {
		const items = await navigator.clipboard.read();
		for (const item of items) {
			for (const type of item.types) {
				if (type.startsWith("image/") || type === "application/pdf") {
					const blob = await item.getType(type);
					await storeFile(
						new File([blob], __("Pasted file"), { type }),
					);
					break;
				}
			}
		}
	} catch (error) {
		noticeText.value = __("Could not read the clipboard.");
	}
	closeUpload();
}

function onCamera() {
	if (!fileInput.value) return;
	// The camera takes the focus away with it, so the panel is dismissed
	// without handing the focus back: the reader is choosing a file, not
	// closing a dialog.
	showUpload.value = false;
	fileInput.value.accept = "image/*";
	fileInput.value.capture = "environment";
	fileInput.value.click();
	fileInput.value.capture = "";
	fileInput.value.accept = "image/*,application/pdf";
}

/**
 * Escape closes the upload panel.
 *
 * The panel is a dialog the reader opened, so the key that closes a
 * dialog closes this one.  The listener is on the document rather than
 * on the panel, because the reader's focus may have moved to a button
 * inside it, and a key that only works when the panel itself holds the
 * focus is a key that works half the time.
 */
function onUploadKeydown(event) {
	if (event.key !== "Escape") return;
	event.preventDefault();
	closeUpload();
}

watch(showUpload, (open) => {
	if (open) {
		document.addEventListener("keydown", onUploadKeydown);
		document.addEventListener("mousedown", onDocumentPointerDown);
	} else {
		document.removeEventListener("keydown", onUploadKeydown);
		document.removeEventListener("mousedown", onDocumentPointerDown);
	}
});

onBeforeUnmount(() => {
	document.removeEventListener("keydown", onUploadKeydown);
	document.removeEventListener("mousedown", onDocumentPointerDown);
});
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
					:class="{ 'albanna-chat__attach-chip-icon--image': file.type.startsWith('image/') }"
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
				<span class="albanna-chat__attach-chip-name">{{ file.name.length > 24 ? file.name.slice(0, 24) + '…' : file.name }}</span>
				<span class="albanna-chat__attach-chip-size">{{ (file.size / 1024).toFixed(1) }} KB</span>
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
			<span v-if="uploading" class="albanna-chat__attach-uploading">{{ __("Uploading…") }}</span>
		</div>
		<div class="albanna-chat__field" @drop="onDrop" @dragover="onDragOver">
			<textarea
				ref="inputEl"
				class="albanna-chat__input"
				rows="1"
				:value="modelValue"
				:placeholder="__('Ask about your data…')"
				:disabled="!canChat"
				:aria-label="__('Your question')"
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
			<button
				v-if="imageSupport"
				ref="attachButtonEl"
				type="button"
				class="albanna-chat__attach"
				:disabled="!canChat"
				:aria-label="__('Attach file')"
				:title="__('Attach file')"
				@click="openUpload"
			>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
					<path
						d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					/>
				</svg>
			</button>
			<input
				ref="fileInput"
				type="file"
				accept="image/*,application/pdf"
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
		<p class="albanna-chat__hint">
			{{ __("Enter to send · Shift+Enter for a new line") }}
		</p>

		<!-- Upload to Frappé Files: the reader stores an attached file under
		     Home/Albanna before sending the turn, so it is already a file on
		     the site when the question is asked.  It is a card above the
		     composer and not a modal over the Desk: the thread keeps its
		     place, the way the approval card does. -->
		<div v-if="showUpload" class="albanna-chat__upload-dialog">
			<div
				ref="uploadPanelEl"
				class="albanna-chat__upload-panel"
				role="dialog"
				aria-labelledby="albanna-upload-title"
				tabindex="-1"
			>
				<div class="albanna-chat__upload-header">
					<span id="albanna-upload-title" class="albanna-chat__upload-title">{{
						__("Upload to Frappé Files")
					}}</span>
					<button
						type="button"
						class="albanna-chat__upload-close"
						@click="closeUpload"
						:aria-label="__('Close')"
					>
						×
					</button>
				</div>
				<div class="albanna-chat__upload-destination">
					<span class="albanna-chat__upload-label">{{ __("Destination") }}:</span>
					<span class="albanna-chat__upload-path">Home/Albanna</span>
				</div>
				<div class="albanna-chat__upload-actions">
					<button
						type="button"
						class="albanna-chat__upload-btn"
						@click="openFilePicker"
						:aria-label="__('Choose File')"
					>
						{{ __("Choose File") }}
					</button>
					<button
						type="button"
						class="albanna-chat__upload-btn"
						@click="onPasteClipboard"
						:aria-label="__('Paste Clipboard')"
					>
						{{ __("Paste Clipboard") }}
					</button>
					<button
						type="button"
						class="albanna-chat__upload-btn"
						@click="onCamera"
						:aria-label="__('Camera')"
					>
						{{ __("Camera") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
