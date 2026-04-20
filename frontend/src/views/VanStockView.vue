<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { listStock, type VanStockRow } from "@/api/van_stock";
import Icon from "@/components/Icon.vue";

const rows = ref<VanStockRow[]>([]);
const warehouse = ref("");
const err = ref("");
const loading = ref(false);
const query = ref("");

async function load() {
  loading.value = true;
  err.value = "";
  try {
    const res = await listStock();
    rows.value = res.items;
    warehouse.value = res.warehouse;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: unknown): string {
  const v = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(v);
}

function tone(qty: number): string {
  if (qty <= 0) return "danger";
  if (qty < 5) return "warning";
  return "success";
}

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return rows.value;
  return rows.value.filter((r) =>
    `${r.item_name} ${r.item_code}`.toLowerCase().includes(q),
  );
});

const totals = computed(() => {
  const count = rows.value.length;
  const low = rows.value.filter((r) => (r.actual_qty ?? 0) < 5 && (r.actual_qty ?? 0) > 0).length;
  const out = rows.value.filter((r) => (r.actual_qty ?? 0) <= 0).length;
  return { count, low, out };
});
</script>

<template>
  <div class="stack">
    <section class="hero card stack">
      <div class="hero-head">
        <div>
          <span class="muted xsmall">Warehouse</span>
          <h2 class="hero-wh">{{ warehouse || "—" }}</h2>
        </div>
        <button class="ghost icon-only" @click="load" :disabled="loading" title="Refresh">
          <Icon name="refresh" :size="18" />
        </button>
      </div>
      <div class="hero-pills">
        <div class="stat">
          <strong>{{ totals.count }}</strong>
          <span class="muted xsmall">SKUs</span>
        </div>
        <div class="stat" data-tone="warning">
          <strong>{{ totals.low }}</strong>
          <span class="muted xsmall">Low</span>
        </div>
        <div class="stat" data-tone="danger">
          <strong>{{ totals.out }}</strong>
          <span class="muted xsmall">Out</span>
        </div>
      </div>
    </section>

    <div class="search">
      <Icon name="search" :size="18" class="search-icon" />
      <input v-model="query" type="search" placeholder="Search item or code" />
    </div>

    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && rows.length === 0" class="stack">
      <div class="skeleton" style="height:3rem" />
      <div class="skeleton" style="height:3rem" />
      <div class="skeleton" style="height:3rem" />
    </div>

    <div v-else-if="rows.length === 0" class="empty">
      <Icon name="stock" :size="32" class="empty-icon" />
      <strong>Van is empty</strong>
      <span class="muted">No stock assigned to this warehouse.</span>
    </div>

    <div v-else-if="filtered.length === 0" class="empty">
      <Icon name="search" :size="28" class="empty-icon" />
      <span class="muted">No items match “{{ query }}”.</span>
    </div>

    <ul v-else class="list">
      <li v-for="r in filtered" :key="r.item_code" class="item">
        <div class="body">
          <strong class="truncate">{{ r.item_name }}</strong>
          <span class="muted xsmall">{{ r.item_code }} · {{ r.stock_uom }}</span>
        </div>
        <span class="qty pill" :data-tone="tone(r.actual_qty)">{{ fmt(r.actual_qty) }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 8%, var(--surface)) 0%, var(--surface) 100%);
}
.hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.hero-wh { margin: 0.15rem 0 0; font-size: var(--text-lg); }

.hero-pills { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }
.stat {
  background: var(--surface-muted);
  padding: 0.6rem 0.5rem;
  border-radius: var(--radius-sm);
  display: flex; flex-direction: column; align-items: center; gap: 0.15rem;
}
.stat strong { font-size: var(--text-lg); font-variant-numeric: tabular-nums; }
.stat[data-tone="warning"] strong { color: var(--warning); }
.stat[data-tone="danger"] strong { color: var(--danger); }

.search { position: relative; }
.search-icon {
  position: absolute; top: 50%; inset-inline-start: 0.75rem; transform: translateY(-50%);
  color: var(--text-muted); pointer-events: none;
}
.search input { padding-inline-start: 2.5rem; }

.list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.item {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 0.65rem 0.8rem;
  box-shadow: var(--shadow-sm);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.75rem;
  align-items: center;
}
.body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.qty { font-variant-numeric: tabular-nums; font-weight: 600; min-width: 2.5rem; text-align: center; }
</style>
