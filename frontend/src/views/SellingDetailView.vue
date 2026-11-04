<script setup lang="ts">
/**
 * Quotation / Sales Order detail, with the next step of the cycle:
 *   Quotation → Sales Order   (customer quotations; lead quotations convert the lead first)
 *   Sales Order → Sales Invoice (a draft, finished in the invoice form: payment, submit)
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  KIND, docDetail, deleteDoc, submitDoc, markQuotationLost, quotationToOrder, orderToInvoice,
  type SellingDetail, type SellingKind,
} from "@/api/selling";
import { convertLead } from "@/api/lead";
import { openPrint } from "@/api/print";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore, confirmSubmit, withCurrency } from "@/stores/confirm";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const props = defineProps<{ kind: SellingKind; name: string }>();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();
const confirm = useConfirmStore();
const k = computed(() => KIND[props.kind]);

const doc = ref<SellingDetail | null>(null);
const loading = ref(false);
const err = ref("");
const busy = ref(false);

async function load() {
  loading.value = true;
  err.value = "";
  try {
    doc.value = await docDetail(props.kind, props.name);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
watch(() => [props.kind, props.name], load);

const fmt = (n: number | null | undefined) =>
  new Intl.NumberFormat(undefined, {
    maximumFractionDigits: session.currencyPrecision, minimumFractionDigits: session.currencyPrecision,
  }).format(Number(n) || 0);
const fmtRate = (n: number | null | undefined) =>
  new Intl.NumberFormat(undefined, {
    maximumFractionDigits: session.ratePrecision, minimumFractionDigits: session.ratePrecision,
  }).format(Number(n) || 0);

function tone(status: string): string {
  const s = status.toLowerCase();
  if (s === "draft") return "info";
  if (["ordered", "completed", "to bill", "to deliver and bill"].includes(s)) return "success";
  if (["lost", "expired", "cancelled", "closed"].includes(s)) return "danger";
  return "warning";
}

const isDraft = computed(() => doc.value?.docstatus === 0);
const isOpen = computed(() => doc.value?.docstatus === 1 && !["Lost", "Expired", "Ordered", "Closed", "Completed", "Cancelled"].includes(doc.value.status));
const isLeadQuote = computed(() => props.kind === "quotation" && doc.value?.quotation_to === "Lead");
const dateLabel = computed(() => k.value.dateLabel);
const dateValue = computed(() => (props.kind === "quotation" ? doc.value?.valid_till : doc.value?.delivery_date));
const linked = computed(() => (props.kind === "quotation" ? doc.value?.orders : doc.value?.invoices) ?? []);

function fail(e: unknown) {
  toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
}

async function run(fn: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  try { await fn(); } catch (e) { fail(e); } finally { busy.value = false; }
}

const submit = () => run(async () => {
  if (!doc.value) return;
  const ok = await confirmSubmit(`Submit ${doc.value.name}?`, [doc.value.party_name, withCurrency(fmt(doc.value.grand_total))]);
  if (!ok) return;
  await submitDoc(props.kind, doc.value.name);
  toasts.success(`Submitted ${doc.value.name}`);
  await load();
});

const remove = () => run(async () => {
  if (!doc.value) return;
  const ok = await confirm.ask({
    title: `Delete draft ${doc.value.name}?`, message: "This cannot be undone.", confirmText: "Delete", danger: true,
  });
  if (!ok) return;
  await deleteDoc(props.kind, doc.value.name);
  toasts.success("Draft deleted");
  void router.replace({ name: k.value.list });
});

const lost = () => run(async () => {
  if (!doc.value) return;
  const ok = await confirm.ask({
    title: `Mark ${doc.value.name} as lost?`, message: "The customer turned this quotation down.",
    confirmText: "Mark lost", danger: true,
  });
  if (!ok) return;
  await markQuotationLost(doc.value.name);
  await load();
});

const toOrder = () => run(async () => {
  if (!doc.value) return;
  const res = await quotationToOrder(doc.value.name);
  toasts.success(`Order ${res.name} created`);
  void router.push({ name: "order-detail", params: { name: res.name } });
});

const toInvoice = () => run(async () => {
  if (!doc.value) return;
  const res = await orderToInvoice(doc.value.name);
  toasts.success(`Invoice ${res.name} drafted — choose payment and submit`);
  void router.push({ name: "invoice-edit", params: { name: res.name } });
});

// A lead quotation cannot be ordered until the lead is a customer.
const convertThenOrder = () => run(async () => {
  if (!doc.value?.party) return;
  const ok = await confirm.ask({
    title: "Convert lead to customer?",
    message: "This quotation can only become an order once the lead is a customer.",
    confirmText: "Convert",
  });
  if (!ok) return;
  const c = await convertLead(doc.value.party);
  toasts.success(`Customer ${c.customer} created`);
  void router.push({ name: "customer-detail", params: { name: c.customer } });
});

async function print() {
  if (!doc.value) return;
  try {
    await openPrint(router, k.value.doctype, doc.value.name, session.printFormats, session.printBehaviour);
  } catch (e) {
    fail(e);
  }
}

const open = (name: string, route: string) => router.push({ name: route, params: { name } });
</script>

<template>
  <div class="stack">
    <p v-if="err" class="error">{{ err }}</p>
    <div v-if="loading && !doc" class="stack">
      <div class="skeleton" style="height:6rem" /><div class="skeleton" style="height:10rem" />
    </div>

    <template v-else-if="doc">
      <section class="hero card stack">
        <div class="hero-head">
          <div>
            <span class="muted xsmall">{{ k.title }}</span>
            <h2 class="doc-name">{{ doc.name }}</h2>
            <span class="muted small">{{ doc.transaction_date }} · {{ doc.party_name }}<template v-if="isLeadQuote"> (lead)</template></span>
          </div>
          <span class="pill" :data-tone="tone(doc.status)">{{ doc.status }}</span>
        </div>
        <div class="hero-total">
          <div>
            <span class="muted xsmall">Grand total</span>
            <strong class="big"><SarSymbol :code="session.currency" />{{ fmt(doc.grand_total) }}</strong>
          </div>
          <div v-if="dateValue" class="hero-sub">
            <span class="muted xsmall">{{ dateLabel }}</span>
            <strong>{{ dateValue }}</strong>
          </div>
        </div>
        <div v-if="kind === 'order' && doc.docstatus === 1" class="muted xsmall">
          Delivered {{ fmt(doc.per_delivered) }}% · Billed {{ fmt(doc.per_billed) }}%
        </div>

        <div class="row actions">
          <template v-if="isDraft">
            <button class="primary" :disabled="busy" @click="submit"><Icon name="check" :size="16" /> Submit</button>
            <button class="ghost" :disabled="busy" @click="router.push({ name: k.edit, params: { name: doc.name } })">
              <Icon name="edit" :size="16" /> Edit
            </button>
            <button class="ghost" :disabled="busy" @click="print"><Icon name="receipt" :size="16" /> Print</button>
            <button class="ghost danger-ghost" :disabled="busy" @click="remove"><Icon name="trash" :size="16" /> Delete</button>
          </template>
          <template v-else-if="isOpen && kind === 'quotation'">
            <button v-if="!isLeadQuote" class="primary" :disabled="busy" @click="toOrder">
              <Icon name="bag" :size="16" /> Make order
            </button>
            <button v-else class="primary" :disabled="busy" @click="convertThenOrder">
              <Icon name="customer" :size="16" /> Convert lead
            </button>
            <button class="ghost danger-ghost" :disabled="busy" @click="lost"><Icon name="x" :size="16" /> Lost</button>
          </template>
          <template v-else-if="isOpen && kind === 'order' && (doc.per_billed ?? 0) < 100">
            <button class="primary" :disabled="busy" @click="toInvoice"><Icon name="invoice" :size="16" /> Create invoice</button>
          </template>
          <button v-if="!isDraft" class="ghost" :disabled="busy" @click="print"><Icon name="receipt" :size="16" /> Print</button>
        </div>
      </section>

      <section v-if="linked.length" class="card stack">
        <h3 class="section-h">{{ kind === "quotation" ? "Orders" : "Invoices" }}</h3>
        <button
          v-for="n in linked" :key="n" class="link-row ghost"
          @click="open(n, kind === 'quotation' ? 'order-detail' : 'invoice-detail')"
        >
          <span>{{ n }}</span><Icon name="chevron-right" :size="16" />
        </button>
      </section>

      <section class="card stack">
        <h3 class="section-h">Items</h3>
        <ul class="lines">
          <li v-for="it in doc.items" :key="it.name" class="line">
            <div class="line-head">
              <strong class="truncate">{{ it.item_name }}</strong>
              <strong class="amt"><SarSymbol :code="session.currency" />{{ fmt(it.amount) }}</strong>
            </div>
            <div class="line-meta muted xsmall">
              <span>{{ fmt(it.qty) }} {{ it.uom || "" }}</span><span>×</span>
              <span><SarSymbol :code="session.currency" />{{ fmtRate(it.rate) }}</span>
              <span v-if="it.discount_percentage > 0" class="disc">- {{ fmt(it.discount_percentage) }}%</span>
            </div>
          </li>
        </ul>
      </section>

      <section class="card stack">
        <h3 class="section-h">Totals</h3>
        <div class="totals-row"><span class="muted">Net total</span><span><SarSymbol :code="session.currency" />{{ fmt(doc.net_total) }}</span></div>
        <div v-if="doc.discount_amount" class="totals-row">
          <span class="muted">Discount</span><span>- <SarSymbol :code="session.currency" />{{ fmt(Math.abs(doc.discount_amount)) }}</span>
        </div>
        <div v-for="(t, i) in doc.taxes" :key="i" class="totals-row">
          <span class="muted">{{ t.description }} ({{ fmt(t.rate) }}%)</span>
          <span><SarSymbol :code="session.currency" />{{ fmt(t.tax_amount) }}</span>
        </div>
        <div class="totals-row big-row">
          <strong>Grand total</strong><strong><SarSymbol :code="session.currency" />{{ fmt(doc.grand_total) }}</strong>
        </div>
      </section>

      <section v-if="doc.remarks" class="card stack">
        <h3 class="section-h">Notes</h3>
        <p class="muted small" style="white-space:pre-wrap">{{ doc.remarks }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hero { background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--surface)) 0%, var(--surface) 100%); }
.hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.doc-name { margin: 0.15rem 0 0.1rem; font-size: var(--text-lg); font-family: var(--font-mono, ui-monospace); }
.hero-total { display: grid; grid-template-columns: 1fr auto; gap: 0.5rem 1rem; align-items: end; padding-block: 0.25rem; }
.hero-total .big { display: block; font-size: var(--text-2xl); font-variant-numeric: tabular-nums; }
.hero-sub { text-align: right; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.actions button { flex: 1 1 7rem; min-height: 2.75rem; justify-content: center; }
.danger-ghost { color: var(--danger); }
.danger-ghost:hover { background: var(--danger-soft); }
.link-row { display: flex; justify-content: space-between; align-items: center; min-height: 2.5rem; }
.section-h { margin: 0 0 0.1rem; font-size: var(--text-sm); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.lines { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.line { display: flex; flex-direction: column; gap: 0.2rem; padding-bottom: 0.5rem; border-bottom: 1px dashed var(--border); }
.line:last-child { border-bottom: none; padding-bottom: 0; }
.line-head { display: flex; justify-content: space-between; gap: 0.5rem; }
.amt { font-variant-numeric: tabular-nums; white-space: nowrap; }
.line-meta { display: flex; gap: 0.4rem; align-items: baseline; flex-wrap: wrap; }
.disc { color: var(--warning); }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.totals-row { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; font-variant-numeric: tabular-nums; }
.big-row { border-top: 1px solid var(--border); padding-top: 0.4rem; }
.big-row strong { font-size: var(--text-lg); }
</style>
