/**
 * Route-hierarchy-driven back-button handler. `router.back()` walks
 * every visited screen, which users hate on Android — they expect
 * one-level-up. This map defines parent routes; the root pops the
 * exit-confirmation.
 *
 * See fatehhr lesson #8 (`PARENT_BY_ROUTE_NAME`).
 */
import type { Router } from "vue-router";

const PARENT_BY_ROUTE_NAME: Record<string, string | null> = {
  dashboard: null, // root — exit on next back
  login: null,
  pin: null,
  customers: "dashboard",
  invoices: "dashboard",
  "invoice-new": "dashboard",
  "payment-new": "dashboard",
  "route-today": "dashboard",
  "van-stock": "dashboard",
  "sync-errors": "dashboard",
};

const EXIT_ROUTES = new Set(["dashboard", "login", "pin"]);

let lastExitPromptAt = 0;
const EXIT_WINDOW_MS = 2000;

/** Register the Android back-button listener on native. */
export async function installNativeBack(router: Router): Promise<void> {
  try {
    // @ts-ignore — optional at build time
    const mod = await import("@capacitor/app");
    if (!mod?.App?.addListener) return;
    mod.App.addListener("backButton", async () => {
      const current = router.currentRoute.value;
      const name = current.name ? String(current.name) : "";
      const parent = PARENT_BY_ROUTE_NAME[name];

      if (parent) {
        await router.replace({ name: parent });
        return;
      }

      if (EXIT_ROUTES.has(name)) {
        const now = Date.now();
        if (now - lastExitPromptAt < EXIT_WINDOW_MS) {
          try {
            await mod.App.exitApp();
          } catch {
            /* exit unsupported — no-op */
          }
          return;
        }
        lastExitPromptAt = now;
        // Lightweight toast via alert; Phase-later UI could swap in a snackbar.
        try {
          // Haptics feedback optional; skip to keep plugin count low.
          window.setTimeout(() => {
            // No-op — the next back within the window exits.
          }, 0);
        } catch {
          /* ignore */
        }
        return;
      }

      // Fallback for any unmapped route — treat as "one level up".
      await router.replace({ name: "dashboard" });
    });
  } catch {
    /* @capacitor/app not bundled (web build) */
  }
}
