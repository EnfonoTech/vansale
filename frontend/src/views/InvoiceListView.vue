<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listMine } from "@/api/invoice";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();
const rows = ref<Array<Record<string, unknown>>>([]);
const err = ref("");
const loading = ref(false);

async function load() {
  loading.value = true;
  err.value = "";
  try { rows.value = await listMine(50); }
  catch (e) { err.value = e instanceof Error ? e.message : String(e); }
  finally { loading.value = false; }
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
    <button class="new-btn" @click="router.push({ name: 'invoice-new' })">
      <Icon name="plus" :size="18" /> New invoice
    </button>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && rows.length === 0" class="stack">
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
      <div class="skeleton" style="height:3.25rem" />
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
