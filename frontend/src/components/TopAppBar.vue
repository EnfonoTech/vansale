<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";
import { useSyncStore } from "@/stores/sync";
import Icon from "./Icon.vue";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const sync = useSyncStore();
const online = useOnline();

const TITLES: Record<string, string> = {
  dashboard: "Home",
  customers: "Customers",
  "customer-new": "New customer",
  "customer-detail": "Customer",
  "customer-statement": "Statement",
  "customer-address": "Address",
  "customer-contact": "Contact",
  invoices: "Invoices",
  "invoice-new": "New invoice",
  "invoice-detail": "Invoice",
  "invoice-return": "Sales return",
  returns: "Returns",
  "return-new": "Bulk return",
  "payment-new": "Collect payment",
  "route-today": "Today's route",
  "van-stock": "Van stock",
  "sync-errors": "Sync errors",
  more: "More",
  "print-view": "Print",
};

/**
 * Hierarchical back: each screen declares its parent so tapping
 * the top-bar back arrow walks UP the tree, not along raw browser
 * history. Detail → list → home. For screens that need to pass
 * params back to the parent (e.g. statement → customer-detail),
 * the mapper receives the current route params.
 *
 * Screens not in this map fall through to `router.back()` or home.
 */
type RouteTarget = { name: string; params?: Record<string, string> };
type RouteLike = { name?: string; params?: Record<string, unknown> };
const PARENTS: Record<string, (r: RouteLike) => RouteTarget> = {
  customers: () => ({ name: "dashboard" }),
  invoices: () => ({ name: "dashboard" }),
  returns: () => ({ name: "dashboard" }),
  "route-today": () => ({ name: "dashboard" }),
  "van-stock": () => ({ name: "dashboard" }),
  more: () => ({ name: "dashboard" }),
  "customer-new": () => ({ name: "customers" }),
  "customer-detail": () => ({ name: "customers" }),
  "customer-statement": (r) => ({
    name: "customer-detail",
    params: { name: String(r.params?.name ?? "") },
  }),
  "customer-address": (r) => ({
    name: "customer-detail",
    params: { name: String(r.params?.name ?? "") },
  }),
  "customer-contact": (r) => ({
    name: "customer-detail",
    params: { name: String(r.params?.name ?? "") },
  }),
  "invoice-new": () => ({ name: "invoices" }),
  "invoice-detail": () => ({ name: "invoices" }),
  "invoice-return": (r) => ({
    name: "invoice-detail",
    params: { name: String(r.params?.name ?? "") },
  }),
  "payment-new": () => ({ name: "dashboard" }),
  "return-new": () => ({ name: "returns" }),
  "sync-errors": () => ({ name: "more" }),
  "print-view": (r) => {
    // Print is launched from invoice detail or statement.
    // Default back to invoice-detail when we have the invoice name.
    const dt = String(r.params?.doctype ?? "");
    const nm = String(r.params?.name ?? "");
    if (dt === "Sales Invoice" && nm) {
      return { name: "invoice-detail", params: { name: nm } };
    }
    return { name: "dashboard" };
  },
};

const title = computed(() => TITLES[String(route.name ?? "")] ?? "Van Sale");

const subtitle = computed(() => {
  if (!session.defaults) return "";
  const parts = [
    session.defaults.van_code,
    session.defaults.default_warehouse,
  ].filter(Boolean);
  return parts.join(" · ");
});

const showBack = computed(() => {
  const r = String(route.name ?? "");
  return [
    "customer-new",
    "customer-detail",
    "customer-statement",
    "customer-address",
    "customer-contact",
    "invoice-new",
    "invoice-detail",
    "invoice-return",
    "return-new",
    "payment-new",
    "sync-errors",
    "print-view",
  ].includes(r);
});

const showSync = computed(() => {
  const r = String(route.name ?? "");
  return r && !["login", "pin"].includes(r);
});

const syncTone = computed(() => {
  if (!online.value) return "offline";
  if (sync.draining) return "syncing";
  if (sync.lastError || sync.pending > 0) return "pending";
  return "ok";
});

function onBack() {
  const rn = String(route.name ?? "");
  const parent = PARENTS[rn];
  if (parent) {
    void router.push(parent({ name: rn, params: route.params as Record<string, unknown> }));
    return;
  }
  router.back();
}

function onSyncTap() {
  if (sync.pending > 0 || sync.lastError) {
    void router.push({ name: "sync-errors" });
  } else if (online.value) {
    void sync.requestDrain();
  }
}
</script>

<template>
  <header class="top-bar">
    <button v-if="showBack" class="icon-only" type="button" @click="onBack" aria-label="Back">
      <Icon name="back" :size="20" />
    </button>
    <div class="title-block">
      <strong>{{ title }}</strong>
      <span v-if="subtitle" class="subtitle">{{ subtitle }}</span>
    </div>
    <button
      v-if="showSync"
      class="sync-chip"
      type="button"
      :data-tone="syncTone"
      @click="onSyncTap"
      aria-label="Sync status"
    >
      <Icon v-if="!online" name="wifi-off" :size="16" />
      <Icon v-else-if="sync.draining" name="sync" :size="16" class="spin" />
      <Icon v-else-if="syncTone === 'pending'" name="alert" :size="16" />
      <Icon v-else name="wifi" :size="16" />
      <span v-if="sync.pending > 0">{{ sync.pending }}</span>
    </button>
  </header>
</template>

<style scoped>
.top-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--top-bar-height);
  padding: 0 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
}
.icon-only {
  background: var(--surface-sunk);
  color: var(--text);
}
.title-block {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.1;
}
.title-block strong {
  font-size: var(--text-lg);
  font-weight: 600;
  letter-spacing: -0.005em;
}
.subtitle {
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sync-chip {
  min-height: 2.25rem;
  padding: 0 0.7rem;
  border-radius: var(--radius-pill);
  background: var(--surface-sunk);
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 600;
  gap: 0.3rem;
}
.sync-chip[data-tone="ok"] { color: var(--success); background: var(--success-soft); }
.sync-chip[data-tone="pending"] { color: var(--warning); background: var(--warning-soft); }
.sync-chip[data-tone="offline"] { color: var(--danger); background: var(--danger-soft); }
.sync-chip[data-tone="syncing"] { color: var(--primary); background: var(--primary-soft); }

.spin { animation: rotate 1.1s linear infinite; }
@keyframes rotate { to { transform: rotate(360deg); } }
</style>
