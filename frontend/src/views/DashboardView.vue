<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useSessionStore } from "@/stores/session";
import { logout } from "@/api/auth";
import {
  todaySales,
  todayCollection,
  recentActivity,
  type TodaySales,
  type TodayCollection,
  type ActivityRow,
} from "@/api/dashboard";
import { NATIVE_VERSION } from "@/app/native-version";
import { isNative } from "@/app/platform";

const router = useRouter();
const session = useSessionStore();
const { t } = useI18n();

const sales = ref<TodaySales | null>(null);
const collection = ref<TodayCollection | null>(null);
const activity = ref<ActivityRow[]>([]);
const loadErr = ref("");

async function load() {
  loadErr.value = "";
  try {
    const [a, b, c] = await Promise.all([todaySales(), todayCollection(), recentActivity(10)]);
    sales.value = a;
    collection.value = b;
    activity.value = c;
  } catch (err) {
    loadErr.value = err instanceof Error ? err.message : String(err);
  }
}

onMounted(load);

function fmt(n: number | undefined): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(n ?? 0);
}

async function onLogout() {
  try { await logout(); } finally { session.logout(); await router.replace({ name: "login" }); }
}
</script>

<template>
  <section class="stack">
    <header class="card stack" style="gap: 0.25rem">
      <h1 style="margin: 0">
        {{ t("dashboard.welcome", { name: session.fullName ?? session.user ?? "" }) }}
      </h1>
      <p class="muted small">
        {{ isNative() ? t("dashboard.env_native") : t("dashboard.env_web") }} ·
        {{ t("dashboard.version", { v: NATIVE_VERSION }) }}
      </p>
    </header>

    <p v-if="loadErr" class="error">{{ loadErr }}</p>

    <div class="tiles">
      <div class="tile">
        <span class="muted small">Today's sales</span>
        <strong>{{ fmt(sales?.amount) }}</strong>
        <span class="muted small">{{ sales?.count ?? 0 }} invoice{{ sales?.count === 1 ? "" : "s" }}</span>
      </div>
      <div class="tile">
        <span class="muted small">Today's collection</span>
        <strong>{{ fmt(collection?.amount) }}</strong>
        <span class="muted small">
          {{ collection?.by_mode?.map((m) => `${m.mode}: ${fmt(m.amount)}`).join(" · ") || "—" }}
        </span>
      </div>
      <div class="tile">
        <span class="muted small">Returned today</span>
        <strong>{{ fmt(sales?.returned) }}</strong>
      </div>
    </div>

    <nav class="actions">
      <button @click="router.push({ name: 'invoice-new' })">New invoice</button>
      <button @click="router.push({ name: 'payment-new' })">Collect payment</button>
      <button class="ghost" @click="router.push({ name: 'customers' })">Customers</button>
      <button class="ghost" @click="router.push({ name: 'invoices' })">Invoices</button>
      <button class="ghost" @click="router.push({ name: 'route-today' })">Today's route</button>
      <button class="ghost" @click="router.push({ name: 'van-stock' })">Van stock</button>
    </nav>

    <section class="card stack">
      <h2 style="margin: 0 0 0.25rem">Recent activity</h2>
      <p v-if="activity.length === 0" class="muted">No activity yet.</p>
      <ul class="activity" v-else>
        <li v-for="row in activity" :key="`${row.kind}:${row.name}`">
          <span class="kind" :data-kind="row.kind">{{ row.kind }}</span>
          <span class="who">{{ row.party }}</span>
          <span class="amt">{{ fmt(row.amount) }}</span>
          <span class="when muted small">{{ row.posting_date }}</span>
        </li>
      </ul>
    </section>

    <button class="ghost" style="align-self: flex-start" @click="onLogout">
      {{ t("nav.logout") }}
    </button>
  </section>
</template>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 0.65rem; }
.tile {
  background: var(--surface);
  padding: 0.85rem;
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  box-shadow: var(--shadow-sm);
}
.tile strong { font-size: 1.25rem; }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.small { font-size: 0.78rem; }
.activity { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.activity li {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.35rem 0.7rem;
  align-items: baseline;
}
.kind {
  grid-column: 1;
  font-size: 0.7rem;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.1);
  color: var(--primary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.kind[data-kind="payment"] { background: rgba(22, 163, 74, 0.12); color: var(--success); }
.who { grid-column: 2; }
.amt { grid-column: 3; font-weight: 600; }
.when { grid-column: 2 / span 2; }
</style>
