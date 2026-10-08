<script setup lang="ts">
/**
 * Bulk return — a credit note without one original invoice ("Return without
 * invoice" setting).
 *
 * Customer + any sales items with qty / UOM / rate. The rate is pre-filled
 * like on a sale (the customer's own price when "Use customer-specific price"
 * is on, else the price list) and can be changed. The server puts the stock
 * back into the van and, on ZATCA sites, references each item to the
 * customer's last invoice for it (items never sold to the customer are
 * refused). Online only, like returns against an invoice.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine as listCustomers, customerLabel, type CustomerRow } from "@/api/customer";
import { listMine as listItems, detail as itemDetail, type ItemRow, type ItemUom } from "@/api/item";
import {
  referenceOptions,
  returnPreview,
  returnWithoutInvoice,
  type ReferenceOptions,
  type ReturnTotals,
} from "@/api/invoice";
import { ApiError, NetworkError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import SearchSelect from "@/components/SearchSelect.vue";
import RefundSection, { type RefundState } from "@/components/RefundSection.vue";

const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();

// Must match RETURN_REASONS in vansale/api/sales_return.py.
const RETURN_REASONS = ["Damaged", "Expired", "Wrong Item", "Customer Refused", "Short Delivery", "Other"] as const;

interface Line {
  item_code: string;
  item_name: string;
  qty: number;
  uom: string;
  rate: number;
  uoms: ItemUom[];
}

const customers = ref<CustomerRow[]>([]);
const customer = ref("");
const items = ref<ItemRow[]>([]);
const itemSearch = ref("");
const lines = ref<Line[]>([]);
const reason = ref("");
const note = ref("");
const busy = ref(false);

const customerOptions = computed(() =>
  customers.value.map((c) => ({
    value: c.name,
    label: customerLabel(c),
    sub: [c.secondary_name, c.vat_number ? `VAT ${c.vat_number}` : ""].filter(Boolean).join(" · "),
  })),
);

const precision = computed(() => session.currencyPrecision);
const round = (n: number) => Math.round((Number(n) || 0) * 10 ** precision.value) / 10 ** precision.value;
const money = (n: number) => (Number(n) || 0).toFixed(precision.value);
// ZATCA references (sites with ksa_compliance): always chosen by the user;
// items never sold to the customer are only flagged.
const refOptions = ref<ReferenceOptions | null>(null);
const references = ref<string[]>([]);
const addRef = ref("");
const refChoices = computed(() =>
  (refOptions.value?.invoices ?? []).filter((i) => !references.value.includes(i.name)),
);

// Net / VAT / total as ERPNext will post them (server dry run).
const totals = ref<ReturnTotals | null>(null);
const refund = ref<RefundState>({ on: false, mode: "", amount: null, reference: "" });
// Blank = the full credit; otherwise a partial refund, never more than the credit.
function refundAmountError(): string | null {
  const a = refund.value.amount;
  if (!refund.value.on || !totals.value?.refundable || a == null) return null;
  if (!(a > 0)) return "Refund amount must be more than 0";
  if (a > totals.value.grand_total + 0.005) return "Refund amount can't be more than the credit";
  return null;
}
function refundPayload() {
  if (!refund.value.on || !totals.value?.refundable || !refund.value.mode) return undefined;
  return {
    mode_of_payment: refund.value.mode,
    amount: refund.value.amount == null ? undefined : Number(refund.value.amount),
    reference_no: refund.value.reference || undefined,
  };
}


const lineKey = () =>
  JSON.stringify([customer.value, lines.value.map((l) => [l.item_code, Number(l.qty) || 0, l.uom, Number(l.rate) || 0])]);
let timer: number | undefined;
let seq = 0;
watch(lineKey, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(async () => {
    const mine = ++seq;
    const picked = lines.value.filter((l) => Number(l.qty) > 0);
    if (!customer.value) { totals.value = null; refOptions.value = null; return; }
    try {
      const [t, o] = await Promise.all([
        picked.length
          ? returnPreview({
              customer: customer.value,
              items: picked.map((l) => ({ item_code: l.item_code, qty: Number(l.qty), uom: l.uom, rate: Number(l.rate) })),
            })
          : Promise.resolve(null),
        referenceOptions(customer.value, [...new Set(picked.map((l) => l.item_code))]),
      ]);
      if (mine !== seq) return;
      totals.value = t;
      refOptions.value = o;
    } catch {
      if (mine === seq) totals.value = null;
    }
  }, 350);
});
watch(customer, () => {
  references.value = [];
});

function removeRef(name: string) {
  references.value = references.value.filter((r) => r !== name);
}
function onAddRef() {
  if (addRef.value && !references.value.includes(addRef.value)) {
    references.value = [...references.value, addRef.value];
  }
  addRef.value = "";
}

async function onCustomerSearch(term: string) {
  try {
    const found = await listCustomers(term || undefined, 50);
    const seen = new Set(customers.value.map((c) => c.name));
    for (const c of found) if (!seen.has(c.name)) customers.value.push(c);
  } catch {
    /* offline — local filter over the loaded page */
  }
}

async function searchItems() {
  // Any sales item (a returned item need not be in the van's stock).
  items.value = await listItems(itemSearch.value || undefined, undefined, 60, false);
}

async function addLine(it: ItemRow) {
  if (!customer.value) { toasts.warn("Pick the customer first — prices depend on it"); return; }
  try {
    const d = await itemDetail(it.item_code, customer.value);
    // Sales UOM first (server order); its price is the default rate.
    const first = d.uoms[0];
    lines.value.push({
      item_code: it.item_code,
      item_name: it.item_name,
      qty: 1,
      uom: first?.uom ?? it.stock_uom,
      rate: round(first?.price_list_rate ?? 0),
      uoms: d.uoms,
    });
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

function onUomChange(l: Line) {
  const u = l.uoms.find((x) => x.uom === l.uom);
  if (u) l.rate = round(u.price_list_rate);
}

function removeLine(i: number) {
  lines.value.splice(i, 1);
}

async function submit() {
  if (!customer.value) { toasts.warn("Pick a customer"); return; }
  const picked = lines.value.filter((l) => Number(l.qty) > 0);
  if (!picked.length) { toasts.warn("Add at least one item with a quantity"); return; }
  if (!reason.value) { toasts.warn("Choose a return reason"); return; }
  if (refOptions.value?.enabled && !references.value.length) {
    toasts.warn("Choose at least one original invoice (ZATCA needs a reference)");
    return;
  }
  const refundErr = refundAmountError();
  if (refundErr) { toasts.warn(refundErr); return; }
  busy.value = true;
  try {
    const res = await returnWithoutInvoice({
      customer: customer.value,
      items: picked.map((l) => ({ item_code: l.item_code, qty: Number(l.qty), uom: l.uom, rate: Number(l.rate) })),
      reason: reason.value,
      note: note.value || undefined,
      references: refOptions.value?.enabled ? references.value : undefined,
      refund: refundPayload(),
    });
    toasts.success(`Credit Note ${res.name} · ${session.currency} ${money(Math.abs(res.grand_total))}`);
    const autoprint = session.printBehaviour?.after_submit ? { autoprint: "1" } : undefined;
    void router.replace({ name: "invoice-detail", params: { name: res.name }, query: autoprint });
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof NetworkError ? "Offline — returns need a connection"
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  try {
    customers.value = await listCustomers(undefined, 200);
  } catch {
    customers.value = [];
  }
  await searchItems();
});
</script>

<template>
  <div class="stack">
    <section class="card stack">
      <span class="label">Customer</span>
      <SearchSelect
        v-model="customer"
        :options="customerOptions"
        placeholder="Search customer by name or code"
        remote
        @search="onCustomerSearch"
      />
    </section>

    <section class="card stack">
      <h3 style="margin:0">Items returned</h3>
      <div v-if="lines.length === 0" class="muted small">Add items from the list below.</div>
      <ul v-else class="lines">
        <li v-for="(l, i) in lines" :key="i" class="line">
          <div class="line-head">
            <strong class="truncate">{{ l.item_name || l.item_code }}</strong>
            <button class="icon-only small" type="button" @click="removeLine(i)" aria-label="Remove">
              <Icon name="x" :size="16" />
            </button>
          </div>
          <div class="line-grid">
            <label>
              <span class="tiny">Qty</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.qty" />
            </label>
            <label>
              <span class="tiny">UOM</span>
              <select v-model="l.uom" @change="onUomChange(l)">
                <option v-for="u in l.uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
              </select>
            </label>
            <label>
              <span class="tiny">Rate</span>
              <input type="number" min="0" step="any" inputmode="decimal" v-model.number="l.rate" />
            </label>
          </div>
          <div class="line-foot muted xsmall">
            <SarSymbol :code="session.currency" />{{ money((Number(l.qty) || 0) * (Number(l.rate) || 0)) }}
          </div>
        </li>
      </ul>
      <template v-if="lines.length && totals">
        <div class="tot-row">
          <span>Net</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(totals.net_total) }}</span>
        </div>
        <div class="tot-row">
          <span>VAT</span>
          <span class="tabular"><SarSymbol :code="session.currency" />{{ money(totals.tax) }}</span>
        </div>
        <div class="tot-row grand">
          <span>Credit total</span>
          <strong class="tabular"><SarSymbol :code="session.currency" />{{ money(totals.grand_total) }}</strong>
        </div>
      </template>
    </section>

    <section v-if="refOptions?.enabled && lines.length" class="card stack">
      <div class="row-head">
        <span class="label">Original invoices (ZATCA reference) *</span>
      </div>
      <p v-if="refOptions.never_sold.length" class="warn small">
        Never sold to this customer: {{ refOptions.never_sold.join(", ") }}
      </p>
      <div class="refs">
        <span v-for="r in references" :key="r" class="ref-chip">
          {{ r }}
          <button type="button" class="chip-x" @click="removeRef(r)" aria-label="Remove">
            <Icon name="x" :size="12" />
          </button>
        </span>
        <span v-if="!references.length" class="muted small">None selected</span>
      </div>
      <select v-model="addRef" @change="onAddRef">
        <option value="">Add an invoice…</option>
        <option v-for="i in refChoices" :key="i.name" :value="i.name">
          {{ i.name }} · {{ i.posting_date }} · {{ money(i.grand_total) }}
        </option>
      </select>
    </section>

    <section class="card stack">
      <div class="search-bar">
        <Icon name="search" :size="18" class="search-ic" />
        <input v-model="itemSearch" placeholder="Search item code / name" @input="searchItems" />
      </div>
      <ul class="catalog">
        <li v-for="it in items" :key="it.item_code">
          <button class="cat-item" type="button" @click="addLine(it)">
            <strong class="truncate">{{ it.item_name }}</strong>
            <span class="muted xsmall">{{ it.item_code }}</span>
          </button>
        </li>
      </ul>
    </section>

    <RefundSection v-if="lines.length" v-model="refund" :totals="totals" :currency="session.currency"
                   :precision="session.currencyPrecision" />

    <section class="card stack">
      <span class="label">Reason *</span>
      <div class="reasons">
        <button
          v-for="r in RETURN_REASONS"
          :key="r"
          type="button"
          class="reason-chip"
          :class="{ 'is-on': reason === r }"
          @click="reason = r"
        >{{ r }}</button>
      </div>
      <textarea
        v-model="note"
        rows="2"
        :placeholder="reason === 'Other' ? 'Describe the reason (required for Other)' : 'Extra detail (optional)'"
      />
    </section>

    <button class="submit" type="button" :disabled="busy" @click="submit">
      <Icon name="check" :size="18" /> {{ busy ? "Creating…" : "Create credit note" }}
    </button>
  </div>
</template>

<style scoped>
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.lines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.75rem; }
.line { border-top: 1px solid var(--border); padding-top: 0.6rem; }
.line:first-child { border-top: none; padding-top: 0; }
.line-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.line-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.4rem; margin-top: 0.4rem; }
.line-grid label { display: flex; flex-direction: column; gap: 0.2rem; }
.line-foot { text-align: end; margin-top: 0.25rem; }
.tot-row { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); }
.tot-row.grand { font-size: var(--text-base); }
.row-head { display: flex; justify-content: space-between; align-items: center; }
.link-btn { all: unset; cursor: pointer; color: var(--primary); font-size: var(--text-xs); font-weight: 600; }
.warn { color: var(--warning); margin: 0; }
.refs { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.ref-chip {
  display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.3rem 0.6rem;
  border-radius: var(--radius-pill); background: var(--primary-soft); color: var(--primary);
  font-size: var(--text-xs); font-weight: 600;
}
.chip-x { all: unset; cursor: pointer; display: inline-flex; }
.catalog { list-style: none; margin: 0; padding: 0; max-height: 18rem; overflow-y: auto; }
.cat-item {
  all: unset; cursor: pointer; box-sizing: border-box; width: 100%;
  display: flex; flex-direction: column; padding: 0.5rem 0; border-top: 1px solid var(--border);
}
.search-bar { position: relative; }
.search-bar input { width: 100%; padding-inline-start: 2rem; }
.search-ic { position: absolute; inset-inline-start: 0.6rem; top: 50%; transform: translateY(-50%); color: var(--text-faint); }
.reasons { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.reason-chip {
  all: unset; cursor: pointer; padding: 0.4rem 0.7rem; border: 1px solid var(--border);
  border-radius: var(--radius-pill); font-size: var(--text-sm); font-weight: 600; color: var(--text-muted);
  min-height: 2.25rem; display: inline-flex; align-items: center;
}
.reason-chip.is-on { background: var(--primary-soft); border-color: var(--primary); color: var(--primary); }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
