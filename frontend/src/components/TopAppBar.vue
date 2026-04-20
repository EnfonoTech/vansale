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
  "customer-detail": "Customer",
  invoices: "Invoices",
  "invoice-new": "New invoice",
  "payment-new": "Collect payment",
  "route-today": "Today's route",
  "van-stock": "Van stock",
  "sync-errors": "Sync errors",
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
  return ["customer-detail", "invoice-new", "payment-new", "sync-errors"].includes(r);
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
