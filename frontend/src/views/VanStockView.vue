<script setup lang="ts">
import { onMounted, ref } from "vue";
import { listStock, type VanStockRow } from "@/api/van_stock";

const rows = ref<VanStockRow[]>([]);
const warehouse = ref("");
const err = ref("");

async function load() {
  err.value = "";
  try {
    const res = await listStock();
    rows.value = res.items;
    warehouse.value = res.warehouse;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(load);
</script>

<template>
  <section class="stack">
    <header class="card stack">
      <h1 style="margin: 0">Van stock</h1>
      <p class="muted small">{{ warehouse || "—" }}</p>
    </header>
    <p v-if="err" class="error">{{ err }}</p>
    <ul class="list">
      <li v-for="r in rows" :key="r.item_code" class="item">
        <div>
          <strong>{{ r.item_name }}</strong>
          <div class="muted small">{{ r.item_code }} · {{ r.stock_uom }}</div>
        </div>
        <strong>{{ r.actual_qty }}</strong>
      </li>
      <li v-if="rows.length === 0" class="muted">Van is empty or not configured.</li>
    </ul>
  </section>
</template>

<style scoped>
.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.item {
  background: var(--surface);
  padding: 0.7rem;
  border-radius: var(--radius);
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
}
.small { font-size: 0.8rem; }
</style>
