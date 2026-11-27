<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers, customerLabel, type CustomerRow } from "@/api/customer";
import { outstanding, save, modesOfPayment, detail as paymentDetail, updateDraft, type ModeOfPayment } from "@/api/payment";
import { ApiError, NetworkError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import SearchSelect from "@/components/SearchSelect.vue";
import { vDecimals } from "@/components/decimals";
import { confirmSubmit, withCurrency } from "@/stores/confirm";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const customers = ref<CustomerRow[]>([]);
const invoices = ref<Array<Record<string, unknown>>>([]);
const mops = ref<ModeOfPayment[]>([]);
const customer = ref(String(route.query.customer ?? ""));
const preselectInvoice = String(route.query.invoice ?? "");
// Editing a draft collection (?draft=<name>): filled from it, saved in place.
const draftName = String(route.query.draft ?? "");
// The draft's invoices, picked once its customer's invoices have loaded.
let draftPicks: string[] | null = null;
let draftAmount: number | null = null;
const selected = ref<Set<string>>(new Set());
const amount = ref<number | "">("");
const mode = ref<string>("Cash");
const reference = ref("");
const remarks = ref("");
const busy = ref(false);
const loadingOutstanding = ref(false);
const outstandingError = ref("");
// "Allow advance payment" setting: take the money without allocating it to
// invoices (it stays as the customer's credit). Off → auto-allocate as before.
const advance = ref(false);
watch(advance, (on) => { if (on) clearPicks(); });

onMounted(async () => {
  customers.value = await listCustomers(undefined, 200);
  try {
    mops.value = await modesOfPayment();
    if (mops.value.length > 0 && !mops.value.some((m) => m.name === mode.value)) {
      mode.value = mops.value[0].name;
    }
  } catch { /* fall back to hardcoded options */ }
  if (draftName) {
    await fillFromDraft();
    return;
  }
  if (customer.value) await loadOutstanding();
});

async function fillFromDraft() {
  try {
    const d = await paymentDetail(draftName);
    if (d.docstatus !== 0 || d.payment_type !== "Receive") {
      toasts.error(`${draftName} is not a draft collection`);
      void router.replace({ name: "payment-detail", params: { name: draftName } });
      return;
    }
    if (!customers.value.some((c) => c.name === d.party)) {
      customers.value.push({ name: d.party, customer_name: d.party_name ?? d.party });
    }
    draftPicks = d.references.filter((r) => r.reference_doctype === "Sales Invoice").map((r) => r.reference_name);
    draftAmount = d.paid_amount;
    advance.value = session.advancePayment && draftPicks.length === 0;
    if (d.mode_of_payment) mode.value = d.mode_of_payment;
    reference.value = d.reference_no ?? "";
    // Only a typed note; ERPNext's own text would go stale with the amount.
    remarks.value = d.custom_remarks ? d.remarks ?? "" : "";
    if (customer.value === d.party) await loadOutstanding();
    else customer.value = d.party; // the watcher loads its invoices
  } catch (e) {
    toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
  }
}

watch(customer, loadOutstanding);

// Searchable customer picker (name, second name, VAT), as on the invoice.
const customerOptions = computed(() =>
  customers.value.map((c) => ({
    value: c.name,
    label: customerLabel(c),
    sub: [c.secondary_name, c.vat_number ? `VAT ${c.vat_number}` : ""].filter(Boolean).join(" · "),
    // Searched but not shown: code, both names, mobile, VAT.
    keywords: [c.name, c.customer_name, c.customer_name_2, c.mobile_no, c.vat_number].filter(Boolean).join(" "),
  })),
);

async function onCustomerSearch(term: string) {
  try {
    const found = await listCustomers(term || undefined, 50);
    const seen = new Set(customers.value.map((c) => c.name));
    for (const c of found) if (!seen.has(c.name)) customers.value.push(c);
  } catch {
    /* offline — local filter over the loaded page */
  }
}

async function loadOutstanding() {
  selected.value = new Set();
  invoices.value = [];
  outstandingError.value = "";
  if (!customer.value) return;
  loadingOutstanding.value = true;
  try {
    invoices.value = await outstanding(customer.value, draftName || undefined);
    if (draftPicks) {
      selected.value = new Set(draftPicks.filter((n) => invoices.value.some((r) => String(r.name) === n)));
      amount.value = draftAmount ?? "";
      draftPicks = null;
    } else if (preselectInvoice) {
      const row = invoices.value.find((r) => String(r.name) === preselectInvoice);
      if (row) togglePick(row);
    }
  } catch (e) {
    if (e instanceof NetworkError) {
      outstandingError.value = "Offline — outstanding invoices unavailable. You can still record a payment.";
    } else if (e instanceof ApiError) {
      outstandingError.value = e.serverMessage ?? "Could not load outstanding invoices";
    } else {
      outstandingError.value = "Could not load outstanding invoices";
    }
  } finally {
    loadingOutstanding.value = false;
  }
}

function fmt(n: unknown): string {
  const v = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: session.currencyPrecision }).format(v);
}

function togglePick(r: Record<string, unknown>) {
  const n = String(r.name);
  const s = new Set(selected.value);
  if (s.has(n)) s.delete(n); else s.add(n);
  selected.value = s;
  // Auto-fill amount with the sum of picked outstanding (user may override).
  amount.value = invoices.value
    .filter((row) => s.has(String(row.name)))
    .reduce((t, row) => t + (Number(row.outstanding_amount) || 0), 0);
}

function selectAll() {
  const s = new Set<string>();
  for (const r of invoices.value) s.add(String(r.name));
  selected.value = s;
  amount.value = invoices.value.reduce((t, r) => t + (Number(r.outstanding_amount) || 0), 0);
}

function clearPicks() {
  selected.value = new Set();
  amount.value = "";
}

function statusTone(status: unknown): string {
  const s = String(status || "").toLowerCase();
  if (s === "overdue") return "danger";
  if (s === "unpaid") return "warning";
  if (s === "partly paid") return "warning";
  return "info";
}

const selectedList = computed(() => Array.from(selected.value));
const hasPicks = computed(() => selected.value.size > 0);
// What the picked invoices (or all of them) still owe.
const openTotal = computed(() =>
  invoices.value
    .filter((r) => !hasPicks.value || selected.value.has(String(r.name)))
    .reduce((t, r) => t + (Number(r.outstanding_amount) || 0), 0),
);
const totalOutstanding = computed(() =>
  invoices.value.reduce((t, r) => t + (Number(r.outstanding_amount) || 0), 0),
);

// Modes posting to a Bank account need a reference number (ERPNext requires No + Date).
const needsReference = computed(() => Boolean(mops.value.find((m) => m.name === mode.value)?.needs_reference));

/** After saving an edited draft: back to its screen when we came from it
 *  (it reloads), else open it in place of this one. */
function backToDraft(name: string) {
  const back = (window.history.state as { back?: unknown } | null)?.back;
  if (typeof back === "string" && back.startsWith(`/payment/${encodeURIComponent(name)}`)) router.back();
  else void router.replace({ name: "payment-detail", params: { name } });
}

/** Save the collection — submitted per the setting, or (where collections
 *  are submitted) kept as a draft to submit later. */
async function submit(submitNow = true) {
  if (busy.value) return;
  if (!customer.value) { toasts.warn("Select customer"); return; }
  const n = Number(amount.value);
  if (!Number.isFinite(n) || n <= 0) { toasts.warn("Amount must be positive"); return; }
  if (needsReference.value && !reference.value.trim()) {
    toasts.warn(`Enter the reference number for ${mode.value}`);
    return;
  }
  // More than the invoices: the rest would sit as an unallocated advance.
  const over = !advance.value && invoices.value.length ? n - openTotal.value : 0;
  if (over > 0.005 && !session.advancePayment) {
    toasts.warn(`That is ${fmt(over)} more than the ${hasPicks.value ? "picked " : ""}invoices (${fmt(openTotal.value)}). Collect up to that amount.`);
    return;
  }
  // Locked from the first tap (a double tap saved two payments).
  busy.value = true;
  if (submitNow) {
    const cust = customers.value.find((c) => c.name === customer.value);
    const ok = await confirmSubmit("Save payment?", [
      cust ? customerLabel(cust) : customer.value,
      `${withCurrency(fmt(n))} · ${mode.value}`,
      advance.value
        ? "Advance (not allocated)"
        : hasPicks.value ? `For ${selectedList.value.length} invoice${selectedList.value.length === 1 ? "" : "s"}` : "Oldest invoices first",
    ], "Yes, save");
    if (!ok) { busy.value = false; return; }
  }
  try {
    if (draftName) {
      const upd = await updateDraft({
        name: draftName,
        paid_amount: n,
        mode_of_payment: mode.value,
        reference_no: reference.value || undefined,
        invoice_names: hasPicks.value && !advance.value ? selectedList.value : undefined,
        remarks: remarks.value || undefined,
        advance: advance.value ? 1 : undefined,
        submit: submitNow ? 1 : 0,
      });
      toasts.success(`${submitNow ? "Payment" : "Draft payment"} ${upd.name} · ${session.currency} ${upd.paid_amount.toFixed(session.currencyPrecision)}`);
      if (!submitNow) backToDraft(upd.name);
      else {
        const autoprint = session.printBehaviour?.after_submit ? { autoprint: "1" } : undefined;
        void router.replace({ name: "payment-detail", params: { name: upd.name }, query: autoprint });
      }
      return;
    }
    const res = await save({
      customer: customer.value,
      paid_amount: n,
      mode_of_payment: mode.value as "Cash" | "Bank" | string,
      reference_no: reference.value || undefined,
      invoice_names: hasPicks.value && !advance.value ? selectedList.value : undefined,
      remarks: remarks.value || undefined,
      advance: advance.value ? 1 : undefined,
      ...(submitNow ? {} : { submit: 0 as const }),
    });
    if (!submitNow && !res.queued) {
      toasts.success(`Draft payment ${res.name} saved`);
      void router.push({ name: "payment-detail", params: { name: res.name } });
      return;
    }
    toasts.success(
      res.queued
        ? "Payment queued offline"
        : `Payment ${res.name} · ${session.currency} ${res.paid_amount.toFixed(session.currencyPrecision)}`,
    );
    // Land on the new payment's detail view so the user sees exactly what
    // was recorded (amount, mode, invoices covered) rather than bouncing
    // back to the dashboard. Queued offline saves have no real name yet,
    // so we fall back to the dashboard in that case.
    if (!res.queued && res.name && !res.name.startsWith("QUEUED")) {
      const autoprint = session.printBehaviour?.after_submit ? { autoprint: "1" } : undefined;
      void router.push({ name: "payment-detail", params: { name: res.name }, query: autoprint });
    } else {
      void router.push({ name: "dashboard" });
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
    <p v-if="draftName" class="draft-note">Editing draft {{ draftName }}</p>
    <section class="card stack">
      <span class="label">Customer</span>
      <SearchSelect
        v-model="customer"
        :options="customerOptions"
        placeholder="Search customer by name or code"
        remote
        :disabled="!!draftName"
        @search="onCustomerSearch"
      />
    </section>

    <section v-if="session.advancePayment && customer" class="card stack">
      <span class="label">Payment for</span>
      <div class="seg">
        <button type="button" class="seg-btn" :data-active="!advance" @click="advance = false">
          <Icon name="receipt" :size="16" /> Invoices
        </button>
        <button type="button" class="seg-btn" :data-active="advance" @click="advance = true">
          <Icon name="clock" :size="16" /> Advance
        </button>
      </div>
      <p v-if="advance" class="hint">
        Not allocated to any invoice — the amount stays as the customer's advance.
      </p>
    </section>

    <template v-if="!advance">
    <section v-if="loadingOutstanding" class="card stack">
      <p class="hint"><Icon name="clock" :size="14" /> Loading outstanding invoices…</p>
    </section>

    <section v-else-if="outstandingError && customer" class="card stack">
      <p class="hint error-hint" role="alert">
        <Icon name="x" :size="14" /> {{ outstandingError }}
      </p>
      <button type="button" class="link-btn" @click="loadOutstanding">Retry</button>
    </section>

    <section v-else-if="invoices.length > 0" class="card stack">
      <div class="row-head">
        <h3 style="margin:0">Outstanding invoices</h3>
        <span class="muted xsmall">
          Total <SarSymbol :code="session.currency" />{{ fmt(totalOutstanding) }}
        </span>
      </div>
      <div class="bulk">
        <button type="button" class="link-btn" @click="selectAll">
          <Icon name="check" :size="13" /> Select all
        </button>
        <button type="button" class="link-btn" @click="clearPicks">
          <Icon name="x" :size="13" /> Clear
        </button>
      </div>
      <p v-if="!hasPicks" class="hint">
        <Icon name="clock" :size="14" />
        None picked — payment will auto-allocate FIFO (oldest first).
      </p>
      <ul class="inv-list">
        <li v-for="r in invoices" :key="String(r.name)">
          <button
            type="button"
            class="inv-row"
            :class="{ active: selected.has(String(r.name)) }"
            @click="togglePick(r)"
          >
            <div class="check-col">
              <span class="check" :data-on="selected.has(String(r.name))">
                <Icon v-if="selected.has(String(r.name))" name="check" :size="14" />
              </span>
              <div>
                <div class="name-row">
                  <strong>{{ r.name }}</strong>
                  <span v-if="r.status" class="pill" :data-tone="statusTone(r.status)">{{ r.status }}</span>
                </div>
                <div class="muted xsmall">{{ r.posting_date }}</div>
              </div>
            </div>
            <div class="amt">
              <strong><SarSymbol :code="session.currency" />{{ fmt(r.outstanding_amount) }}</strong>
              <span class="muted xsmall">of {{ fmt(r.grand_total) }}</span>
              <span v-if="Number(r.pending_amount) > 0" class="muted xsmall">
                {{ fmt(Number(r.pending_amount)) }} awaiting office
              </span>
            </div>
          </button>
        </li>
      </ul>
    </section>

    <section v-else-if="customer" class="card stack">
      <p class="hint">
        <Icon name="check" :size="14" />
        No outstanding invoices for this customer.
      </p>
    </section>
    </template>

    <section class="card stack">
      <label class="field">
        <span class="label">Amount</span>
        <div class="amount-input">
          <span class="amount-currency"><SarSymbol :code="session.currency" /></span>
          <input
            type="number"
            min="0"
            step="any"
            inputmode="decimal"
            v-model.number="amount"
            v-decimals="session.currencyPrecision"
            placeholder="0.00"
          />
        </div>
      </label>
      <label class="field">
        <span class="label">Mode of payment</span>
        <select v-if="mops.length > 0" v-model="mode">
          <option v-for="m in mops" :key="m.name" :value="m.name">{{ m.name }}</option>
        </select>
        <select v-else v-model="mode">
          <option :value="mode">{{ mode }}</option>
        </select>
      </label>
      <label class="field">
        <span class="label">Reference {{ needsReference ? "(required)" : "(optional)" }}</span>
        <input v-model="reference" placeholder="Cheque / transaction no." />
      </label>
      <label class="field">
        <span class="label">Notes (optional)</span>
        <textarea v-model="remarks" rows="2" />
      </label>
    </section>

    <!-- Save draft only where collections are submitted ("Payment collection
         status" = Submit); with Draft every collection is a draft already. -->
    <div :class="{ actions: session.collectionSubmit }">
      <button v-if="session.collectionSubmit" class="btn-ghost" type="button" :disabled="busy" @click="submit(false)">
        <Icon name="edit" :size="18" /> Save draft
      </button>
      <button class="submit" :disabled="busy" @click="submit(true)">
      <Icon name="check" :size="18" />
      {{ busy ? "Saving…" : "Record payment" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer;
  padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center;
  font-weight: 500; display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }

.row-head { display: flex; justify-content: space-between; align-items: center; }
.hint {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: var(--text-xs); color: var(--text-muted);
  background: var(--surface-muted); padding: 0.35rem 0.55rem;
  border-radius: var(--radius-sm); margin: 0;
}
.hint.error-hint {
  background: color-mix(in srgb, var(--danger, #dc2626) 10%, transparent);
  color: var(--danger, #dc2626);
}
.inv-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.inv-row {
  all: unset; box-sizing: border-box; cursor: pointer; width: 100%;
  display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  border: 1px solid transparent;
  transition: all var(--dur-fast) var(--ease);
}
.inv-row.active { background: var(--primary-soft); border-color: var(--primary); }
.inv-row .amt { text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 0.15rem; }
.check-col { display: flex; align-items: center; gap: 0.6rem; }
.check {
  width: 1.2rem; height: 1.2rem;
  border: 2px solid var(--border);
  border-radius: 4px; display: grid; place-items: center;
  color: white; background: transparent;
  transition: all var(--dur-fast) var(--ease);
}
.check[data-on="true"] { background: var(--primary); border-color: var(--primary); }

.amount-input {
  position: relative;
}
.amount-currency {
  position: absolute; top: 50%; inset-inline-start: 0.9rem; transform: translateY(-50%);
  font-size: var(--text-sm); font-weight: 600; color: var(--text-muted);
  pointer-events: none;
}
.amount-input input { padding-inline-start: 3rem; font-size: var(--text-xl); font-weight: 600; padding-block: 0.9rem; }

.bulk { display: flex; gap: 0.5rem; }
.link-btn {
  all: unset; cursor: pointer; color: var(--primary);
  font-size: var(--text-xs); font-weight: 600;
  display: inline-flex; align-items: center; gap: 0.2rem;
}
.name-row { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }

.submit { min-height: 3.25rem; font-size: var(--text-base); width: 100%; }
/* Save draft + Save, as on the invoice form. */
.actions { display: grid; grid-template-columns: 1fr 1.4fr; gap: 0.5rem; }
.btn-ghost {
  all: unset; cursor: pointer; box-sizing: border-box;
  min-height: 3.25rem; border-radius: var(--radius);
  background: var(--surface-muted); text-align: center;
  display: inline-flex; justify-content: center; align-items: center; gap: 0.4rem;
  font-weight: 600;
}
.btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.draft-note { margin: 0; padding: 0.5rem 0.75rem; border-radius: var(--radius); background: var(--info-soft); color: var(--info); font-size: var(--text-sm); font-weight: 600; }
</style>
