<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { customerLabel, detail, type CustomerDetail } from "@/api/customer";
import { listMine as listInvoices } from "@/api/invoice";
import { endVisit } from "@/api/route";
import { currentPosition } from "@/features/van/gps";
import { useSessionStore } from "@/stores/session";
import { useRouteVisitStore } from "@/stores/routeVisit";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const visit = useRouteVisitStore();
const toasts = useToastStore();

const customer = ref<CustomerDetail | null>(null);
const invoices = ref<Array<Record<string, unknown>>>([]);
const loading = ref(false);
const err = ref("");
const ending = ref(false);

const customerName = String(route.params.name ?? "");

// True when this detail page is for the customer currently checked-in on
// the route. We show an inline End-visit card so the user never has to
// back out through multiple screens to close the visit (user complaint
// from v1.0.12 — once a customer was opened from the route, the only
// way to end the visit was to navigate all the way back to RouteToday).
const activeForThisCustomer = computed(
  () => visit.hasActive && visit.activeCustomer === customerName,
);

function editContact() {
  if (!customer.value) return;
  void router.push({ name: "customer-contact", params: { name: customer.value.name } });
}

function editAddress(address?: string) {
  if (!customer.value) return;
  void router.push({
    name: "customer-address",
    params: { name: customer.value.name, address: address ?? "" },
  });
}

async function load() {
  if (!customerName) return;
  loading.value = true;
  err.value = "";
  try {
    customer.value = await detail(customerName);
    invoices.value = await listInvoices(10, customerName);
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: unknown): string {
  const num = typeof n === "number" ? n : Number(n) || 0;
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(num);
}

function newInvoice() {
  void router.push({ name: "invoice-new", query: { customer: customerName } });
}
function newPayment() {
  void router.push({ name: "payment-new", query: { customer: customerName } });
}
function callMobile() {
  if (customer.value?.mobile_no) window.location.href = `tel:${customer.value.mobile_no}`;
}
function openInvoice(name: string) {
  void router.push({ name: "invoice-detail", params: { name } });
}
function printStatement() {
  // Navigate in-app rather than `window.open`. On native the WebView lives at
  // `https://localhost`, so a relative `/api/method/...` URL doesn't cross
  // over to the Frappe site. The StatementView fetches through `apiCall`
  // (same auth path as everything else) and offers its own Print button.
  void router.push({ name: "customer-statement", params: { name: customerName } });
}

async function onEndVisit() {
  if (!visit.active || ending.value) return;
  ending.value = true;
  try {
    let lat: number | undefined;
    let lng: number | undefined;
    if (session.requireLocation) {
      const geo = await currentPosition();
      lat = geo?.lat;
      lng = geo?.lng;
    }
    const res = await endVisit({
      customer: visit.active.stop.customer,
      lat,
      lng,
      notes: visit.active.notes || null,
    });
    toasts.success(res.queued ? "Visit queued offline" : `Visit closed · ${res.name}`);
    visit.clear();
    void router.replace({ name: "route-today" });
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    ending.value = false;
  }
}
</script>

<template>
  <div class="stack">
    <div v-if="loading && !customer" class="stack">
      <div class="skeleton" style="height:4rem" />
      <div class="skeleton" style="height:8rem" />
    </div>
    <p v-if="err" class="error">{{ err }}</p>

    <template v-if="customer">
      <section v-if="activeForThisCustomer" class="card stack visit-banner">
        <div class="visit-head">
          <Icon name="map-pin" :size="18" />
          <div>
            <span class="muted xsmall">Active visit</span>
            <strong>{{ customerLabel(customer) }}</strong>
          </div>
        </div>
        <button class="submit danger" :disabled="ending" @click="onEndVisit">
          <Icon name="check" :size="18" />
          {{ ending ? "Closing…" : "End visit" }}
        </button>
      </section>

      <section class="card stack">
        <div class="header-row">
          <span class="avatar">
            {{ customerLabel(customer).split(/\s+/).slice(0,2).map(s=>s.charAt(0).toUpperCase()).join("") || "?" }}
          </span>
          <div class="title-block">
            <h2 class="truncate" style="margin:0">{{ customerLabel(customer) }}</h2>
            <div v-if="customer.secondary_name" class="muted small truncate">{{ customer.secondary_name }}</div>
          </div>
        </div>
        <div class="meta-grid">
          <div v-if="customer.mobile_no" class="meta-item" @click="callMobile">
            <Icon name="phone" :size="16" />
            <span>{{ customer.mobile_no }}</span>
          </div>
          <div v-if="customer.territory" class="meta-item">
            <Icon name="map-pin" :size="16" />
            <span>{{ customer.territory }}</span>
          </div>
          <div v-if="customer.email_id" class="meta-item">
            <Icon name="user" :size="16" />
            <span>{{ customer.email_id }}</span>
          </div>
          <div v-if="customer.vat_number || customer.tax_id" class="meta-item">
            <Icon name="tag" :size="16" />
            <span>VAT {{ customer.vat_number || customer.tax_id }}</span>
          </div>
          <button type="button" class="link-btn" @click="editContact">
            <Icon name="edit" :size="14" />
            {{ customer.mobile_no || customer.email_id ? "Edit contact" : "Add phone / email" }}
          </button>
        </div>
      </section>

      <section class="card outstanding" :data-positive="customer.outstanding > 0">
        <span class="muted xsmall">Outstanding</span>
        <strong><SarSymbol :code="session.currency" />{{ fmt(customer.outstanding) }}</strong>
      </section>
      <p v-if="(customer.pending ?? 0) > 0" class="muted xsmall pending-note">
        <SarSymbol :code="session.currency" />{{ fmt(customer.pending ?? 0) }} collected, awaiting office approval
      </p>

      <section class="actions-row">
        <button class="action-btn primary" @click="newInvoice">
          <Icon name="invoice" :size="18" /> Invoice
        </button>
        <button class="action-btn success" @click="newPayment">
          <Icon name="payment" :size="18" /> Payment
        </button>
        <button class="action-btn ghost" @click="printStatement">
          <Icon name="receipt" :size="18" /> Statement
        </button>
      </section>

      <section class="card stack">
        <div class="addr-head">
          <h3 style="margin:0 0 0.25rem">Addresses</h3>
          <button type="button" class="link-btn" @click="editAddress()">
            <Icon name="plus" :size="14" /> Add
          </button>
        </div>
        <p v-if="customer.addresses.length === 0" class="muted small">No address yet.</p>
        <button
          v-for="(a, i) in customer.addresses"
          :key="i"
          type="button"
          class="address"
          @click="editAddress(a.name)"
        >
          <Icon name="map-pin" :size="16" class="addr-ic" />
          <div class="addr-body">
            <div>
              <span v-if="a.building_number" class="mono">{{ a.building_number }}</span>
              {{ [a.address_line1, a.address_line2].filter(Boolean).join(", ") }}
            </div>
            <div class="muted small">
              {{ [a.district, a.city, a.pincode, a.state, a.country].filter(Boolean).join(", ") }}
            </div>
            <div v-if="a.additional_number" class="muted xsmall">Additional no. {{ a.additional_number }}</div>
            <div v-if="a.phone" class="muted xsmall">{{ a.phone }}</div>
          </div>
          <Icon name="edit" :size="16" class="addr-edit" />
        </button>
      </section>

      <section class="card stack">
        <h3 style="margin:0 0 0.25rem">Recent invoices</h3>
        <div v-if="invoices.length === 0" class="empty" style="padding:1rem 0">
          <Icon name="invoice" :size="28" class="empty-icon" />
          <span class="muted small">No invoices yet.</span>
        </div>
        <ul v-else class="inv-list">
          <li v-for="r in invoices" :key="String(r.name)">
            <button type="button" class="inv-row" @click="openInvoice(String(r.name))">
              <div>
                <strong>{{ r.name }}</strong>
                <div class="muted xsmall">{{ r.posting_date }} · {{ r.status }}</div>
              </div>
              <strong>{{ fmt(r.grand_total) }}</strong>
            </button>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.header-row { display: flex; align-items: center; gap: 0.75rem; }
.title-block { min-width: 0; display: flex; flex-direction: column; gap: 0.1rem; }
.avatar {
  width: 3rem; height: 3rem;
  border-radius: var(--radius-pill);
  display: grid; place-items: center;
  background: var(--primary-soft); color: var(--primary);
  font-weight: 700; font-size: var(--text-lg);
}
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.meta-grid { display: flex; flex-direction: column; gap: 0.4rem; }
.meta-item {
  display: flex; align-items: center; gap: 0.5rem;
  font-size: var(--text-sm); color: var(--text-muted);
}
.meta-item svg { color: var(--text-faint); flex-shrink: 0; }

.outstanding {
  display: flex; justify-content: space-between; align-items: baseline;
  background: var(--surface-sunk);
}
.outstanding[data-positive="true"] { background: var(--warning-soft); color: var(--warning); }
.outstanding strong { font-size: var(--text-xl); font-variant-numeric: tabular-nums; }

.actions-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.5rem; }
.action-btn { min-height: 3rem; font-size: var(--text-sm); padding: 0 0.4rem; }
.action-btn.success { background: var(--success); }
.action-btn.ghost { background: var(--surface-muted); color: var(--text); }

.address {
  display: flex; gap: 0.5rem; padding: 0.5rem 0;
  border-top: 1px solid var(--border);
}
.address:first-of-type { border-top: none; padding-top: 0; }
.addr-head { display: flex; justify-content: space-between; align-items: center; }
.link-btn {
  all: unset; cursor: pointer; color: var(--primary);
  font-size: var(--text-xs); font-weight: 600;
  display: inline-flex; align-items: center; gap: 0.25rem;
}
button.address {
  all: unset; cursor: pointer; box-sizing: border-box; width: 100%;
  display: flex; gap: 0.5rem; padding: 0.5rem 0; border-top: 1px solid var(--border);
}
.addr-body { flex: 1; min-width: 0; }
.addr-edit { color: var(--text-muted); align-self: center; }
.addr-ic { color: var(--text-faint); flex-shrink: 0; margin-top: 0.15rem; }

.inv-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0; }
.inv-row {
  all: unset; cursor: pointer; width: 100%;
  display: flex; justify-content: space-between; align-items: center;
  padding: 0.55rem 0.25rem;
  border-top: 1px solid var(--border);
  transition: background var(--dur-fast) var(--ease);
}
.inv-row:first-of-type { border-top: none; }
.inv-row:active { background: var(--surface-muted); }

.visit-banner {
  background: linear-gradient(135deg, var(--primary-soft) 0%, var(--surface) 100%);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
.visit-head { display: flex; align-items: center; gap: 0.6rem; color: var(--primary); }
.visit-head strong { display: block; color: var(--text); }
.submit.danger { background: var(--success); min-height: 3rem; }
</style>
