<script setup lang="ts">
/**
 * My requests: the documents the user raised that are still in approval,
 * with where each stands (state), who holds it, and how many days it has
 * waited. Tapping a row opens the read-only detail. Loads its own data on
 * mount; needs no van setup.
 */
import { onMounted, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useOnline } from "@/app/online";
import { useApprovalsStore } from "@/stores/approvals";
import { priorityTone } from "@/features/approvals/format";
import { ageKey } from "@/features/approvals/lists";
import type { MyRequestRow } from "@/api/approvals";
import ApprovalListState from "./ApprovalListState.vue";
import Icon from "./Icon.vue";

const { t, locale } = useI18n();
const router = useRouter();
const store = useApprovalsStore();
const online = useOnline();

/** More than this many days waiting reads as overdue (the desk's own line). */
const OVERDUE_DAYS = 30;

function reload(): Promise<void> {
  return store.loadMine();
}

onMounted(reload);
// A list that never loaded, or failed, tries again as soon as the connection is back.
watch(online, (now) => {
  if (now && (!store.lists.mine.loaded || store.lists.mine.error)) void reload();
});
defineExpose({ reload });

function age(days: number): string {
  return t(`approvalsLists.age.${ageKey(days, locale.value)}`, { n: days });
}

function holderText(row: MyRequestRow): string {
  if (row.holder) return t("approvalsLists.mine.with", { holder: row.holder });
  return row.role_id ? t("approvalsLists.mine.waitingFor", { role: row.role_id }) : "";
}

function priorityText(row: MyRequestRow): string {
  return t(`approvalsLists.priority.${priorityTone(row.priority)}`);
}

function open(row: MyRequestRow) {
  void router.push({ name: "approval-detail", params: { doctype: row.doctype, name: row.docname } });
}
</script>

<template>
  <ApprovalListState
    :loading="store.lists.mine.loading"
    :error="store.lists.mine.error"
    :loaded="store.lists.mine.loaded"
    :count="store.mine.length"
    :offline="!online"
    icon="clock"
    :empty-title="t('approvalsLists.mine.emptyTitle')"
    :empty-hint="t('approvalsLists.mine.emptyHint')"
    @retry="reload"
  >
    <ul class="rows">
      <li v-for="row in store.mine" :key="`${row.doctype}/${row.docname}`">
        <button
          type="button"
          class="row"
          :data-priority="priorityTone(row.priority)"
          :aria-label="t('approvalsLists.mine.open', { name: row.docname })"
          @click="open(row)"
        >
          <span class="body">
            <span class="head">
              <strong class="doc">{{ row.docname }}</strong>
              <span class="pill" data-tone="info">{{ row.state }}</span>
            </span>
            <span class="sub">{{ row.transaction || row.doctype }}</span>
            <span class="meta">
              <span v-if="holderText(row)" class="tag">
                <Icon name="user" :size="12" /> {{ holderText(row) }}
              </span>
              <span class="tag" :class="{ late: row.days > OVERDUE_DAYS }">
                <Icon name="clock" :size="12" /> {{ age(row.days) }}
              </span>
              <span class="tag" :data-priority="priorityTone(row.priority)">{{ priorityText(row) }}</span>
            </span>
          </span>
          <Icon name="chevron-right" :size="16" class="go" />
        </button>
      </li>
    </ul>
  </ApprovalListState>
</template>

<style scoped>
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }

/* The priority colour bar: Critical dark red, High red, Medium amber, Low green. */
.row {
  --bar: var(--warning);
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
  border-inline-start: 5px solid var(--bar);
  box-shadow: var(--shadow-sm);
  text-align: start;
  transition: transform var(--dur-fast) var(--ease);
}
.row:active { transform: scale(0.99); }
.row:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.row[data-priority="critical"] { --bar: #7a1f24; }
.row[data-priority="high"] { --bar: var(--danger); }
.row[data-priority="medium"] { --bar: var(--warning); }
.row[data-priority="low"] { --bar: var(--success); }

.body { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.doc { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: var(--text-sm); color: var(--text-muted); }
.meta { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.25rem; }
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
.tag.late { background: var(--danger-soft); color: var(--danger); }
.tag[data-priority="critical"], .tag[data-priority="high"] { background: var(--danger-soft); color: var(--danger); }
.tag[data-priority="medium"] { background: var(--warning-soft); color: var(--warning); }
.tag[data-priority="low"] { background: var(--success-soft); color: var(--success); }
.go { color: var(--text-faint); }
[dir="rtl"] .go { transform: scaleX(-1); }
</style>
