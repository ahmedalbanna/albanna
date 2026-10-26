<script setup>
/**
 * The composer: the question box, the send button, and the hint.
 */
import { nextTick, onMounted, ref, watch } from "vue";

const props = defineProps({
	modelValue: { type: String, default: "" },
	busy: { type: Boolean, default: false },
	canChat: { type: Boolean, default: false },
	image: { type: String, default: "" },
	imageSupport: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "send", "stop", "update:image"]);

const inputEl = ref(null);
const fileInput = ref(null);

const speechSupported = ref(
	typeof window !== "undefined" &&
		!!(window.SpeechRecognition || window.webkitSpeechRecognition),
);
const listening = ref(false);
let recognition = null;

function toggleVoice() {
	if (!speechSupported.value || props.busy || !props.canChat) return;
	if (listening.value) {
		if (recognition) recognition.stop();
		return;
	}
	const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
	recognition = new Ctor();
	recognition.continuous = false;
	recognition.interimResults = true;
	recognition.lang = (window.frappe && window.frappe.boot && window.frappe.boot.lang) || "en-US";
	let finalText = props.modelValue || "";
	recognition.onresult = (event) => {
		let interim = "";
		for (let i = event.resultIndex; i < event.results.length; i++) {
			const transcript = event.results[i][0].transcript;
			if (event.results[i].isFinal) {
				finalText = (finalText ? finalText + " " : "") + transcript;
			} else {
				interim += transcript;
			}
		}
		emit("update:modelValue", finalText + (interim ? " " + interim : ""));
	};
	recognition.onend = () => {
		listening.value = false;
		emit("update:modelValue", finalText.trim());
	};
	recognition.onerror = () => {
		listening.value = false;
	};
	listening.value = true;
	try {
		recognition.start();
	} catch (error) {
		listening.value = false;
	}
}

const MAX_HEIGHT = 140;
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

function resize() {
	const el = inputEl.value;
	if (!el) return;
	el.style.height = "auto";
	el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

watch(() => props.modelValue, () => nextTick(resize));
onMounted(resize);

function onKeydown(event) {
	if (event.key === "Enter" && !event.shiftKey) {
		event.preventDefault();
		submit();
	}
}

function submit() {
	if (props.busy || !props.canChat) return;
	const question = (props.modelValue || "").trim();
	if (!question && !props.image) return;
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

function attachFile(file) {
	if (!file || !file.type.startsWith("image/")) return;
	if (file.size > MAX_IMAGE_BYTES) {
		emit("update:image", "");
		return;
	}
	const reader = new FileReader();
	reader.onload = () => {
		emit("update:image", String(reader.result || ""));
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
	const files = event.dataTransfer && event.dataTransfer.files;
	if (files && files.length) attachFile(files[0]);
}

function onDragOver(event) {
	event.preventDefault();
}

function removeImage() {
	emit("update:image", "");
}

function openFilePicker() {
	if (fileInput.value) fileInput.value.click();
}
</script>

<template>
	<div class="albanna-chat__composer">
		<div v-if="image" class="albanna-chat__attach-preview">
			<img :src="image" alt="" class="albanna-chat__attach-thumb" />
			<button
				type="button"
				class="albanna-chat__attach-remove"
				:aria-label="__('Remove image')"
				@click="removeImage"
			>
				×
			</button>
		</div>
		<div
			class="albanna-chat__field"
			@drop="onDrop"
			@dragover="onDragOver"
		>
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
					<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
					<path d="M19 10v2a7 7 0 0 1-14 0v-2" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
					<line x1="12" y1="19" x2="12" y2="23" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
					<line x1="8" y1="23" x2="16" y2="23" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
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
					<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
				</svg>
			</button>
			<input
				ref="fileInput"
				type="file"
				accept="image/*"
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