<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers, customerLabel, type CustomerRow } from "@/api/customer";
import { outstanding, save, modesOfPayment, type ModeOfPayment } from "@/api/payment";
import { ApiError, NetworkError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";
import SearchSelect from "@/components/SearchSelect.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const customers = ref<CustomerRow[]>([]);
const invoices = ref<Array<Record<string, unknown>>>([]);
const mops = ref<ModeOfPayment[]>([]);
const customer = ref(String(route.query.customer ?? ""));
const preselectInvoice = String(route.query.invoice ?? "");
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
  if (customer.value) await loadOutstanding();
});

watch(customer, loadOutstanding);

// Searchable customer picker (name, second name, VAT), as on the invoice.
const customerOptions = computed(() =>
  customers.value.map((c) => ({
    value: c.name,
    label: customerLabel(c),
    sub: [c.secondary_name, c.vat_number ? `VAT ${c.vat_number}` : ""].filter(Boolean).join(" · "),
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
    invoices.value = await outstanding(customer.value);
    if (preselectInvoice) {
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
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(v);
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
const totalOutstanding = computed(() =>
  invoices.value.reduce((t, r) => t + (Number(r.outstanding_amount) || 0), 0),
);

// Modes posting to a Bank account need a reference number (ERPNext requires No + Date).
const needsReference = computed(() => Boolean(mops.value.find((m) => m.name === mode.value)?.needs_reference));

async function submit() {
  if (!customer.value) { toasts.warn("Select customer"); return; }
  const n = Number(amount.value);
  if (!Number.isFinite(n) || n <= 0) { toasts.warn("Amount must be positive"); return; }
  if (needsReference.value && !reference.value.trim()) {
    toasts.warn(`Enter the reference number for ${mode.value}`);
    return;
  }
  busy.value = true;
  try {
    const res = await save({
      customer: customer.value,
      paid_amount: n,
      mode_of_payment: mode.value as "Cash" | "Bank" | string,
      reference_no: reference.value || undefined,
      invoice_names: hasPicks.value && !advance.value ? selectedList.value : undefined,
      remarks: remarks.value || undefined,
      advance: advance.value ? 1 : undefined,
    });
    toasts.success(
      res.queued
        ? "Payment queued offline"
        : `Payment ${res.name} · ${session.currency} ${res.paid_amount.toFixed(2)}`,
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

    <button class="submit" :disabled="busy" @click="submit">
      <Icon name="check" :size="18" />
      {{ busy ? "Saving…" : "Record payment" }}
    </button>
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

.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
