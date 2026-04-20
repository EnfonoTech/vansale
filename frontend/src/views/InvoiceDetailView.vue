<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { detail, type InvoiceDetail } from "@/api/invoice";
import { useSessionStore } from "@/stores/session";
import Icon from "@/components/Icon.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();

const inv = ref<InvoiceDetail | null>(null);
const loading = ref(false);
const err = ref("");

const name = computed(() => String(route.params.name ?? ""));

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

onMounted(load);

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

function payHere() {
  if (!inv.value) return;
  void router.push({
    name: "payment-new",
    query: { customer: inv.value.customer, invoice: inv.value.name },
  });
}

function printInvoice() {
  if (!inv.value) return;
  // TODO(phase-D): wire to server print format + ZATCA. For now open Frappe's print view.
  const url = `/printview?doctype=Sales%20Invoice&name=${encodeURIComponent(inv.value.name)}&format=Standard&no_letterhead=0`;
  window.open(url, "_blank");
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
            <span class="muted xsmall">Invoice</span>
            <h2 class="inv-name">{{ inv.name }}</h2>
            <span class="muted small">{{ inv.posting_date }} · {{ inv.customer_name }}</span>
          </div>
          <span class="pill" :data-tone="tone(inv.status)">{{ inv.status }}</span>
        </div>
        <div class="hero-total">
          <div>
            <span class="muted xsmall">Grand total</span>
            <strong class="big">{{ session.currency }} {{ fmt(inv.grand_total) }}</strong>
          </div>
          <div class="hero-sub">
            <span class="muted xsmall">Outstanding</span>
            <strong :class="inv.outstanding_amount > 0 ? 'warn' : ''">{{ session.currency }} {{ fmt(inv.outstanding_amount) }}</strong>
          </div>
        </div>
        <div class="row actions">
          <button
            v-if="inv.outstanding_amount > 0 && inv.docstatus === 1"
            class="primary"
            @click="payHere"
          >
            <Icon name="payment" :size="16" /> Collect
          </button>
          <button class="ghost" @click="printInvoice">
            <Icon name="receipt" :size="16" /> Print
          </button>
        </div>
      </section>

      <section class="card stack">
        <h3 class="section-h">Items</h3>
        <ul class="lines">
          <li v-for="(it, i) in inv.items" :key="i" class="line">
            <div class="line-head">
              <strong class="truncate">{{ it.item_name }}</strong>
              <strong class="amt">{{ session.currency }} {{ fmt(it.amount) }}</strong>
            </div>
            <div class="line-meta muted xsmall">
              <span>{{ fmt(it.qty) }} {{ it.uom || "" }}</span>
              <span>×</span>
              <span>{{ session.currency }} {{ fmt(it.rate) }}</span>
              <span v-if="it.discount_percentage > 0" class="disc">- {{ fmt(it.discount_percentage) }}%</span>
            </div>
          </li>
        </ul>
      </section>

      <section class="card stack">
        <h3 class="section-h">Totals</h3>
        <div class="totals-row"><span class="muted">Net total</span><span>{{ session.currency }} {{ fmt(inv.net_total) }}</span></div>
        <div v-if="inv.discount_amount > 0" class="totals-row">
          <span class="muted">Discount</span><span>- {{ session.currency }} {{ fmt(inv.discount_amount) }}</span>
        </div>
        <template v-if="inv.taxes.length">
          <div class="divider" />
          <div v-for="(t, i) in inv.taxes" :key="i" class="totals-row">
            <span class="muted">{{ t.description }} ({{ fmt(t.rate) }}%)</span>
            <span>{{ session.currency }} {{ fmt(t.tax_amount) }}</span>
          </div>
        </template>
        <div class="divider" />
        <div class="totals-row big-row">
          <strong>Grand total</strong>
          <strong>{{ session.currency }} {{ fmt(inv.grand_total) }}</strong>
        </div>
        <div class="totals-row">
          <span class="muted">Paid</span>
          <span>{{ session.currency }} {{ fmt(inv.paid_amount) }}</span>
        </div>
        <div class="totals-row">
          <span class="muted">Outstanding</span>
          <strong :class="inv.outstanding_amount > 0 ? 'warn' : ''">{{ session.currency }} {{ fmt(inv.outstanding_amount) }}</strong>
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
.actions { display: flex; gap: 0.5rem; }
.actions button { flex: 1; min-height: 2.75rem; justify-content: center; }

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
.big-row strong { font-size: var(--text-lg); }

.sp-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.sp-row { display: grid; grid-template-columns: auto 1fr auto; gap: 0.5rem; align-items: center; }
</style>
