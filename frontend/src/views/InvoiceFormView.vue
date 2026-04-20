<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers } from "@/api/customer";
import { listMine as listItems, type ItemRow } from "@/api/item";
import { save, type InvoiceItem } from "@/api/invoice";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const customers = ref<Array<{ name: string; customer_name: string }>>([]);
const items = ref<ItemRow[]>([]);

const customer = ref(String(route.query.customer ?? ""));
const warehouse = computed(() => session.defaultWarehouse ?? "");
const lines = ref<InvoiceItem[]>([]);
const itemSearch = ref("");
const remarks = ref("");

const busy = ref(false);

const total = computed(() =>
  lines.value.reduce((sum, l) => sum + (Number(l.qty) || 0) * (Number(l.rate) || 0), 0),
);

const selectedCustomer = computed(() =>
  customers.value.find((c) => c.name === customer.value),
);

async function loadAll() {
  customers.value = await listCustomers(undefined, 200);
  items.value = await listItems(undefined, warehouse.value || undefined, 300);
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
  if (!customer.value) { toasts.warn("Pick a customer"); return; }
  if (lines.value.length === 0) { toasts.warn("Add at least one item"); return; }
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
    toasts.success(
      res.queued
        ? "Saved offline — will sync when online"
        : `Invoice ${res.name} saved (${session.currency} ${res.grand_total.toFixed(2)})`,
    );
    lines.value = [];
    setTimeout(() => router.push({ name: "dashboard" }), 700);
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
  }
}

onMounted(loadAll);
</script>

<template>
  <div class="stack">
    <section class="card stack">
      <label class="field">
        <span class="label">Customer</span>
        <select v-model="customer">
          <option value="" disabled>Select customer…</option>
          <option v-for="c in customers" :key="c.name" :value="c.name">
            {{ c.customer_name }}
          </option>
        </select>
      </label>
      <div v-if="selectedCustomer" class="selected-hint">
        <Icon name="customer" :size="14" /> {{ selectedCustomer.customer_name }}
      </div>
      <div v-if="warehouse" class="muted small">
        <Icon name="truck" :size="14" /> {{ warehouse }}
      </div>
    </section>

    <section class="card stack">
      <div class="section-head">
        <h3 style="margin:0">Lines</h3>
        <strong v-if="lines.length > 0">
          {{ session.currency }} {{ total.toFixed(2) }}
        </strong>
      </div>
      <div v-if="lines.length === 0" class="empty" style="padding:1rem 0">
        <Icon name="bag" :size="28" class="empty-icon" />
        <span>Add items from the catalog.</span>
      </div>
      <ul v-else class="lines">
        <li v-for="(l, i) in lines" :key="`${l.item_code}-${i}`" class="line">
          <div class="line-head">
            <strong class="truncate">{{ l.item_name || l.item_code }}</strong>
            <button class="icon-only small" type="button" @click="removeLine(i)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="muted xsmall">{{ l.item_code }} · {{ l.uom || "" }}</div>
          <div class="line-inputs">
            <label>
              <span class="tiny">Qty</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.qty" />
            </label>
            <label>
              <span class="tiny">Rate</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.rate" />
            </label>
            <div class="line-amount">
              <span class="tiny">Total</span>
              <strong>{{ ((Number(l.qty) || 0) * (Number(l.rate) || 0)).toFixed(2) }}</strong>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <section class="card stack">
      <h3 style="margin:0">Catalog</h3>
      <div class="search-bar">
        <Icon name="search" :size="18" class="search-ic" />
        <input v-model="itemSearch" placeholder="Search item code / name / barcode" @input="searchItems" />
      </div>
      <ul class="catalog">
        <li v-for="it in items" :key="it.item_code">
          <button class="cat-item" type="button" @click="addLine(it)">
            <div>
              <strong class="truncate">{{ it.item_name }}</strong>
              <div class="muted xsmall">{{ it.item_code }}</div>
            </div>
            <div class="right-col">
              <strong>{{ session.currency }} {{ (it.standard_rate ?? 0).toFixed(2) }}</strong>
              <span v-if="typeof it.stock_qty === 'number'" class="pill" data-tone="primary">
                {{ it.stock_qty }} in stock
              </span>
            </div>
          </button>
        </li>
      </ul>
    </section>

    <label class="field">
      <span class="label">Notes (optional)</span>
      <textarea v-model="remarks" rows="2" />
    </label>

    <button class="submit" :disabled="busy || lines.length === 0" @click="submit">
      <Icon name="check" :size="18" />
      {{ busy ? "Saving…" : `Save invoice${lines.length ? ` · ${session.currency} ${total.toFixed(2)}` : ""}` }}
    </button>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.selected-hint { font-size: var(--text-xs); color: var(--primary); display: inline-flex; align-items: center; gap: 0.3rem; }

.section-head { display: flex; justify-content: space-between; align-items: center; }

.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line { background: var(--surface-muted); border-radius: var(--radius); padding: 0.6rem 0.75rem; display: flex; flex-direction: column; gap: 0.25rem; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-inputs { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.4rem; align-items: end; margin-top: 0.3rem; }
.line-inputs label { display: flex; flex-direction: column; gap: 0.15rem; }
.line-inputs input { padding: 0.45rem 0.55rem; font-size: var(--text-sm); }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.line-amount { text-align: right; }
.line-amount strong { font-variant-numeric: tabular-nums; }

.search-bar { position: relative; }
.search-ic { position: absolute; inset-inline-start: 0.7rem; top: 50%; transform: translateY(-50%); color: var(--text-faint); pointer-events: none; }
.search-bar input { padding-inline-start: 2.3rem; }

.catalog { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; max-height: 22rem; overflow-y: auto; padding-right: 0.25rem; }
.cat-item {
  all: unset; width: 100%; cursor: pointer;
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
  transition: background var(--dur-fast) var(--ease);
}
.cat-item:active { background: var(--primary-soft); }
.right-col { display: flex; flex-direction: column; align-items: flex-end; gap: 0.2rem; }

.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.submit { min-height: 3.25rem; font-size: var(--text-base); }
.icon-only.small { min-height: 1.8rem; width: 1.8rem; padding: 0.3rem; }
</style>
