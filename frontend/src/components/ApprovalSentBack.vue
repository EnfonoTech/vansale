<script setup lang="ts">
/**
 * Sent back: the documents an approver returned to the user for correction,
 * with the reason, who sent it back and how long ago. "Open and correct" goes
 * to the app's own edit screen for a Quotation, Sales Order or Sales Invoice
 * (when the user has the van app), and to the desk form for every other type,
 * for a return, and for a user without the van app. Loads its own data on mount;
 * needs no van setup.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useOnline } from "@/app/online";
import { absoluteUrl } from "@/app/platform";
import { useApprovalsStore } from "@/stores/approvals";
import { useSessionStore } from "@/stores/session";
import { ageKey, searchRows, sentBackTarget } from "@/features/approvals/lists";
import type { SentBackRow } from "@/api/approvals";
import ApprovalListState from "./ApprovalListState.vue";
import Icon from "./Icon.vue";
import ListSearch from "./ListSearch.vue";

const { t, locale } = useI18n();
const router = useRouter();
const store = useApprovalsStore();
const session = useSessionStore();
const online = useOnline();

const search = ref("");
const searching = computed(() => search.value.trim() !== "");
/** The returned documents that match the search text (all of them when it is empty). */
const rows = computed<SentBackRow[]>(() =>
  searchRows(store.sentBack, search.value, [
    "docname",
    "doctype",
    "transaction",
    "state",
    "submitted_by",
    "sent_back_by",
    "role",
    "reason",
  ]),
);
/** Rows exist but the search hides them all: say so, rather than "nothing sent back". */
const noMatch = computed(() => searching.value && store.sentBack.length > 0 && rows.value.length === 0);

function reload(): Promise<void> {
  return store.loadSentBack();
}

onMounted(reload);
watch(online, (now) => {
  if (now && (!store.lists.sentBack.loaded || store.lists.sentBack.error)) void reload();
});
defineExpose({ reload });

/** "2 days ago", or "Today". */
function ago(days: number): string {
  const key = ageKey(days, locale.value);
  const age = t(`approvalsLists.age.${key}`, { n: days });
  return key === "today" ? age : t("approvalsLists.ago", { age });
}

/** The edit screens belong to the van app: a user without it is sent to the desk form. */
function targetOf(row: SentBackRow) {
  return sentBackTarget(row, session.hasVanShell);
}

function canOpen(row: SentBackRow): boolean {
  const target = targetOf(row);
  return target.kind === "route" || !!target.url;
}

function openAndCorrect(row: SentBackRow) {
  const target = targetOf(row);
  if (target.kind === "route") {
    void router.push(target.location);
  } else if (target.url) {
    // The desk is a page of the site, not of this app (on the phone app it needs the server's address).
    window.location.assign(absoluteUrl(target.url));
  }
}
</script>

<template>
  <div class="sent-back">
    <ListSearch v-model="search" :placeholder="t('approvalsLists.search.placeholder')" />

    <ApprovalListState
      :loading="store.lists.sentBack.loading"
      :error="store.lists.sentBack.error"
      :loaded="store.lists.sentBack.loaded"
      :count="rows.length"
      :offline="!online"
      :icon="noMatch ? 'search' : store.sentBackUnavailable ? 'alert' : 'edit'"
      :empty-title="noMatch ? t('approvalsLists.search.noMatchTitle') : store.sentBackUnavailable ? t('approvalsLists.sentBack.unavailableTitle') : t('approvalsLists.sentBack.emptyTitle')"
      :empty-hint="noMatch ? t('approvalsLists.search.noMatchHint') : store.sentBackUnavailable ? t('approvalsLists.sentBack.unavailableHint') : t('approvalsLists.sentBack.emptyHint')"
      @retry="reload"
    >
      <ul class="rows">
        <li v-for="row in rows" :key="`${row.doctype}/${row.docname}`" class="card-row">
          <div class="head">
            <strong class="doc">{{ row.docname }}</strong>
            <span class="pill" data-tone="warning">{{ row.state }}</span>
          </div>
          <div class="sub">{{ row.transaction || row.doctype }}</div>

          <blockquote class="reason">
            {{ row.reason || t("approvalsLists.sentBack.noReason") }}
          </blockquote>

          <div class="meta">
            <span v-if="row.sent_back_by" class="tag warn">
              <Icon name="user" :size="12" />
              {{ t("approvalsLists.sentBack.by", { name: row.sent_back_by }) }}<template v-if="row.role"> · {{ row.role }}</template>
            </span>
            <span class="tag">
              <Icon name="clock" :size="12" /> {{ ago(row.days) }}
            </span>
          </div>

          <button type="button" class="open" :disabled="!canOpen(row)" @click="openAndCorrect(row)">
            <Icon name="edit" :size="16" /> {{ t("approvalsLists.sentBack.openAndCorrect") }}
          </button>
          <p v-if="!canOpen(row)" class="no-link">{{ t("approvalsLists.sentBack.noLink") }}</p>
        </li>
      </ul>
    </ApprovalListState>
  </div>
</template>

<style scoped>
.sent-back { display: flex; flex-direction: column; gap: 0.75rem; }
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.card-row {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem 0.85rem;
  background: var(--surface);
  border-radius: var(--radius);
  border-inline-start: 5px solid var(--warning);
  box-shadow: var(--shadow-sm);
}
.head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.doc { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: var(--text-sm); color: var(--text-muted); }
.reason {
  margin: 0.35rem 0 0;
  padding-inline-start: 0.6rem;
  border-inline-start: 3px solid var(--warning);
  font-style: italic;
  color: var(--text-muted);
  font-size: var(--text-sm);
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.meta { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.3rem; }
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
.tag.warn { background: var(--warning-soft); color: var(--warning); }
.open { margin-top: 0.5rem; min-height: 2.75rem; width: 100%; }
.no-link { margin: 0.25rem 0 0; font-size: var(--text-xs); color: var(--text-muted); }
</style>
