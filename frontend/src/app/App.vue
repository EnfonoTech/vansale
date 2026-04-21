<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import TopAppBar from "@/components/TopAppBar.vue";
import BottomNav from "@/components/BottomNav.vue";
import Toasts from "@/components/Toasts.vue";
import Icon from "@/components/Icon.vue";
import { useRouteVisitStore } from "@/stores/routeVisit";

const route = useRoute();
const router = useRouter();
const visit = useRouteVisitStore();

const isChrome = computed(() => {
  const name = String(route.name ?? "");
  return !["login", "pin"].includes(name);
});

const showVisitPill = computed(() => {
  if (!visit.hasActive) return false;
  const name = String(route.name ?? "");
  // Hide on the route page itself — the End visit button is already there.
  return isChrome.value && name !== "route-today";
});

function gotoRoute() {
  void router.push({ name: "route-today" });
}
</script>

<template>
  <div class="app-root">
    <TopAppBar v-if="isChrome" />
    <main class="app-main" :class="{ 'app-main--chrome': isChrome }">
      <RouterView v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>

    <button
      v-if="showVisitPill"
      type="button"
      class="visit-pill"
      @click="gotoRoute"
      aria-label="Return to active visit"
    >
      <Icon name="map-pin" :size="16" />
      <span class="visit-pill__text">Active · {{ visit.activeCustomer }}</span>
      <span class="visit-pill__cta">End</span>
    </button>

    <BottomNav v-if="isChrome" />
    <Toasts />
  </div>
</template>

<style>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
}
.app-main {
  flex: 1;
  width: 100%;
  max-width: var(--max-content);
  margin: 0 auto;
  padding: 1rem;
  padding-inline: 1rem;
}
.app-main--chrome {
  padding-bottom: calc(var(--bottom-nav-height) + 1rem + var(--safe-bottom));
}

.page-enter-from { opacity: 0; transform: translateY(6px); }
.page-enter-active { transition: all var(--dur) var(--ease); }
.page-leave-to { opacity: 0; transform: translateY(-2px); }
.page-leave-active { transition: all var(--dur-fast) var(--ease); }

.visit-pill {
  position: fixed;
  left: 50%;
  transform: translateX(-50%);
  bottom: calc(var(--bottom-nav-height) + 0.6rem + var(--safe-bottom));
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.55rem 0.65rem 0.55rem 0.85rem;
  min-height: 2.6rem;
  background: var(--primary);
  color: var(--primary-ink);
  border: 0;
  border-radius: 999px;
  box-shadow: var(--shadow-float);
  font-size: var(--text-sm);
  font-weight: 600;
  z-index: 40;
  max-width: min(92vw, 32rem);
  cursor: pointer;
}
.visit-pill__text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 16rem;
}
.visit-pill__cta {
  background: color-mix(in srgb, white 22%, transparent);
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: var(--text-xs);
  letter-spacing: 0.02em;
}
.visit-pill:active { transform: translateX(-50%) scale(0.98); }
</style>
