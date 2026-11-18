<script setup lang="ts">
/**
 * History: the decisions the user took, and the outcome of documents they
 * submitted, with a date range and a transaction filter. Tapping a row opens
 * the read-only detail. Loads its own data on mount; needs no van setup.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useOnline } from "@/app/online";
import { useApprovalsStore } from "@/stores/approvals";
import { dateRangeReversed, mergeTransactions, type TransactionOption } from "@/features/approvals/lists";
import type { HistoryRow } from "@/api/approvals";
import ApprovalListState from "./ApprovalListState.vue";
import Icon from "./Icon.vue";

const { t } = useI18n();
const router = useRouter();
const store = useApprovalsStore();
const online = useOnline();

/** The page size asked for; a full page says there may be older rows. */
const LIMIT = 100;

const from = ref("");
const to = ref("");
const transaction = ref("");
/** Every transaction seen so far, so choosing one does not empty the dropdown. */
const options = ref<TransactionOption[]>([]);
/** The first answer of this visit has arrived: until then rows left by an earlier visit are not shown. */
const settled = ref(false);

const reversed = computed(() => dateRangeReversed(from.value, to.value));
const filtered = computed(() => !!from.value || !!to.value || !!transaction.value);
/** Rows from an earlier visit may belong to other filters, so they wait for this visit's answer (offline they are all there is). */
const rows = computed<HistoryRow[]>(() => (settled.value || !online.value ? store.history : []));

async function reload(): Promise<void> {
  if (reversed.value) return;
  await store.loadHistory({
    fromDate: from.value,
    toDate: to.value,
    transaction: transaction.value,
    limit: LIMIT,
  });
  settled.value = true;
}

onMounted(reload);
watch([from, to, transaction], () => void reload());
watch(
  () => store.history,
  (history) => {
    options.value = mergeTransactions(options.value, history);
  },
  { immediate: true },
);
watch(online, (now) => {
  if (now && (!store.lists.history.loaded || store.lists.history.error)) void reload();
});
defineExpose({ reload });

function clear() {
  from.value = "";
  to.value = "";
  transaction.value = "";
}

function open(row: HistoryRow) {
  void router.push({ name: "approval-detail", params: { doctype: row.doctype, name: row.docname } });
}

/** "Pending → Approved", or just the one state when it has not moved. */
function stateText(row: HistoryRow): string {
  if (!row.action_state || row.action_state === row.current_state) return row.current_state;
  return t("approvalsLists.history.stateChange", { from: row.action_state, to: row.current_state });
}
</script>

<template>
  <div class="history">
    <div class="filters" role="group" :aria-label="t('approvalsLists.history.filtersLabel')">
      <label class="field">
        <span class="label">{{ t("approvalsLists.history.from") }}</span>
        <input v-model="from" type="date" :max="to || undefined" />
      </label>
      <label class="field">
        <span class="label">{{ t("approvalsLists.history.to") }}</span>
        <input v-model="to" type="date" :min="from || undefined" />
      </label>
      <label class="field wide">
        <span class="label">{{ t("approvalsLists.history.transaction") }}</span>
        <select v-model="transaction">
          <option value="">{{ t("approvalsLists.history.allTransactions") }}</option>
          <option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <button v-if="filtered" type="button" class="ghost small clear" @click="clear">
        <Icon name="x" :size="14" /> {{ t("approvalsLists.history.clear") }}
      </button>
    </div>
    <p v-if="reversed" class="error" role="alert">{{ t("approvalsLists.history.rangeReversed") }}</p>

    <ApprovalListState
      :loading="store.lists.history.loading"
      :error="store.lists.history.error"
      :loaded="settled || store.lists.history.loaded"
      :count="rows.length"
      :offline="!online"
      icon="receipt"
      :empty-title="filtered ? t('approvalsLists.history.emptyFilteredTitle') : t('approvalsLists.history.emptyTitle')"
      :empty-hint="filtered ? t('approvalsLists.history.emptyFilteredHint') : t('approvalsLists.history.emptyHint')"
      @retry="reload"
    >
      <ul class="rows">
        <li v-for="row in rows" :key="row.name">
          <button
            type="button"
            class="row"
            :aria-label="t('approvalsLists.history.open', { name: row.docname })"
            @click="open(row)"
          >
            <span class="body">
              <span class="head">
                <strong class="doc">{{ row.docname }}</strong>
                <span class="when">{{ row.date }}</span>
              </span>
              <span class="sub">{{ row.transaction || row.doctype }}</span>
              <span class="meta">
                <span v-if="stateText(row)" class="pill" data-tone="primary">{{ stateText(row) }}</span>
                <span v-if="row.completed_by" class="tag">
                  <Icon name="user" :size="12" />
                  {{ t("approvalsLists.history.by", { name: row.completed_by }) }}<template v-if="row.role"> · {{ row.role }}</template>
                </span>
              </span>
            </span>
            <Icon name="chevron-right" :size="16" class="go" />
          </button>
        </li>
      </ul>
      <p v-if="rows.length >= LIMIT" class="limit muted">
        {{ t("approvalsLists.history.limitNote", { limit: LIMIT }) }}
      </p>
    </ApprovalListState>
  </div>
</template>

<style scoped>
.history { display: flex; flex-direction: column; gap: 0.75rem; }

.filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
  align-items: end;
}
.field { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.field.wide { grid-column: 1 / -1; }
.label { font-size: var(--text-xs); font-weight: 600; color: var(--text-muted); }
.clear { grid-column: 1 / -1; justify-self: start; }

.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.row {
  all: unset;
  box-sizing: border-box;
  width: 100%;
  cursor: pointer;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.75rem;
  padding: 0.7rem 0.85rem;
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  text-align: start;
  transition: transform var(--dur-fast) var(--ease);
}
.row:active { transform: scale(0.99); }
.row:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.body { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.doc { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.when { font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
.sub { font-size: var(--text-sm); color: var(--text-muted); }
.meta { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.25rem; align-items: center; }
.tag {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1rem 0.5rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  background: var(--surface-sunk);
  color: var(--text-muted);
}
.go { color: var(--text-faint); }
[dir="rtl"] .go { transform: scaleX(-1); }
.limit { margin: 0.25rem 0 0; font-size: var(--text-xs); text-align: center; }
</style>
