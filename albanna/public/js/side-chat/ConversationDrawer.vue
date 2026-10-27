<script setup>
/**
 * The conversation drawer.
 *
 * A view inside the panel, not a second panel: the panel is a column of the
 * Desk, and a drawer floating over it would be a second floating thing on a
 * page that already has one.  So the drawer takes the panel's place, and
 * the header's back button returns to the transcript.
 */
import { computed, nextTick, ref, watch } from "vue";
import { readablePage, relativeTime } from "./format.mjs";
import { groupByDate } from "./groups.mjs";

const props = defineProps({
	/** The conversations, newest first. */
	conversations: { type: Array, default: () => [] },
	/** True while the list is being fetched. */
	loading: { type: Boolean, default: false },
	/** The conversation currently open in the transcript, if any. */
	active: { type: String, default: "" },
	/** Whether more conversations may be loaded. */
	hasMore: { type: Boolean, default: false },
	/** Whether more conversations are being loaded. */
	loadingMore: { type: Boolean, default: false },
	/** The current search term (controlled by the parent). */
	search: { type: String, default: "" },
});

const emit = defineEmits(["open", "rename", "remove", "new", "back", "loadmore", "pin", "search"]);

const searchInput = ref(props.search);

watch(
	() => props.search,
	(value) => {
		searchInput.value = value;
	},
);

const onSearchInput = (event) => {
	const value = event.target.value || "";
	searchInput.value = value;
	emit("search", value);
};

const editing = ref("");

/**
 * The conversations, grouped by the day they were last used.
 *
 * A drawer that lists thirty conversations in one column is a list the
 * reader scans rather than reads.  Grouping them by day turns it into
 * something a person can navigate.
 */
const groups = computed(() => groupByDate(props.conversations));

/**
 * The heading of a group, in the reader's language.
 *
 * @param {string} key the group's key
 * @returns {string} the heading
 */
function groupLabel(key) {
	switch (key) {
		case "today":
			return __("Today");
		case "yesterday":
			return __("Yesterday");
		case "week":
			return __("This week");
		default:
			return __("Earlier");
	}
}

function startRename(conversation) {
	editing.value = conversation.name;
}

function cancelRename() {
	editing.value = "";
}

/**
 * The focus follows the list.
 *
 * The drawer is shown while its list is still being fetched, so the
 * focus cannot be moved when the view changes — there is nothing to move
 * it to yet.  It is moved when the list arrives.
 */
watch(
	() => props.conversations,
	async (rows) => {
		if (!rows || !rows.length) return;
		await nextTick();
		const first = document.querySelector(".albanna-drawer__title");
		if (first) first.focus();
	},
);

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

		<!--
			The search box stays while a search is on, even one that matched
			nothing.  A reader who typed the wrong word has to be able to
			correct it without closing the drawer and hunting for the button
			again.  And the search is a server-side one: an empty list means
			nothing matched, not that the reader has no conversations.
		-->
		<div
			v-if="!loading && (conversations.length || searchInput.trim())"
			class="albanna-drawer__search"
		>
			<input
				type="search"
				class="albanna-drawer__search-input"
				:placeholder="__('Search conversations…')"
				:aria-label="__('Search conversations')"
				:value="searchInput"
				@input="onSearchInput"
			/>
		</div>

		<div
			v-if="!loading && !conversations.length && !searchInput.trim()"
			class="albanna-drawer__empty"
		>
			<p class="albanna-drawer__empty-title">{{ __("No conversations yet") }}</p>
			<p class="albanna-drawer__empty-detail">
				{{ __("Questions you ask will be listed here.") }}
			</p>
		</div>

		<div
			v-if="!loading && !conversations.length && searchInput.trim()"
			class="albanna-drawer__empty"
		>
			<p class="albanna-drawer__empty-title">{{ __("No matches") }}</p>
			<p class="albanna-drawer__empty-detail">
				{{ __("No conversations match “{0}”.", [searchInput]) }}
			</p>
		</div>

		<div v-if="!loading && conversations.length" class="albanna-drawer__list">
			<section v-for="group in groups" :key="group.key" class="albanna-drawer__group">
				<h3 class="albanna-drawer__group-title">{{ groupLabel(group.key) }}</h3>
				<ul class="albanna-drawer__group-list">
					<li
						v-for="conversation in group.conversations"
						:key="conversation.name"
						class="albanna-drawer__item"
						:class="{
							'albanna-drawer__item--active': conversation.name === props.active,
						}"
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
								<span v-if="conversation.turns">{{
									__(" {0} turn(s)", [conversation.turns])
								}}</span>
							</p>
						</div>

						<div class="albanna-drawer__actions">
							<button
								type="button"
								class="albanna-drawer__action"
								:aria-label="conversation.pinned ? __('Unpin') : __('Pin')"
								:title="conversation.pinned ? __('Unpin') : __('Pin')"
								@click="emit('pin', conversation, !conversation.pinned)"
							>
								<svg
									v-if="conversation.pinned"
									width="14"
									height="14"
									viewBox="0 0 16 16"
									fill="currentColor"
									aria-hidden="true"
								>
									<path d="M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1 0 .707l-1.414 1.414a.5.5 0 0 1-.707 0L11.5 6.428 7.586 10.34l-.354 2.475a.5.5 0 0 1-.854.293L3.55 10.28l-2.475.354a.5.5 0 0 1-.293-.854l2.475-.354L7.17 5.5l-1.51-1.51a.5.5 0 0 1 0-.707L7.075 1.87a.5.5 0 0 1 .707 0l2.046 2.047Z" />
								</svg>
								<svg
									v-else
									width="14"
									height="14"
									viewBox="0 0 16 16"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									aria-hidden="true"
								>
									<path d="M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1 0 .707l-1.414 1.414a.5.5 0 0 1-.707 0L11.5 6.428 7.586 10.34l-.354 2.475a.5.5 0 0 1-.854.293L3.55 10.28l-2.475.354a.5.5 0 0 1-.293-.854l2.475-.354L7.17 5.5l-1.51-1.51a.5.5 0 0 1 0-.707L7.075 1.87a.5.5 0 0 1 .707 0l2.046 2.047Z" />
								</svg>
							</button>
							<button
								type="button"
								class="albanna-drawer__action"
								:aria-label="__('Rename')"
								:title="__('Rename')"
								@click="startRename(conversation)"
							>
								<svg
									width="14"
									height="14"
									viewBox="0 0 24 24"
									fill="none"
									aria-hidden="true"
								>
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
								<svg
									width="14"
									height="14"
									viewBox="0 0 24 24"
									fill="none"
									aria-hidden="true"
								>
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
			</section>
			<button
				v-if="hasMore"
				type="button"
				class="albanna-drawer__loadmore"
				:disabled="loadingMore"
				@click="emit('loadmore')"
			>
				{{ loadingMore ? __("Loading…") : __("Load more") }}
			</button>
		</div>
	</div>
</template>
