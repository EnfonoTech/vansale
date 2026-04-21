<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { logout } from "@/api/auth";
import { useSyncStore } from "@/stores/sync";
import Icon from "@/components/Icon.vue";
import SarSymbol from "@/components/SarSymbol.vue";

const router = useRouter();
const session = useSessionStore();
const sync = useSyncStore();
const appVersion = __APP_VERSION__;

const initials = computed(() => {
  const name = session.fullName ?? session.email ?? "";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s.charAt(0).toUpperCase())
    .join("") || "?";
});

async function onLogout() {
  try { await logout(); }
  finally { session.logout(); await router.replace({ name: "login" }); }
}

interface Link {
  icon: "customer" | "stock" | "sync" | "refresh" | "truck" | "invoice" | "receipt" | "plus" | "payment";
  label: string;
  sub?: string;
  to: string;
  tone?: "primary" | "success" | "warning" | "danger";
  badge?: number | null;
}

const links = computed<Link[]>(() => [
  { icon: "plus", label: "New invoice", sub: "Start a sale", to: "invoice-new", tone: "primary" },
  { icon: "invoice", label: "All invoices", sub: "Browse submitted & drafts", to: "invoices" },
  { icon: "payment", label: "Payments", sub: "Collections & receipts", to: "payments", tone: "success" },
  { icon: "receipt", label: "Returns", sub: "Credit notes against invoices", to: "returns", tone: "warning" },
  { icon: "customer", label: "Customers", sub: "Browse & create", to: "customers" },
  { icon: "stock", label: "Van stock", sub: "Current warehouse", to: "van-stock", tone: "success" },
  { icon: "truck", label: "Today's route", sub: "Stops, visits, signatures", to: "route-today" },
  {
    icon: "sync",
    label: "Sync errors",
    sub: sync.pending > 0 ? `${sync.pending} pending` : sync.lastError ?? "All clear",
    to: "sync-errors",
    tone: sync.pending > 0 || sync.lastError ? "danger" : undefined,
    badge: sync.pending > 0 ? sync.pending : null,
  },
]);
</script>

<template>
  <div class="stack more">
    <section class="profile card">
      <div class="avatar">{{ initials }}</div>
      <div class="identity">
        <strong class="truncate">{{ session.fullName || session.email }}</strong>
        <span class="muted xsmall truncate">{{ session.email }}</span>
        <div v-if="session.defaults" class="van-chip">
          <Icon name="truck" :size="14" />
          <span>{{ session.defaults.van_code ?? "—" }}</span>
          <span v-if="session.defaults.default_warehouse" class="dot">·</span>
          <span v-if="session.defaults.default_warehouse">{{ session.defaults.default_warehouse }}</span>
        </div>
      </div>
    </section>

    <section class="card stack">
      <h3 class="section-h">Shortcuts</h3>
      <ul class="link-list">
        <li
          v-for="l in links"
          :key="l.to"
          class="link-row"
          role="button"
          tabindex="0"
          @click="router.push({ name: l.to })"
          @keyup.enter="router.push({ name: l.to })"
        >
          <Icon :name="l.icon" :size="18" class="link-icon" :data-tone="l.tone" />
          <div class="link-body">
            <strong>{{ l.label }}</strong>
            <span v-if="l.sub" class="muted xsmall">{{ l.sub }}</span>
          </div>
          <span v-if="l.badge" class="pill" data-tone="danger">{{ l.badge }}</span>
          <Icon name="chevron-right" :size="16" class="chev" />
        </li>
      </ul>
    </section>

    <section class="card stack">
      <h3 class="section-h">App</h3>
      <div class="meta-row">
        <span class="muted">Version</span>
        <span>{{ appVersion }}</span>
      </div>
      <div class="meta-row">
        <span class="muted">Language</span>
        <span>{{ session.language ?? "en" }}</span>
      </div>
      <div class="meta-row">
        <span class="muted">Currency</span>
        <span><SarSymbol :code="session.currency" /> {{ session.currency }}</span>
      </div>
    </section>

    <button class="danger-ghost" @click="onLogout">
      <Icon name="logout" :size="18" /> Log out
    </button>
  </div>
</template>

<style scoped>
.more { gap: 0.875rem; padding-bottom: 1.5rem; }

.profile {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.85rem;
  align-items: center;
  padding: 1rem;
}
.avatar {
  width: 3.25rem; height: 3.25rem;
  border-radius: var(--radius-pill);
  background: linear-gradient(135deg, var(--primary) 0%, color-mix(in srgb, var(--primary) 70%, #0f172a) 100%);
  color: var(--primary-ink);
  display: grid; place-items: center;
  font-weight: 700;
  font-size: var(--text-lg);
  box-shadow: var(--shadow-sm);
}
.identity { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.van-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.25rem;
  padding: 0.2rem 0.55rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 600;
  align-self: flex-start;
}
.van-chip .dot { color: var(--text-faint); }
.truncate { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.section-h {
  margin: 0 0 0.1rem;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.link-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.2rem; }
.link-row {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  gap: 0.65rem;
  align-items: center;
  padding: 0.65rem 0.5rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}
.link-row:hover, .link-row:focus-visible { background: var(--surface-muted); outline: none; }
.link-icon {
  padding: 0.45rem;
  background: var(--primary-soft);
  color: var(--primary);
  border-radius: var(--radius-sm);
  box-sizing: content-box;
}
.link-icon[data-tone="success"] { background: var(--success-soft); color: var(--success); }
.link-icon[data-tone="warning"] { background: var(--warning-soft); color: var(--warning); }
.link-icon[data-tone="danger"] { background: var(--danger-soft); color: var(--danger); }
.link-body { display: flex; flex-direction: column; gap: 0.05rem; min-width: 0; }
.chev { color: var(--text-muted); }

.meta-row { display: flex; justify-content: space-between; align-items: baseline; font-variant-numeric: tabular-nums; }

.danger-ghost {
  all: unset;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-height: 3rem;
  border-radius: var(--radius);
  background: var(--danger-soft);
  color: var(--danger);
  font-weight: 600;
  transition: transform var(--dur-fast) var(--ease);
}
.danger-ghost:active { transform: scale(0.98); }
</style>
