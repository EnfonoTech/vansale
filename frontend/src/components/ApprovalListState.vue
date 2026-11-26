<script setup lang="ts">
/**
 * The frame the My requests, Sent back and History tabs share: while the
 * list is loading, when it failed, when the phone is offline, when it is
 * empty, and the notice above a list that is shown but may be old. The rows
 * themselves go in the default slot.
 */
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import Icon from "./Icon.vue";

type IconName = InstanceType<typeof Icon>["$props"]["name"];

const props = defineProps<{
  loading: boolean;
  /** The last load's failure, as the server worded it. */
  error: string | null;
  /** An answer has arrived at least once, so an empty list is really empty. */
  loaded: boolean;
  /** How many rows the slot holds. */
  count: number;
  offline: boolean;
  icon: IconName;
  emptyTitle: string;
  emptyHint?: string;
}>();
defineEmits<{ (e: "retry"): void }>();

const { t } = useI18n();

type Mode = "list" | "skeleton" | "error" | "offline" | "empty";

const mode = computed<Mode>(() => {
  if (props.count > 0) return "list";
  if (props.loading) return "skeleton";
  if (props.error) return "error";
  if (props.offline && !props.loaded) return "offline";
  if (props.loaded) return "empty";
  return "skeleton";
});

/** The line above a list that is on screen: why it may not be current. */
const notice = computed(() => {
  if (mode.value !== "list") return "";
  if (props.offline) return t("approvalsLists.state.offlineOld");
  if (props.error) return t("approvalsLists.state.failedOld");
  return "";
});
</script>

<template>
  <div class="list-state">
    <p v-if="notice" class="notice" role="status" :data-tone="error && !offline ? 'danger' : 'warning'">
      <span>{{ notice }}</span>
      <button v-if="error && !offline" type="button" class="ghost small" @click="$emit('retry')">
        {{ t("approvalsLists.state.retry") }}
      </button>
    </p>

    <slot v-if="mode === 'list'" />

    <div v-else-if="mode === 'skeleton'" class="stack" role="status" aria-busy="true" :aria-label="t('approvalsLists.state.loading')">
      <div class="skeleton" style="height: 4.25rem" />
      <div class="skeleton" style="height: 4.25rem" />
      <div class="skeleton" style="height: 4.25rem" />
    </div>

    <div v-else-if="mode === 'error'" class="empty" role="alert">
      <Icon name="alert" :size="32" class="empty-icon" />
      <strong>{{ t("approvalsLists.state.loadFailed") }}</strong>
      <span class="muted small">{{ error }}</span>
      <button type="button" @click="$emit('retry')">
        <Icon name="refresh" :size="16" /> {{ t("approvalsLists.state.retry") }}
      </button>
    </div>

    <div v-else-if="mode === 'offline'" class="empty" role="status">
      <Icon name="wifi-off" :size="32" class="empty-icon" />
      <strong>{{ t("approvalsLists.state.offline") }}</strong>
    </div>

    <div v-else class="empty">
      <Icon :name="icon" :size="32" class="empty-icon" />
      <strong>{{ emptyTitle }}</strong>
      <span v-if="emptyHint" class="muted small">{{ emptyHint }}</span>
    </div>
  </div>
</template>

<style scoped>
.list-state { display: flex; flex-direction: column; gap: 0.75rem; }
.notice {
  margin: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  background: var(--warning-soft);
  color: var(--warning);
}
.notice[data-tone="danger"] { background: var(--danger-soft); color: var(--danger); }
.notice .ghost { color: inherit; flex-shrink: 0; }
</style>
