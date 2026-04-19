<script setup lang="ts">
import { onMounted, ref } from "vue";
import { listMine } from "@/api/invoice";

const rows = ref<Array<Record<string, unknown>>>([]);
const err = ref("");
const loading = ref(false);

async function load() {
  err.value = "";
  loading.value = true;
  try {
    rows.value = await listMine(50);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: unknown): string {
  const num = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(num);
}
</script>

<template>
  <section class="stack">
    <h1>Invoices</h1>
    <p v-if="loading" class="muted">Loading…</p>
    <p v-if="err" class="error">{{ err }}</p>
    <ul class="list">
      <li v-for="r in rows" :key="String(r.name)" class="item">
        <div>
          <strong>{{ r.customer_name || r.customer }}</strong>
          <div class="muted small">{{ r.name }} · {{ r.posting_date }}</div>
        </div>
        <div class="amt">
          <strong>{{ fmt(r.grand_total) }}</strong>
          <div class="muted small">{{ r.status }}</div>
        </div>
      </li>
      <li v-if="!loading && rows.length === 0" class="muted">No invoices yet.</li>
    </ul>
  </section>
</template>

<style scoped>
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.item {
  background: var(--surface);
  padding: 0.75rem;
  border-radius: var(--radius);
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
}
.amt { text-align: right; }
.small { font-size: 0.8rem; }
</style>
