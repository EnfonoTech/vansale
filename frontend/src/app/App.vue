<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import TopAppBar from "@/components/TopAppBar.vue";
import BottomNav from "@/components/BottomNav.vue";
import Toasts from "@/components/Toasts.vue";
import ConfirmModal from "@/components/ConfirmModal.vue";
import Icon from "@/components/Icon.vue";
import { useRouteVisitStore } from "@/stores/routeVisit";
import { useOnline } from "@/app/online";
import { useSessionStore } from "@/stores/session";
import { warmCaches } from "@/offline/warm";

const route = useRoute();
const router = useRouter();
const visit = useRouteVisitStore();
const online = useOnline();
const session = useSessionStore();

// Offline→online transition: opportunistically warm the item + customer
// caches so the next screen the driver opens has fresh data. The warm
// helper internally rate-limits to once per 10 min so this never spams.
// Also re-read config: a van that was offline while the office changed a
// module toggle should pick it up the moment it has signal again.
watch(online, (isNow, wasNow) => {
  if (isNow && !wasNow && session.isAuthenticated) {
    void session.refreshDefaults();
    void warmCaches({
      warehouse: session.defaultWarehouse ?? undefined,
      force: true,
    }).catch(() => {});
  }
});

/**
 * Keep module toggles current without forcing a re-login.
 *
 * `defaults` is persisted and used to be written only at login and PIN
 * unlock. With login lasting until uninstall, an admin turning route planning
 * off in ERPNext would not reach a running app — the Route tab stayed visible
 * indefinitely. Refresh on start and whenever Android brings the app back to
 * the foreground, which is when a driver would notice a change anyway.
 */
onMounted(() => {
  if (session.isAuthenticated) void session.refreshDefaults();

  void (async () => {
    try {
      const { App: CapApp } = await import("@capacitor/app");
      await CapApp.addListener("appStateChange", ({ isActive }) => {
        if (isActive && session.isAuthenticated) void session.refreshDefaults();
      });
    } catch {
      /* web build — @capacitor/app not bundled */
    }
  })();

  // Web PWA: the tab coming back into view is the same signal.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && session.isAuthenticated) {
      void session.refreshDefaults();
    }
  });
});

// If route planning is switched off while the driver is standing on the Route
// screen, the tab disappears from under them but the view stays mounted. Move
// them to Home rather than leaving a screen with no way back to it.
watch(
  () => session.routeEnabled,
  (enabled) => {
    if (!enabled && route.name === "route-today") {
      void router.replace({ name: "dashboard" });
    }
  },
);

// Pre-auth screens carry no app chrome. `setup` belongs here too: the top bar
// and bottom nav were rendering around the server-address form, offering tabs
// that cannot work before a server is even configured.
const CHROMELESS_ROUTES = ["setup", "login", "pin"];

const isChrome = computed(() => {
  const name = String(route.name ?? "");
  return !CHROMELESS_ROUTES.includes(name);
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
    <ConfirmModal />
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
