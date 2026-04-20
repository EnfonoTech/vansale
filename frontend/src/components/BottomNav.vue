<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "./Icon.vue";

const router = useRouter();
const route = useRoute();

interface Tab { name: string; icon: "home" | "route" | "invoice" | "customer" | "more"; label: string; routes: string[] }

const tabs: Tab[] = [
  { name: "dashboard", icon: "home", label: "Home", routes: ["dashboard"] },
  { name: "route-today", icon: "route", label: "Route", routes: ["route-today"] },
  { name: "invoices", icon: "invoice", label: "Sales", routes: ["invoices", "invoice-new", "invoice-detail"] },
  { name: "customers", icon: "customer", label: "Customers", routes: ["customers", "customer-detail"] },
  { name: "more", icon: "more", label: "More", routes: ["more", "van-stock", "sync-errors"] },
];

const activeName = computed(() => String(route.name ?? ""));

function go(tab: Tab) {
  if (tab.routes.includes(activeName.value)) return;
  void router.push({ name: tab.name });
}
</script>

<template>
  <nav class="bottom-nav">
    <button
      v-for="tab in tabs"
      :key="tab.name"
      :class="['tab', tab.routes.includes(activeName) && 'tab--active']"
      @click="go(tab)"
    >
      <Icon :name="tab.icon" :size="22" />
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
  padding: 0.4rem 0.35rem calc(0.4rem + var(--safe-bottom));
  background: color-mix(in srgb, var(--surface) 94%, transparent);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-top: 1px solid var(--border);
  display: grid;
  grid-template-columns: repeat(5, 1fr);
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
.tab--active {
  color: var(--primary);
  background: var(--primary-soft);
}
</style>
