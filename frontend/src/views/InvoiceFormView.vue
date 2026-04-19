<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listMine as listCustomers } from "@/api/customer";
import { listMine as listItems, type ItemRow } from "@/api/item";
import { save, type InvoiceItem } from "@/api/invoice";
import { warehouses } from "@/api/dashboard";
import { ApiError } from "@/app/frappe";

const router = useRouter();

const customers = ref<Array<{ name: string; customer_name: string }>>([]);
const items = ref<ItemRow[]>([]);
const whs = ref<Array<{ name: string; warehouse_name: string }>>([]);

const customer = ref("");
const warehouse = ref("");
const lines = ref<InvoiceItem[]>([]);
const itemSearch = ref("");
const remarks = ref("");

const busy = ref(false);
const err = ref("");
const success = ref("");

const total = computed(() => lines.value.reduce((sum, l) => sum + l.qty * l.rate, 0));

async function loadAll() {
  customers.value = await listCustomers(undefined, 200);
  items.value = await listItems(undefined, warehouse.value || undefined, 300);
  whs.value = await warehouses();
  if (!warehouse.value && whs.value.length > 0) warehouse.value = whs.value[0].name;
}

async function searchItems() {
  items.value = await listItems(itemSearch.value || undefined, warehouse.value || undefined, 80);
}

function addLine(item: ItemRow) {
  const existing = lines.value.find((l) => l.item_code === item.item_code);
  if (existing) {
    existing.qty += 1;
    return;
  }
  lines.value.push({
    item_code: item.item_code,
    item_name: item.item_name,
    qty: 1,
    rate: item.standard_rate ?? 0,
    uom: item.stock_uom,
    warehouse: warehouse.value || undefined,
  });
}

function removeLine(idx: number) {
  lines.value.splice(idx, 1);
}

async function submit() {
  err.value = "";
  success.value = "";
  if (!customer.value) {
    err.value = "Pick a customer";
    return;
  }
  if (lines.value.length === 0) {
    err.value = "Add at least one item";
    return;
  }
  busy.value = true;
  try {
    const res = await save({
      customer: customer.value,
      warehouse: warehouse.value || undefined,
      items: lines.value,
      remarks: remarks.value || undefined,
      update_stock: 1,
      submit: 1,
    });
    success.value = res.queued
      ? `Saved offline (${res.clientId.slice(0, 8)}) — will sync when online.`
      : `Saved as ${res.name} (${res.grand_total})`;
    lines.value = [];
    setTimeout(() => router.push({ name: "dashboard" }), 900);
  } catch (e) {
    err.value = e instanceof ApiError ? (e.serverMessage ?? e.message) : e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(loadAll);
</script>

<template>
  <section class="stack">
    <h1>New invoice</h1>

    <section class="card stack">
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Customer</span>
        <select v-model="customer">
          <option value="" disabled>Select…</option>
          <option v-for="c in customers" :key="c.name" :value="c.name">
            {{ c.customer_name }} ({{ c.name }})
          </option>
        </select>
      </label>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Warehouse</span>
        <select v-model="warehouse" @change="searchItems">
          <option value="">Default</option>
          <option v-for="w in whs" :key="w.name" :value="w.name">
            {{ w.warehouse_name }}
          </option>
        </select>
      </label>
    </section>

    <section class="card stack">
      <strong>Lines</strong>
      <ul class="lines" v-if="lines.length > 0">
        <li v-for="(l, i) in lines" :key="`${l.item_code}-${i}`" class="line">
          <div>
            <strong>{{ l.item_name || l.item_code }}</strong>
            <div class="muted small">{{ l.item_code }} · {{ l.uom || "" }}</div>
          </div>
          <input type="number" min="0" step="any" v-model.number="l.qty" aria-label="Qty" />
          <input type="number" min="0" step="any" v-model.number="l.rate" aria-label="Rate" />
          <button class="ghost" type="button" @click="removeLine(i)">✕</button>
        </li>
      </ul>
      <p v-else class="muted small">Pick from the catalog below.</p>
      <div class="total" v-if="lines.length > 0">
        <span class="muted">Total</span>
        <strong>{{ total.toFixed(3) }}</strong>
      </div>
    </section>

    <section class="card stack">
      <strong>Catalog</strong>
      <input v-model="itemSearch" placeholder="Search items / code / barcode" @input="searchItems" />
      <ul class="catalog">
        <li v-for="it in items" :key="it.item_code" class="cat-item">
          <button type="button" class="ghost" style="text-align: left" @click="addLine(it)">
            <div><strong>{{ it.item_name }}</strong></div>
            <div class="muted small">
              {{ it.item_code }} · {{ it.standard_rate ?? 0 }}
              <span v-if="typeof it.stock_qty === 'number'">· stock {{ it.stock_qty }}</span>
            </div>
          </button>
        </li>
      </ul>
    </section>

    <label class="stack" style="gap: 0.3rem">
      <span class="muted">Notes</span>
      <textarea v-model="remarks" rows="2" />
    </label>

    <p v-if="err" class="error">{{ err }}</p>
    <p v-if="success" class="success">{{ success }}</p>

    <button :disabled="busy" @click="submit">
      {{ busy ? "Saving…" : "Save + submit" }}
    </button>
    <button class="ghost" type="button" @click="router.back()">Cancel</button>
  </section>
</template>

<style scoped>
.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.line {
  display: grid;
  grid-template-columns: 1fr 3.5rem 4.5rem auto;
  gap: 0.5rem;
  align-items: center;
}
.line input { padding: 0.4rem 0.5rem; }
.total { display: flex; justify-content: space-between; }
.catalog { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; max-height: 18rem; overflow-y: auto; }
.cat-item .ghost { width: 100%; padding: 0.55rem 0.65rem; border-radius: 0.5rem; background: rgba(37, 99, 235, 0.04); }
.small { font-size: 0.78rem; }
.success { color: var(--success); font-size: 0.9rem; }
</style>
