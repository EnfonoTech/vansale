<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listMine as listCustomers } from "@/api/customer";
import { outstanding, save } from "@/api/payment";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const toasts = useToastStore();

const customers = ref<Array<{ name: string; customer_name: string }>>([]);
const invoices = ref<Array<Record<string, unknown>>>([]);
const customer = ref(String(route.query.customer ?? ""));
const preselectInvoice = String(route.query.invoice ?? "");
const selected = ref<Set<string>>(new Set());
const amount = ref<number | "">("");
const mode = ref<"Cash" | "Bank">("Cash");
const reference = ref("");
const remarks = ref("");
const busy = ref(false);

onMounted(async () => {
  customers.value = await listCustomers(undefined, 200);
  if (customer.value) await loadOutstanding();
});

watch(customer, loadOutstanding);

async function loadOutstanding() {
  selected.value = new Set();
  invoices.value = [];
  if (customer.value) {
    try { invoices.value = await outstanding(customer.value); }
    catch { /* keep empty; user can still free-text a payment */ }
    if (preselectInvoice) {
      const row = invoices.value.find((r) => String(r.name) === preselectInvoice);
      if (row) togglePick(row);
    }
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

const selectedList = computed(() => Array.from(selected.value));
const hasPicks = computed(() => selected.value.size > 0);
const totalOutstanding = computed(() =>
  invoices.value.reduce((t, r) => t + (Number(r.outstanding_amount) || 0), 0),
);

async function submit() {
  if (!customer.value) { toasts.warn("Select customer"); return; }
  const n = Number(amount.value);
  if (!Number.isFinite(n) || n <= 0) { toasts.warn("Amount must be positive"); return; }
  busy.value = true;
  try {
    const res = await save({
      customer: customer.value,
      paid_amount: n,
      mode_of_payment: mode.value,
      reference_no: reference.value || undefined,
      invoice_names: hasPicks.value ? selectedList.value : undefined,
      remarks: remarks.value || undefined,
    });
    toasts.success(
      res.queued
        ? "Payment queued offline"
        : `Payment ${res.name} · ${session.currency} ${res.paid_amount.toFixed(2)}`,
    );
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
    </section>

    <section v-if="invoices.length > 0" class="card stack">
      <div class="row-head">
        <h3 style="margin:0">Outstanding invoices</h3>
        <span class="muted xsmall">
          Total {{ session.currency }} {{ fmt(totalOutstanding) }}
        </span>
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
                <strong>{{ r.name }}</strong>
                <div class="muted xsmall">{{ r.posting_date }}</div>
              </div>
            </div>
            <div class="amt">
              <strong>{{ session.currency }} {{ fmt(r.outstanding_amount) }}</strong>
              <span class="muted xsmall">of {{ fmt(r.grand_total) }}</span>
            </div>
          </button>
        </li>
      </ul>
    </section>

    <section class="card stack">
      <label class="field">
        <span class="label">Amount</span>
        <div class="amount-input">
          <span class="amount-currency">{{ session.currency }}</span>
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
      <div>
        <span class="label" style="display:block;margin-bottom:0.35rem">Mode of payment</span>
        <div class="mode-row">
          <button
            class="mode-btn"
            :class="{ active: mode === 'Cash' }"
            type="button"
            @click="mode = 'Cash'"
          >
            <Icon name="payment" :size="18" />
            Cash
          </button>
          <button
            class="mode-btn"
            :class="{ active: mode === 'Bank' }"
            type="button"
            @click="mode = 'Bank'"
          >
            <Icon name="receipt" :size="18" />
            Bank
          </button>
        </div>
      </div>
      <label class="field">
        <span class="label">Reference (optional)</span>
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

.row-head { display: flex; justify-content: space-between; align-items: center; }
.hint {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: var(--text-xs); color: var(--text-muted);
  background: var(--surface-muted); padding: 0.35rem 0.55rem;
  border-radius: var(--radius-sm); margin: 0;
}
.inv-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.inv-row {
  all: unset; cursor: pointer; width: 100%;
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

.mode-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.mode-btn {
  all: unset; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; gap: 0.25rem;
  padding: 0.75rem;
  border-radius: var(--radius);
  background: var(--surface-muted);
  color: var(--text-muted);
  font-weight: 600;
  border: 2px solid transparent;
  transition: all var(--dur-fast) var(--ease);
}
.mode-btn.active {
  background: var(--primary-soft);
  color: var(--primary);
  border-color: var(--primary);
}

.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
