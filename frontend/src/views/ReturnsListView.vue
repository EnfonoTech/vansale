<script setup lang="ts">
/**
 * Sales returns (credit notes) list.
 *
 * Backed by `invoice.list_mine?is_return=1`. Each row shows the credit-note
 * name + amount + the original invoice it was issued against (ERPNext's
 * `return_against` field). Tapping the original invoice link dives into
 * the regular InvoiceDetailView.
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listReturns, type ReturnRow } from "@/api/invoice";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();

const rows = ref<ReturnRow[]>([]);
const loading = ref(false);
const err = ref("");

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
</script>

<template>
  <div class="stack">
    <header class="head-row">
      <div>
        <h2 class="title">Sales returns</h2>
        <span class="muted xsmall">Credit notes issued against submitted invoices</span>
      </div>
      <button class="ghost icon-only" @click="load" :disabled="loading" title="Refresh">
        <Icon name="refresh" :size="18" />
      </button>
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
      <span class="muted">Returns you create appear here with a link back to the original invoice.</span>
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
</style>
