<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { detail, submitDraft, deleteDraft, refundCreditNote, type InvoiceDetail } from "@/api/invoice";
import { modesOfPayment, type ModeOfPayment } from "@/api/payment";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore } from "@/stores/confirm";
import { ApiError } from "@/app/frappe";
import { openPrint, printDocument, defaultPrintFormat } from "@/api/print";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();
const confirm = useConfirmStore();

const inv = ref<InvoiceDetail | null>(null);
const loading = ref(false);
const err = ref("");
const busy = ref(false);

const name = computed(() => String(route.params.name ?? ""));

// Sum of implicit line-level discounts = Σ qty × (price_list_rate - rate).
// Used as a fallback Totals row when `doc.discount_amount` is zero but
// ERPNext stored the discount on each item row (common when we submit
// `rate < price_list_rate`, since ERPNext moves the stamp from header
// to line items during validate()).
const itemDiscountTotal = computed(() => {
  const doc = inv.value;
  if (!doc?.items) return 0;
  return doc.items.reduce((sum, it) => {
    const pl = Number(it.price_list_rate) || 0;
    const r = Number(it.rate) || 0;
    const qty = Number(it.qty) || 0;
    if (pl > r && qty > 0) return sum + (pl - r) * qty;
    return sum;
  }, 0);
});

async function load() {
  loading.value = true;
  err.value = "";
  try {
    inv.value = await detail(name.value);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

/** Print once on arrival when sent here with ?autoprint=1 ("Print after submit"). */
async function autoPrint() {
  if (route.query.autoprint !== "1" || !inv.value || inv.value.docstatus !== 1) return;
  void router.replace({ query: {} });
  try {
    await printDocument(
      "Sales Invoice",
      inv.value.name,
      defaultPrintFormat("Sales Invoice", session.printFormats),
      session.printBehaviour?.copies ?? 1,
    );
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

onMounted(async () => {
  await load();
  await autoPrint();
});

function fmt(n: number | null | undefined): string {
  const v = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(v);
}

function tone(status: string | undefined): string {
  const s = String(status || "").toLowerCase();
  if (s === "paid") return "success";
  if (s === "overdue" || s === "cancelled") return "danger";
  if (s === "unpaid" || s === "partly paid") return "warning";
  if (s === "draft") return "info";
  return "info";
}

// Refund a credit note later: the return kept the money as customer credit.
const canRefund = computed(
  () => !!inv.value && inv.value.is_return && inv.value.docstatus === 1 && (inv.value.refundable_amount ?? 0) > 0.005,
);
const refundOpen = ref(false);
const refundMops = ref<ModeOfPayment[]>([]);
const refundMode = ref("");
const refundAmount = ref<number | null>(null);
const refundRef = ref("");
const refundAmountModel = computed<number | string>({
  get: () => (refundAmount.value == null ? inv.value?.refundable_amount ?? 0 : refundAmount.value),
  set: (v) => {
    const n = Number(v);
    refundAmount.value = (v as unknown) === "" || !Number.isFinite(n) ? null : n;
  },
});
const refundNeedsRef = computed(() => Boolean(refundMops.value.find((m) => m.name === refundMode.value)?.needs_reference));

async function openRefund() {
  refundOpen.value = true;
  if (refundMops.value.length) return;
  try {
    refundMops.value = await modesOfPayment();
  } catch {
    refundMops.value = [];
  }
  if (!refundMode.value && refundMops.value.length) {
    refundMode.value = (refundMops.value.find((m) => m.type === "Cash") ?? refundMops.value[0]).name;
  }
}

async function doRefund() {
  if (!inv.value || !refundMode.value) return;
  const max = inv.value.refundable_amount ?? 0;
  const a = refundAmount.value;
  if (a != null && !(a > 0)) { toasts.warn("Refund amount must be more than 0"); return; }
  if (a != null && a > max + 0.005) { toasts.warn("Refund amount can't be more than the credit"); return; }
  busy.value = true;
  try {
    const res = await refundCreditNote({
      credit_note: inv.value.name,
      mode_of_payment: refundMode.value,
      amount: a ?? undefined,
      reference_no: refundRef.value || undefined,
    });
    toasts.success(`Refund ${res.payment_entry}${res.docstatus === 0 ? " · draft, awaiting office" : ""}`);
    const autoprint = session.printBehaviour?.after_submit ? { autoprint: "1" } : undefined;
    void router.push({ name: "payment-detail", params: { name: res.payment_entry }, query: autoprint });
  } catch (e) {
    toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

function payHere() {
  if (!inv.value) return;
  void router.push({
    name: "payment-new",
    query: { customer: inv.value.customer, invoice: inv.value.name },
  });
}

async function printInvoice() {
  if (!inv.value) return;
  // Print at once ("Print directly") or open the preview screen.
  try {
    await openPrint(router, "Sales Invoice", inv.value.name, session.printFormats, session.printBehaviour);
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

function returnInvoice() {
  if (!inv.value) return;
  void router.push({ name: "invoice-return", params: { name: inv.value.name } });
}

function editDraft() {
  if (!inv.value) return;
  void router.push({ name: "invoice-edit", params: { name: inv.value.name } });
}

/**
 * Draft-stage actions.
 * - Submit flips docstatus 0 → 1 (posts stock, opens outstanding).
 * - Delete removes the draft entirely (only safe while docstatus === 0).
 *
 * Both go through Frappe's generic whitelisted helpers (`frappe.client.submit`
 * / `frappe.client.delete`) — the app's custom `vansale.api.invoice` module
 * doesn't expose a submit endpoint, and adding one would require a server
 * deploy. These generic endpoints respect the doctype permissions and
 * validations set in ERPNext, so there's no perms bypass.
 */
async function submitInvoice() {
  if (!inv.value || busy.value) return;
  busy.value = true;
  try {
    await submitDraft(inv.value.name);
    toasts.success(`Submitted ${inv.value.name}`);
    await load();
    if (session.printBehaviour?.after_submit) {
      await printDocument(
        "Sales Invoice",
        inv.value.name,
        defaultPrintFormat("Sales Invoice", session.printFormats),
        session.printBehaviour.copies ?? 1,
      );
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

async function deleteInvoice() {
  if (!inv.value || busy.value) return;
  const ok = await confirm.ask({
    title: `Delete draft ${inv.value.name}?`,
    message: "This cannot be undone.",
    confirmText: "Delete",
    danger: true,
  });
  if (!ok) return;
  busy.value = true;
  try {
    await deleteDraft(inv.value.name);
    toasts.success("Draft deleted");
    void router.replace({ name: "invoices" });
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

    <div v-if="loading && !inv" class="stack">
      <div class="skeleton" style="height:6rem" />
      <div class="skeleton" style="height:10rem" />
    </div>

    <template v-else-if="inv">
      <section class="hero card stack">
        <div class="hero-head">
          <div>
            <span class="muted xsmall">{{ inv.is_return ? "Credit note" : "Invoice" }}</span>
            <h2 class="inv-name">{{ inv.name }}</h2>
            <span class="muted small">{{ inv.posting_date }} · {{ inv.customer_name }}</span>
          </div>
          <span class="pill" :data-tone="tone(inv.status)">{{ inv.status }}</span>
        </div>
        <div class="hero-total">
          <div>
            <span class="muted xsmall">Grand total</span>
            <strong class="big"><SarSymbol :code="session.currency" />{{ fmt(inv.grand_total) }}</strong>
          </div>
          <div class="hero-sub">
            <span class="muted xsmall">Outstanding</span>
            <strong :class="inv.outstanding_amount > 0 ? 'warn' : ''"><SarSymbol :code="session.currency" />{{ fmt(inv.outstanding_amount) }}</strong>
          </div>
        </div>
        <div class="row actions">
          <!-- Draft stage: submit or delete. Print is also allowed
               (useful to preview the invoice before committing stock). -->
          <template v-if="inv.docstatus === 0">
            <button class="primary" :disabled="busy" @click="submitInvoice">
              <Icon name="check" :size="16" /> {{ busy ? "Submitting…" : "Submit" }}
            </button>
            <button class="ghost" :disabled="busy" @click="editDraft">
              <Icon name="edit" :size="16" /> Edit
            </button>
            <button class="ghost" :disabled="busy" @click="printInvoice">
              <Icon name="receipt" :size="16" /> Print
            </button>
            <button class="ghost danger-ghost" :disabled="busy" @click="deleteInvoice">
              <Icon name="trash" :size="16" /> Delete
            </button>
          </template>
          <!-- Submitted stage: collect payment, print, return. -->
          <template v-else>
            <button
              v-if="inv.outstanding_amount > 0 && inv.docstatus === 1"
              class="primary"
              @click="payHere"
            >
              <Icon name="payment" :size="16" /> Collect
            </button>
            <button v-if="canRefund && !refundOpen" class="primary" @click="openRefund">
              <Icon name="payment" :size="16" /> Refund
            </button>
            <button class="ghost" @click="printInvoice">
              <Icon name="receipt" :size="16" /> Print
            </button>
            <button
              v-if="inv.docstatus === 1 && !inv.is_return"
              class="ghost"
              @click="returnInvoice"
            >
              <Icon name="x" :size="16" /> Return
            </button>
          </template>
        </div>
      </section>

      <!-- Pay the customer back for this credit note (kept as credit at the return). -->
      <section v-if="canRefund && refundOpen" class="card stack">
        <div class="refund-head">
          <h3 class="section-h">Refund to customer</h3>
          <span class="muted xsmall">Credit left <SarSymbol :code="session.currency" />{{ fmt(inv.refundable_amount ?? 0) }}</span>
        </div>
        <div class="refund-grid">
          <label class="field">
            <span class="tiny">Mode of Payment</span>
            <select v-model="refundMode">
              <option v-for="m in refundMops" :key="m.name" :value="m.name">{{ m.name }}</option>
            </select>
          </label>
          <label class="field">
            <span class="tiny">Amount</span>
            <input type="number" min="0" step="any" inputmode="decimal" v-model.number="refundAmountModel" />
          </label>
          <input v-if="refundNeedsRef" class="full" type="text" v-model="refundRef" placeholder="Reference no. (optional)" />
        </div>
        <div class="row actions">
          <button class="ghost" :disabled="busy" @click="refundOpen = false">Cancel</button>
          <button class="primary" :disabled="busy || !refundMode" @click="doRefund">
            <Icon name="payment" :size="16" />
            {{ busy ? "Refunding…" : `Refund ${fmt(refundAmount ?? inv.refundable_amount ?? 0)}` }}
          </button>
        </div>
      </section>

      <section class="card stack">
        <h3 class="section-h">Items</h3>
        <ul class="lines">
          <li v-for="(it, i) in inv.items" :key="i" class="line">
            <div class="line-head">
              <strong class="truncate">{{ it.item_name }}</strong>
              <strong class="amt"><SarSymbol :code="session.currency" />{{ fmt(it.amount) }}</strong>
            </div>
            <div class="line-meta muted xsmall">
              <span>{{ fmt(it.qty) }} {{ it.uom || "" }}</span>
              <span>×</span>
              <template v-if="it.price_list_rate && it.price_list_rate > it.rate">
                <span class="strike"><SarSymbol :code="session.currency" />{{ fmt(it.price_list_rate) }}</span>
                <span class="after-disc"><SarSymbol :code="session.currency" />{{ fmt(it.rate) }}</span>
                <span class="disc">- {{ fmt(it.discount_percentage || ((it.price_list_rate - it.rate) / it.price_list_rate * 100)) }}%</span>
              </template>
              <template v-else>
                <span><SarSymbol :code="session.currency" />{{ fmt(it.rate) }}</span>
                <span v-if="it.discount_percentage > 0" class="disc">- {{ fmt(it.discount_percentage) }}%</span>
              </template>
            </div>
          </li>
        </ul>
      </section>

      <section class="card stack">
        <h3 class="section-h">Totals</h3>
        <div class="totals-row"><span class="muted">Net total</span><span><SarSymbol :code="session.currency" />{{ fmt(inv.net_total) }}</span></div>
        <div v-if="inv.discount_amount && inv.discount_amount !== 0" class="totals-row">
          <span class="muted">Discount</span><span>- <SarSymbol :code="session.currency" />{{ fmt(Math.abs(inv.discount_amount)) }}</span>
        </div>
        <!-- Sum of per-item discounts (shown when ERPNext spreads the
             doc-level discount into item rows rather than keeping it at
             header level). Prevents the Totals section from looking like
             there's no discount at all when the line items clearly carry
             a strike-through price. -->
        <div
          v-else-if="itemDiscountTotal > 0"
          class="totals-row"
        >
          <span class="muted">Discount</span>
          <span>- <SarSymbol :code="session.currency" />{{ fmt(itemDiscountTotal) }}</span>
        </div>
        <template v-if="inv.taxes.length">
          <div class="divider" />
          <div v-for="(t, i) in inv.taxes" :key="i" class="totals-row">
            <span class="muted">{{ t.description }} ({{ fmt(t.rate) }}%)</span>
            <span><SarSymbol :code="session.currency" />{{ fmt(t.tax_amount) }}</span>
          </div>
        </template>
        <div class="divider" />
        <div class="totals-row big-row">
          <strong>Grand total</strong>
          <strong><SarSymbol :code="session.currency" />{{ fmt(inv.grand_total) }}</strong>
        </div>
        <div class="totals-row">
          <span class="muted">Paid</span>
          <span><SarSymbol :code="session.currency" />{{ fmt(inv.paid_amount) }}</span>
        </div>
        <div class="totals-row">
          <span class="muted">Outstanding</span>
          <strong :class="inv.outstanding_amount > 0 ? 'warn' : ''"><SarSymbol :code="session.currency" />{{ fmt(inv.outstanding_amount) }}</strong>
        </div>
      </section>

      <section v-if="inv.sales_persons.length" class="card stack">
        <h3 class="section-h">Sales person</h3>
        <ul class="sp-list">
          <li v-for="sp in inv.sales_persons" :key="sp.sales_person" class="sp-row">
            <Icon name="user" :size="16" />
            <span class="truncate">{{ sp.sales_person }}</span>
            <span class="muted xsmall">{{ fmt(sp.allocated_percentage) }}%</span>
          </li>
        </ul>
      </section>

      <section v-if="inv.remarks" class="card stack">
        <h3 class="section-h">Notes</h3>
        <p class="muted small" style="white-space:pre-wrap">{{ inv.remarks }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--surface)) 0%, var(--surface) 100%);
}
.hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.inv-name { margin: 0.15rem 0 0.1rem; font-size: var(--text-lg); font-family: var(--font-mono, ui-monospace); }
.hero-total {
  display: grid; grid-template-columns: 1fr auto; gap: 0.5rem 1rem; align-items: end;
  padding-block: 0.25rem;
}
.hero-total .big { display: block; font-size: var(--text-2xl); font-variant-numeric: tabular-nums; }
.hero-sub { text-align: right; }
.warn { color: var(--warning); }
.refund-head { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.refund-grid { display: grid; grid-template-columns: 1fr 8rem; gap: 0.5rem; }
.refund-grid .full { grid-column: 1 / -1; }
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.tiny { font-size: var(--text-xs); color: var(--text-muted); }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.actions button { flex: 1 1 7rem; min-height: 2.75rem; justify-content: center; }
.danger-ghost { color: var(--danger); }
.danger-ghost:hover { background: var(--danger-soft); }

.section-h { margin: 0 0 0.1rem; font-size: var(--text-sm); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }

.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.line { display: flex; flex-direction: column; gap: 0.2rem; padding-bottom: 0.5rem; border-bottom: 1px dashed var(--border); }
.line:last-child { border-bottom: none; padding-bottom: 0; }
.line-head { display: flex; justify-content: space-between; gap: 0.5rem; }
.amt { font-variant-numeric: tabular-nums; white-space: nowrap; }
.line-meta { display: flex; gap: 0.4rem; align-items: baseline; flex-wrap: wrap; }
.line-meta .strike { text-decoration: line-through; opacity: 0.7; }
.line-meta .after-disc { font-weight: 600; color: var(--text); }
.disc { color: var(--warning); }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.totals-row { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; font-variant-numeric: tabular-nums; }
.big-row strong { font-size: var(--text-lg); }

.sp-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.sp-row { display: grid; grid-template-columns: auto 1fr auto; gap: 0.5rem; align-items: center; }
</style>
