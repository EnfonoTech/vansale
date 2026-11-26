<script setup lang="ts">
import { computed, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { approvalsOnly } from "@/features/approvals/inbox";
import { useApprovalsStore } from "@/stores/approvals";
import { useSessionStore } from "@/stores/session";
import Icon from "./Icon.vue";

const router = useRouter();
const route = useRoute();
const session = useSessionStore();
const approvals = useApprovalsStore();
const { t } = useI18n();

interface Tab {
  name: string;
  icon: "home" | "route" | "stock" | "invoice" | "customer" | "more" | "approval";
  label: string;
  routes: string[];
  /** A number on the icon (the count waiting), or a plain dot, or nothing. */
  count?: number;
  dot?: boolean;
}

const showMoreDot = computed(() => session.approvalsEnabled && approvals.badge > 0);

/**
 * Fourth slot is Route or Van Stock, never both — a van either follows a
 * planned route or sells freely, and a five-icon bar has no room for a
 * sixth. `van-stock` therefore has to move between this tab's `routes` and
 * the More tab's, or whichever tab does not own it highlights wrongly.
 */
const tabs = computed<Tab[]>(() => {
  // No van setup: the app is Approvals and More, and no van screen is offered.
  if (approvalsOnly(session)) {
    return [
      {
        name: "approvals",
        icon: "approval",
        label: t("approvalsInbox.nav.approvals"),
        routes: ["approvals", "approval-detail"],
        count: approvals.badge,
      },
      { name: "more", icon: "more", label: "More", routes: ["more"] },
    ];
  }
  const fourth: Tab = session.routeEnabled
    ? { name: "route-today", icon: "route", label: "Route", routes: ["route-today"] }
    : { name: "van-stock", icon: "stock", label: "Stock", routes: ["van-stock"] };
  // Approvals has no tab of its own for a van user: it lives under More.
  const moreRoutes = session.routeEnabled
    ? ["more", "van-stock", "sync-errors", "approvals", "approval-detail"]
    : ["more", "sync-errors", "approvals", "approval-detail"];
  return [
    { name: "dashboard", icon: "home", label: "Home", routes: ["dashboard"] },
    {
      name: "invoices",
      icon: "invoice",
      label: "Sales",
      routes: ["invoices", "invoice-new", "invoice-detail"],
    },
    { name: "customers", icon: "customer", label: "Customers", routes: ["customers", "customer-detail"] },
    fourth,
    // Approvals is reached from Home and from More: a dot on More says something waits there.
    { name: "more", icon: "more", label: "More", routes: moreRoutes, dot: showMoreDot.value },
  ];
});

const activeName = computed(() => String(route.name ?? ""));

// The nav shows how many approvals wait, so it asks for the number itself,
// at most every 30 s and not on the Approvals screen (that one keeps it fresh).
const COUNT_EVERY_MS = 30_000;
let askedAt = 0;
watch(
  () => [route.name, session.approvalsEnabled],
  () => {
    if (!session.approvalsEnabled || !session.isAuthenticated) return;
    const name = String(route.name ?? "");
    if (name === "approvals" || name === "approval-detail") return;
    if (Date.now() - askedAt < COUNT_EVERY_MS) return;
    askedAt = Date.now();
    void approvals.refreshCount();
  },
  { immediate: true },
);

function go(tab: Tab) {
  if (tab.routes.includes(activeName.value)) return;
  void router.push({ name: tab.name });
}
</script>

<template>
  <nav class="bottom-nav" :style="{ '--tabs': tabs.length }">
    <button
      v-for="tab in tabs"
      :key="tab.name"
      :class="['tab', tab.routes.includes(activeName) && 'tab--active']"
      @click="go(tab)"
    >
      <span class="tab-icon">
        <Icon :name="tab.icon" :size="22" />
        <span v-if="tab.count" class="tab-count">{{ tab.count > 99 ? "99+" : tab.count }}</span>
        <span v-else-if="tab.dot" class="tab-dot" />
      </span>
      <span>{{ tab.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.bottom-nav {
  position: fixed;
  inset-inline: 0;
  bottom: 0;
  z-index: 20;
  padding-block: 0.4rem calc(0.4rem + var(--safe-bottom));
  /* Tabs stay grouped under the page column on wide screens. */
  padding-inline: max(0.35rem, calc((100% - var(--max-content)) / 2));
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-top: 1px solid var(--border);
  display: grid;
  grid-template-columns: repeat(var(--tabs, 5), 1fr);
  gap: 0.25rem;
}

.tab {
  all: unset;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1rem;
  padding: 0.45rem 0.25rem;
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
  min-height: 3.25rem;
}
.tab:active { transform: scale(0.97); }
.tab-icon { position: relative; display: inline-flex; }
.tab-dot {
  position: absolute;
  inset-block-start: -0.1rem;
  inset-inline-end: -0.15rem;
  width: 0.55rem;
  height: 0.55rem;
  border-radius: var(--radius-pill);
  background: var(--danger);
  box-shadow: 0 0 0 2px var(--surface);
}
.tab-count {
  position: absolute;
  inset-block-start: -0.35rem;
  inset-inline-start: 55%;
  min-width: 1.05rem;
  padding: 0 0.28rem;
  border-radius: var(--radius-pill);
  background: var(--danger);
  color: #fff;
  font-size: 0.62rem;
  line-height: 1.05rem;
  text-align: center;
  box-shadow: 0 0 0 2px var(--surface);
}
.tab--active {
  color: var(--primary);
  background: var(--primary-soft);
}
</style>
