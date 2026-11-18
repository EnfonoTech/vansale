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
 */
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import type { ApprovalItem } from "@/api/approvals";
import { useOnline } from "@/app/online";
import { filterItems } from "@/features/approvals/filter";
import { areaCounts, filterSections, formatStamp, itemKey, parseServerTime } from "@/features/approvals/inbox";
import { useApprovalsStore } from "@/stores/approvals";
import ApprovalCard from "@/components/ApprovalCard.vue";
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
  <div class="to-approve">
    <div v-if="!online" class="note" data-tone="warning" role="status">
      <Icon name="wifi-off" :size="16" />
      <span>{{ t("approvalsInbox.offline.banner") }}</span>
    </div>

    <div v-if="inbox" class="stats">
      <span><b>{{ stats.needsYou }}</b> {{ t("approvalsInbox.stats.needsYou") }}</span>
      <span :class="{ hot: stats.high > 0 }"><b>{{ stats.high }}</b> {{ t("approvalsInbox.stats.high") }}</span>
      <span :class="{ hot: stats.overdue > 0 }"><b>{{ stats.overdue }}</b> {{ t("approvalsInbox.stats.overdue") }}</span>
      <span class="spacer" />
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
        <ApprovalCard v-for="item in section.items" :key="itemKey(item)" :item="item" @open="open" />
      </section>

      <section v-if="waiting.length" class="group">
        <h3 class="group-h">{{ t("approvalsInbox.sections.waiting") }} · {{ waiting.length }}</h3>
        <ApprovalCard v-for="item in waiting" :key="itemKey(item)" :item="item" @open="open" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.to-approve { display: flex; flex-direction: column; gap: 0.7rem; }

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
