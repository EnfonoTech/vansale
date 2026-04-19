<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { today, startVisit, endVisit, type RouteStop } from "@/api/route";
import { currentPosition } from "@/features/van/gps";
import { resolveSignatureToRealUrl } from "@/offline/signatures";
import { isOnline } from "@/app/online";
import SignaturePad from "@/components/SignaturePad.vue";

const router = useRouter();

const plan = ref<Record<string, string | null | undefined> | null>(null);
const stops = ref<RouteStop[]>([]);
const err = ref("");
const info = ref("");

const active = ref<RouteStop | null>(null);
const signaturePlaceholder = ref<string | null>(null);
const notes = ref("");
const busy = ref(false);

async function load() {
  err.value = "";
  try {
    const res = await today();
    plan.value = res.plan as Record<string, string | null | undefined> | null;
    stops.value = res.stops;
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  }
}

async function onStart(stop: RouteStop) {
  if (!plan.value?.name) return;
  try {
    if (isOnline()) await startVisit(plan.value.name, stop.idx);
    active.value = { ...stop, status: "in_progress" };
    signaturePlaceholder.value = null;
    notes.value = "";
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
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
      // Upload signature now if online; drain handles it otherwise.
      if (isOnline()) {
        try { sigUrl = await resolveSignatureToRealUrl(signaturePlaceholder.value); }
        catch { sigUrl = signaturePlaceholder.value; } // fall through — drain will retry
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
    info.value = res.queued ? "Visit queued offline" : `Visit logged ${res.name}`;
    active.value = null;
    await load();
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="stack">
    <h1>Today's route</h1>
    <p v-if="err" class="error">{{ err }}</p>
    <p v-if="info" class="success">{{ info }}</p>

    <section v-if="plan" class="card stack">
      <strong>{{ plan.plan_date }}</strong>
      <p class="muted small">{{ plan.notes || "" }}</p>
    </section>
    <p v-else class="muted">No route plan for today.</p>

    <ul class="stops">
      <li v-for="s in stops" :key="s.name" class="stop" :data-status="s.status">
        <div class="head">
          <strong>{{ s.customer }}</strong>
          <span class="muted small">{{ s.planned_time || "" }} · {{ s.status }}</span>
        </div>
        <p class="muted small" v-if="s.address">{{ s.address }}</p>
        <div class="row" v-if="s.status === 'pending'">
          <button @click="onStart(s)">Start visit</button>
        </div>
      </li>
    </ul>

    <section v-if="active" class="card stack">
      <h2 style="margin: 0">Active visit · {{ active.customer }}</h2>
      <p class="muted small">
        Create an invoice / collect payment from the dashboard — the visit stays active.
      </p>
      <label class="stack" style="gap: 0.3rem">
        <span class="muted">Notes</span>
        <textarea v-model="notes" rows="2" />
      </label>
      <SignaturePad v-model="signaturePlaceholder" />
      <button :disabled="busy" @click="onEnd">{{ busy ? "Closing…" : "End visit" }}</button>
      <button class="ghost" @click="router.push({ name: 'invoice-new' })">New invoice</button>
      <button class="ghost" @click="router.push({ name: 'payment-new' })">Collect payment</button>
    </section>
  </section>
</template>

<style scoped>
.stops { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.stop { background: var(--surface); padding: 0.75rem; border-radius: var(--radius); box-shadow: var(--shadow-sm); display: flex; flex-direction: column; gap: 0.35rem; }
.stop[data-status="done"] { opacity: 0.7; }
.stop[data-status="in_progress"] { border-left: 3px solid var(--primary); }
.head { display: flex; justify-content: space-between; gap: 0.5rem; }
.small { font-size: 0.8rem; }
.success { color: var(--success); font-size: 0.9rem; }
</style>
