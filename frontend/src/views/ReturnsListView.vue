<script setup lang="ts">
/**
 * Sales returns (credit notes) list.
 *
 * Backed by `invoice.list_mine?is_return=1`. Each row shows the credit-note
 * name + amount + the original invoice it was issued against (ERPNext's
 * `return_against` field). Tapping the original invoice link dives into
 * the regular InvoiceDetailView.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listReturns, listMine, type ReturnRow } from "@/api/invoice";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();

const rows = ref<ReturnRow[]>([]);
const loading = ref(false);
const err = ref("");

// Picker modal — lists recent submitted, non-return invoices eligible as
// return_against targets. Returns must reference an existing submitted
// invoice (ERPNext rule), so we surface the picker rather than a
// zero-context "new return" form.
const pickerOpen = ref(false);
const pickerRows = ref<Array<Record<string, unknown>>>([]);
const pickerLoading = ref(false);
const pickerErr = ref("");
const pickerSearch = ref("");

const filteredPicker = computed(() => {
  const q = pickerSearch.value.trim().toLowerCase();
  if (!q) return pickerRows.value;
  return pickerRows.value.filter((r) => {
    const name = String(r.name || "").toLowerCase();
    const cust = String(r.customer_name || r.customer || "").toLowerCase();
    return name.includes(q) || cust.includes(q);
  });
});

async function load() {
  loading.value = true;
  err.value = "";
  try {
    rows.value = await listReturns(80);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: unknown): string {
  const num = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Math.abs(num));
}

function openReturn(name: string) {
  void router.push({ name: "invoice-detail", params: { name } });
}
function openOriginal(name: string | null | undefined) {
  if (!name) return;
  void router.push({ name: "invoice-detail", params: { name } });
}

async function openPicker() {
  pickerOpen.value = true;
  pickerErr.value = "";
  pickerLoading.value = true;
  pickerSearch.value = "";
  try {
    // Fetch last 50 invoices — filter client-side to submitted & non-return
    // so the picker only shows valid return_against targets.
    const all = await listMine(50);
    pickerRows.value = all.filter((r) =>
      Number(r.docstatus) === 1 && Number(r.is_return) !== 1
      && String(r.status || "").toLowerCase() !== "cancelled",
    );
  } catch (e) {
    pickerErr.value = e instanceof Error ? e.message : String(e);
  } finally {
    pickerLoading.value = false;
  }
}

function closePicker() {
  pickerOpen.value = false;
}

function pickInvoice(name: string) {
  pickerOpen.value = false;
  void router.push({ name: "invoice-return", params: { name } });
}
</script>

<template>
  <div class="stack">
    <header class="head-row">
      <div>
        <h2 class="title">Sales returns</h2>
        <span class="muted xsmall">Credit notes issued against submitted invoices</span>
      </div>
      <div class="head-actions">
        <button class="primary new-ret-btn" @click="openPicker">
          <Icon name="plus" :size="16" /> New return
        </button>
        <button class="ghost icon-only" @click="load" :disabled="loading" title="Refresh">
          <Icon name="refresh" :size="18" />
        </button>
      </div>
    </header>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && rows.length === 0" class="stack">
      <div class="skeleton" style="height:4rem" />
      <div class="skeleton" style="height:4rem" />
      <div class="skeleton" style="height:4rem" />
    </div>

    <div v-else-if="rows.length === 0" class="empty">
      <Icon name="receipt" :size="32" class="empty-icon" />
      <strong>No returns yet</strong>
      <span class="muted">Tap New return to issue a credit note against a submitted invoice.</span>
      <button @click="openPicker">
        <Icon name="plus" :size="16" /> New return
      </button>
    </div>

    <ul v-else class="ret-list">
      <li v-for="r in rows" :key="r.name" class="ret-row">
        <button type="button" class="ret-main" @click="openReturn(r.name)">
          <div class="body">
            <strong class="name">{{ r.name }}</strong>
            <span class="muted xsmall">
              {{ r.customer_name || r.customer }} · {{ r.posting_date }}
            </span>
          </div>
          <strong class="amount">- <SarSymbol :code="session.currency" />{{ fmt(r.grand_total) }}</strong>
        </button>
        <button
          v-if="r.return_against"
          type="button"
          class="link-invoice"
          @click="openOriginal(r.return_against)"
          :aria-label="`Open original invoice ${r.return_against}`"
        >
          <Icon name="invoice" :size="14" />
          <span class="muted xsmall">Against</span>
          <span class="inv-name">{{ r.return_against }}</span>
          <Icon name="chevron-right" :size="14" class="chev" />
        </button>
      </li>
    </ul>

    <!-- Invoice picker modal — surfaces return_against targets. Separate
         from the v-if/v-else list chain so opening it doesn't unmount the
         underlying list. -->
    <div v-if="pickerOpen" class="modal-overlay" @click.self="closePicker">
      <div class="modal-card stack" role="dialog" aria-label="Pick invoice to return">
        <div class="modal-head">
          <div>
            <h3 style="margin:0">Pick invoice</h3>
            <span class="muted xsmall">Only submitted invoices can be returned</span>
          </div>
          <button class="icon-only ghost" @click="closePicker" aria-label="Close">
            <Icon name="x" :size="18" />
          </button>
        </div>
        <div class="search-bar">
          <Icon name="search" :size="16" class="search-ic" />
          <input v-model="pickerSearch" placeholder="Search invoice # or customer" />
        </div>
        <p v-if="pickerErr" class="error">{{ pickerErr }}</p>
        <div v-if="pickerLoading" class="stack">
          <div class="skeleton" style="height:3.25rem" />
          <div class="skeleton" style="height:3.25rem" />
          <div class="skeleton" style="height:3.25rem" />
        </div>
        <div v-else-if="filteredPicker.length === 0" class="empty" style="padding:1rem 0">
          <Icon name="invoice" :size="28" class="empty-icon" />
          <span class="muted">No eligible invoices found.</span>
        </div>
        <ul v-else class="picker-list">
          <li v-for="r in filteredPicker" :key="String(r.name)">
            <button type="button" class="picker-row" @click="pickInvoice(String(r.name))">
              <div class="picker-body">
                <strong class="truncate">{{ r.customer_name || r.customer }}</strong>
                <span class="muted xsmall">{{ r.name }} · {{ r.posting_date }}</span>
              </div>
              <div class="picker-right">
                <strong><SarSymbol :code="session.currency" />{{ fmt(r.grand_total) }}</strong>
                <Icon name="chevron-right" :size="14" class="chev" />
              </div>
            </button>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}
.title { margin: 0; font-size: var(--text-lg); letter-spacing: -0.01em; }

.ret-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.ret-row {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 0.6rem 0.75rem 0.5rem;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  border-inline-start: 3px solid var(--warning);
}
.ret-main {
  all: unset;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 0.75rem;
}
.ret-main:active { opacity: 0.7; }
.body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.name { font-variant-numeric: tabular-nums; }
.amount {
  color: var(--warning);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.link-invoice {
  all: unset;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.5rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: var(--text);
  font-size: var(--text-xs);
}
.link-invoice:active { opacity: 0.75; }
.link-invoice .inv-name { font-weight: 600; margin-inline-start: 0.15rem; font-variant-numeric: tabular-nums; }
.link-invoice .chev { margin-inline-start: auto; color: var(--text-muted); }

.head-actions { display: inline-flex; gap: 0.4rem; align-items: center; }
.new-ret-btn {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.5rem 0.85rem; min-height: 2.4rem;
  font-size: var(--text-sm); font-weight: 600;
}

.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(10,10,14,0.55);
  backdrop-filter: blur(3px);
  display: grid; place-items: end center;
  padding: 1rem;
  z-index: 100;
  animation: fade-in var(--dur-fast) var(--ease);
}
.modal-card {
  width: 100%; max-width: 32rem; max-height: 82vh;
  overflow-y: auto;
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 1rem;
  box-shadow: var(--shadow-float);
  animation: slide-up var(--dur-fast) var(--ease);
}
.modal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; }

.search-bar { position: relative; }
.search-ic {
  position: absolute; top: 50%; inset-inline-start: 0.65rem;
  transform: translateY(-50%); color: var(--text-muted); pointer-events: none;
}
.search-bar input { padding-inline-start: 2.1rem; }

.picker-list {
  list-style: none; padding: 0; margin: 0;
  display: flex; flex-direction: column; gap: 0.35rem;
}
.picker-row {
  all: unset; cursor: pointer; width: 100%;
  display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  transition: background var(--dur-fast) var(--ease);
}
.picker-row:active { background: var(--primary-soft); }
.picker-body { display: flex; flex-direction: column; min-width: 0; gap: 0.05rem; }
.picker-right { display: flex; align-items: center; gap: 0.35rem; color: var(--text-muted); }
.picker-right strong { font-variant-numeric: tabular-nums; color: var(--text); }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

@keyframes fade-in { from { opacity: 0 } to { opacity: 1 } }
@keyframes slide-up {
  from { transform: translateY(20px); opacity: 0 }
  to   { transform: translateY(0); opacity: 1 }
}
</style>
