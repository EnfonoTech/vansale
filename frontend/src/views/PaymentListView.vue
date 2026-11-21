<script setup lang="ts">
/**
 * Payment Entries list — scoped by the backend to the logged-in user
 * (via `list_mine`). Drafts are included so the user can open them,
 * edit or delete. Submitted entries are read-only from here — tap
 * opens the receipt view where Print is available.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine } from "@/api/payment";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import ListSearch from "@/components/ListSearch.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import CustomerName from "@/components/CustomerName.vue";
import { drivers as listDrivers, myCash, type DriverRow, type MyCash } from "@/api/steelforce";
import { isOnline } from "@/app/online";

const router = useRouter();
const session = useSessionStore();
// Steel Force: cash from the salesman's own sales not yet collected, against
// his cash limit / payment days (sf_trading refuses his next order past them).
const cash = ref<MyCash>({});
// Steel Force: cash the branch's delivery persons still hold from sales
// handed to them (sf_trading's "Delivery Person Payment Pending").
const driverCash = ref<DriverRow[]>([]);
const driverTotal = computed(() => driverCash.value.reduce((t, d) => t + (d.holding ?? 0), 0));
const money = (n: number) =>
  new Intl.NumberFormat(undefined, {
    minimumFractionDigits: session.currencyPrecision,
    maximumFractionDigits: session.currencyPrecision,
  }).format(Number(n) || 0);
const day = (d: string) => {
  const t = new Date(`${d}T00:00:00`);
  return Number.isNaN(t.getTime()) ? d : t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const share = (used: number, limit: number) => (limit > 0 ? Math.min(100, Math.max(0, (used / limit) * 100)) : 0);
// One word for the salesman's own cash: fine, getting close, or stopped.
const cashTone = computed(() => {
  const c = cash.value;
  if (c.overdue) return { tone: "danger", text: "Overdue" };
  if (c.cash_limit && (c.holding ?? 0) >= c.cash_limit) return { tone: "danger", text: "At limit" };
  if (c.cash_limit && (c.holding ?? 0) >= 0.8 * c.cash_limit) return { tone: "warning", text: "Near limit" };
  // No limit is not "good", just no rule: a plain pill, no colour.
  return c.cash_limit ? { tone: "success", text: "Within limit" } : { tone: undefined, text: "No limit" };
});
onMounted(() => {
  if (!isOnline()) return;
  void myCash().then((c) => (cash.value = c || {})).catch(() => {});
  if (session.askDriver) {
    void listDrivers()
      .then((d) => (driverCash.value = d.filter((x) => (x.holding ?? 0) > 0)))
      .catch(() => {});
  }
});
const rows = ref<Array<Record<string, unknown>>>([]);
const err = ref("");
const loading = ref(false);
// Searches on the server, so older entries beyond the latest page are found.
const search = ref("");
let searchTimer: number | undefined;
watch(search, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 300);
});

const CACHE_KEY = "vansale.payments.v1";

async function load() {
  err.value = "";

  // SWR paint: previous snapshot instantly, then refresh.
  const term = search.value.trim();
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!term && raw && rows.value.length === 0) {
      rows.value = JSON.parse(raw);
    }
  } catch { /* ignore */ }

  loading.value = rows.value.length === 0;
  try {
    const fresh = await listMine(50, undefined, term || undefined);
    rows.value = fresh;
    // The snapshot is the unfiltered list only.
    if (!term) {
      try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(fresh)); } catch { /* quota */ }
    }
  } catch (e) {
    if (rows.value.length === 0) err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: unknown): string {
  const num = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: session.currencyPrecision,
    minimumFractionDigits: session.currencyPrecision,
  }).format(num);
}

function tone(docstatus: unknown, status: unknown): string {
  if (Number(docstatus) === 0) return "info";
  const s = String(status || "").toLowerCase();
  if (s === "submitted") return "success";
  if (s === "cancelled") return "danger";
  return "success";
}

function statusLabel(docstatus: unknown, status: unknown): string {
  if (Number(docstatus) === 0) return "Draft";
  return String(status || "Submitted");
}
</script>

<template>
  <div class="stack">

    <!-- Search and New share one row (fits a small phone). -->
    <div class="toolbar">
      <ListSearch v-model="search" placeholder="Search payments" />
      <button class="new-btn" :aria-label="'New payment'" @click="router.push({ name: 'payment-new' })">
        <Icon name="plus" :size="18" /> New
      </button>
    </div>

    <!-- Steel Force: the salesman's own cash, against his limits. -->
    <section v-if="(cash.holding ?? 0) > 0 || cash.cash_limit" class="card cash-card" :data-tone="cashTone.tone">
      <div class="cash-head">
        <span class="cash-title"><Icon name="payment" :size="16" /> Your cash sales not yet collected</span>
        <span class="pill" :data-tone="cashTone.tone">{{ cashTone.text }}</span>
      </div>
      <div class="cash-amount">
        <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(cash.holding ?? 0) }}</strong>
        <span v-if="cash.cash_limit" class="muted small">of {{ money(cash.cash_limit) }} limit</span>
      </div>
      <div v-if="cash.cash_limit" class="bar" :data-tone="cashTone.tone">
        <span :style="{ width: `${share(cash.holding ?? 0, cash.cash_limit)}%` }" />
      </div>
      <p v-if="cash.branch" class="muted xsmall line">
        {{ cash.branch }} branch: {{ money(cash.branch_holding ?? 0) }} of {{ money(cash.branch_limit ?? 0) }}
      </p>
      <p v-if="cash.overdue" class="alert-line">
        <Icon name="alert" :size="14" />
        <span>{{ cash.overdue.name }} of {{ day(cash.overdue.posting_date) }} is past your {{ cash.payment_days }} payment days. Collect it before the next order.</span>
      </p>
      <p v-else-if="cashTone.tone === 'danger'" class="alert-line">
        <Icon name="alert" :size="14" /><span>At your cash limit. Collect before the next order.</span>
      </p>
    </section>

    <!-- Steel Force: cash the branch's delivery persons still hold. -->
    <section v-if="driverCash.length" class="card cash-card">
      <div class="cash-head">
        <span class="cash-title"><Icon name="truck" :size="16" /> Cash with delivery persons</span>
        <span class="muted small tabular"><SarSymbol :code="session.currency" />{{ money(driverTotal) }}</span>
      </div>
      <ul class="drivers">
        <li v-for="d in driverCash" :key="d.name" class="driver">
          <div class="driver-top">
            <span class="driver-name"><Icon name="user" :size="14" /> {{ d.full_name }}</span>
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(d.holding ?? 0) }}</strong>
          </div>
          <div v-if="d.cash_limit" class="bar thin" :data-tone="(d.holding ?? 0) >= d.cash_limit ? 'danger' : 'ok'">
            <span :style="{ width: `${share(d.holding ?? 0, d.cash_limit)}%` }" />
          </div>
          <p v-if="d.blocked" class="alert-line small-alert">
            <Icon name="alert" :size="12" /><span>{{ d.blocked }}</span>
          </p>
        </li>
      </ul>
    </section>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && rows.length === 0" class="stack">
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
    </div>
    <div v-else-if="rows.length === 0 && search.trim()" class="empty">
      <Icon name="search" :size="32" class="empty-icon" />
      <strong>No matches</strong>
      <span class="muted">Nothing found for “{{ search.trim() }}”.</span>
    </div>
    <div v-else-if="rows.length === 0" class="empty">
      <Icon name="payment" :size="32" class="empty-icon" />
      <strong>No payments yet</strong>
      <span class="muted">Collect your first payment of the day.</span>
      <button @click="router.push({ name: 'payment-new' })">Collect payment</button>
    </div>
    <ul v-else class="list">
      <li
        v-for="r in rows"
        :key="String(r.name)"
        class="item"
        role="button"
        tabindex="0"
        @click="router.push({ name: 'payment-detail', params: { name: String(r.name) } })"
        @keyup.enter="router.push({ name: 'payment-detail', params: { name: String(r.name) } })"
      >
        <div class="body">
          <CustomerName :title="r.party_title" :name="r.party_name" :id="r.party" />
          <span class="muted xsmall">
            {{ r.name }} · {{ r.posting_date }}
            <template v-if="r.mode_of_payment"> · {{ r.mode_of_payment }}</template>
          </span>
        </div>
        <div class="right">
          <strong><SarSymbol :code="session.currency" />{{ fmt(r.paid_amount) }}</strong>
          <span class="pill" :data-tone="tone(r.docstatus, r.status)">
            {{ statusLabel(r.docstatus, r.status) }}
          </span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.cash-card { display: flex; flex-direction: column; gap: 0.5rem; border-inline-start: 3px solid transparent; }
.cash-card[data-tone="danger"] { border-inline-start-color: var(--danger); }
.cash-card[data-tone="warning"] { border-inline-start-color: var(--warning); }
.cash-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.cash-title { display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 600; font-size: var(--text-sm); }
.cash-amount { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.cash-amount strong { font-size: 1.35rem; }
.bar { position: relative; height: 0.45rem; border-radius: 999px; background: var(--surface-sunk); overflow: hidden; }
.bar.thin { height: 0.3rem; }
.bar span { position: absolute; inset: 0 auto 0 0; border-radius: 999px; background: var(--success); }
.bar[data-tone="warning"] span { background: var(--warning); }
.bar[data-tone="danger"] span { background: var(--danger); }
.bar[data-tone="ok"] span { background: var(--primary); }
.line { margin: 0; }
.alert-line {
  margin: 0; display: flex; gap: 0.35rem; align-items: flex-start;
  padding: 0.4rem 0.55rem; border-radius: var(--radius-sm);
  background: var(--danger-soft); color: var(--danger); font-size: var(--text-xs); line-height: 1.35;
}
.alert-line :deep(svg) { flex: none; margin-top: 0.1rem; }
.drivers { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.driver { display: flex; flex-direction: column; gap: 0.35rem; padding: 0.55rem 0; border-top: 1px solid var(--border); }
.driver:first-child { border-top: 0; padding-top: 0.15rem; }
.driver-top { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.driver-name { display: inline-flex; align-items: center; gap: 0.35rem; font-weight: 500; }
/* Per driver: a quiet red line, not a box — several boxes in one card shout. */
.small-alert { padding: 0; background: none; }
.tabular { font-variant-numeric: tabular-nums; }
.toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: center; }
.new-btn { height: 2.75rem; min-height: 0; padding: 0 0.95rem; white-space: nowrap; }

.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 0.75rem 0.85rem;
  box-shadow: var(--shadow-sm);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.75rem;
  align-items: center;
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.item:active { transform: scale(0.99); }
.item:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.body { display: flex; flex-direction: column; gap: 0.15rem; min-width: 0; }
.right { text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; }
.right strong { font-variant-numeric: tabular-nums; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
