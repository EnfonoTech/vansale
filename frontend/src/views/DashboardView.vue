<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";
import {
  todaySales,
  todayCollection,
  recentActivity,
  type TodaySales,
  type TodayCollection,
  type ActivityRow,
} from "@/api/dashboard";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();

const sales = ref<TodaySales | null>(null);
const collection = ref<TodayCollection | null>(null);
const activity = ref<ActivityRow[]>([]);
const loading = ref(false);
const loadErr = ref("");

const CACHE_KEY = "vansale.dashboard.v1";

type Snapshot = { sales: TodaySales; collection: TodayCollection; activity: ActivityRow[]; at: number };

function readCache(): Snapshot | null {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Snapshot;
    // Discard if older than 5 min — stale numbers on today's sales are
    // worse than a spinner.
    if (Date.now() - parsed.at > 5 * 60_000) return null;
    return parsed;
  } catch { return null; }
}

function writeCache(snap: Snapshot) {
  try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(snap)); } catch { /* quota */ }
}

async function load() {
  loadErr.value = "";

  // SWR: paint last-known snapshot instantly, then refresh.
  const cached = readCache();
  if (cached) {
    sales.value = cached.sales;
    collection.value = cached.collection;
    activity.value = cached.activity;
  }

  loading.value = !cached;

  try {
    const [a, b, c] = await Promise.all([todaySales(), todayCollection(), recentActivity(8)]);
    sales.value = a;
    collection.value = b;
    activity.value = c;
    writeCache({ sales: a, collection: b, activity: c, at: Date.now() });
  } catch (err) {
    if (!cached) loadErr.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function fmt(n: number | undefined | null): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(Number(n) || 0);
}

const currency = computed(() => session.currency ?? "");
const greeting = computed(() => session.fullName ?? session.user ?? "");
const timeOfDay = computed(() => {
  const h = new Date().getHours();
  if (h < 5) return "Still up";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
});

interface Quick { icon: "invoice" | "payment" | "customer" | "route" | "stock" | "receipt"; label: string; to: string; tone: string }
const quickActions: Quick[] = [
  { icon: "invoice", label: "New invoice", to: "invoice-new", tone: "primary" },
  { icon: "payment", label: "Collect payment", to: "payment-new", tone: "success" },
  { icon: "customer", label: "Customers", to: "customers", tone: "info" },
  { icon: "route", label: "Today's route", to: "route-today", tone: "warning" },
];

function kindIcon(kind: ActivityRow["kind"]): "invoice" | "payment" {
  return kind === "invoice" ? "invoice" : "payment";
}

function onActivityClick(row: ActivityRow) {
  if (row.kind === "invoice") {
    void router.push({ name: "invoice-detail", params: { name: row.name } });
  }
  // payment detail view — future
}
</script>

<template>
  <div class="dashboard stack">
    <section class="greeting">
      <span class="muted small">{{ timeOfDay }},</span>
      <h1>{{ greeting }}</h1>
      <div v-if="session.defaults" class="van-chip">
        <Icon name="truck" :size="16" />
        <span>{{ session.defaults.van_code ?? "—" }}</span>
        <span v-if="session.defaults.default_warehouse" class="dot">·</span>
        <span v-if="session.defaults.default_warehouse">{{ session.defaults.default_warehouse }}</span>
      </div>
    </section>

    <section class="hero">
      <div class="hero-row">
        <span class="muted xsmall">Today's sales</span>
        <span class="hero-currency"><SarSymbol :code="currency" /></span>
      </div>
      <div class="hero-amount">
        <span v-if="loading && !sales" class="skeleton" style="height:2.5rem;width:60%"></span>
        <template v-else>{{ fmt(sales?.amount) }}</template>
      </div>
      <div class="hero-meta">
        <span class="pill" data-tone="primary">
          <Icon name="invoice" :size="14" />
          {{ sales?.count ?? 0 }} invoice{{ sales?.count === 1 ? "" : "s" }}
        </span>
        <span class="pill" data-tone="success">
          <Icon name="payment" :size="14" />
          <SarSymbol :code="currency" />{{ fmt(collection?.amount) }} collected
        </span>
        <span v-if="(sales?.returned ?? 0) > 0" class="pill" data-tone="warning">
          <Icon name="refresh" :size="14" />
          <SarSymbol :code="currency" />{{ fmt(sales?.returned) }} returned
        </span>
      </div>
    </section>

    <section class="quick">
      <button
        v-for="q in quickActions"
        :key="q.to"
        class="quick-btn"
        :data-tone="q.tone"
        @click="router.push({ name: q.to })"
      >
        <Icon :name="q.icon" :size="22" />
        <span>{{ q.label }}</span>
      </button>
    </section>

    <section class="card stack">
      <div class="section-head">
        <h3 style="margin:0">Recent activity</h3>
        <button v-if="activity.length > 0" class="ghost small" @click="router.push({ name: 'invoices' })">
          View all
          <Icon name="chevron-right" :size="16" />
        </button>
      </div>
      <p v-if="loadErr" class="error">{{ loadErr }}</p>
      <div v-if="loading && activity.length === 0" class="stack">
        <div class="skeleton" style="height:3rem"></div>
        <div class="skeleton" style="height:3rem"></div>
      </div>
      <div v-else-if="activity.length === 0" class="empty">
        <Icon name="tag" :size="32" class="empty-icon" />
        <span>No invoices or payments today yet.</span>
        <button @click="router.push({ name: 'invoice-new' })">Start selling</button>
      </div>
      <ul v-else class="activity">
        <li
          v-for="row in activity"
          :key="`${row.kind}:${row.name}`"
          class="activity-row"
          :class="{ clickable: row.kind === 'invoice' }"
          :role="row.kind === 'invoice' ? 'button' : undefined"
          :tabindex="row.kind === 'invoice' ? 0 : -1"
          @click="onActivityClick(row)"
          @keyup.enter="onActivityClick(row)"
        >
          <span class="avatar" :data-kind="row.kind">
            <Icon :name="kindIcon(row.kind)" :size="18" />
          </span>
          <div class="activity-main">
            <strong class="truncate">{{ row.party }}</strong>
            <span class="muted xsmall">{{ row.name }} · {{ row.posting_date }}</span>
          </div>
          <strong class="activity-amt">{{ fmt(row.amount) }}</strong>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.dashboard { gap: 0.875rem; }

.greeting h1 { margin: 0.1rem 0 0.5rem; }
.van-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.7rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-pill);
  font-weight: 600;
  font-size: var(--text-xs);
}
.van-chip .dot { color: var(--text-faint); }

.hero {
  background: linear-gradient(135deg, var(--primary) 0%, color-mix(in srgb, var(--primary) 75%, #0f172a) 100%);
  color: var(--primary-ink);
  padding: 1.25rem;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-float);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.hero-row { display: flex; justify-content: space-between; align-items: baseline; opacity: 0.85; }
.hero .muted { color: rgba(255,255,255,0.78); }
.hero-currency { font-size: var(--text-xs); font-weight: 600; letter-spacing: 0.04em; }
.hero-amount { font-size: var(--text-3xl); font-weight: 700; letter-spacing: -0.01em; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.35rem; }
.hero-meta .pill { background: rgba(255,255,255,0.15); color: #fff; }

.quick {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.6rem;
}
.quick-btn {
  all: unset;
  cursor: pointer;
  min-height: 4.5rem;
  padding: 0.9rem 1rem;
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.35rem;
  font-weight: 600;
  color: var(--text);
  transition: transform var(--dur-fast) var(--ease);
}
.quick-btn:active { transform: scale(0.97); }
.quick-btn svg {
  padding: 0.4rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-sm);
  box-sizing: content-box;
}
.quick-btn[data-tone="success"] svg { background: var(--success-soft); color: var(--success); }
.quick-btn[data-tone="info"] svg { background: var(--info-soft); color: var(--info); }
.quick-btn[data-tone="warning"] svg { background: var(--warning-soft); color: var(--warning); }

.section-head { display: flex; align-items: center; justify-content: space-between; }

.activity { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.activity-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.6rem;
  align-items: center;
  border-radius: var(--radius-sm);
  padding: 0.1rem 0.1rem;
  transition: background var(--dur-fast) var(--ease);
}
.activity-row.clickable { cursor: pointer; }
.activity-row.clickable:hover { background: var(--surface-muted); }
.activity-row.clickable:active { transform: scale(0.99); }
.activity-row:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.avatar {
  width: 2.25rem; height: 2.25rem;
  border-radius: var(--radius-pill);
  display: grid; place-items: center;
  background: var(--primary-soft); color: var(--primary);
}
.avatar[data-kind="payment"] { background: var(--success-soft); color: var(--success); }
.activity-main { display: flex; flex-direction: column; min-width: 0; gap: 0.1rem; }
.activity-amt { font-variant-numeric: tabular-nums; }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
