<script setup lang="ts">
/**
 * Payment Entries list — scoped by the backend to the logged-in user
 * (via `list_mine`). Drafts are included so the user can open them,
 * edit or delete. Submitted entries are read-only from here — tap
 * opens the receipt view where Print is available.
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listMine } from "@/api/payment";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();
const rows = ref<Array<Record<string, unknown>>>([]);
const err = ref("");
const loading = ref(false);

const CACHE_KEY = "vansale.payments.v1";

async function load() {
  err.value = "";

  // SWR paint: previous snapshot instantly, then refresh.
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (raw && rows.value.length === 0) {
      rows.value = JSON.parse(raw);
    }
  } catch { /* ignore */ }

  loading.value = rows.value.length === 0;
  try {
    const fresh = await listMine(50);
    rows.value = fresh;
    try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(fresh)); } catch { /* quota */ }
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
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
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
    <button class="new-btn" @click="router.push({ name: 'payment-new' })">
      <Icon name="plus" :size="18" /> New payment
    </button>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && rows.length === 0" class="stack">
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
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
          <strong class="truncate">{{ r.party_name || r.party }}</strong>
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
.new-btn { align-self: flex-start; min-height: 2.5rem; padding: 0.55rem 0.9rem; }

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
