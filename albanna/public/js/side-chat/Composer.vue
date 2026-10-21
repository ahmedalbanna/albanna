<script setup>
/**
 * The composer: the question box, the send button, and the hint.
 *
 * It is a component of its own because it owns one thing the panel does
 * not: the box grows with what is typed.  A two-line box that cannot grow
 * makes a long question a scroll inside a scroll, and the second scroll
 * is invisible — the reader does not know there is more of their own
 * question below the fold.
 *
 * The box and the button are *one* thing — a field with a button in it —
 * rather than a box with a button beside it.  A box and a button beside
 * it read as a form: something to fill in and submit.  A chat is not a
 * form; it is a place you say something, and the arrow in the corner says
 * "go" rather than "submit".
 *
 * The button is a circle of a fixed size.  It holds its size when it
 * becomes a stop, so the thing the reader is about to click does not move
 * under their cursor at the moment the turn starts.
 */
import { nextTick, onMounted, ref, watch } from "vue";

const props = defineProps({
	/** The text in the box.  The panel owns it, so a retry can refill it. */
	modelValue: { type: String, default: "" },
	/** True while a turn is running. */
	busy: { type: Boolean, default: false },
	/** False when the user may not chat at all. */
	canChat: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue", "send", "stop"]);

const inputEl = ref(null);

/** How tall the box may grow before it starts scrolling its own text. */
const MAX_HEIGHT = 140;

function resize() {
	const el = inputEl.value;
	if (!el) return;
	// `auto` first, or the box can only ever get taller: the measured
	// scrollHeight is the height it already has, and a box that has been
	// grown cannot be measured smaller without resetting it.
	el.style.height = "auto";
	el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
}

watch(
	() => props.modelValue,
	() => nextTick(resize),
);

onMounted(resize);

function onKeydown(event) {
	// Enter sends; Shift+Enter is a new line.
	if (event.key === "Enter" && !event.shiftKey) {
		event.preventDefault();
		submit();
	}
}

function submit() {
	if (props.busy || !props.canChat) return;
	const question = (props.modelValue || "").trim();
	if (!question) return;
	emit("update:modelValue", "");
	emit("send", question);
}

/**
 * What the button does.
 *
 * While a turn is running it stops it.  A disabled button is a dead end,
 * and a turn the user cannot end is the one thing in a chat that must
 * never be a dead end.
 */
function onAction() {
	if (props.busy) {
		emit("stop");
		return;
	}
	submit();
}
</script>

<template>
	<div class="albanna-chat__composer">
		<div class="albanna-chat__field">
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
			></textarea>
			<button
				type="button"
				class="albanna-chat__send"
				:class="{ 'albanna-chat__send--stop': busy }"
				:disabled="!busy && (!canChat || !modelValue.trim())"
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
