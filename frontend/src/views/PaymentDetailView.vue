<script setup lang="ts">
/**
 * Payment Entry detail page — the landing after a successful payment save.
 *
 * Before 2026-04-21 the payment form silently redirected to the dashboard
 * on save, which left the user with no confirmation of what they just
 * recorded. The real-world expectation is "I just took 500 SAR from the
 * customer — show me the receipt". This view is that receipt: amount,
 * mode, posting date, which invoices the payment was allocated against,
 * and a Print button hooked up to the same native print bridge the
 * invoice view uses.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { detail, deletePayment, type PaymentDetail } from "@/api/payment";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore } from "@/stores/confirm";
import { ApiError } from "@/app/frappe";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();
const confirm = useConfirmStore();

const doc = ref<PaymentDetail | null>(null);
const loading = ref(false);
const err = ref("");
const busy = ref(false);

const name = computed(() => String(route.params.name ?? ""));

async function load() {
  if (!name.value) return;
  loading.value = true;
  err.value = "";
  try {
    doc.value = await detail(name.value);
  } catch (e) {
    err.value =
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function fmt(n: number | null | undefined): string {
  const v = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(v);
}

function tone(status: string | undefined): string {
  const s = String(status || "").toLowerCase();
  if (s === "submitted") return "success";
  if (s === "cancelled") return "danger";
  return "info";
}

function printEntry() {
  if (!doc.value) return;
  void router.push({
    name: "print-view",
    params: { doctype: "Payment Entry", name: doc.value.name },
  });
}

function openInvoice(ref: string) {
  void router.push({ name: "invoice-detail", params: { name: ref } });
}

/**
 * Delete a draft Payment Entry. Submitted entries are intentionally
 * blocked at the backend — cancelling a posted payment reverses GL
 * entries, which needs the Desk workflow with proper controls.
 */
async function onDelete() {
  if (!doc.value || busy.value) return;
  const ok = await confirm.ask({
    title: `Delete draft ${doc.value.name}?`,
    message: "This cannot be undone.",
    confirmText: "Delete",
    danger: true,
  });
  if (!ok) return;
  busy.value = true;
  try {
    await deletePayment(doc.value.name);
    toasts.success("Draft deleted");
    void router.replace({ name: "payments" });
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="stack">
    <p v-if="err" class="error">{{ err }}</p>

    <div v-if="loading && !doc" class="stack">
      <div class="skeleton" style="height: 6rem" />
      <div class="skeleton" style="height: 8rem" />
    </div>

    <template v-else-if="doc">
      <section class="hero card stack">
        <div class="hero-head">
          <div>
            <span class="muted xsmall">Payment</span>
            <h2 class="pe-name">{{ doc.name }}</h2>
            <span class="muted small">{{ doc.posting_date }} · {{ doc.party_name || doc.party }}</span>
          </div>
          <span class="pill" :data-tone="tone(doc.status)">{{ doc.status }}</span>
        </div>
        <div class="hero-total">
          <span class="muted xsmall">Amount collected</span>
          <strong class="big"><SarSymbol :code="session.currency" />{{ fmt(doc.paid_amount) }}</strong>
        </div>
        <div class="row actions">
          <button class="ghost" @click="printEntry">
            <Icon name="receipt" :size="16" /> Print
          </button>
          <button class="ghost" @click="router.push({ name: 'payment-new' })">
            <Icon name="plus" :size="16" /> New payment
          </button>
          <button
            v-if="doc.docstatus === 0"
            class="ghost danger-ghost"
            :disabled="busy"
            @click="onDelete"
          >
            <Icon name="trash" :size="16" /> Delete
          </button>
        </div>
      </section>

      <section class="card stack">
        <h3 class="section-h">Details</h3>
        <div class="kv"><span class="muted">Mode</span><strong>{{ doc.mode_of_payment || '—' }}</strong></div>
        <div v-if="doc.reference_no" class="kv">
          <span class="muted">Reference</span>
          <strong>{{ doc.reference_no }}</strong>
        </div>
        <div v-if="doc.reference_date" class="kv">
          <span class="muted">Ref. date</span>
          <strong>{{ doc.reference_date }}</strong>
        </div>
        <div class="kv">
          <span class="muted">Type</span>
          <strong>{{ doc.payment_type }}</strong>
        </div>
      </section>

      <section v-if="doc.references.length" class="card stack">
        <h3 class="section-h">Invoices covered</h3>
        <ul class="ref-list">
          <li v-for="r in doc.references" :key="r.reference_name">
            <button class="ref-row" type="button" @click="openInvoice(r.reference_name)">
              <div class="ref-name">
                <strong>{{ r.reference_name }}</strong>
                <span class="muted xsmall">of <SarSymbol :code="session.currency" />{{ fmt(r.total_amount) }}</span>
              </div>
              <div class="ref-amt">
                <strong><SarSymbol :code="session.currency" />{{ fmt(r.allocated_amount) }}</strong>
                <span class="muted xsmall">allocated</span>
              </div>
            </button>
          </li>
        </ul>
      </section>

      <section v-if="doc.remarks" class="card stack">
        <h3 class="section-h">Notes</h3>
        <p class="muted small" style="white-space:pre-wrap">{{ doc.remarks }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 10%, var(--surface)) 0%, var(--surface) 100%);
}
.hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.pe-name { margin: 0.15rem 0 0.1rem; font-size: var(--text-lg); font-family: var(--font-mono, ui-monospace); }
.hero-total { display: flex; flex-direction: column; gap: 0.1rem; padding-block: 0.25rem; }
.hero-total .big { font-size: var(--text-2xl); font-variant-numeric: tabular-nums; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.actions button { flex: 1 1 7rem; min-height: 2.75rem; justify-content: center; }

.section-h { margin: 0 0 0.1rem; font-size: var(--text-sm); color: var(--text-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.kv { display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; }

.ref-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.ref-row {
  all: unset; cursor: pointer; width: 100%;
  display: flex; justify-content: space-between; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.75rem;
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  transition: background var(--dur-fast) var(--ease);
}
.ref-row:active { background: var(--primary-soft); }
.ref-name { display: flex; flex-direction: column; min-width: 0; }
.ref-amt { display: flex; flex-direction: column; align-items: flex-end; gap: 0.05rem; }
</style>
