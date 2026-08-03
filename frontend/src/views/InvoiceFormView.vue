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
import { save, detail, updateDraft, type InvoiceItem } from "@/api/invoice";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const props = defineProps<{ name?: string }>();

// Edit mode: we're editing an existing draft invoice. Saved doc name is
// captured so submit can delete-old + save-new (drafts only — safe because
// no stock is posted and no GL entries exist until submit).
const editName = computed(() => props.name || String(route.params.name ?? ""));
const isEditMode = computed(() => Boolean(editName.value));

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

// The catalog only lists items with stock in this van (see `loadAll`), so
// distinguish "your search matched nothing" from "this van is empty" —
// the second one needs the office to post a transfer, not a retype.
const emptyCatalogHint = computed(() => {
  if (itemSearch.value.trim()) return "No item in this van's stock matches that search.";
  return warehouse.value
    ? `No stock in ${warehouse.value}. Ask the office to transfer stock into the van.`
    : "No van warehouse assigned to your user. Ask the office to set one.";
});

const netTotal = computed(() => lines.value.reduce((s, l) => s + l.amount, 0));
const taxTotal = computed(() => (netTotal.value - (discountAmount.value || 0)) * TAX_RATE);
const grandTotal = computed(() => netTotal.value - (discountAmount.value || 0) + taxTotal.value);

/**
 * Itemwise split preview — shows how the invoice-level discount is spread
 * across each line proportionally to its amount. Mirrors the math in
 * `doSave()` so the operator sees exactly what the backend will store.
 */
interface DiscountSplitRow {
  item_name: string;
  qty: number;
  share: number;      // total discount absorbed by this line
  perUnit: number;    // per-unit discount_amount stamped on the row
  netAfter: number;   // line amount after discount
}
const discountSplit = computed<DiscountSplitRow[]>(() => {
  const docDisc = Number(discountAmount.value) || 0;
  const subtotal = netTotal.value;
  if (docDisc <= 0 || subtotal <= 0 || lines.value.length === 0) return [];
  const rows: DiscountSplitRow[] = [];
  let allocated = 0;
  lines.value.forEach((l, i) => {
    const qty = Number(l.qty) || 0;
    if (qty <= 0) {
      rows.push({ item_name: l.item_name || l.item_code, qty, share: 0, perUnit: 0, netAfter: l.amount });
      return;
    }
    const isLast = i === lines.value.length - 1;
    const share = isLast
      ? Math.max(0, docDisc - allocated)
      : docDisc * ((Number(l.amount) || 0) / subtotal);
    allocated += share;
    rows.push({
      item_name: l.item_name || l.item_code,
      qty,
      share,
      perUnit: share / qty,
      netAfter: Math.max(0, (Number(l.amount) || 0) - share),
    });
  });
  return rows;
});

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
  // `onlyInStock` — a van can only sell what it carries, and an item with
  // no incoming stock has no valuation rate, which ERPNext rejects at
  // submit time (surfacing as an unfixable sync error days later).
  items.value = await listItems(undefined, warehouse.value || undefined, 300, true);
  if (isEditMode.value) {
    await prefillFromDraft(editName.value);
  }
}

async function prefillFromDraft(name: string) {
  try {
    const doc = await detail(name);
    if (doc.docstatus !== 0) {
      toasts.error("Only draft invoices can be edited");
      void router.replace({ name: "invoice-detail", params: { name } });
      return;
    }
    customer.value = doc.customer;
    remarks.value = doc.remarks || "";
    discountAmount.value = doc.discount_amount || null;
    // Rebuild line rows. We skip UOM re-fetching since the doc already has
    // rate/price_list_rate frozen; operator can still change qty/rate inline.
    lines.value = doc.items.map<Line>((it) => ({
      item_code: it.item_code,
      item_name: it.item_name,
      qty: it.qty,
      rate: it.rate,
      price_list_rate: it.price_list_rate,
      discount_percentage: it.discount_percentage,
      discount_amount: it.discount_amount,
      uom: it.uom ?? undefined,
      conversion_factor: 1,  // server recomputes on save
      warehouse: it.warehouse ?? undefined,
      uoms: it.uom ? [{ uom: it.uom, conversion_factor: 1, price_list_rate: it.price_list_rate }] : [],
      amount: it.amount,
    }));
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
    void router.replace({ name: "invoices" });
  }
}

async function searchItems() {
  items.value = await listItems(itemSearch.value || undefined, warehouse.value || undefined, 80, true);
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
    /*
     * Split the invoice-level discount across items proportionally by
     * line amount and stamp each line's `discount_amount`. The backend
     * then stores discount on every line (per-item traceability) rather
     * than carrying a floating doc-level discount that disappears into
     * a tax row. This is what the user means by "split to itemwise" —
     * each row's discount is visible in the printed invoice and the
     * ledger.
     *
     * Math:
     *   lineNet_i = qty_i * rate_i * (1 - line_disc_pct_i/100)
     *   share_i  = docDiscount * lineNet_i / sum(lineNet)
     *   perUnit  = share_i / qty_i
     * The last line absorbs any rounding drift so the sum still equals
     * the docDiscount the operator entered.
     */
    const docDisc = Number(discountAmount.value) || 0;
    const subtotal = lines.value.reduce((s, l) => s + (Number(l.amount) || 0), 0);
    const perLineExtraDisc: number[] = lines.value.map(() => 0);
    if (docDisc > 0 && subtotal > 0) {
      let allocated = 0;
      lines.value.forEach((l, i) => {
        const qty = Number(l.qty) || 0;
        if (qty <= 0) return;
        const isLast = i === lines.value.length - 1;
        const share = isLast
          ? Math.max(0, docDisc - allocated)
          : docDisc * ((Number(l.amount) || 0) / subtotal);
        allocated += share;
        perLineExtraDisc[i] = share / qty;   // discount amount per unit
      });
    }

    const payload = {
      customer: customer.value,
      warehouse: warehouse.value || undefined,
      // ERPNext computes `discount_amount` + `discount_percentage` from
      // (price_list_rate - rate). If we pass `rate == price_list_rate`
      // AND `discount_amount`, ERPNext resets disc to 0 on validate()
      // — which is why submitted invoices lost their discount. Collapse
      // everything into an effective `rate`: line-% first, then doc-level
      // split per unit. ERPNext then stores price_list_rate (original)
      // and rate (after-discount), computes disc_%/disc_amount itself
      // — so both the detail view and the ZATCA print format see the
      // strike-through + discounted rate we want.
      items: lines.value.map<InvoiceItem>((l, i) => {
        const baseRate = Number(l.price_list_rate) || Number(l.rate) || 0;
        const linePct = Math.max(0, Math.min(100, Number(l.discount_percentage) || 0));
        const rateAfterLinePct = baseRate * (1 - linePct / 100);
        const perUnitDoc = perLineExtraDisc[i] || 0;
        const effectiveRate = Math.max(0, rateAfterLinePct - perUnitDoc);
        return {
          item_code: l.item_code,
          item_name: l.item_name,
          qty: l.qty,
          rate: effectiveRate,
          price_list_rate: baseRate,
          // Do NOT send discount_percentage / discount_amount — let ERPNext
          // derive both from (price_list_rate - rate) so the stored values
          // survive submit (its on_submit recalc overrides stamps we send).
          uom: l.uom,
          conversion_factor: l.conversion_factor,
          warehouse: l.warehouse,
        };
      }),
      remarks: remarks.value || undefined,
      update_stock: 1 as const,
      submit,
      payment_type: paymentType.value,
      mode_of_payment: paymentType.value === "cash" ? modeOfPayment.value : undefined,
      // Doc-level discount is now pre-distributed into item-level
      // discount_amount, so we don't also send the doc discount field.
      discount_amount: undefined,
      apply_discount_on: undefined,
    };
    // Edit mode uses server-side `update_draft` which mutates the existing
    // doc in place — Van Users have write perm on their own drafts but NOT
    // delete perm, so the previous delete-then-save flow always raised
    // "Insufficient Permission for Sales Invoice". Keep the same payload
    // shape; `updateDraft` swaps the endpoint.
    const res = isEditMode.value
      ? await updateDraft({
          name: editName.value,
          items: payload.items,
          remarks: payload.remarks,
          warehouse: payload.warehouse,
          submit: payload.submit,
          payment_type: payload.payment_type,
          mode_of_payment: payload.mode_of_payment,
          discount_amount: payload.discount_amount,
          apply_discount_on: payload.apply_discount_on,
        })
      : await save(payload);
    toasts.success(
      res.queued
        ? "Saved offline — will sync when online"
        : `Invoice ${res.name} ${flag ? "submitted" : isEditMode.value ? "updated" : "saved as draft"} (${session.currency} ${res.grand_total.toFixed(2)})`,
    );
    lines.value = [];
    // Always land on the detail view after a successful save/submit so the
    // user can see the QR, tax breakup and hit Print manually. The old flow
    // auto-opened a `window.open` print popup (hostile on the Capacitor
    // WebView — it maps `_blank` to the host browser) and then bounced to
    // the dashboard on the queued path, which felt like "submit = home".
    if (!res.queued && res.name && !res.name.startsWith("QUEUED")) {
      void router.push({ name: "invoice-detail", params: { name: res.name } });
    } else {
      // Queued offline — no real doc name, so the detail page can't resolve.
      void router.push({ name: "invoices" });
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
          <SarSymbol :code="session.currency" />{{ netTotal.toFixed(2) }}
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
              List: <SarSymbol :code="session.currency" />{{ (l.price_list_rate || 0).toFixed(2) }}
            </span>
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ l.amount.toFixed(2) }}</strong>
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
              <strong><SarSymbol :code="session.currency" />{{ (it.standard_rate ?? 0).toFixed(2) }}</strong>
              <span v-if="typeof it.stock_qty === 'number'" class="pill" data-tone="primary">
                {{ it.stock_qty }} in stock
              </span>
            </div>
          </button>
        </li>
      </ul>
      <!--
        The catalog is filtered to items the van actually carries, so an
        empty list is a stock problem, not a broken screen. Say which, or
        the driver reads a blank panel as "the app is down".
      -->
      <p v-if="items.length === 0" class="muted small">{{ emptyCatalogHint }}</p>
    </section>

    <!-- Totals preview -->
    <section v-if="lines.length > 0" class="card stack totals">
      <div class="tot-row">
        <span>Net total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ netTotal.toFixed(2) }}</span>
      </div>
      <label class="field">
        <span class="tiny">Invoice discount ({{ session.currency }})</span>
        <input type="number" min="0" step="any" inputmode="decimal" v-model.number="discountAmount" placeholder="0" />
      </label>
      <!-- Itemwise split preview — only visible when operator enters a
           doc-level discount. Shows exactly how the amount flows into each
           line's per-unit discount_amount (what gets stored + printed). -->
      <div v-if="discountSplit.length > 0" class="disc-split">
        <div class="disc-split-head">
          <Icon name="tag" :size="14" />
          <span>Discount split across items</span>
        </div>
        <ul class="disc-split-list">
          <li v-for="(row, i) in discountSplit" :key="i" class="disc-split-row">
            <div class="disc-split-name">
              <strong class="truncate">{{ row.item_name }}</strong>
              <span class="muted xsmall">
                {{ row.qty }} × - <SarSymbol :code="session.currency" />{{ row.perUnit.toFixed(2) }}/unit
              </span>
            </div>
            <div class="disc-split-amt">
              <strong class="tabular warn"><SarSymbol :code="session.currency" />{{ row.share.toFixed(2) }}</strong>
              <span class="muted xsmall">Net <SarSymbol :code="session.currency" />{{ row.netAfter.toFixed(2) }}</span>
            </div>
          </li>
        </ul>
      </div>
      <div class="tot-row muted">
        <span>VAT ({{ (TAX_RATE * 100).toFixed(0) }}%)</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ taxTotal.toFixed(2) }}</span>
      </div>
      <div class="tot-row grand">
        <span>Grand total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ grandTotal.toFixed(2) }}</span>
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

.disc-split {
  background: var(--warning-soft, color-mix(in srgb, var(--warning) 14%, transparent));
  border: 1px dashed var(--warning);
  border-radius: var(--radius-sm);
  padding: 0.55rem 0.7rem;
  display: flex; flex-direction: column; gap: 0.45rem;
}
.disc-split-head {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-size: var(--text-xs); font-weight: 600; color: var(--warning);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.disc-split-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.disc-split-row {
  display: grid; grid-template-columns: 1fr auto; gap: 0.5rem; align-items: center;
  font-size: var(--text-sm);
}
.disc-split-name { display: flex; flex-direction: column; min-width: 0; }
.disc-split-amt { display: flex; flex-direction: column; align-items: flex-end; gap: 0.05rem; }
.warn { color: var(--warning); }

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
