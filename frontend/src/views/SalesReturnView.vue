<script setup lang="ts">
/**
 * Sales Return — create a Credit Note against a submitted invoice.
 *
 * Loads the original invoice detail, lets user pick which lines to return
 * and how much qty (bounded by original qty minus already-returned qty).
 * Submitting hits POST `vansale.api.invoice.return_against` which creates a
 * Sales Invoice with `is_return=1`, negative qty, `return_against=<orig>`.
 * Stock flows back; the customer's receivable drops by the credit amount.
 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  detail,
  returnAgainst,
  returnPreview,
  type ReturnTotals,
  type InvoiceDetail,
  type InvoiceDetailItem,
} from "@/api/invoice";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import RefundSection, { type RefundState } from "@/components/RefundSection.vue";

interface ReturnRowState {
  include: boolean;
  qty: number;              // positive qty being returned, in `uom`
  maxQty: number;           // cap in `uom`: what is left after earlier returns
  uom: string;              // the sold UOM or a smaller one (sold a carton, return pieces)
  cf: number;               // conversion factor of `uom`
  leftStock: number;        // stock units left to return on this row
}

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();

const orig = ref<InvoiceDetail | null>(null);
const rows = reactive<Record<number, ReturnRowState>>({});
/**
 * Structured reason, mandatory. Kept as a fixed list rather than free text so
 * returns can be reported on by cause — "why are returns up this month" is the
 * first question the office asks, and a textarea cannot answer it.
 * Must match RETURN_REASONS in vansale/api/sales_return.py.
 */
const RETURN_REASONS = [
  "Damaged",
  "Expired",
  "Wrong Item",
  "Customer Refused",
  "Short Delivery",
  "Other",
] as const;
const reason = ref<string>("");
const remarks = ref("");
const busy = ref(false);
const err = ref("");

const origName = computed(() => String(route.params.name ?? ""));

onMounted(async () => {
  try {
    orig.value = await detail(origName.value);
    if (orig.value.docstatus !== 1) {
      err.value = "Can only return submitted invoices";
      return;
    }
    if (orig.value.is_return) {
      err.value = "Cannot return a credit note";
      return;
    }
    orig.value.items.forEach((it, i) => {
      const cf = it.conversion_factor || 1;
      const stockQty = it.stock_qty ?? it.qty * cf;
      const leftStock = Math.max(0, stockQty - (it.returned_stock_qty ?? (it.returned_qty ?? 0) * cf));
      const left = qtyIn(leftStock, cf);
      rows[i] = { include: false, qty: left, maxQty: left, uom: it.uom ?? "", cf, leftStock };
    });
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  }
});

// Whole units of `cf` left (3 decimals, never rounding up past what's left).
function qtyIn(stock: number, cf: number): number {
  return Math.floor((stock / (cf || 1)) * 1000 + 1e-6) / 1000;
}

const ratePrecision = computed(() => session.currencyPrecision);
/** The sale's rate converted to the row's chosen unit (as the server does). */
function rateIn(it: InvoiceDetailItem, cf: number): number {
  const p = 10 ** ratePrecision.value;
  return Math.round(((it.rate || 0) / (it.conversion_factor || 1)) * cf * p) / p;
}

function onUomChange(i: number, it: InvoiceDetailItem) {
  const r = rows[i];
  const u = it.return_uoms?.find((x) => x.uom === r.uom);
  r.cf = u?.conversion_factor || it.conversion_factor || 1;
  r.maxQty = qtyIn(r.leftStock, r.cf);
  r.qty = r.maxQty;
}

function fmt(n: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(n);
}

const selectedCount = computed(() =>
  Object.values(rows).filter((r) => r.include && r.qty > 0).length,
);

// Net / VAT / total as ERPNext will post them — calculated by the server
// (dry run, nothing saved) whenever the selection changes.
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

let previewTimer: number | undefined;
let previewSeq = 0;
function selectedLines() {
  if (!orig.value) return [];
  return orig.value.items
    .map((it, i) => ({ it, r: rows[i] }))
    .filter(({ r }) => r?.include && r.qty > 0)
    .map(({ it, r }) => ({ sales_invoice_item: it.name, item_code: it.item_code, qty: r.qty, uom: r.uom || undefined }));
}
watch(
  () => JSON.stringify(selectedLines()),
  () => {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(async () => {
      const seq = ++previewSeq;
      const items = selectedLines();
      if (!orig.value || !items.length) { totals.value = null; return; }
      try {
        const t = await returnPreview({ original_invoice: orig.value.name, items });
        if (seq === previewSeq) totals.value = t;
      } catch {
        if (seq === previewSeq) totals.value = null;
      }
    }, 350);
  },
)

function toggleAll(value: boolean) {
  // Fully returned lines have nothing left to select.
  Object.values(rows).forEach((r) => {
    r.include = value && r.maxQty > 0;
  });
}

function clampQty(idx: number, it: InvoiceDetailItem) {
  const r = rows[idx];
  if (!r) return;
  if (r.qty < 0) r.qty = 0;
  if (r.qty > r.maxQty) r.qty = r.maxQty;
  if (r.qty > 0 && !r.include) r.include = true;
  void it;
}

async function submit() {
  if (!orig.value) return;
  const picks = orig.value.items
    .map((it, i) => ({ it, r: rows[i] }))
    .filter(({ r }) => r?.include && r.qty > 0);
  if (picks.length === 0) {
    toasts.warn("Select at least one line");
    return;
  }
  if (!reason.value) {
    toasts.warn("Choose a return reason");
    return;
  }
  const refundErr = refundAmountError();
  if (refundErr) { toasts.warn(refundErr); return; }
  busy.value = true;
  try {
    const res = await returnAgainst({
      original_name: orig.value.name,
      items: picks.map(({ it, r }) => ({
        // The invoice row being returned, so a repeated item maps correctly.
        sales_invoice_item: it.name,
        item_code: it.item_code,
        qty: r.qty,
        rate: rateIn(it, r.cf),
        uom: r.uom || it.uom || undefined,
        warehouse: it.warehouse ?? undefined,
      })),
      reason: reason.value,
      note: remarks.value || undefined,
      submit: 1,
      refund: refundPayload(),
    });
    toasts.success(`Credit Note ${res.name} · ${session.currency} ${Math.abs(res.grand_total).toFixed(2)}`);
    if (session.printBehaviour?.after_submit) {
      // "Print after submit": the credit note's detail view prints on arrival.
      void router.push({ name: "invoice-detail", params: { name: res.name }, query: { autoprint: "1" } });
    } else {
      // Route to in-app print view — same format handles is_return.
      // Native WebView can't open the server /printview route directly.
      void router.push({
        name: "print-view",
        params: { doctype: "Sales Invoice", name: res.name },
      });
    }
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="stack">
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="orig && !err">
      <section class="card stack">
        <div class="row-head">
          <div>
            <span class="muted xsmall">Return against</span>
            <h3 class="inv-name">{{ orig.name }}</h3>
            <span class="muted small">{{ orig.customer_name }} · {{ orig.posting_date }}</span>
          </div>
          <span class="pill" data-tone="info">{{ orig.status }}</span>
        </div>
        <div class="grand-row">
          <span class="muted">Original grand total</span>
          <strong><SarSymbol :code="session.currency" />{{ fmt(orig.grand_total) }}</strong>
        </div>
      </section>

      <section class="card stack">
        <div class="row-head">
          <h3 style="margin:0">Lines to return</h3>
          <div class="bulk">
            <button type="button" class="link-btn" @click="toggleAll(true)">Select all</button>
            <button type="button" class="link-btn" @click="toggleAll(false)">Clear</button>
          </div>
        </div>
        <ul class="lines">
          <li v-for="(it, i) in orig.items" :key="i" class="line" :class="{ active: rows[i]?.include }">
            <label class="line-head">
              <input
                type="checkbox"
                v-model="rows[i].include"
                :disabled="rows[i].maxQty <= 0"
              />
              <div class="head-body">
                <strong class="truncate">{{ it.item_name }}</strong>
                <span class="muted xsmall">{{ it.item_code }} · {{ it.uom || "" }} · <SarSymbol :code="session.currency" />{{ fmt(it.rate) }}</span>
              </div>
              <strong class="line-amt"><SarSymbol :code="session.currency" />{{ fmt(it.amount) }}</strong>
            </label>
            <div v-if="rows[i]?.include" class="line-grid" :class="{ 'has-uom': (it.return_uoms?.length ?? 0) > 1 }">
              <label v-if="(it.return_uoms?.length ?? 0) > 1">
                <span class="tiny">Unit</span>
                <select v-model="rows[i].uom" @change="onUomChange(i, it)">
                  <option v-for="u in it.return_uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
                </select>
              </label>
              <label>
                <span class="tiny">Return qty</span>
                <input
                  type="number"
                  min="0"
                  :max="rows[i].maxQty"
                  step="any"
                  inputmode="decimal"
                  v-model.number="rows[i].qty"
                  @input="clampQty(i, it)"
                />
              </label>
              <div class="cap">
                <span class="tiny">Max {{ fmt(rows[i].maxQty) }} {{ rows[i].uom }}</span>
                <span v-if="rows[i].uom !== it.uom" class="tiny">
                  <SarSymbol :code="session.currency" />{{ fmt(rateIn(it, rows[i].cf)) }} / {{ rows[i].uom }}
                </span>
                <span v-if="it.returned_qty" class="tiny muted">Returned {{ fmt(it.returned_qty) }}</span>
              </div>
            </div>
          </li>
        </ul>
      </section>

      <label class="field">
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
          v-model="remarks"
          rows="2"
          :placeholder="reason === 'Other' ? 'Describe the reason (required for Other)' : 'Extra detail (optional)'"
        />
      </label>

      <section v-if="selectedCount > 0" class="card stack totals">
        <div class="tot-row">
          <span>Lines selected</span>
          <strong>{{ selectedCount }}</strong>
        </div>
        <template v-if="totals">
          <div class="tot-row">
            <span>Net</span>
            <span><SarSymbol :code="session.currency" />{{ fmt(totals.net_total) }}</span>
          </div>
          <div class="tot-row">
            <span>VAT</span>
            <span><SarSymbol :code="session.currency" />{{ fmt(totals.tax) }}</span>
          </div>
          <div class="tot-row grand">
            <span>Credit total</span>
            <strong><SarSymbol :code="session.currency" />{{ fmt(totals.grand_total) }}</strong>
          </div>
        </template>
        <p v-else class="muted xsmall">Calculating…</p>
      </section>

      <RefundSection v-model="refund" :totals="totals" :currency="session.currency"
                     :precision="session.currencyPrecision" />

      <button class="submit danger" :disabled="busy || selectedCount === 0 || !reason" @click="submit">
        <Icon name="receipt" :size="18" />
        {{ busy ? "Processing…" : "Submit Credit Note" }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.row-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.inv-name { margin: 0.15rem 0; font-size: var(--text-lg); font-family: var(--font-mono, ui-monospace); }
.grand-row { display: flex; justify-content: space-between; align-items: baseline; font-variant-numeric: tabular-nums; }

.bulk { display: flex; gap: 0.4rem; }
.link-btn { all: unset; cursor: pointer; color: var(--primary); font-size: var(--text-xs); font-weight: 600; }

.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.line {
  padding: 0.6rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  border: 1px solid transparent;
  transition: all var(--dur-fast) var(--ease);
  display: flex; flex-direction: column; gap: 0.4rem;
}
.line.active { background: var(--primary-soft); border-color: var(--primary); }
.line-head { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 0.6rem; cursor: pointer; }
.head-body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.line-amt { font-variant-numeric: tabular-nums; white-space: nowrap; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.line-grid { display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 0.5rem; }
.line-grid.has-uom { grid-template-columns: minmax(0, 7rem) 1fr auto; }
.cap { padding-bottom: 0.5rem; display: flex; flex-direction: column; align-items: flex-end; }

.tiny { font-size: var(--text-xs); color: var(--text-muted); }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }

.totals .tot-row { display: flex; justify-content: space-between; align-items: baseline; font-variant-numeric: tabular-nums; }
.totals .tot-row.grand strong { font-size: var(--text-lg); }

.submit { min-height: 3.25rem; font-size: var(--text-base); }
.submit.danger { background: var(--danger); color: white; }
.submit.danger:disabled { opacity: 0.5; }

.reasons { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }
.reason-chip {
  all: unset;
  cursor: pointer;
  padding: 0.4rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-muted);
  min-height: 2.25rem;
  display: inline-flex;
  align-items: center;
}
.reason-chip.is-on {
  background: var(--primary-soft);
  border-color: var(--primary);
  color: var(--primary);
}
</style>
