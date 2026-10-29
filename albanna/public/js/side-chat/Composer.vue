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
	image: { type: String, default: "" },
	fileName: { type: String, default: "" },
	imageSupport: { type: Boolean, default: false },
	maxImageSizeKb: { type: Number, default: 0 },
});

const emit = defineEmits(["update:modelValue", "send", "stop", "update:image", "update:fileName"]);

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
	if (!question && !props.image) return;
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

function attachFile(file) {
	if (!file) return;
	noticeText.value = "";
	if (!props.imageSupport) {
		/* The site has images switched off.  Accepting the file and letting
		 * the server drop it later is how a user ends up believing the
		 * assistant saw a picture it never received. */
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
	uploading.value = true;
	const reader = new FileReader();
	reader.onload = () => {
		uploading.value = false;
		emit("update:image", String(reader.result || ""));
		emit("update:fileName", file.name || "");
	};
	reader.onerror = () => {
		uploading.value = false;
	};
	reader.readAsDataURL(file);
}

function onFileChange(event) {
	const file = event.target.files && event.target.files[0];
	if (file) attachFile(file);
	if (event.target) event.target.value = "";
}

function onPaste(event) {
	const items = event.clipboardData && event.clipboardData.items;
	if (!items) return;
	for (let i = 0; i < items.length; i++) {
		const item = items[i];
		if (item.kind === "file" && item.type.startsWith("image/")) {
			const file = item.getAsFile();
			if (file) {
				event.preventDefault();
				attachFile(file);
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
	attachFile(files[0]);
}

function onDragOver(event) {
	event.preventDefault();
}

function removeImage() {
	noticeText.value = "";
	emit("update:image", "");
	emit("update:fileName", "");
}

function openFilePicker() {
	if (fileInput.value) fileInput.value.click();
}
</script>

<template>
	<div class="albanna-chat__composer">
		<div v-if="image || uploading || noticeText" class="albanna-chat__attach-preview">
			<span v-if="noticeText" class="albanna-chat__attach-notice">{{ noticeText }}</span>
			<img
				v-if="image && image.startsWith('data:image/')"
				:src="image"
				alt=""
				class="albanna-chat__attach-thumb"
			/>
			<span v-else-if="image" class="albanna-chat__attach-file">
				{{ fileName || __("Attached file") }}
			</span>
			<span v-else class="albanna-chat__attach-uploading">{{ __("Uploading…") }}</span>
			<button
				v-if="image"
				type="button"
				class="albanna-chat__attach-remove"
				:aria-label="__('Remove image')"
				@click="removeImage"
			>
				×
			</button>
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
				type="button"
				class="albanna-chat__attach"
				:disabled="!canChat"
				:aria-label="__('Attach image')"
				:title="__('Attach image')"
				@click="openFilePicker"
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
				@change="onFileChange"
			/>
			<button
				type="button"
				class="albanna-chat__send"
				:class="{ 'albanna-chat__send--stop': busy }"
				:disabled="!busy && (!canChat || (!modelValue.trim() && !image))"
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
	</div>
</template>
