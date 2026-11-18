<script setup lang="ts">
/**
 * Quotation / Sales Order form. One view for both (`kind`).
 *
 * Mirrors the invoice form's line editing (catalog, per-line qty / UOM / rate /
 * discount, server-resolved tax preview) without its payment section and
 * without the in-stock catalog filter: a quote or an order does not move
 * stock, so the whole price list is sellable.
 *
 * A quotation may be addressed to a Lead (`?lead=CRM-LEAD-…`); an order is
 * always for a customer.
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers, customerLabel, type CustomerRow } from "@/api/customer";
import { listMine as listItems, detail as itemDetail, priceFor, type ItemRow, type ItemUom } from "@/api/item";
import { taxInfo, type TaxInfo } from "@/api/invoice";
import { leadDetail, listLeads, type LeadRow } from "@/api/lead";
import {
  KIND, docDetail, saveDoc, updateDocDraft, type SellingKind, type SellingLine,
} from "@/api/selling";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { computeTaxTotals } from "@/features/van/tax";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import SearchSelect from "@/components/SearchSelect.vue";
import { vDecimals } from "@/components/decimals";
import { revealOnFocus } from "@/components/reveal";
import { inputValue } from "@/components/liveInput";
import { confirmSubmit, withCurrency } from "@/stores/confirm";
import { precheckBeforeSubmit } from "@/api/precheck";
import CreditPanel from "@/components/CreditPanel.vue";
import LineInsight from "@/components/LineInsight.vue";
import { useLineInsight } from "@/features/van/lineInsight";
import { stockLabel } from "@/features/van/stock";
import { creditRefusal, useCreditStatus } from "@/features/van/credit";

const props = defineProps<{ kind: SellingKind; name?: string }>();
const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();
const k = computed(() => KIND[props.kind]);

const isEdit = computed(() => Boolean(props.name));
// A quotation may be for a lead; the lead becomes a customer when the quotation is ordered.
const leadId = ref(String(route.query.lead ?? ""));
const quotationTo = ref<"Customer" | "Lead">(leadId.value && props.kind === "quotation" ? "Lead" : "Customer");
const leadLabel = ref("");
const leads = ref<LeadRow[]>([]);
const leadOptions = computed(() =>
  leads.value.map((l) => ({
    value: l.name,
    label: l.company_name || l.lead_name,
    sub: [l.company_name ? l.lead_name : "", l.mobile_no].filter(Boolean).join(" · "),
    keywords: [l.name, l.lead_name, l.company_name, l.mobile_no, l.email_id].filter(Boolean).join(" "),
  })),
);
async function onLeadSearch(term: string) {
  try {
    const found = await listLeads(50, term || undefined);
    const seen = new Set(leads.value.map((l) => l.name));
    for (const l of found) if (!seen.has(l.name) && !l.customer && l.status !== "Converted") leads.value.push(l);
  } catch { /* the preloaded list still filters locally */ }
}
const canPickLead = computed(() => props.kind === "quotation" && !isEdit.value);

interface Line extends SellingLine { uoms?: ItemUom[]; discount_percentage: number; amount: number; min_rate?: number }

/** Rate after the line discount — what a site's minimum price is compared with. */
function effectiveRate(l: Line): number {
  const disc = session.lineDiscount ? Number(l.discount_percentage) || 0 : 0;
  return (Number(l.rate) || 0) * (1 - disc / 100);
}
const belowMin = (l: Line) => Boolean(l.min_rate) && effectiveRate(l) + 0.0001 < (l.min_rate ?? 0);

const customers = ref<CustomerRow[]>([]);
const items = ref<ItemRow[]>([]);
const customer = ref(String(route.query.customer ?? ""));
const lines = ref<Line[]>([]);
const itemSearch = ref("");
const remarks = ref("");
const discountAmount = ref<number | null>(null);
const busy = ref(false);

const addDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
// Quotes stay valid a month by default, orders are delivered within a week.
const date = ref(addDays(props.kind === "quotation" ? 30 : 7));
// Cash / credit on an order, where the site keeps it there (Steel Force's credit checks read it).
const showPayment = computed(() => props.kind === "order" && session.orderPaymentType);
const paymentType = ref<"cash" | "credit">(session.defaultPaymentType === "credit" ? "credit" : "cash");
// An order counts against the customer's credit limit: show it, and refuse
// Credit on tap (with the reason) when the customer can't have it.
const { status: credit, loading: creditLoading } = useCreditStatus(
  customer,
  computed(() => props.kind === "order" && quotationTo.value === "Customer"),
);
const creditRefused = computed(() => creditRefusal(credit.value, "credit"));
function pickPayment(t: "cash" | "credit") {
  if (t === "credit" && creditRefused.value && paymentType.value !== "credit") {
    toasts.warn(creditRefused.value);
    return;
  }
  paymentType.value = t;
}
const warehouse = computed(() => session.defaultWarehouse ?? "");
// Last price to this customer and short stock, under each line (a lead has no sales yet).
const insightCustomer = computed(() => (quotationTo.value === "Customer" ? customer.value : ""));
const insight = useLineInsight({ customer: insightCustomer, lines, warehouse: computed(() => warehouse.value || undefined) });

const party = computed(() => (quotationTo.value === "Lead" ? leadId.value : customer.value));

const tax = ref<TaxInfo>({ template: null, rate: 0, inclusive: false, simple: true, taxes: [] });
async function loadTax() {
  try {
    tax.value = await taxInfo(quotationTo.value === "Customer" ? customer.value || undefined : undefined);
  } catch { /* preview only; the server recomputes */ }
}

const round = (n: number) => {
  const f = 10 ** session.currencyPrecision;
  return Math.round((Number(n) || 0) * f) / f;
};
const roundRate = (n: number) => {
  const f = 10 ** session.ratePrecision;
  return Math.round((Number(n) || 0) * f) / f;
};
const money = (n: number) => (Number(n) || 0).toFixed(session.currencyPrecision);

/** A past price tapped under the line: it becomes the line's rate (as sold, so no line discount on top). */
function usePrice(l: Line, rate: number) {
  l.rate = roundRate(rate);
  l.discount_percentage = 0;
  recalc(l);
}

function recalc(l: Line) {
  const disc = session.lineDiscount ? Number(l.discount_percentage) || 0 : 0;
  l.amount = round(Math.max(0, (Number(l.qty) || 0) * (Number(l.rate) || 0) * (1 - disc / 100)));
}

const netTotal = computed(() => lines.value.reduce((s, l) => s + l.amount, 0));
const totals = computed(() =>
  computeTaxTotals({
    net: netTotal.value,
    discount: discountAmount.value,
    ratePercent: tax.value.rate,
    inclusive: tax.value.inclusive,
    applyOn: session.applyDiscountOn,
  }),
);

const customerOptions = computed(() =>
  customers.value.map((c) => ({
    value: c.name,
    label: customerLabel(c),
    sub: [c.secondary_name, c.vat_number ? `VAT ${c.vat_number}` : ""].filter(Boolean).join(" · "),
    keywords: [c.name, c.customer_name, c.customer_name_2, c.mobile_no, c.vat_number].filter(Boolean).join(" "),
  })),
);
async function onCustomerSearch(term: string) {
  try {
    const found = await listCustomers(term || undefined, 50);
    const seen = new Set(customers.value.map((c) => c.name));
    for (const c of found) if (!seen.has(c.name)) customers.value.push(c);
  } catch { /* offline — cached page still filters locally */ }
}

// Prices differ per customer — re-price when the customer changes.
const uomCache = reactive<Record<string, ItemUom[]>>({});
const uomKey = (code: string) => `${customer.value}|${code}`;
let keepRates = false;
watch(customer, async (c) => {
  void loadTax();
  if (keepRates) { keepRates = false; return; }
  if (!c) return;
  for (const l of lines.value) {
    try {
      const p = await priceFor(l.item_code, c, l.uom);
      if (p.price_list_rate) {
        l.price_list_rate = roundRate(p.price_list_rate);
        l.rate = roundRate(p.price_list_rate);
        recalc(l);
      }
    } catch { /* keep the typed rate */ }
  }
});

async function searchItems() {
  // The whole catalog, with the stock in the salesman's warehouse shown.
  items.value = await listItems(itemSearch.value || undefined, warehouse.value || undefined, 80, false);
}

async function addLine(item: ItemRow) {
  insight.noteStock(item);
  let uoms = uomCache[uomKey(item.item_code)];
  let listRate = 0;
  if (!uoms) {
    try {
      const d = await itemDetail(item.item_code, quotationTo.value === "Customer" ? customer.value || undefined : undefined);
      uoms = d.uoms;
      listRate = d.price_list_rate || 0;
      uomCache[uomKey(item.item_code)] = uoms;
    } catch {
      uoms = [{ uom: item.stock_uom, conversion_factor: 1, price_list_rate: 0 }];
    }
  }
  const first = session.uomChangeAllowed ? uoms[0] : (uoms.find((u) => u.uom === item.stock_uom) ?? uoms[0]);
  const rate = roundRate(first?.price_list_rate || listRate);
  const line: Line = {
    item_code: item.item_code,
    item_name: item.item_name,
    qty: 1,
    rate,
    price_list_rate: rate,
    uom: first?.uom || item.stock_uom,
    conversion_factor: first?.conversion_factor || 1,
    discount_percentage: 0,
    uoms,
    amount: 0,
    min_rate: first?.min_rate,
  };
  recalc(line);
  lines.value.push(line);
}

async function onUomChange(l: Line) {
  const chosen = l.uoms?.find((u) => u.uom === l.uom);
  if (!chosen) return;
  l.conversion_factor = chosen.conversion_factor;
  l.price_list_rate = roundRate(chosen.price_list_rate);
  l.rate = roundRate(chosen.price_list_rate);
  l.min_rate = chosen.min_rate;
  recalc(l);
}

async function prefill(name: string) {
  try {
    const d = await docDetail(props.kind, name);
    if (d.docstatus !== 0) {
      toasts.error("Only drafts can be edited");
      void router.replace({ name: k.value.detail, params: { name } });
      return;
    }
    if (props.kind === "quotation") {
      quotationTo.value = d.quotation_to ?? "Customer";
      // The lead itself too, or saving the draft stopped at "Pick a lead".
      if (quotationTo.value === "Lead") {
        leadId.value = d.party ?? "";
        leadLabel.value = d.party_name;
      }
    }
    keepRates = Boolean(d.customer) && customer.value !== d.customer;
    customer.value = d.customer ?? "";
    date.value = (props.kind === "quotation" ? d.valid_till : d.delivery_date) ?? date.value;
    if (d.payment_type === "cash" || d.payment_type === "credit") paymentType.value = d.payment_type;
    remarks.value = d.remarks ?? "";
    discountAmount.value = d.discount_amount || null;
    lines.value = d.items.map<Line>((it) => ({
      item_code: it.item_code,
      item_name: it.item_name,
      qty: it.qty,
      rate: it.rate,
      price_list_rate: it.price_list_rate,
      uom: it.uom ?? undefined,
      conversion_factor: it.conversion_factor ?? 1,
      discount_percentage: it.discount_percentage,
      uoms: it.uom ? [{ uom: it.uom, conversion_factor: it.conversion_factor ?? 1, price_list_rate: it.price_list_rate ?? 0 }] : [],
      amount: it.amount,
    }));
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
    void router.replace({ name: k.value.list });
  }
}

async function loadAll() {
  void loadTax();
  const jobs: Promise<unknown>[] = [
    listCustomers(undefined, 200).then(async (r) => {
      customers.value = r;
      // Opened for a customer outside the first page (e.g. from the customer
      // screen): fetch it, or the picker shows empty although one is chosen.
      if (customer.value && !r.some((c) => c.name === customer.value)) await onCustomerSearch(customer.value);
    }).catch(() => {}),
    searchItems().catch(() => {}),
  ];
  if (canPickLead.value) {
    jobs.push(listLeads(100).then((r) => { leads.value = r.filter((l) => !l.customer && l.status !== "Converted"); }).catch(() => {}));
  }
  if (leadId.value && quotationTo.value === "Lead" && !isEdit.value) {
    jobs.push(leadDetail(leadId.value).then((l) => { leadLabel.value = l.company_name || l.lead_name; }).catch(() => {}));
  }
  await Promise.all(jobs);
  if (props.name) await prefill(props.name);
}

async function doSave(submit: 0 | 1) {
  if (busy.value) return;
  if (!party.value) { toasts.warn(quotationTo.value === "Lead" ? "Pick a lead" : "Pick a customer"); return; }
  if (!lines.value.length) { toasts.warn("Add at least one item"); return; }
  const bad = lines.value.find((l) => !(Number(l.qty) > 0));
  if (bad) { toasts.warn(`Enter a quantity for ${bad.item_name || bad.item_code}`); return; }
  const low = lines.value.find(belowMin);
  if (low) {
    toasts.warn(`${low.item_name || low.item_code}: the lowest rate allowed is ${(low.min_rate ?? 0).toFixed(session.ratePrecision)}`);
    return;
  }
  // Lock the buttons from the first tap: the pre-check and the confirm take a
  // moment, and a second tap meanwhile submitted a second document.
  busy.value = true;
  if (submit && quotationTo.value === "Customer") {
    const go = await precheckBeforeSubmit(
      props.kind === "order" ? "Sales Order" : "Quotation",
      customer.value,
      showPayment.value ? paymentType.value : undefined,
      lines.value.map((l) => ({ item_code: l.item_code, item_name: l.item_name, rate: effectiveRate(l), conversion_factor: l.conversion_factor })),
      { amount: props.kind === "order" ? totals.value.grand : 0 },
    );
    if (!go) { busy.value = false; return; }
  }
  if (submit) {
    const ok = await confirmSubmit(`Submit ${k.value.title.toLowerCase()}?`, [
      quotationTo.value === "Lead" ? leadOptions.value.find((o) => o.value === leadId.value)?.label ?? leadLabel.value : customerOptions.value.find((o) => o.value === customer.value)?.label,
      `${lines.value.length} item${lines.value.length === 1 ? "" : "s"} · ${withCurrency(money(totals.value.grand))}`,
    ]);
    if (!ok) { busy.value = false; return; }
  }
  try {
    const payload = {
      party: party.value,
      quotation_to: quotationTo.value,
      date: date.value || undefined,
      warehouse: props.kind === "order" ? warehouse.value || undefined : undefined,
      payment_type: showPayment.value ? paymentType.value : undefined,
      remarks: remarks.value,
      discount_amount: Math.max(0, Number(discountAmount.value) || 0),
      submit,
      items: lines.value.map<SellingLine>((l) => {
        const listRate = Number(l.price_list_rate) || 0;
        const base = Number(l.rate) || listRate;
        const pct = session.lineDiscount ? Math.max(0, Math.min(100, Number(l.discount_percentage) || 0)) : 0;
        return {
          item_code: l.item_code,
          item_name: l.item_name,
          qty: l.qty,
          rate: Math.max(0, base * (1 - pct / 100)),
          // Same rule as the invoice: a typed rate above the list price becomes the list price.
          price_list_rate: Math.max(listRate, base),
          uom: l.uom,
          conversion_factor: l.conversion_factor,
        };
      }),
    };
    const res = props.name
      ? await updateDocDraft(props.kind, props.name, payload)
      : await saveDoc(props.kind, payload);
    toasts.success(`${k.value.title} ${res.name} ${submit ? "submitted" : "saved as draft"}`);
    void router.replace({ name: k.value.detail, params: { name: res.name } });
  } catch (e) {
    toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

onMounted(loadAll);
</script>

<template>
  <div class="stack form-split">
    <section class="card stack">
      <div class="row-head">
        <span class="label">{{ quotationTo === "Lead" ? "Lead" : "Customer" }}</span>
        <button v-if="quotationTo === 'Customer' && !isEdit" type="button" class="link-btn"
                @click="router.push({ name: 'customer-new' })">
          <Icon name="plus" :size="14" /> New
        </button>
        <button v-else-if="quotationTo === 'Lead' && !isEdit" type="button" class="link-btn"
                @click="router.push({ name: 'lead-new' })">
          <Icon name="plus" :size="14" /> New lead
        </button>
      </div>
      <div v-if="canPickLead" class="seg">
        <button type="button" class="seg-btn" :data-active="quotationTo === 'Customer'" @click="quotationTo = 'Customer'">
          <Icon name="customer" :size="16" /> Customer
        </button>
        <button type="button" class="seg-btn" :data-active="quotationTo === 'Lead'" @click="quotationTo = 'Lead'">
          <Icon name="user" :size="16" /> Lead
        </button>
      </div>
      <template v-if="quotationTo === 'Lead'">
        <div v-if="isEdit" class="selected-hint"><Icon name="user" :size="14" /> {{ leadLabel || leadId }}</div>
        <template v-else>
          <SearchSelect v-model="leadId" :options="leadOptions" placeholder="Search lead by name, company or mobile"
                        remote @search="onLeadSearch" />
          <p class="muted xsmall">The lead becomes a customer when this quotation is ordered.</p>
        </template>
      </template>
      <SearchSelect v-else v-model="customer" :options="customerOptions" placeholder="Search customer by name or code"
                    remote :disabled="isEdit" @search="onCustomerSearch" />
      <label class="field">
        <span class="tiny">{{ k.dateLabel }}</span>
        <input type="date" v-model="date" />
      </label>
      <div v-if="showPayment" class="seg">
        <button type="button" class="seg-btn" :data-active="paymentType === 'cash'" @click="pickPayment('cash')">
          <Icon name="payment" :size="16" /> Cash
        </button>
        <button type="button" class="seg-btn" :data-active="paymentType === 'credit'"
                :data-blocked="Boolean(creditRefused)" @click="pickPayment('credit')">
          <Icon :name="creditRefused ? 'alert' : 'clock'" :size="16" /> Credit
        </button>
      </div>
      <CreditPanel
        v-if="kind === 'order' && quotationTo === 'Customer' && customer"
        :status="credit"
        :loading="creditLoading"
        :payment="showPayment ? paymentType : undefined"
        :adds="totals.grand"
      />
    </section>

    <section class="card stack">
      <div class="section-head">
        <h3 style="margin:0">Lines</h3>
        <strong v-if="lines.length" class="tabular"><SarSymbol :code="session.currency" />{{ money(netTotal) }}</strong>
      </div>
      <div v-if="!lines.length" class="empty" style="padding:1rem 0">
        <Icon name="bag" :size="28" class="empty-icon" /><span>Add items from the catalog.</span>
      </div>
      <ul v-else class="lines">
        <li v-for="(l, i) in lines" :key="i" class="line">
          <div class="line-head">
            <strong class="truncate">{{ l.item_name || l.item_code }}</strong>
            <button class="icon-only small" type="button" @click="lines.splice(i, 1)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="muted xsmall">{{ l.item_code }}</div>
          <div class="line-grid" :class="{ 'no-disc': !session.lineDiscount }">
            <label><span class="tiny">Qty</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.qty" @input="recalc(l)" />
            </label>
            <label><span class="tiny">UOM</span>
              <select v-if="session.uomChangeAllowed && l.uoms && l.uoms.length > 1" v-model="l.uom" @change="onUomChange(l)">
                <option v-for="u in l.uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
              </select>
              <input v-else type="text" :value="l.uom" disabled />
            </label>
            <label><span class="tiny">Rate</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.rate"
                     :class="{ 'below-min': belowMin(l) }" v-decimals="session.ratePrecision" @input="recalc(l)" />
            </label>
            <label v-if="session.lineDiscount"><span class="tiny">Disc %</span>
              <input type="number" min="0" max="100" step="any" inputmode="decimal"
                     v-model.number="l.discount_percentage" @input="recalc(l)" />
            </label>
          </div>
          <LineInsight :item-code="l.item_code" :customer="insightCustomer" :uom="l.uom"
                       :conversion-factor="l.conversion_factor" :last="insight.lastSale(l.item_code)"
                       :short="insight.shortage(l)" @use="(r: number) => usePrice(l, r)" />
          <div class="line-foot">
            <span v-if="l.min_rate" class="xsmall" :class="belowMin(l) ? 'min-low' : 'muted'">
              Min: <SarSymbol :code="session.currency" />{{ (l.min_rate ?? 0).toFixed(session.ratePrecision) }}
            </span>
            <span v-else />
            <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(l.amount) }}</strong>
          </div>
        </li>
      </ul>
    </section>

    <section class="card stack split-side">
      <h3 style="margin:0">Catalog</h3>
      <div class="search-bar">
        <Icon name="search" :size="18" class="search-ic" />
        <input :value="itemSearch" placeholder="Search item code / name / barcode"
               @input="itemSearch = inputValue($event); searchItems()" @focus="revealOnFocus" />
      </div>
      <ul class="catalog">
        <li v-for="it in items" :key="it.item_code">
          <button class="cat-item" type="button" @click="addLine(it)">
            <div>
              <strong class="truncate">{{ it.item_name }}</strong>
              <div class="muted xsmall">{{ it.item_code }}</div>
            </div>
            <span v-if="typeof it.stock_qty === 'number' && it.is_stock_item !== 0" class="pill" data-tone="primary">
              {{ stockLabel(it.stock_qty, it.stock_uom, it.sales_uom, it.sales_cf) }}
            </span>
          </button>
        </li>
      </ul>
      <p v-if="!items.length" class="muted small">No item matches.</p>
    </section>

    <section v-if="lines.length" class="card stack totals">
      <div class="tot-row"><span>Net total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(netTotal) }}</span></div>
      <label class="field">
        <span class="tiny">Additional discount on {{ session.applyDiscountOn }} ({{ session.currency }})</span>
        <input type="number" min="0" step="any" inputmode="decimal" v-model.number="discountAmount"
               v-decimals="session.currencyPrecision" placeholder="0" />
      </label>
      <div class="tot-row muted">
        <span>{{ tax.taxes[0]?.description || "VAT" }} ({{ tax.rate.toFixed(tax.rate % 1 ? 2 : 0) }}%)</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(totals.tax) }}</span>
      </div>
      <div class="tot-row grand"><span>Grand total</span>
        <span class="tabular"><SarSymbol :code="session.currency" />{{ money(totals.grand) }}</span></div>
    </section>

    <label class="field">
      <span class="label">Notes (optional)</span>
      <textarea v-model="remarks" rows="2" />
    </label>

    <div class="actions">
      <button class="btn-ghost" type="button" :disabled="busy || !lines.length" @click="doSave(0)">
        <Icon name="edit" :size="18" /> {{ busy ? "Saving…" : "Save draft" }}
      </button>
      <button class="submit" type="button" :disabled="busy || !lines.length" @click="doSave(1)">
        <Icon name="check" :size="18" /> Submit · {{ session.currency }} {{ money(totals.grand) }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.below-min { border-color: var(--danger); color: var(--danger); }
.min-low { color: var(--danger); font-weight: 600; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer; padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center; font-weight: 500;
  display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }
.seg-btn[data-blocked="true"]:not([data-active="true"]) { color: var(--text-faint); }
.seg-btn[data-blocked="true"][data-active="true"] { background: var(--danger); }
.row-head { display: flex; justify-content: space-between; align-items: center; }
.link-btn { all: unset; cursor: pointer; color: var(--primary); font-size: var(--text-xs); font-weight: 600; display: inline-flex; align-items: center; gap: 0.25rem; }
.selected-hint { font-size: var(--text-sm); color: var(--primary); display: inline-flex; align-items: center; gap: 0.3rem; }
.section-head { display: flex; justify-content: space-between; align-items: center; }
.tabular { font-variant-numeric: tabular-nums; }
.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line { background: var(--surface-muted); border-radius: var(--radius); padding: 0.65rem 0.75rem; display: flex; flex-direction: column; gap: 0.3rem; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.4rem; align-items: end; margin-top: 0.3rem; }
.line-grid.no-disc { grid-template-columns: 1fr 1fr 1fr; }
.line-grid label { display: flex; flex-direction: column; gap: 0.15rem; }
.line-grid input, .line-grid select { padding: 0.45rem 0.55rem; font-size: var(--text-sm); }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.line-foot { display: flex; justify-content: space-between; align-items: center; padding-top: 0.25rem; border-top: 1px dashed var(--border); }
.search-bar { position: relative; }
.search-ic { position: absolute; inset-inline-start: 0.7rem; top: 50%; transform: translateY(-50%); color: var(--text-faint); pointer-events: none; }
.search-bar input { padding-inline-start: 2.3rem; }
.catalog { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; max-height: 22rem; overflow-y: auto; }
.cat-item {
  all: unset; box-sizing: border-box; width: 100%; cursor: pointer; padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm); background: var(--surface-muted);
  display: flex; align-items: center; justify-content: space-between; gap: 0.5rem;
}
.cat-item:active { background: var(--primary-soft); }
.totals .tot-row { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); }
.totals .tot-row.grand { font-size: var(--text-base); font-weight: 700; border-top: 1px solid var(--border); padding-top: 0.4rem; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.actions { display: grid; grid-template-columns: 1fr 1.4fr; gap: 0.5rem; }
.btn-ghost {
  all: unset; cursor: pointer; min-height: 3.25rem; border-radius: var(--radius); background: var(--surface-muted);
  text-align: center; display: inline-flex; justify-content: center; align-items: center; gap: 0.4rem; font-weight: 600;
}
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
.icon-only.small { min-height: 1.8rem; width: 1.8rem; padding: 0.3rem; }

@media (min-width: 1100px) {
  .form-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 24rem); column-gap: 1rem; align-items: start; }
  .form-split > * { grid-column: 1; margin-bottom: 0.75rem; }
  .form-split > .split-side { grid-column: 2; grid-row: 1 / span 12; position: sticky; top: calc(var(--top-bar-height) + 1rem); }
}
</style>
