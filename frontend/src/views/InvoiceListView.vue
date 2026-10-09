<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine } from "@/api/invoice";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import ListSearch from "@/components/ListSearch.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();
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

const CACHE_KEY = "vansale.invoices.v1";

async function load() {
  err.value = "";

  // SWR paint: pull last snapshot from sessionStorage so the list shows
  // instantly, then refresh in background. Cuts perceived load from 2-3s
  // to ~0 for repeat visits during the same session.
  const term = search.value.trim();
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!term && raw && rows.value.length === 0) {
      rows.value = JSON.parse(raw);
    }
  } catch { /* stale/invalid cache is fine */ }

  loading.value = rows.value.length === 0;
  try {
    const fresh = await listMine(50, undefined, false, term || undefined);
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
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(num);
}

function tone(status: unknown): string {
  const s = String(status || "").toLowerCase();
  if (s === "paid") return "success";
  if (s === "overdue") return "danger";
  if (s === "cancelled") return "danger";
  if (s === "unpaid") return "warning";
  return "info";
}
</script>

<template>
  <div class="stack">

    <!-- Search and New share one row (fits a small phone). -->
    <div class="toolbar">
      <ListSearch v-model="search" placeholder="Search invoices" />
      <button class="new-btn" :aria-label="'New invoice'" @click="router.push({ name: 'invoice-new' })">
        <Icon name="plus" :size="18" /> New
      </button>
    </div>

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
      <Icon name="invoice" :size="32" class="empty-icon" />
      <strong>No invoices yet</strong>
      <span class="muted">Create your first invoice of the day.</span>
      <button @click="router.push({ name: 'invoice-new' })">Start selling</button>
    </div>
    <ul v-else class="list">
      <li
        v-for="r in rows"
        :key="String(r.name)"
        class="item"
        role="button"
        tabindex="0"
        @click="router.push({ name: 'invoice-detail', params: { name: String(r.name) } })"
        @keyup.enter="router.push({ name: 'invoice-detail', params: { name: String(r.name) } })"
      >
        <div class="body">
          <strong class="truncate">{{ r.customer_name || r.customer }}</strong>
          <span class="muted xsmall">{{ r.name }} · {{ r.posting_date }}</span>
        </div>
        <div class="right">
          <strong><SarSymbol :code="session.currency" />{{ fmt(r.grand_total) }}</strong>
          <span class="pill" :data-tone="tone(r.status)">{{ r.status }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
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
