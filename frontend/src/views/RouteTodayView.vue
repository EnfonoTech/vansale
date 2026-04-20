<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { today, startVisit, endVisit, type RouteStop } from "@/api/route";
import { currentPosition } from "@/features/van/gps";
import { resolveSignatureToRealUrl } from "@/offline/signatures";
import { isOnline } from "@/app/online";
import { useToastStore } from "@/stores/toasts";
import SignaturePad from "@/components/SignaturePad.vue";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const toasts = useToastStore();

const plan = ref<Record<string, string | null | undefined> | null>(null);
const stops = ref<RouteStop[]>([]);
const err = ref("");
const loading = ref(false);

const active = ref<RouteStop | null>(null);
const signaturePlaceholder = ref<string | null>(null);
const notes = ref("");
const busy = ref(false);

async function load() {
  loading.value = true;
  err.value = "";
  try {
    const res = await today();
    plan.value = res.plan as Record<string, string | null | undefined> | null;
    stops.value = res.stops;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function onStart(stop: RouteStop) {
  if (!plan.value?.name) return;
  try {
    if (isOnline()) await startVisit(plan.value.name, stop.idx);
    active.value = { ...stop, status: "in_progress" };
    signaturePlaceholder.value = null;
    notes.value = "";
    toasts.info(`Visit started · ${stop.customer}`);
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
}

async function onEnd() {
  if (!plan.value?.name || !active.value) return;
  busy.value = true;
  err.value = "";
  try {
    const geo = await currentPosition();
    let sigUrl: string | null = null;
    if (signaturePlaceholder.value) {
      if (isOnline()) {
        try { sigUrl = await resolveSignatureToRealUrl(signaturePlaceholder.value); }
        catch { sigUrl = signaturePlaceholder.value; }
      } else {
        sigUrl = signaturePlaceholder.value;
      }
    }
    const res = await endVisit({
      plan_name: plan.value.name as string,
      stop_idx: active.value.idx,
      lat: geo?.lat,
      lng: geo?.lng,
      signature_file: sigUrl,
      notes: notes.value || null,
    });
    toasts.success(res.queued ? "Visit queued offline" : `Visit logged ${res.name}`);
    active.value = null;
    await load();
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
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
        <div class="stop-head">
          <div class="body">
            <strong class="truncate">{{ s.customer }}</strong>
            <span class="muted xsmall" v-if="s.address">{{ s.address }}</span>
            <span class="muted xsmall" v-if="s.planned_time">{{ s.planned_time }}</span>
          </div>
          <span class="pill" :data-tone="statusTone(s.status)">
            <Icon :name="statusIcon(s.status)" :size="12" />
            {{ s.status }}
          </span>
        </div>
        <button v-if="s.status === 'pending'" class="start-btn" @click="onStart(s)">
          <Icon name="map-pin" :size="16" /> Start visit
        </button>
      </li>
    </ul>

    <section v-if="active" class="active-card card stack">
      <div class="active-head">
        <Icon name="map-pin" :size="20" />
        <div>
          <span class="muted xsmall">Active visit</span>
          <strong>{{ active.customer }}</strong>
        </div>
      </div>
      <p class="muted small">
        Create invoice or collect payment from dashboard — visit stays active.
      </p>
      <label class="field">
        <span class="label">Notes</span>
        <textarea v-model="notes" rows="2" placeholder="Observation…" />
      </label>
      <SignaturePad v-model="signaturePlaceholder" />
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
.body { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.start-btn { align-self: flex-start; min-height: 2.25rem; padding: 0.4rem 0.75rem; font-size: var(--text-sm); }

.active-card {
  background: linear-gradient(135deg, var(--primary-soft) 0%, var(--surface) 100%);
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
.active-head { display: flex; align-items: center; gap: 0.6rem; color: var(--primary); }
.active-head strong { display: block; color: var(--text); }

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.submit { min-height: 3rem; }
</style>
