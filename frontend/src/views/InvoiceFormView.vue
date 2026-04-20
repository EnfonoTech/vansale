<script setup lang="ts">
/**
 * Sales invoice form — rewritten for Phase B.
 *
 * Features (per PDF 2026-04-20 §1):
 *  - Customer select + inline "new customer" hook (Phase C will wire)
 *  - Catalog: each click adds a new line (same item → multiple rows)
 *  - Per-line: qty, rate (editable), UOM select from item's UOMs,
 *              discount %, line total
 *  - Price List rate auto-fetched per (customer, item, uom)
 *  - Payment type toggle: Cash / Credit
 *  - Mode of payment select when Cash — invoice.save auto-adds payments row
 *  - Save as Draft / Save & Submit buttons
 *  - Tax preview (15% VAT) — real breakup appears on detail view after save
 *  - Sales person chip (auto-tagged by backend)
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers } from "@/api/customer";
import {
  listMine as listItems,
  detail as itemDetail,
  priceFor,
  type ItemRow,
  type ItemUom,
} from "@/api/item";
import { save, type InvoiceItem } from "@/api/invoice";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

interface Line extends InvoiceItem {
  uoms?: ItemUom[];        // per-line UOM choices
  amount: number;          // computed
}

const customers = ref<Array<{ name: string; customer_name: string }>>([]);
const items = ref<ItemRow[]>([]);

const customer = ref(String(route.query.customer ?? ""));
const warehouse = computed(() => session.defaultWarehouse ?? "");
const lines = ref<Line[]>([]);
const itemSearch = ref("");
const remarks = ref("");

const paymentType = ref<"cash" | "credit">("cash");
const modeOfPayment = ref<string>("Cash");
const discountAmount = ref<number | null>(null);

const busy = ref(false);
const savingDraft = ref(false);

// UOM cache — item_code → uoms list, so re-adding same item doesn't refetch.
const uomCache = reactive<Record<string, ItemUom[]>>({});

const TAX_RATE = 0.15;

const netTotal = computed(() => lines.value.reduce((s, l) => s + l.amount, 0));
const taxTotal = computed(() => (netTotal.value - (discountAmount.value || 0)) * TAX_RATE);
const grandTotal = computed(() => netTotal.value - (discountAmount.value || 0) + taxTotal.value);

const selectedCustomer = computed(() =>
  customers.value.find((c) => c.name === customer.value),
);

// Re-price all lines when customer changes (different price list).
watch(customer, async (newCustomer) => {
  if (!newCustomer) return;
  for (const l of lines.value) {
    try {
      const p = await priceFor(l.item_code, newCustomer, l.uom);
      if (p.price_list_rate) {
        l.price_list_rate = p.price_list_rate;
        l.rate = p.price_list_rate;
        recalc(l);
      }
    } catch {
      /* ignore per-line failures */
    }
  }
});

async function loadAll() {
  customers.value = await listCustomers(undefined, 200);
  items.value = await listItems(undefined, warehouse.value || undefined, 300);
}

async function searchItems() {
  items.value = await listItems(itemSearch.value || undefined, warehouse.value || undefined, 80);
}

function recalc(l: Line) {
  const qty = Number(l.qty) || 0;
  const rate = Number(l.rate) || 0;
  const disc = Number(l.discount_percentage) || 0;
  const net = qty * rate * (1 - disc / 100);
  l.amount = Math.max(0, net);
}

async function addLine(item: ItemRow) {
  // Always add a new row (same-item multi-row per PDF 1a).
  let uoms = uomCache[item.item_code];
  let priceListRate = item.standard_rate ?? 0;
  if (!uoms) {
    try {
      const d = await itemDetail(item.item_code, customer.value || undefined);
      uoms = d.uoms;
      priceListRate = d.price_list_rate || priceListRate;
      uomCache[item.item_code] = uoms;
    } catch {
      uoms = [
        {
          uom: item.stock_uom,
          conversion_factor: 1,
          price_list_rate: item.standard_rate ?? 0,
        },
      ];
    }
  } else {
    // Pick the stock_uom entry for price seed.
    const match = uoms.find((u) => u.uom === item.stock_uom) ?? uoms[0];
    priceListRate = match?.price_list_rate || priceListRate;
  }
  const firstUom = uoms[0];
  const line: Line = {
    item_code: item.item_code,
    item_name: item.item_name,
    qty: 1,
    rate: firstUom?.price_list_rate || priceListRate,
    price_list_rate: firstUom?.price_list_rate || priceListRate,
    uom: firstUom?.uom || item.stock_uom,
    conversion_factor: firstUom?.conversion_factor || 1,
    discount_percentage: 0,
    warehouse: warehouse.value || undefined,
    uoms,
    amount: 0,
  };
  recalc(line);
  lines.value.push(line);
}

async function onUomChange(l: Line) {
  if (!l.uoms) return;
  const chosen = l.uoms.find((u) => u.uom === l.uom);
  if (chosen) {
    l.conversion_factor = chosen.conversion_factor;
    l.price_list_rate = chosen.price_list_rate;
    l.rate = chosen.price_list_rate;
  } else {
    try {
      const p = await priceFor(l.item_code, customer.value || undefined, l.uom);
      l.price_list_rate = p.price_list_rate;
      l.rate = p.price_list_rate;
    } catch {
      /* keep existing rate */
    }
  }
  recalc(l);
}

function removeLine(idx: number) {
  lines.value.splice(idx, 1);
}

async function doSave(submit: 0 | 1) {
  if (!customer.value) { toasts.warn("Pick a customer"); return; }
  if (lines.value.length === 0) { toasts.warn("Add at least one item"); return; }
  const flag = submit === 1;
  if (flag) busy.value = true; else savingDraft.value = true;
  try {
    const payload = {
      customer: customer.value,
      warehouse: warehouse.value || undefined,
      items: lines.value.map<InvoiceItem>((l) => ({
        item_code: l.item_code,
        item_name: l.item_name,
        qty: l.qty,
        rate: l.rate,
        price_list_rate: l.price_list_rate,
        discount_percentage: l.discount_percentage,
        uom: l.uom,
        conversion_factor: l.conversion_factor,
        warehouse: l.warehouse,
      })),
      remarks: remarks.value || undefined,
      update_stock: 1 as const,
      submit,
      payment_type: paymentType.value,
      mode_of_payment: paymentType.value === "cash" ? modeOfPayment.value : undefined,
      discount_amount: discountAmount.value ?? undefined,
      apply_discount_on: discountAmount.value ? ("Grand Total" as const) : undefined,
    };
    const res = await save(payload);
    toasts.success(
      res.queued
        ? "Saved offline — will sync when online"
        : `Invoice ${res.name} ${flag ? "submitted" : "saved as draft"} (${session.currency} ${res.grand_total.toFixed(2)})`,
    );
    lines.value = [];
    if (!res.queued && res.name && !res.name.startsWith("QUEUED")) {
      // Auto-print popup on submit (PDF §1g). Skip for drafts.
      if (flag) {
        const url = `/printview?doctype=Sales%20Invoice&name=${encodeURIComponent(res.name)}&trigger_print=1&format=Standard&no_letterhead=0`;
        window.open(url, "_blank", "noopener,noreferrer");
      }
      setTimeout(() => router.push({ name: "invoice-detail", params: { name: res.name } }), 600);
    } else {
      setTimeout(() => router.push({ name: "dashboard" }), 700);
    }
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
    savingDraft.value = false;
  }
}

function newCustomerClick() {
  router.push({ name: "customer-new", query: { redirect: "invoice" } });
}

onMounted(loadAll);
</script>

<template>
  <div class="stack">
    <!-- Customer -->
    <section class="card stack">
      <div class="row-head">
        <span class="label">Customer</span>
        <button type="button" class="link-btn" @click="newCustomerClick">
          <Icon name="plus" :size="14" /> New
        </button>
      </div>
      <select v-model="customer">
        <option value="" disabled>Select customer…</option>
        <option v-for="c in customers" :key="c.name" :value="c.name">
          {{ c.customer_name }}
        </option>
      </select>
      <div v-if="selectedCustomer" class="selected-hint">
        <Icon name="customer" :size="14" /> {{ selectedCustomer.customer_name }}
      </div>
      <div v-if="warehouse" class="muted small">
        <Icon name="truck" :size="14" /> {{ warehouse }}
      </div>
      <div v-if="session.$state.defaults?.sales_person_name" class="sp-chip">
        <Icon name="user" :size="12" /> Sales: {{ session.$state.defaults.sales_person_name }}
      </div>
    </section>

    <!-- Payment -->
    <section class="card stack">
      <span class="label">Payment</span>
      <div class="seg">
        <button
          type="button"
          class="seg-btn"
          :data-active="paymentType === 'cash'"
          @click="paymentType = 'cash'"
        >
          <Icon name="payment" :size="16" /> Cash
        </button>
        <button
          type="button"
          class="seg-btn"
          :data-active="paymentType === 'credit'"
          @click="paymentType = 'credit'"
        >
          <Icon name="clock" :size="16" /> Credit
        </button>
      </div>
      <label v-if="paymentType === 'cash'" class="field">
        <span class="tiny">Mode of Payment</span>
        <select v-model="modeOfPayment">
          <option value="Cash">Cash</option>
          <option value="Bank Draft">Bank</option>
          <option value="Credit Card">Credit Card</option>
        </select>
      </label>
    </section>

    <!-- Lines -->
    <section class="card stack">
      <div class="section-head">
        <h3 style="margin:0">Lines</h3>
        <strong v-if="lines.length > 0" class="tabular">
          {{ session.currency }} {{ netTotal.toFixed(2) }}
        </strong>
      </div>
      <div v-if="lines.length === 0" class="empty" style="padding:1rem 0">
        <Icon name="bag" :size="28" class="empty-icon" />
        <span>Add items from the catalog.</span>
      </div>
      <ul v-else class="lines">
        <li v-for="(l, i) in lines" :key="i" class="line">
          <div class="line-head">
            <strong class="truncate">{{ l.item_name || l.item_code }}</strong>
            <button class="icon-only small" type="button" @click="removeLine(i)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="muted xsmall">{{ l.item_code }}</div>
          <div class="line-grid">
            <label>
              <span class="tiny">Qty</span>
              <input type="number" min="0" step="any" inputmode="decimal"
                     v-model.number="l.qty" @input="recalc(l)" />
            </label>
            <label>
              <span class="tiny">UOM</span>
              <select v-if="l.uoms && l.uoms.length > 1" v-model="l.uom" @change="onUomChange(l)">
                <option v-for="u in l.uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
              </select>
              <input v-else type="text" :value="l.uom" disabled />
            </label>
            <label>
              <span class="tiny">Rate</span>
              <input type="number" min="0" step="any" inputmode="decimal"
                     v-model.number="l.rate" @input="recalc(l)" />
            </label>
            <label>
              <span class="tiny">Disc %</span>
              <input type="number" min="0" max="100" step="any" inputmode="decimal"
                     v-model.number="l.discount_percentage" @input="recalc(l)" />
            </label>
          </div>
          <div class="line-foot">
            <span v-if="l.price_list_rate && l.price_list_rate !== l.rate" class="muted xsmall">
              List: {{ session.currency }} {{ (l.price_list_rate || 0).toFixed(2) }}
            </span>
            <strong class="tabular">{{ session.currency }} {{ l.amount.toFixed(2) }}</strong>
          </div>
        </li>
      </ul>
    </section>

    <!-- Catalog -->
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

    <!-- Totals preview -->
    <section v-if="lines.length > 0" class="card stack totals">
      <div class="tot-row">
        <span>Net total</span>
        <span class="tabular">{{ session.currency }} {{ netTotal.toFixed(2) }}</span>
      </div>
      <label class="field">
        <span class="tiny">Invoice discount ({{ session.currency }})</span>
        <input type="number" min="0" step="any" inputmode="decimal" v-model.number="discountAmount" placeholder="0" />
      </label>
      <div class="tot-row muted">
        <span>VAT ({{ (TAX_RATE * 100).toFixed(0) }}%)</span>
        <span class="tabular">{{ session.currency }} {{ taxTotal.toFixed(2) }}</span>
      </div>
      <div class="tot-row grand">
        <span>Grand total</span>
        <span class="tabular">{{ session.currency }} {{ grandTotal.toFixed(2) }}</span>
      </div>
      <p class="muted xsmall">Final tax breakup computed by server on save.</p>
    </section>

    <label class="field">
      <span class="label">Notes (optional)</span>
      <textarea v-model="remarks" rows="2" />
    </label>

    <div class="actions">
      <button class="btn-ghost" type="button"
              :disabled="savingDraft || busy || lines.length === 0"
              @click="doSave(0)">
        <Icon name="edit" :size="18" />
        {{ savingDraft ? "Saving…" : "Save draft" }}
      </button>
      <button class="submit" type="button"
              :disabled="busy || savingDraft || lines.length === 0"
              @click="doSave(1)">
        <Icon name="check" :size="18" />
        {{ busy ? "Submitting…" : `Submit · ${session.currency} ${grandTotal.toFixed(2)}` }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.row-head { display: flex; justify-content: space-between; align-items: center; }
.link-btn {
  all: unset; cursor: pointer; color: var(--primary);
  font-size: var(--text-xs); font-weight: 600;
  display: inline-flex; align-items: center; gap: 0.25rem;
}
.selected-hint { font-size: var(--text-xs); color: var(--primary); display: inline-flex; align-items: center; gap: 0.3rem; }
.sp-chip {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: var(--text-xs); color: var(--text-muted);
  background: var(--surface-muted); padding: 0.2rem 0.5rem;
  border-radius: 999px; width: fit-content;
}

.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer;
  padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center;
  font-weight: 500; display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }

.section-head { display: flex; justify-content: space-between; align-items: center; }
.tabular { font-variant-numeric: tabular-nums; }

.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line { background: var(--surface-muted); border-radius: var(--radius); padding: 0.65rem 0.75rem; display: flex; flex-direction: column; gap: 0.3rem; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.4rem; align-items: end; margin-top: 0.3rem; }
.line-grid label { display: flex; flex-direction: column; gap: 0.15rem; }
.line-grid input, .line-grid select { padding: 0.45rem 0.55rem; font-size: var(--text-sm); }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.line-foot { display: flex; justify-content: space-between; align-items: center; padding-top: 0.25rem; border-top: 1px dashed var(--border-soft, rgba(0,0,0,.08)); }

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

.totals .tot-row { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); }
.totals .tot-row.grand { font-size: var(--text-base); font-weight: 700; border-top: 1px solid var(--border-soft, rgba(0,0,0,.08)); padding-top: 0.4rem; margin-top: 0.1rem; }

.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.actions { display: grid; grid-template-columns: 1fr 1.4fr; gap: 0.5rem; }
.btn-ghost {
  all: unset; cursor: pointer;
  min-height: 3.25rem; border-radius: var(--radius);
  background: var(--surface-muted); text-align: center;
  display: inline-flex; justify-content: center; align-items: center; gap: 0.4rem;
  font-weight: 600;
}
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
.icon-only.small { min-height: 1.8rem; width: 1.8rem; padding: 0.3rem; }
</style>
