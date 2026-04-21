<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { today, startVisit, endVisit, skipVisit, dailyReport, type RouteStop, type DailyReport } from "@/api/route";
import { currentPosition } from "@/features/van/gps";
import { isOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import { useConfirmStore } from "@/stores/confirm";
import { useRouteVisitStore } from "@/stores/routeVisit";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const toasts = useToastStore();
const session = useSessionStore();
const confirm = useConfirmStore();
const visit = useRouteVisitStore();

const plan = ref<Record<string, string | null | undefined> | null>(null);
const stops = ref<RouteStop[]>([]);
const err = ref("");
const loading = ref(false);
const busy = ref(false);

async function load() {
  loading.value = true;
  err.value = "";
  try {
    const res = await today();
    plan.value = res.plan as Record<string, string | null | undefined> | null;
    stops.value = res.stops;
    // Reconcile: if server marked the active visit as done/skipped, drop local state.
    if (visit.active && plan.value?.name) {
      const match = stops.value.find((s) => s.idx === visit.active?.stop.idx);
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
  if (!plan.value?.name) return;
  try {
    // Capture GPS at start too so ops can see the van was actually at the
    // customer when the visit began — prior flow only recorded lat/lng on
    // End, which meant a "start from across town, drive later" looked
    // identical to "started at the stop". requireLocation gates the ask.
    if (session.requireLocation) {
      try {
        await currentPosition();
      } catch {
        // Soft-fail: if the user denies or GPS is off, still start the
        // visit rather than blocking van-sales entirely.
      }
    }
    if (isOnline()) await startVisit(plan.value.name, stop.idx);
    visit.start(plan.value.name as string, stop);
    toasts.info(`Visit started · ${stop.customer}`);
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
      plan_name: visit.active.planName,
      stop_idx: visit.active.stop.idx,
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

async function onSkip(stop: RouteStop) {
  if (!plan.value?.name) return;
  // Confirm destructive action — especially important when unsticking a
  // stop left hanging from a prior session. Don't want an accidental tap
  // to wipe a real in-flight visit.
  const ok = await confirm.ask({
    title: `Skip ${stop.customer}?`,
    message: "Marks this stop as skipped. You can still visit the customer manually.",
    confirmText: "Skip",
    danger: true,
  });
  if (!ok) return;
  try {
    await skipVisit(plan.value.name, stop.idx);
    if (visit.active && visit.active.stop.idx === stop.idx) visit.clear();
    toasts.info(`Skipped · ${stop.customer}`);
    await load();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
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
const inProgressCount = computed(() => stops.value.filter((s) => s.status === "in_progress").length);

// "Complete Route" is now always surfaced once a plan exists — the v1.0.18
// build gated it on every-stop-resolved, and multiple drivers reported
// they couldn't find the button because pendingCount never hit 0 (they
// don't skip non-visits, they just leave them). Always-visible with an
// early-close confirm matches the mental model of "I'm done for today,
// here's my summary". The confirm tells them exactly how many are open.
const unresolvedCount = computed(() =>
  pendingCount.value + inProgressCount.value,
);
const canCompleteRoute = computed(() =>
  stops.value.length > 0 && !visit.hasActive,
);

const report = ref<DailyReport | null>(null);
const reporting = ref(false);
const reportErr = ref("");

async function onCompleteRoute() {
  if (!plan.value?.name || !canCompleteRoute.value) return;
  const hasUnresolved = unresolvedCount.value > 0;
  const ok = await confirm.ask({
    title: hasUnresolved ? "Close route now?" : "Complete today's route?",
    message: hasUnresolved
      ? `${unresolvedCount.value} of ${stops.value.length} stops still open (${doneCount.value} done, ${skippedCount.value} skipped). Close anyway and view summary?`
      : `You've handled all ${stops.value.length} stops (${doneCount.value} done, ${skippedCount.value} skipped). View your daily summary?`,
    confirmText: hasUnresolved ? "Close anyway" : "Complete",
    danger: hasUnresolved,
  });
  if (!ok) return;
  reporting.value = true;
  reportErr.value = "";
  try {
    report.value = await dailyReport(String(plan.value.plan_date ?? ""));
    toasts.success("Route completed — nice work!");
  } catch (e) {
    reportErr.value = e instanceof Error ? e.message : String(e);
  } finally {
    reporting.value = false;
  }
}

function closeReport() {
  report.value = null;
  void router.replace({ name: "dashboard" });
}

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
</script>

<template>
  <div class="stack">
    <section v-if="plan" class="hero card stack">
      <div class="hero-head">
        <div>
          <span class="muted xsmall">Route plan</span>
          <h2 class="hero-date">{{ plan.plan_date }}</h2>
          <p v-if="plan.notes" class="muted small">{{ plan.notes }}</p>
        </div>
        <button class="ghost icon-only" @click="load" :disabled="loading" title="Refresh">
          <Icon name="refresh" :size="18" />
        </button>
      </div>
      <div class="hero-pills">
        <div class="stat"><strong>{{ stops.length }}</strong><span class="muted xsmall">Stops</span></div>
        <div class="stat" data-tone="success"><strong>{{ doneCount }}</strong><span class="muted xsmall">Done</span></div>
        <div class="stat"><strong>{{ pendingCount }}</strong><span class="muted xsmall">Pending</span></div>
      </div>
      <!--
        Always-visible Complete Route button. The v1.0.18 build gated this
        below the list so drivers who don't skip non-visits never saw it.
        Keep it here in the hero — disabled only while a visit is actively
        open (finish that first), never hidden. Label is "Close early" when
        stops remain so the driver knows what they're confirming.
      -->
      <button
        v-if="stops.length > 0 && !report"
        class="complete-btn"
        :disabled="reporting || visit.hasActive"
        @click="onCompleteRoute"
        :class="{ 'is-partial': unresolvedCount > 0 }"
      >
        <Icon name="check" :size="16" />
        <span v-if="visit.hasActive">End active visit first</span>
        <span v-else-if="reporting">Wrapping up…</span>
        <span v-else-if="unresolvedCount > 0">Close route ({{ unresolvedCount }} open)</span>
        <span v-else>Complete route</span>
      </button>
    </section>

    <div v-else-if="loading" class="stack">
      <div class="skeleton" style="height:6rem" />
      <div class="skeleton" style="height:3.5rem" />
      <div class="skeleton" style="height:3.5rem" />
    </div>

    <div v-else class="empty">
      <Icon name="route" :size="32" class="empty-icon" />
      <strong>No plan for today</strong>
      <span class="muted">Ask ops to assign a route plan.</span>
    </div>

    <p v-if="err" class="error">{{ err }}</p>

    <ul v-if="stops.length" class="stops">
      <li v-for="s in stops" :key="s.name" class="stop" :data-status="s.status">
        <button
          type="button"
          class="stop-head link"
          @click="openCustomer(s.customer)"
          :aria-label="`Open customer ${s.customer}`"
        >
          <div class="body">
            <strong class="truncate">{{ s.customer }}</strong>
            <span class="muted xsmall" v-if="s.address">{{ s.address }}</span>
            <span class="muted xsmall" v-if="s.planned_time">{{ s.planned_time }}</span>
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
            <Icon name="map-pin" :size="16" /> Start visit
          </button>
          <!--
            Active stop (in_progress AND matches this device's active visit)
            gets an inline "End visit" button — the 2026-04-21 feedback was
            "where is the option to complete a customer in route, you've
            added skip what is this". Previously the End button was buried
            in the floating active-card below the list; inline matches the
            mental model of "close out this stop in-place".
          -->
          <button
            v-if="s.status === 'in_progress' && visit.active && visit.active.stop.idx === s.idx"
            class="start-btn end-btn"
            :disabled="busy"
            @click="onEnd"
          >
            <Icon name="check" :size="16" /> {{ busy ? "Ending…" : "End visit" }}
          </button>
          <button
            v-if="s.status === 'in_progress' && (!visit.active || visit.active.stop.idx !== s.idx)"
            class="ghost small warning"
            @click="onSkip(s)"
            title="Clear a stuck visit (marks the stop as skipped)"
          >
            <Icon name="x" :size="14" /> Skip
          </button>
          <button class="ghost small" @click="openCustomer(s.customer)">
            <Icon name="customer" :size="14" /> Open
          </button>
        </div>
      </li>
    </ul>

    <p v-if="reportErr" class="error">{{ reportErr }}</p>

    <!-- Inline daily summary after Complete Route succeeds. -->
    <section v-if="report" class="summary card stack">
      <div class="summary-head">
        <Icon name="check" :size="22" />
        <div>
          <span class="muted xsmall">Daily summary</span>
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
        <Icon name="check" :size="18" /> Done
      </button>
    </section>

    <section v-if="visit.active" class="active-card card stack">
      <div class="active-head">
        <Icon name="map-pin" :size="20" />
        <div>
          <span class="muted xsmall">Active visit</span>
          <strong>{{ visit.active.stop.customer }}</strong>
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

.hero-pills { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }
.stat {
  background: var(--surface-muted);
  padding: 0.6rem 0.5rem;
  border-radius: var(--radius-sm);
  display: flex; flex-direction: column; align-items: center; gap: 0.15rem;
}
.stat strong { font-size: var(--text-lg); font-variant-numeric: tabular-nums; }
.stat[data-tone="success"] strong { color: var(--success); }

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

.complete-btn {
  margin-top: 0.25rem;
  min-height: 2.75rem;
  width: 100%;
  background: var(--success, #16a34a);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}
.complete-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.complete-btn.is-partial { background: color-mix(in srgb, var(--warning, #d97706) 85%, var(--success, #16a34a)); }

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
