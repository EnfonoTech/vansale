<script setup lang="ts">
/**
 * The second tap of a bulk decision: lists every selected document with its
 * party and amount and their total, asks for ONE shared comment when the
 * action needs it, then applies the action to the batch. The server answers
 * for each document on its own, so the sheet shows each result (green or red,
 * with the server's words) and offers Retry for the ones refused; one refusal
 * never hides the rest. Closing after anything was sent emits `done` (the
 * parent reloads the inbox); closing before that emits `close`.
 *
 * A request that fails after it was sent is NOT a refusal: the server decides
 * and commits the documents one by one, so some or all of the batch may be
 * decided already. The sheet then says the result is unknown and offers only
 * "Close and reload"; it never sends the batch a second time (a user who holds
 * two steps in a row could decide a document twice).
 *
 * Approvals need a connection and are never queued, so with no connection the
 * action stays disabled.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { applyBulk } from "@/api/approvals";
import type { ApprovalItem, BulkRow } from "@/api/approvals";
import { useOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";
import { actionTone } from "@/features/approvals/inbox";
import { bulkShared } from "@/features/approvals/rules";
import {
  BULK_LIMIT,
  bulkStateAfterFailure,
  bulkTotals,
  mergeResults,
  retryNames,
  rowStates,
} from "@/features/approvals/lists";
import type { RowState } from "@/features/approvals/lists";
import Icon from "./Icon.vue";
import SarSymbol from "./SarSymbol.vue";

const props = defineProps<{ items: ApprovalItem[]; action: string; needsComment: boolean }>();
const emit = defineEmits<{ (e: "close"): void; (e: "done"): void }>();

const { t } = useI18n();
const session = useSessionStore();
const online = useOnline();

/**
 * The batch as it was when the sheet opened. The inbox reloads behind the
 * sheet (the 60 s refresh, and after the decisions land), and a document
 * decided a moment ago must not drop out of the list the results belong to.
 */
const docs = props.items.slice();
const names = docs.map((doc) => doc.docname);
const doctype = docs[0]?.doctype ?? "";

const comment = ref("");
const busy = ref(false);
/** The answers so far, one per document (a retry replaces a row). */
const results = ref<BulkRow[]>([]);
/** Something was sent: the server may have acted, so closing must reload the inbox. */
const sent = ref(false);
/** The request failed after it was sent: the batch may be decided already, so it is never sent again. */
const unknown = ref(false);
/** What the failed request said (the connection, the wait that ran out). */
const failureMessage = ref("");

const mixed = computed(() => bulkShared(docs).reason);
const tooMany = computed(() => docs.length > BULK_LIMIT);
const states = computed(() => rowStates(names, results.value));
const hasResults = computed(() => results.value.length > 0);
const toSend = computed(() => retryNames(names, results.value));
const okCount = computed(() => names.length - toSend.value.length);
const failedCount = computed(() => results.value.filter((row) => !row.ok).length);
const finished = computed(() => hasResults.value && toSend.value.length === 0);
/** Nothing more can be decided here: all done, or the result of a sent request is unknown. */
const closedOnly = computed(() => finished.value || unknown.value);
/** The rows carry a mark and a line once there is something to say about them. */
const showMarks = computed(() => hasResults.value || unknown.value);
const totals = computed(() => bulkTotals(docs, session.currency ?? ""));
/**
 * The button is coloured as the inbox's bulk bar colours the same action: from
 * the action shared by the whole batch (the flag the bar was built from), read
 * with the same `actionTone`.
 */
const tone = computed(() => {
  const flag = bulkShared(docs).actions.find((shared) => shared.action === props.action);
  return flag ? actionTone(flag) : "other";
});

const commentOk = computed(() => !props.needsComment || comment.value.trim().length > 0);
const blocker = computed(() => {
  if (!docs.length) return t("approvalsLists.bulk.noItems");
  if (mixed.value) return t(mixed.value);
  if (tooMany.value) return t("approvalsLists.bulk.tooMany", { max: BULK_LIMIT });
  if (!online.value) return t("approvalsLists.bulk.needsConnection");
  return "";
});
const canApply = computed(
  () => !busy.value && !unknown.value && !blocker.value && commentOk.value && toSend.value.length > 0,
);

function fmt(amount: number): string {
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: session.currencyPrecision,
    maximumFractionDigits: session.currencyPrecision,
  }).format(amount);
}

/** What a row shows: a document not known to be done reads as unanswered once the result is unknown. */
function stateOf(name: string): RowState {
  const state = states.value.get(name) ?? { kind: "idle" as const };
  return unknown.value && state.kind !== "ok" ? { kind: "idle" } : state;
}

/** The server's words for a refused document, or a plain line when it gave none. */
function failure(name: string): string {
  const state = states.value.get(name);
  return (state?.kind === "failed" && state.message) || t("approvalsLists.bulk.refused");
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function apply() {
  if (!canApply.value) return;
  busy.value = true;
  sent.value = true;
  try {
    const answer = await applyBulk(doctype, toSend.value, props.action, comment.value.trim());
    results.value = mergeResults(results.value, answer.results ?? []);
  } catch (error) {
    // No answer is not a refusal: the server may have decided some or all of the batch.
    failureMessage.value = messageOf(error);
    unknown.value = bulkStateAfterFailure(sent.value) === "unknown";
  } finally {
    busy.value = false;
  }
}

function close() {
  if (busy.value) return;
  if (sent.value) emit("done");
  else emit("close");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") close();
}

const commentBox = ref<HTMLTextAreaElement | null>(null);
let previousOverflow = "";

onMounted(() => {
  window.addEventListener("keydown", onKey);
  // Lock the page behind the sheet, as the confirm modal does.
  previousOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  if (props.needsComment) void nextTick(() => commentBox.value?.focus());
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.body.style.overflow = previousOverflow;
});
</script>

<template>
  <Teleport to="body">
    <div class="scrim" @click.self="close">
      <section class="sheet" role="dialog" aria-modal="true" aria-labelledby="bulk-title">
        <header class="head">
          <h3 id="bulk-title">{{ action }}</h3>
          <span class="count">{{ t("approvalsLists.bulk.documents", { count: docs.length }) }}</span>
        </header>

        <ul class="docs" :aria-busy="busy">
          <li
            v-for="doc in docs"
            :key="doc.docname"
            class="doc"
            :data-state="showMarks ? stateOf(doc.docname).kind : 'idle'"
          >
            <span v-if="showMarks" class="mark" aria-hidden="true">
              <Icon v-if="stateOf(doc.docname).kind === 'ok'" name="check" :size="14" />
              <Icon v-else-if="stateOf(doc.docname).kind === 'failed'" name="x" :size="14" />
              <Icon v-else name="alert" :size="14" />
            </span>
            <div class="what">
              <div class="line">
                <strong class="name">{{ doc.docname }}</strong>
                <span v-if="doc.amount != null" class="amount">
                  <SarSymbol :code="doc.currency || session.currency || ''" />{{ fmt(doc.amount) }}
                </span>
              </div>
              <div class="sub">
                <span v-if="doc.party">{{ doc.party }}</span>
                <span v-if="doc.party && doc.transaction"> · </span>
                <span v-if="doc.transaction">{{ doc.transaction }}</span>
              </div>
              <template v-if="showMarks">
                <div v-if="stateOf(doc.docname).kind === 'ok'" class="result ok">
                  {{ t("approvalsLists.bulk.statusOk") }}
                </div>
                <div v-else-if="stateOf(doc.docname).kind === 'failed'" class="result failed" role="alert">
                  {{ failure(doc.docname) }}
                </div>
                <div v-else class="result idle">{{ t("approvalsLists.bulk.notAnswered") }}</div>
              </template>
            </div>
          </li>
        </ul>

        <div v-if="totals.totals.length" class="total">
          <span>{{ t("approvalsLists.bulk.total") }}</span>
          <span class="sums">
            <strong v-for="sum in totals.totals" :key="sum.code" class="sum">
              <SarSymbol :code="sum.code" />{{ fmt(sum.total) }}
            </strong>
          </span>
        </div>
        <p v-if="totals.unknown" class="hint">{{ t("approvalsLists.bulk.unknownAmounts", { count: totals.unknown }) }}</p>

        <label v-if="needsComment && !closedOnly" class="comment">
          <span class="label">{{ t("approvalsLists.bulk.commentLabel") }}</span>
          <textarea
            ref="commentBox"
            v-model="comment"
            rows="3"
            :placeholder="t('approvalsLists.bulk.commentPlaceholder')"
            :disabled="busy"
            :aria-invalid="!commentOk"
          />
          <span class="hint" :class="{ need: !commentOk }">{{ t("approvalsLists.bulk.commentHint") }}</span>
        </label>

        <p v-if="hasResults" class="summary" role="status" aria-live="polite">
          {{ t("approvalsLists.bulk.summary", { ok: okCount, count: docs.length }) }}
          <template v-if="failedCount"> · {{ t("approvalsLists.bulk.refusedCount", { failed: failedCount }) }}</template>
        </p>
        <p v-if="unknown" class="problem" role="alert">
          {{ t("approvalsLists.bulk.resultUnknown", { message: failureMessage }) }}
        </p>
        <p v-if="blocker && !closedOnly" class="problem" role="status">{{ blocker }}</p>

        <footer class="actions">
          <template v-if="closedOnly">
            <button type="button" class="go" :data-tone="unknown ? 'other' : 'approve'" @click="close">
              {{ unknown ? t("approvalsLists.bulk.closeReload") : t("approvalsLists.bulk.close") }}
            </button>
          </template>
          <template v-else>
            <button type="button" class="secondary" :disabled="busy" @click="close">
              {{ hasResults ? t("approvalsLists.bulk.close") : t("approvalsLists.bulk.cancel") }}
            </button>
            <button type="button" class="go" :data-tone="tone" :disabled="!canApply" @click="apply">
              <template v-if="busy">{{ t("approvalsLists.bulk.applying") }}</template>
              <template v-else-if="hasResults">
                {{ t("approvalsLists.bulk.retry", { failed: toSend.length }) }}
              </template>
              <template v-else>{{ t("approvalsLists.bulk.confirm", { action, count: docs.length }) }}</template>
            </button>
          </template>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: color-mix(in srgb, black 50%, transparent);
  display: flex;
  align-items: flex-end;
  justify-content: center;
}
.sheet {
  width: 100%;
  max-width: 32rem;
  max-height: 88vh;
  overflow-y: auto;
  background: var(--surface);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  padding: 1rem 1rem calc(1rem + var(--safe-bottom));
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.head h3 { margin: 0; }
.count { font-size: var(--text-sm); color: var(--text-muted); }

.docs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.doc { display: flex; gap: 0.6rem; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--border); border-inline-start: 4px solid transparent; }
.doc:last-child { border-bottom: 0; }
.doc[data-state="ok"] { border-inline-start-color: var(--success); background: var(--success-soft); }
.doc[data-state="failed"] { border-inline-start-color: var(--danger); background: var(--danger-soft); }
.doc[data-state="idle"] { border-inline-start-color: transparent; }
.mark { display: inline-grid; place-items: center; width: 1.4rem; height: 1.4rem; border-radius: 999px; flex-shrink: 0; margin-top: 0.1rem; background: var(--warning-soft); color: var(--warning); }
.doc[data-state="ok"] .mark { background: var(--success); color: white; }
.doc[data-state="failed"] .mark { background: var(--danger); color: white; }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.1rem; }
.line { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.amount { font-variant-numeric: tabular-nums; white-space: nowrap; }
.sub { font-size: var(--text-sm); color: var(--text-muted); overflow-wrap: anywhere; }
.result { font-size: var(--text-sm); font-weight: 600; overflow-wrap: anywhere; }
.result.ok { color: var(--success); }
.result.failed { color: var(--danger); }
.result.idle { color: var(--warning); }

.total { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; padding: 0.1rem 0.25rem; font-weight: 600; }
.sums { display: flex; flex-direction: column; align-items: flex-end; font-variant-numeric: tabular-nums; }
.hint { margin: 0; font-size: var(--text-xs); color: var(--text-muted); }
.hint.need { color: var(--danger); }

.comment { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); font-weight: 600; }
.comment textarea { resize: vertical; min-height: 4.5rem; }

.summary { margin: 0; font-weight: 600; }
.problem { margin: 0; font-size: var(--text-sm); color: var(--danger); overflow-wrap: anywhere; }

.actions { display: grid; grid-template-columns: 1fr 1.4fr; gap: 0.6rem; margin-top: 0.25rem; }
.actions .go:only-child { grid-column: 1 / -1; }
.actions button { min-height: 2.9rem; }
/* Coloured as the inbox's bulk bar colours the action: approve green, reject red, anything else blue. */
.go { background: var(--success); color: white; }
.go[data-tone="reject"] { background: var(--danger); }
.go[data-tone="other"] { background: var(--primary); }
</style>
