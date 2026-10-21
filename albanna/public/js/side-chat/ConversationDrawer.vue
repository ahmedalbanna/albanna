<script setup>
/**
 * The conversation drawer.
 *
 * A view inside the panel, not a second panel: the panel is a column of the
 * Desk, and a drawer floating over it would be a second floating thing on a
 * page that already has one.  So the drawer takes the panel's place, and
 * the header's back button returns to the transcript.
 */
import { ref } from "vue";
import { readablePage, relativeTime } from "./format.mjs";

const props = defineProps({
	/** The conversations, newest first. */
	conversations: { type: Array, default: () => [] },
	/** True while the list is being fetched. */
	loading: { type: Boolean, default: false },
	/** The conversation currently open in the transcript, if any. */
	active: { type: String, default: "" },
});

const emit = defineEmits(["open", "rename", "remove", "new", "back"]);

const editing = ref("");

function startRename(conversation) {
	editing.value = conversation.name;
}

function cancelRename() {
	editing.value = "";
}

function commitRename(conversation, event) {
	const title = (event.target.value || "").trim();
	editing.value = "";
	if (title && title !== conversation.title) {
		emit("rename", conversation.name, title);
	}
}
</script>

<template>
	<div class="albanna-drawer">
		<div v-if="loading" class="albanna-drawer__loading">{{ __("Loading…") }}</div>

		<div v-else-if="!conversations.length" class="albanna-drawer__empty">
			<p class="albanna-drawer__empty-title">{{ __("No conversations yet") }}</p>
			<p class="albanna-drawer__empty-detail">
				{{ __("Questions you ask will be listed here.") }}
			</p>
		</div>

		<ul v-else class="albanna-drawer__list">
			<li
				v-for="conversation in conversations"
				:key="conversation.name"
				class="albanna-drawer__item"
				:class="{ 'albanna-drawer__item--active': conversation.name === props.active }"
			>
				<div class="albanna-drawer__item-main">
					<input
						v-if="editing === conversation.name"
						class="albanna-drawer__rename"
						type="text"
						:value="conversation.title"
						:aria-label="__('Conversation title')"
						@keydown.enter.prevent="commitRename(conversation, $event)"
						@keydown.esc.prevent="cancelRename"
						@blur="commitRename(conversation, $event)"
					/>
					<button
						v-else
						type="button"
						class="albanna-drawer__title"
						@click="emit('open', conversation)"
					>
						{{ conversation.title || __("New conversation") }}
					</button>

					<p class="albanna-drawer__meta">
						<span v-if="readablePage(conversation.page)">{{
							readablePage(conversation.page)
						}}</span>
						<span v-if="conversation.last_activity_ts">{{
							relativeTime(conversation.last_activity_ts)
						}}</span>
					</p>
				</div>

				<div class="albanna-drawer__actions">
					<button
						type="button"
						class="albanna-drawer__action"
						:aria-label="__('Rename')"
						:title="__('Rename')"
						@click="startRename(conversation)"
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
							<path
								d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"
							/>
						</svg>
					</button>
					<button
						type="button"
						class="albanna-drawer__action albanna-drawer__action--danger"
						:aria-label="__('Delete')"
						:title="__('Delete')"
						@click="emit('remove', conversation)"
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
							<path
								d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6M10 11v6M14 11v6"
								stroke="currentColor"
								stroke-width="1.8"
								stroke-linecap="round"
								stroke-linejoin="round"
							/>
						</svg>
					</button>
				</div>
			</li>
		</ul>
	</div>
</template>
