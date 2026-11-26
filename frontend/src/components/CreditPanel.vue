<script setup lang="ts">
/**
 * The customer's credit at a glance: limit, used, available (with a bar),
 * overdue invoices, and — on a sale screen — what this sale does to it.
 *
 * Used on the invoice and order forms (inside Payment) and on the customer
 * screen. Steel Force sites add the approval state, the credit-days overdue
 * that blocks a credit sale, and the branch sub-limit.
 */
import { computed } from "vue";
import type { CreditStatus } from "@/api/customer";
import { creditImpact, creditRefusal, usedShare, type PayType } from "@/features/van/credit";
import { useSessionStore } from "@/stores/session";
import SarSymbol from "@/components/SarSymbol.vue";

const props = withDefaults(
  defineProps<{
    status: CreditStatus | null;
    loading?: boolean;
    /** The sale's payment type; omit on the customer screen (and on an order
     *  where the site keeps none — the whole order then counts). */
    payment?: PayType;
    /** Unpaid part of this sale (counts against the limit). */
    adds?: number;
  }>(),
  { loading: false, payment: undefined, adds: 0 },
);

const session = useSessionStore();
const fmt = (n: number) =>
  new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: session.currencyPrecision,
  }).format(Number(n) || 0);

const s = computed(() => props.status);
// A sale screen: a payment type, or (an order without one) an amount it adds.
const onSale = computed(() => props.payment !== undefined || props.adds > 0);
const impact = computed(() => creditImpact(s.value, props.payment, props.adds));
const refusal = computed(() => (props.payment ? creditRefusal(s.value, props.payment) : null));
const limit = computed(() => s.value?.credit_limit ?? 0);
const usedPct = computed(() => usedShare(s.value?.used ?? 0, limit.value) * 100);
// The part this sale adds, drawn after the used part (capped at the bar's end).
const addsPct = computed(() =>
  impact.value.counts && limit.value > 0
    ? Math.max(usedShare(impact.value.after, limit.value) * 100 - usedPct.value, 0)
    : 0,
);
const approvalPending = computed(() => Boolean(s.value?.approval?.covered && !s.value.approval.approved));

/** One-word state for the pill. */
const headline = computed<{ text: string; tone: string }>(() => {
  const v = s.value;
  if (!v) return { text: "", tone: "" };
  if (approvalPending.value) return { text: "Awaiting approval", tone: "danger" };
  if (!v.credit_allowed) return { text: "Cash only", tone: "warning" };
  if (impact.value.over) return { text: "Over limit", tone: "danger" };
  if (v.blocking_overdue) return { text: "Credit on hold", tone: "danger" };
  if (limit.value <= 0) return { text: "No limit set", tone: "info" };
  if ((v.available ?? 0) <= 0) return { text: "Limit used up", tone: "danger" };
  return { text: "Credit OK", tone: "success" };
});
const barTone = computed(() =>
  impact.value.over || (limit.value > 0 && (s.value?.available ?? 0) <= 0)
    ? "danger"
    : usedPct.value + addsPct.value >= 80 ? "warning" : "ok",
);
</script>

<template>
  <div v-if="loading && !s" class="credit muted xsmall">Checking credit…</div>
  <div v-else-if="s" class="credit" :data-tone="headline.tone">
    <div class="cr-head">
      <span class="tiny">Credit</span>
      <span class="pill" :data-tone="headline.tone">{{ headline.text }}</span>
    </div>

    <template v-if="limit > 0">
      <div class="bar" :data-tone="barTone" role="img"
           :aria-label="`Used ${fmt(s.used)} of ${fmt(limit)}`">
        <span class="bar-used" :style="{ width: `${usedPct}%` }" />
        <span v-if="addsPct > 0" class="bar-adds" :style="{ left: `${usedPct}%`, width: `${addsPct}%` }" />
      </div>
      <div class="nums">
        <div>
          <span class="tiny">Used</span>
          <strong class="tabular"><SarSymbol :code="session.currency" />{{ fmt(s.used) }}</strong>
        </div>
        <div>
          <span class="tiny">Limit</span>
          <strong class="tabular"><SarSymbol :code="session.currency" />{{ fmt(limit) }}</strong>
        </div>
        <div>
          <span class="tiny">Available</span>
          <strong class="tabular" :class="{ bad: (s.available ?? 0) <= 0 }">
            <SarSymbol :code="session.currency" />{{ fmt(s.available ?? 0) }}
          </strong>
        </div>
      </div>
    </template>
    <div v-else class="nums">
      <div>
        <span class="tiny">{{ s.used < 0 ? "In advance" : "Owes" }}</span>
        <strong class="tabular"><SarSymbol :code="session.currency" />{{ fmt(Math.abs(s.used)) }}</strong>
      </div>
    </div>

    <!-- This sale -->
    <template v-if="onSale">
      <p v-if="refusal" class="line bad">{{ refusal }}</p>
      <p v-else-if="impact.over" class="line bad">
        This sale goes <SarSymbol :code="session.currency" />{{ fmt(impact.overBy) }} over the limit and will be
        refused. Collect part now, or ask the office to raise the limit.
      </p>
      <p v-else-if="impact.counts && limit > 0 && payment !== 'cash'" class="line muted">
        After this sale: <SarSymbol :code="session.currency" />{{ fmt(impact.availableAfter ?? 0) }} available.
      </p>
      <p v-else-if="impact.exempt && limit > 0" class="line muted">Cash sale — doesn't use the credit limit.</p>
      <p v-if="impact.branchOver && s.branch" class="line bad">
        Over the {{ s.branch.name }} branch limit
        (<SarSymbol :code="session.currency" />{{ fmt(s.branch.used) }} used of {{ fmt(s.branch.limit) }}).
      </p>
    </template>
    <template v-else>
      <p v-if="!s.credit_allowed && s.credit_problem" class="line muted">{{ s.credit_problem }}</p>
      <p v-else-if="limit > 0" class="line muted">Used = unpaid invoices + open orders, all vans.</p>
    </template>

    <p v-if="s.blocking_overdue && !(onSale && refusal)" class="line" :class="payment === 'cash' ? 'warn' : 'bad'">
      Overdue: {{ s.blocking_overdue.name }} ({{ s.blocking_overdue.posting_date }}),
      <SarSymbol :code="session.currency" />{{ fmt(s.blocking_overdue.outstanding_amount) }} —
      no credit sale until it is paid.
    </p>
    <p v-else-if="s.overdue" class="line warn">
      {{ s.overdue.count }} invoice{{ s.overdue.count === 1 ? "" : "s" }} overdue,
      <SarSymbol :code="session.currency" />{{ fmt(s.overdue.amount) }} (due since {{ s.overdue.oldest_due }}).
    </p>
    <p v-if="s.branch && !(onSale && impact.branchOver)" class="line muted">
      {{ s.branch.name }} branch: <SarSymbol :code="session.currency" />{{ fmt(s.branch.used) }} used of
      {{ fmt(s.branch.limit) }}.
    </p>

    <div v-if="approvalPending" class="line bad stack-xs">
      <span>Customer waiting for approval ({{ s.approval?.status || "Draft" }}) — no sale until approved.</span>
      <span v-for="m in s.approval?.missing ?? []" :key="m" class="muted">• {{ m }}</span>
    </div>
    <p v-if="s.fromCache" class="line muted">Offline — last known figures.</p>
  </div>
</template>

<style scoped>
.credit {
  display: flex; flex-direction: column; gap: 0.45rem;
  padding: 0.65rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  border-inline-start: 3px solid transparent;
}
.credit[data-tone="danger"] { border-inline-start-color: var(--danger); }
.credit[data-tone="warning"] { border-inline-start-color: var(--warning); }
.cr-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.bar {
  position: relative; height: 0.4rem; border-radius: 999px; overflow: hidden;
  background: var(--border-strong);
}
.bar-used, .bar-adds { position: absolute; top: 0; bottom: 0; }
.bar-used { left: 0; background: var(--primary); border-radius: 999px; }
.bar-adds { background: var(--primary); opacity: 0.4; }
.bar[data-tone="warning"] .bar-used, .bar[data-tone="warning"] .bar-adds { background: var(--warning); }
.bar[data-tone="danger"] .bar-used, .bar[data-tone="danger"] .bar-adds { background: var(--danger); }
.nums { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.5rem; }
.nums > div { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.nums strong { font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tabular { font-variant-numeric: tabular-nums; }
.line { margin: 0; font-size: var(--text-xs); }
.bad { color: var(--danger); }
.warn { color: var(--warning); }
.stack-xs { display: flex; flex-direction: column; gap: 0.15rem; }
</style>
