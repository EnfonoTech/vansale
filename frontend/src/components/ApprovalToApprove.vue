<script setup lang="ts">
/**
 * The To approve tab: the documents waiting on the user, then those waiting
 * on others (shown for the count, nothing to press).
 *
 * The inbox lives in the approvals store; this only filters it (area chip,
 * search text) and lays it out. The sections keep the order the server sent,
 * which is Permission Manager's own: its categories, urgency first.
 *
 * Offline it shows the saved list with when it was fetched. A failed fetch
 * with a list on screen keeps the list and says so.
 *
 * Selection (a long press, or Select): tick documents that can be decided
 * together, then take one action on all of them. `bulkShared` says which
 * documents may join and which actions the bar offers; the others are greyed
 * with the reason. An action never applies at once: it opens the confirm
 * sheet, which lists every document and takes the second tap. Approvals need
 * a connection, so selection cannot start offline and the bar's buttons stop
 * if the connection drops.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { ActionFlag, ApprovalItem } from "@/api/approvals";
import { useOnline } from "@/app/online";
import { filterItems } from "@/features/approvals/filter";
import {
  BULK_MAX,
  actionTone,
  areaCounts,
  blockedReason,
  filterSections,
  formatStamp,
  itemKey,
  parseServerTime,
} from "@/features/approvals/inbox";
import { bulkShared } from "@/features/approvals/rules";
import { useApprovalsStore } from "@/stores/approvals";
import ApprovalCard from "@/components/ApprovalCard.vue";
import BulkConfirmSheet from "@/components/BulkConfirmSheet.vue";
import Icon from "@/components/Icon.vue";
import ListSearch from "@/components/ListSearch.vue";

const AREAS = ["All", "Accounts", "Purchase", "Sales", "Masters"] as const;

const { t, locale } = useI18n();
const router = useRouter();
const store = useApprovalsStore();
const online = useOnline();

const area = ref<string>("All");
const search = ref("");

const inbox = computed(() => store.inbox);
const filter = computed(() => ({ area: area.value, query: search.value }));
const sections = computed(() => filterSections(inbox.value?.sections ?? [], filter.value));
const waiting = computed(() => filterItems(inbox.value?.waiting_items ?? [], filter.value));
const everything = computed<ApprovalItem[]>(() => [
  ...(inbox.value?.sections.flatMap((section) => section.items) ?? []),
  ...(inbox.value?.waiting_items ?? []),
]);
const counts = computed(() => areaCounts(everything.value));
const shownCount = computed(
  () => sections.value.reduce((sum, section) => sum + section.items.length, 0) + waiting.value.length,
);

const stats = computed(() => ({
  needsYou: store.counts?.needs_you ?? inbox.value?.needs_you ?? 0,
  high: store.counts?.high ?? inbox.value?.stats.high ?? 0,
  overdue: store.counts?.overdue ?? inbox.value?.stats.overdue ?? 0,
}));

const firstLoad = computed(() => store.loading && !inbox.value);
const failed = computed(() => Boolean(store.error) && online.value);

/** When the list on screen was fetched, in the phone's clock and the app's language. */
const fetchedAt = computed(() => {
  const when = parseServerTime(inbox.value?.fetched_at);
  return when ? formatStamp(when, locale.value) : "";
});
const showStamp = computed(() => Boolean(fetchedAt.value) && (store.stale || !online.value));

// --- selection --------------------------------------------------------------

const selecting = ref(false);
/** Keys of the ticked documents, in the order they were ticked. */
const chosen = ref<string[]>([]);

/** The documents that wait on the user: only these can be selected. */
const needsYou = computed(() => inbox.value?.sections.flatMap((section) => section.items) ?? []);
const selectedItems = computed<ApprovalItem[]>(() => {
  const byKey = new Map(needsYou.value.map((item) => [itemKey(item), item]));
  return chosen.value.map((key) => byKey.get(key)).filter((item): item is ApprovalItem => Boolean(item));
});
const shared = computed(() => bulkShared(selectedItems.value));
/** Reject first, approve last (the way the buttons sit in the bar). */
const barActions = computed(() => {
  const rank = { reject: 0, other: 1, approve: 2 } as const;
  return shared.value.actions
    .map((flag, index) => ({ flag, index, tone: actionTone(flag) }))
    .sort((a, b) => rank[a.tone] - rank[b.tone] || a.index - b.index);
});

// A document someone else decided leaves the list on the next refresh: it leaves the selection too.
watch(needsYou, (items) => {
  const present = new Set(items.map(itemKey));
  if (chosen.value.some((key) => !present.has(key))) chosen.value = chosen.value.filter((key) => present.has(key));
});

// Selection needs a connection: nothing ticked can be decided without one.
const canSelect = (item: ApprovalItem) => online.value && !item.is_waiting;

function startSelecting(item?: ApprovalItem) {
  if (!online.value) return;
  selecting.value = true;
  if (item && !chosen.value.length && !blockedReason([], item)) chosen.value = [itemKey(item)];
}

function stopSelecting() {
  selecting.value = false;
  chosen.value = [];
}

function toggle(item: ApprovalItem) {
  const key = itemKey(item);
  if (chosen.value.includes(key)) {
    chosen.value = chosen.value.filter((entry) => entry !== key);
  } else if (!blockedReason(selectedItems.value, item)) {
    chosen.value = [...chosen.value, key];
  }
}

/** Why `item` may not be ticked now, worded; "" when it may (or selection is off). */
function blockText(item: ApprovalItem): string {
  if (!selecting.value || item.is_waiting) return "";
  const key = blockedReason(selectedItems.value, item);
  return key ? t(key, { max: BULK_MAX }) : "";
}

const sheet = ref<{ items: ApprovalItem[]; action: string; needsComment: boolean } | null>(null);

function runAction(flag: ActionFlag) {
  if (!online.value || !selectedItems.value.length) return;
  // The sheet keeps the documents it was opened with, whatever a refresh does behind it.
  sheet.value = {
    items: [...selectedItems.value],
    action: flag.action,
    needsComment: flag.require_comment || flag.is_return_for_correction,
  };
}

async function onDone() {
  sheet.value = null;
  stopSelecting();
  await store.refresh();
}

function open(item: ApprovalItem) {
  void router.push({ name: "approval-detail", params: { doctype: item.doctype, name: item.docname } });
}

function reload() {
  void store.refresh();
}

function categoryName(category: string): string {
  return category || t("approvalsInbox.sections.uncategorised");
}
</script>

<template>
  <div class="to-approve" :class="{ 'has-bar': selecting }">
    <div v-if="!online" class="note" data-tone="warning" role="status">
      <Icon name="wifi-off" :size="16" />
      <span>{{ t("approvalsInbox.offline.banner") }}</span>
    </div>

    <div v-if="selecting" class="selecting-head">
      <strong>{{ t("approvalsInbox.selection.count", { count: selectedItems.length }) }}</strong>
      <button type="button" class="ghost small" @click="stopSelecting">{{ t("approvalsInbox.selection.cancel") }}</button>
    </div>

    <div v-else-if="inbox" class="stats">
      <span><b>{{ stats.needsYou }}</b> {{ t("approvalsInbox.stats.needsYou") }}</span>
      <span :class="{ hot: stats.high > 0 }"><b>{{ stats.high }}</b> {{ t("approvalsInbox.stats.high") }}</span>
      <span :class="{ hot: stats.overdue > 0 }"><b>{{ stats.overdue }}</b> {{ t("approvalsInbox.stats.overdue") }}</span>
      <span class="spacer" />
      <button
        v-if="needsYou.length"
        type="button"
        class="select-btn"
        :disabled="!online"
        :title="online ? undefined : t('approvalsInbox.offline.disabled')"
        @click="startSelecting()"
      >
        {{ t("approvalsInbox.selection.select") }}
      </button>
      <button
        type="button"
        class="icon-btn"
        :disabled="!online || store.loading"
        :aria-label="t('approvalsInbox.refresh')"
        @click="reload"
      >
        <Icon name="refresh" :size="16" :class="{ spin: store.loading }" />
      </button>
    </div>
    <div v-if="showStamp" class="stamp">{{ t("approvalsInbox.offline.updated", { time: fetchedAt }) }}</div>

    <div class="chips" role="group" :aria-label="t('approvalsInbox.areas.label')">
      <button
        v-for="name in AREAS"
        :key="name"
        type="button"
        class="chip"
        :aria-pressed="area === name"
        @click="area = name"
      >
        {{ t(`approvalsInbox.areas.${name}`) }}
        <span v-if="name !== 'All' && counts[name]" class="n">{{ counts[name] }}</span>
      </button>
    </div>

    <ListSearch v-model="search" :placeholder="t('approvalsInbox.search')" />

    <div v-if="failed" class="failed" role="alert">
      <span class="error">{{ t("approvalsInbox.error.load") }}: {{ store.error }}</span>
      <button type="button" class="ghost small" @click="reload">{{ t("approvalsInbox.error.retry") }}</button>
    </div>

    <div v-if="firstLoad" class="stack">
      <div class="skeleton" style="height: 4.25rem" />
      <div class="skeleton" style="height: 4.25rem" />
      <div class="skeleton" style="height: 4.25rem" />
    </div>

    <div v-else-if="inbox && everything.length === 0" class="empty">
      <Icon name="check" :size="32" class="empty-icon" />
      <strong>{{ t("approvalsInbox.empty.title") }}</strong>
      <span>{{ t("approvalsInbox.empty.hint") }}</span>
    </div>

    <div v-else-if="inbox && shownCount === 0" class="empty">
      <Icon name="search" :size="32" class="empty-icon" />
      <strong>{{ t("approvalsInbox.empty.noMatch") }}</strong>
      <span>{{ t("approvalsInbox.empty.noMatchHint") }}</span>
    </div>

    <template v-else-if="inbox">
      <section v-for="section in sections" :key="section.category" class="group">
        <h3 class="group-h">{{ categoryName(section.category) }} · {{ section.items.length }}</h3>
        <ApprovalCard
          v-for="item in section.items"
          :key="itemKey(item)"
          :item="item"
          :selecting="selecting"
          :selected="chosen.includes(itemKey(item))"
          :blocked="blockText(item)"
          :can-select="canSelect(item)"
          @open="open"
          @toggle="toggle"
          @select="startSelecting"
        />
      </section>

      <section v-if="waiting.length" class="group">
        <h3 class="group-h">{{ t("approvalsInbox.sections.waiting") }} · {{ waiting.length }}</h3>
        <ApprovalCard v-for="item in waiting" :key="itemKey(item)" :item="item" @open="open" />
      </section>
    </template>

    <div v-if="selecting" class="bar" role="toolbar" :aria-label="t('approvalsInbox.selection.bar')">
      <div class="bar-inner">
        <span v-if="!online" class="bar-note">{{ t("approvalsInbox.offline.disabled") }}</span>
        <div class="bar-actions">
          <button
            v-for="entry in barActions"
            :key="entry.flag.action"
            type="button"
            class="act"
            :data-tone="entry.tone"
            :disabled="!online || !selectedItems.length"
            @click="runAction(entry.flag)"
          >
            {{ t("approvalsInbox.selection.action", { action: entry.flag.action, count: selectedItems.length }) }}
          </button>
          <span v-if="!barActions.length" class="bar-note">
            {{ selectedItems.length ? t("approvalsInbox.selection.noShared") : t("approvalsInbox.selection.hint") }}
          </span>
        </div>
      </div>
    </div>

    <BulkConfirmSheet
      v-if="sheet"
      :items="sheet.items"
      :action="sheet.action"
      :needs-comment="sheet.needsComment"
      @close="sheet = null"
      @done="onDone"
    />
  </div>
</template>

<style scoped>
.to-approve { display: flex; flex-direction: column; gap: 0.7rem; }
/* Room for the action bar, which floats above the bottom nav. */
.to-approve.has-bar { padding-bottom: 5.5rem; }

.note {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  background: var(--surface-sunk);
  color: var(--text-muted);
}
.note[data-tone="warning"] { background: var(--warning-soft); color: var(--warning); }

.stats {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.2rem 0.85rem;
  font-size: var(--text-sm);
  color: var(--text-muted);
}
.stats b { color: var(--text); font-variant-numeric: tabular-nums; }
.stats .hot b { color: var(--danger); }
.spacer { flex: 1; }
.select-btn {
  all: unset;
  box-sizing: border-box;
  padding: 0.3rem 0.8rem;
  border-radius: var(--radius-pill);
  background: var(--primary-soft);
  color: var(--primary);
  font-size: var(--text-sm);
  font-weight: 600;
  cursor: pointer;
}
.select-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.select-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

.selecting-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 2.1rem;
}
.stamp { margin-top: -0.35rem; font-size: var(--text-xs); color: var(--text-muted); }

.icon-btn {
  all: unset;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.1rem;
  height: 2.1rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunk);
  color: var(--text-muted);
  cursor: pointer;
}
.icon-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.icon-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.spin { animation: rotate 1.1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }

.chips { display: flex; gap: 0.4rem; overflow-x: auto; padding-block: 0.1rem; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip {
  all: unset;
  box-sizing: border-box;
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.8rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunk);
  color: var(--text-muted);
  font-size: var(--text-sm);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}
.chip:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.chip[aria-pressed="true"] { background: var(--primary); color: var(--primary-ink); }
.chip .n { font-size: var(--text-xs); opacity: 0.8; font-variant-numeric: tabular-nums; }

.failed {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
}
.failed .error { margin: 0; }

.bar {
  position: fixed;
  inset-inline: 0;
  bottom: calc(var(--bottom-nav-height) + var(--safe-bottom));
  z-index: 19;
  padding-inline: max(0.75rem, calc((100% - var(--max-content)) / 2));
  padding-block: 0.6rem;
  background: var(--surface);
  border-top: 1px solid var(--border);
  box-shadow: 0 -6px 18px rgba(15, 23, 42, 0.08);
}
.bar-inner { display: flex; flex-direction: column; gap: 0.35rem; }
.bar-actions { display: flex; gap: 0.5rem; }
.bar-note { font-size: var(--text-xs); color: var(--text-muted); }
.act {
  flex: 1;
  min-height: 2.9rem;
  font-weight: 700;
  background: var(--surface-sunk);
  color: var(--text);
}
.act[data-tone="approve"] { flex: 1.3; background: var(--success); color: #fff; }
.act[data-tone="reject"] { background: var(--danger-soft); color: var(--danger); }

.group { display: flex; flex-direction: column; gap: 0.5rem; }
.group-h {
  margin: 0.3rem 0.15rem 0;
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}
</style>
