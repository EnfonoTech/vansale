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
import { useApprovalsStore } from "@/stores/approvals";
import { warmCaches } from "@/offline/warm";
import { useSyncStore } from "@/stores/sync";
import { useToastStore } from "@/stores/toasts";
import { SESSION_EXPIRED_EVENT } from "@/app/frappe";

const route = useRoute();
const router = useRouter();
const visit = useRouteVisitStore();
const online = useOnline();
const session = useSessionStore();
const sync = useSyncStore();
const approvals = useApprovalsStore();

/**
 * Send what was saved offline. Nothing did this on its own: the badge that
 * synced on reconnect was never placed on a screen, so queued sales waited
 * until the salesman opened the sync screen and tapped Retry. Safe to call
 * often — one drain at a time, each entry waits out its own backoff, and the
 * server ignores a sale it already has (client_id).
 */
function syncPending() {
  // Reads only the local queue and drains when something is waiting, so it is
  // safe for any signed-in user (a user without the van app has an empty
  // queue). It must not wait on who the user is: a van user whose settings
  // have not loaded, or who has a van without either van role, still has
  // sales saved offline to send.
  if (!session.isAuthenticated) return;
  void sync.refresh().then(() => {
    if (sync.pending > 0) void sync.requestDrain();
  });
}

/**
 * The number on the Approvals entry points is only read when a screen opens,
 * so an approval that arrived while the app sat in the background would not
 * show until the next navigation. Reading it when the app comes back to the
 * front keeps the badge honest. Numbers only (no inbox), and nothing at all
 * on a site without approvals; offline it asks nothing.
 */
function refreshApprovalsBadge() {
  if (!session.isAuthenticated || !session.approvalsEnabled) return;
  void approvals.refreshCount();
}

// Offline→online transition: opportunistically warm the item + customer
// caches so the next screen the driver opens has fresh data. The warm
// helper internally rate-limits to once per 10 min so this never spams.
// Also re-read config: a van that was offline while the office changed a
// module toggle should pick it up the moment it has signal again.
watch(online, async (isNow, wasNow) => {
  if (isNow && !wasNow && session.isAuthenticated) {
    // Who the user is comes first: the warm-up reads van endpoints, which a
    // user without the van app must never trigger. Unknown settings (never
    // loaded) warm nothing.
    await session.refreshDefaults();
    syncPending();
    refreshApprovalsBadge();
    if (session.defaults !== null && session.hasVanShell) {
      void warmCaches({
        warehouse: session.defaultWarehouse ?? undefined,
        force: true,
      }).catch(() => {});
    }
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
// The web session ended (every call came back 403 and the app looked stuck):
// say so once and go to sign-in. Queued work stays on the phone and is sent
// after the same user signs in again.
let expiryShown = false;
function onSessionExpired() {
  if (expiryShown || route.name === "login") return;
  expiryShown = true;
  useToastStore().warn("Your session has ended — sign in again. Unsent work stays on this phone.", 6000);
  session.logout();
  void router.replace({ name: "login" }).finally(() => {
    expiryShown = false;
  });
}

onMounted(() => {
  window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
  if (session.isAuthenticated) void session.refreshDefaults();
  syncPending();

  void (async () => {
    try {
      const { App: CapApp } = await import("@capacitor/app");
      await CapApp.addListener("appStateChange", ({ isActive }) => {
        if (isActive && session.isAuthenticated) {
          void session.refreshDefaults();
          syncPending();
          refreshApprovalsBadge();
        }
      });
    } catch {
      /* web build — @capacitor/app not bundled */
    }
  })();

  // Web PWA: the tab coming back into view is the same signal.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && session.isAuthenticated) {
      void session.refreshDefaults();
      syncPending();
      refreshApprovalsBadge();
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
  <div class="app-root" :class="{ 'app-root--wide': route.meta.wide }">
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
/* Two-column screens (route meta `wide`): page, top bar and tabs all take
   the wider column. */
.app-root--wide { --max-content: var(--max-content-wide); }
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
