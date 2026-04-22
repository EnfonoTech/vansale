<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  today,
  startVisit,
  endVisit,
  skipVisit,
  dailyReport,
  type RouteStop,
  type DailyReport,
} from "@/api/route";
import { currentPosition } from "@/features/van/gps";
import { isOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore } from "@/stores/confirm";
import { useRouteVisitStore } from "@/stores/routeVisit";
import Icon from "@/components/Icon.vue";

/**
 * RouteTodayView — post-Apr 22 rewrite.
 *
 * The route system is now "everything tagged to my sales person today"
 * — there is no route plan, no stops table, no recurrence. The driver
 * just sees a live list of their customers and taps start/end/skip/
 * complete per customer.
 *
 * Visit state is keyed by `customer`. The old plan-based identity
 * (`plan_name + stop_idx`) is gone and so is the per-route "Complete
 * Route" button; drivers show up the next day, the list regenerates,
 * and the daily summary is surfaced via its own panel.
 */

const router = useRouter();
const toasts = useToastStore();
const session = useSessionStore();
const confirm = useConfirmStore();
const visit = useRouteVisitStore();

const stops = ref<RouteStop[]>([]);
const salesPerson = ref<string | null>(null);
const visitDate = ref("");
const err = ref("");
const loading = ref(false);
const busy = ref(false);
// Per-stop Complete button spinner. Keyed by customer so concurrent
// taps on different stops don't fight over a single flag.
const stopBusy = ref<Record<string, boolean>>({});
const report = ref<DailyReport | null>(null);
const reporting = ref(false);

async function load() {
  loading.value = true;
  err.value = "";
  try {
    const res = await today();
    stops.value = res.stops;
    salesPerson.value = res.sales_person;
    visitDate.value = res.visit_date;
    // Reconcile: if server says the active visit is done/skipped, drop
    // local state so the "End visit" sheet doesn't dangle.
    if (visit.active) {
      const match = stops.value.find((s) => s.customer === visit.active?.stop.customer);
      if (!match || match.status === "done" || match.status === "skipped") {
        visit.clear();
      }
    }
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function openCustomer(name: string) {
  if (!name) return;
  void router.push({ name: "customer-detail", params: { name } });
}

async function onStart(stop: RouteStop) {
  try {
    // Capture GPS at start so ops can confirm the van was at the
    // customer when the visit began — previous flow only logged
    // lat/lng on End, masking "started across town then drove over".
    if (session.requireLocation) {
      try {
        await currentPosition();
      } catch {
        // Soft-fail: if the user denies or GPS is off, still start the
        // visit rather than blocking van-sales entirely.
      }
    }
    if (isOnline()) await startVisit(stop.customer);
    visit.start(stop);
    toasts.info(`Visit started \u00b7 ${stop.customer_name || stop.customer}`);
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

async function onEnd() {
  if (!visit.active) return;
  busy.value = true;
  err.value = "";
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
    toasts.success(res.queued ? "Visit queued offline" : `Visit logged ${res.name}`);
    visit.clear();
    await load();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}

/**
 * Per-customer "Complete" action. End the visit with no invoice /
 * payment / notes — for when the driver visited but had nothing to
 * transact. Same idempotent end_visit endpoint so Van Visit Log still
 * captures it. Works on pending (virtual start → end in one go) or
 * in_progress.
 */
async function onCompleteStop(stop: RouteStop) {
  const label = stop.customer_name || stop.customer;
  const ok = await confirm.ask({
    title: `Mark ${label} complete?`,
    message: "Closes this stop with no invoice or payment. Use this for courtesy visits or when nothing was transacted.",
    confirmText: "Mark complete",
  });
  if (!ok) return;
  stopBusy.value = { ...stopBusy.value, [stop.customer]: true };
  try {
    if (stop.status === "pending" && isOnline()) {
      try { await startVisit(stop.customer); } catch { /* soft-fail */ }
    }
    await endVisit({
      customer: stop.customer,
      notes: null,
    });
    if (visit.active && visit.active.stop.customer === stop.customer) visit.clear();
    toasts.success(`Completed \u00b7 ${label}`);
    await load();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    stopBusy.value = { ...stopBusy.value, [stop.customer]: false };
  }
}

async function onSkip(stop: RouteStop) {
  const label = stop.customer_name || stop.customer;
  const ok = await confirm.ask({
    title: `Skip ${label}?`,
    message: "Marks this stop as skipped. You can still visit the customer manually.",
    confirmText: "Skip",
    danger: true,
  });
  if (!ok) return;
  try {
    await skipVisit(stop.customer);
    if (visit.active && visit.active.stop.customer === stop.customer) visit.clear();
    toasts.info(`Skipped \u00b7 ${label}`);
    await load();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

async function onShowSummary() {
  reporting.value = true;
  try {
    report.value = await dailyReport();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    reporting.value = false;
  }
}

function closeReport() {
  report.value = null;
}

onMounted(load);

function statusTone(s: string | undefined): string {
  switch (s) {
    case "done": return "success";
    case "in_progress": return "info";
    case "skipped": return "warning";
    default: return "info";
  }
}

function statusIcon(s: string | undefined): "check" | "clock" | "x" | "map-pin" {
  switch (s) {
    case "done": return "check";
    case "in_progress": return "clock";
    case "skipped": return "x";
    default: return "map-pin";
  }
}

const doneCount = computed(() => stops.value.filter((s) => s.status === "done").length);
const pendingCount = computed(() => stops.value.filter((s) => s.status === "pending").length);
const skippedCount = computed(() => stops.value.filter((s) => s.status === "skipped").length);

function fmt(n: number): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(n);
}

const notesModel = computed({
  get: () => visit.active?.notes ?? "",
  set: (v: string) => visit.setNotes(v),
});

// Hero date label — "Wednesday, 22 Apr". The server's timezone can
// differ from the driver's phone (user report 2026-04-22), so we
// format on the client.
const todayLabel = computed(() => {
  const d = visitDate.value ? new Date(visitDate.value + "T00:00:00") : new Date();
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "short",
  });
});
</script>

<template>
  <div class="stack">
    <section class="hero card stack">
      <div class="hero-head">
        <div>
          <span class="muted xsmall">Today \u00b7 {{ todayLabel }}</span>
          <h2 class="hero-date">My customers</h2>
          <p v-if="salesPerson" class="muted xsmall">Sales person: {{ salesPerson }}</p>
        </div>
        <button class="ghost icon-only" @click="load" :disabled="loading" title="Refresh">
          <Icon name="refresh" :size="18" />
        </button>
      </div>
      <div class="hero-pills">
        <div class="stat"><strong>{{ stops.length }}</strong><span class="muted xsmall">Total</span></div>
        <div class="stat" data-tone="success"><strong>{{ doneCount }}</strong><span class="muted xsmall">Done</span></div>
        <div class="stat"><strong>{{ pendingCount }}</strong><span class="muted xsmall">Pending</span></div>
        <div class="stat" data-tone="warning" v-if="skippedCount > 0"><strong>{{ skippedCount }}</strong><span class="muted xsmall">Skipped</span></div>
      </div>
      <button
        v-if="stops.length > 0"
        class="summary-btn"
        :disabled="reporting"
        @click="onShowSummary"
      >
        <Icon name="check" :size="16" />
        <span v-if="reporting">Loading summary…</span>
        <span v-else>Show today's summary</span>
      </button>
    </section>

    <div v-if="loading && stops.length === 0" class="stack">
      <div class="skeleton" style="height:6rem" />
      <div class="skeleton" style="height:3.5rem" />
      <div class="skeleton" style="height:3.5rem" />
    </div>

    <div v-else-if="!salesPerson" class="empty">
      <Icon name="route" :size="32" class="empty-icon" />
      <strong>No sales person mapped</strong>
      <span class="muted">Ask ops to link you to a Sales Person in Vansale Configuration.</span>
    </div>

    <div v-else-if="stops.length === 0" class="empty">
      <Icon name="route" :size="32" class="empty-icon" />
      <strong>No customers assigned yet</strong>
      <span class="muted">Ask ops to assign customers to your sales person via the Van Customer Assignment page.</span>
    </div>

    <p v-if="err" class="error">{{ err }}</p>

    <ul v-if="stops.length" class="stops">
      <li v-for="s in stops" :key="s.customer" class="stop" :data-status="s.status">
        <button
          type="button"
          class="stop-head link"
          @click="openCustomer(s.customer)"
          :aria-label="`Open customer ${s.customer_name || s.customer}`"
        >
          <div class="body">
            <strong class="truncate">{{ s.customer_name || s.customer }}</strong>
            <span class="muted xsmall" v-if="s.mobile_no">{{ s.mobile_no }}</span>
            <span class="muted xsmall" v-if="s.address">{{ s.address }}</span>
          </div>
          <span class="pill" :data-tone="statusTone(s.status)">
            <Icon :name="statusIcon(s.status)" :size="12" />
            {{ s.status }}
          </span>
        </button>
        <div class="stop-actions">
          <button
            v-if="s.status === 'pending' && !visit.hasActive"
            class="start-btn"
            @click="onStart(s)"
          >
            <Icon name="map-pin" :size="16" /> Visit
          </button>
          <button
            v-if="s.status === 'in_progress' && visit.active && visit.active.stop.customer === s.customer"
            class="start-btn end-btn"
            :disabled="busy"
            @click="onEnd"
          >
            <Icon name="check" :size="16" /> {{ busy ? "Ending…" : "End visit" }}
          </button>
          <!-- Mark-complete button — available on pending and in_progress
               stops that aren't the driver's active visit. -->
          <button
            v-if="(s.status === 'pending' || s.status === 'in_progress') && (!visit.active || visit.active.stop.customer !== s.customer)"
            class="complete-stop-btn"
            :disabled="!!stopBusy[s.customer]"
            @click="onCompleteStop(s)"
          >
            <Icon name="check" :size="14" />
            {{ stopBusy[s.customer] ? "…" : "Complete" }}
          </button>
          <button
            v-if="s.status === 'pending' || s.status === 'in_progress'"
            class="ghost small warning"
            @click="onSkip(s)"
            :title="s.status === 'in_progress' ? 'Clear a stuck visit (marks the stop as skipped)' : 'Skip this customer'"
          >
            <Icon name="x" :size="14" /> Skip
          </button>
          <button class="ghost small" @click="openCustomer(s.customer)">
            <Icon name="customer" :size="14" /> Open
          </button>
        </div>
      </li>
    </ul>

    <!-- On-demand daily summary. -->
    <section v-if="report" class="summary card stack">
      <div class="summary-head">
        <Icon name="check" :size="22" />
        <div>
          <span class="muted xsmall">Today's summary</span>
          <strong>{{ report.plan_date }}</strong>
        </div>
      </div>
      <dl class="summary-grid">
        <div><dt class="muted xsmall">Stops</dt><dd>{{ report.stop_count }}</dd></div>
        <div><dt class="muted xsmall">Visits</dt><dd>{{ report.visits }}</dd></div>
        <div><dt class="muted xsmall">Sales</dt><dd>{{ session.currency }} {{ fmt(report.sales) }}</dd></div>
        <div><dt class="muted xsmall">Collections</dt><dd>{{ session.currency }} {{ fmt(report.collections) }}</dd></div>
        <div v-if="report.returns > 0"><dt class="muted xsmall">Returns</dt><dd>{{ session.currency }} {{ fmt(report.returns) }}</dd></div>
      </dl>
      <button class="submit" @click="closeReport">
        <Icon name="check" :size="18" /> Close
      </button>
    </section>

    <section v-if="visit.active" class="active-card card stack">
      <div class="active-head">
        <Icon name="map-pin" :size="20" />
        <div>
          <span class="muted xsmall">Active visit</span>
          <strong>{{ visit.active.stop.customer_name || visit.active.stop.customer }}</strong>
        </div>
      </div>
      <p class="muted small">
        Create invoice or collect payment — visit stays active until you end it.
      </p>
      <label class="field">
        <span class="label">Notes</span>
        <textarea v-model="notesModel" rows="2" placeholder="Observation…" />
      </label>
      <div class="row actions">
        <button class="ghost" @click="router.push({ name: 'invoice-new' })">
          <Icon name="invoice" :size="16" /> Invoice
        </button>
        <button class="ghost" @click="router.push({ name: 'payment-new' })">
          <Icon name="payment" :size="16" /> Payment
        </button>
      </div>
      <button class="submit" :disabled="busy" @click="onEnd">
        <Icon name="check" :size="18" />
        {{ busy ? "Closing…" : "End visit" }}
      </button>
    </section>
  </div>
</template>

<style scoped>
.hero {
  background: linear-gradient(135deg, color-mix(in srgb, var(--primary) 8%, var(--surface)) 0%, var(--surface) 100%);
}
.hero-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.hero-date { margin: 0.15rem 0 0; font-size: var(--text-lg); }

.hero-pills { display: grid; grid-template-columns: repeat(auto-fit, minmax(4.5rem, 1fr)); gap: 0.5rem; }
.stat {
  background: var(--surface-muted);
  padding: 0.6rem 0.5rem;
  border-radius: var(--radius-sm);
  display: flex; flex-direction: column; align-items: center; gap: 0.15rem;
}
.stat strong { font-size: var(--text-lg); font-variant-numeric: tabular-nums; }
.stat[data-tone="success"] strong { color: var(--success); }
.stat[data-tone="warning"] strong { color: var(--warning, #d97706); }

.stops { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.stop {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 0.75rem 0.85rem;
  box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 0.5rem;
  border-inline-start: 3px solid transparent;
  transition: border-color var(--dur-fast) var(--ease);
}
.stop[data-status="done"] { opacity: 0.75; }
.stop[data-status="in_progress"] { border-inline-start-color: var(--primary); }

.stop-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; }
.stop-head.link {
  all: unset;
  cursor: pointer;
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}
.stop-head.link:active { opacity: 0.7; }
.body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.stop-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.start-btn { min-height: 2.25rem; padding: 0.4rem 0.75rem; font-size: var(--text-sm); }
.end-btn { background: var(--success, #16a34a); color: white; }
.end-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.active-card {
  background: linear-gradient(135deg, var(--primary-soft) 0%, var(--surface) 100%);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
}

.summary-btn {
  margin-top: 0.25rem;
  min-height: 2.75rem;
  width: 100%;
  background: var(--primary-soft, color-mix(in srgb, var(--primary) 15%, transparent));
  color: var(--primary);
  border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  border-radius: var(--radius-sm);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}
.summary-btn:disabled { opacity: 0.55; cursor: not-allowed; }

.complete-stop-btn {
  min-height: 2.25rem;
  padding: 0.35rem 0.7rem;
  font-size: var(--text-sm);
  font-weight: 600;
  background: color-mix(in srgb, var(--success, #16a34a) 12%, var(--surface));
  color: var(--success, #16a34a);
  border: 1px solid color-mix(in srgb, var(--success, #16a34a) 45%, transparent);
  border-radius: var(--radius-sm);
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
}
.complete-stop-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.complete-stop-btn:not(:disabled):hover {
  background: var(--success, #16a34a);
  color: #fff;
}

.summary {
  background: linear-gradient(135deg,
    color-mix(in srgb, var(--success, #16a34a) 10%, var(--surface)) 0%,
    var(--surface) 100%);
}
.summary-head { display: flex; align-items: center; gap: 0.6rem; color: var(--success, #16a34a); }
.summary-head strong { display: block; color: var(--text); font-size: var(--text-lg); }
.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.6rem;
  margin: 0;
}
.summary-grid > div {
  background: var(--surface-muted);
  padding: 0.6rem 0.7rem;
  border-radius: var(--radius-sm);
}
.summary-grid dt { margin: 0 0 0.1rem; }
.summary-grid dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
.active-head { display: flex; align-items: center; gap: 0.6rem; color: var(--primary); }
.active-head strong { display: block; color: var(--text); }

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.submit { min-height: 3rem; }
</style>
