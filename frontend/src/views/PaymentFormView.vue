<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { listMine as listCustomers } from "@/api/customer";
import { outstanding, save } from "@/api/payment";
import { ApiError } from "@/app/frappe";

const router = useRouter();

const customers = ref<Array<{ name: string; customer_name: string }>>([]);
const invoices = ref<Array<Record<string, unknown>>>([]);
const customer = ref("");
const invoiceName = ref("");
const amount = ref<number | "">("");
const mode = ref<"Cash" | "Bank">("Cash");
const reference = ref("");
const remarks = ref("");

const busy = ref(false);
const err = ref("");
const success = ref("");

onMounted(async () => {
  customers.value = await listCustomers(undefined, 200);
});

watch(customer, async (val) => {
  invoiceName.value = "";
  invoices.value = [];
  if (val) invoices.value = await outstanding(val);
});

async function submit() {
  err.value = ""; success.value = "";
  if (!customer.value) { err.value = "Select customer"; return; }
  const n = Number(amount.value);
  if (!Number.isFinite(n) || n <= 0) { err.value = "Amount must be positive"; return; }
  busy.value = true;
  try {
    const res = await save({
      customer: customer.value,
      paid_amount: n,
      mode_of_payment: mode.value,
      reference_no: reference.value || undefined,
      invoice_name: invoiceName.value || undefined,
      remarks: remarks.value || undefined,
    });
    success.value = res.queued
      ? `Queued offline (${res.clientId.slice(0, 8)})`
      : `Recorded ${res.name} — ${res.paid_amount}`;
    setTimeout(() => router.push({ name: "dashboard" }), 900);
  } catch (e) {
    err.value = e instanceof ApiError ? (e.serverMessage ?? e.message) : e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="stack">
    <h1>Collect payment</h1>
    <section class="card stack">
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Customer</span>
        <select v-model="customer">
          <option value="" disabled>Select…</option>
          <option v-for="c in customers" :key="c.name" :value="c.name">
            {{ c.customer_name }}
          </option>
        </select>
      </label>
      <label class="stack" style="gap: 0.3rem" v-if="invoices.length > 0">
        <span class="muted">Against invoice (optional)</span>
        <select v-model="invoiceName">
          <option value="">— no specific invoice —</option>
          <option v-for="inv in invoices" :key="String(inv.name)" :value="inv.name">
            {{ inv.name }} · outstanding {{ inv.outstanding_amount }}
          </option>
        </select>
      </label>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Mode</span>
        <select v-model="mode">
          <option value="Cash">Cash</option>
          <option value="Bank">Bank</option>
        </select>
      </label>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Amount</span>
        <input type="number" min="0" step="any" v-model.number="amount" />
      </label>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Reference (cheque / txn)</span>
        <input v-model="reference" />
      </label>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Notes</span>
        <textarea v-model="remarks" rows="2" />
      </label>
    </section>
    <p v-if="err" class="error">{{ err }}</p>
    <p v-if="success" class="success">{{ success }}</p>
    <button :disabled="busy" @click="submit">{{ busy ? "Saving…" : "Record payment" }}</button>
    <button class="ghost" type="button" @click="router.back()">Cancel</button>
  </section>
</template>

<style scoped>
.success { color: var(--success); font-size: 0.9rem; }
</style>
