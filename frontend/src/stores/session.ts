/**
 * Session state — persists across app kill so offline PIN unlock still
 * knows who the user is, which credentials to present, and when the
 * last successful PIN verification happened (for 2h grace period).
 *
 * Also caches the user's Vansale Configuration defaults (company,
 * warehouse, cost center) so forms can pre-fill them even when offline.
 *
 * See fatehhr lesson §5.3: PIN session window stored as `pinVerifiedAt`.
 */
import { defineStore } from "pinia";
import type { ConfigDefaults } from "@/api/me";

const LS_KEY = "vansale.session";
const PIN_WINDOW_MS = 2 * 60 * 60 * 1000; // 2 hours

interface Persisted {
  user: string | null;
  fullName: string | null;
  email: string | null;
  language: string;
  pinVerifiedAt: number | null;
  defaults: ConfigDefaults | null;
  /**
   * Effective PIN requirement (user row -> van -> global), delivered by the
   * login response and refreshed on every `configDefaults`. Persisted so an
   * offline relaunch does not fall back to prompting for a PIN the admin
   * switched off.
   */
  requirePin: boolean;
}

function loadPersisted(): Persisted {
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) return { ...initial(), ...(JSON.parse(raw) as Partial<Persisted>) };
  } catch {
    /* ignore corrupt localStorage */
  }
  return initial();
}

function initial(): Persisted {
  return {
    user: null,
    fullName: null,
    email: null,
    language: "en",
    pinVerifiedAt: null,
    defaults: null,
    requirePin: true,
  };
}

function persist(state: Persisted): void {
  window.localStorage.setItem(LS_KEY, JSON.stringify(state));
}

export const useSessionStore = defineStore("session", {
  state: (): Persisted => loadPersisted(),
  getters: {
    isAuthenticated: (s) => Boolean(s.user),
    /** False when the admin turned PIN unlock off for this user or van. */
    pinRequired: (s) => s.requirePin !== false,
    // A disabled PIN is always "valid" — the guard must not bounce the user
    // to a screen that would ask for a PIN they were never asked to set.
    pinStillValid: (s) =>
      s.requirePin === false ||
      (s.pinVerifiedAt !== null && Date.now() - s.pinVerifiedAt < PIN_WINDOW_MS),
    defaultWarehouse: (s) => s.defaults?.default_warehouse ?? null,
    defaultCostCenter: (s) => s.defaults?.default_cost_center ?? null,
    defaultCompany: (s) => s.defaults?.company ?? null,
    currency: (s) => s.defaults?.currency ?? null,
    isVanUser: (s) => Boolean(s.defaults?.is_van_user),
    requireLocation: (s) => Boolean(s.defaults?.require_location),
    /**
     * Route planning is opt-out per van. Defaults to true while `defaults`
     * is still null (first paint, or a site that predates the field) so the
     * Route tab never flickers away on an app that does use routes.
     */
    routeEnabled: (s) => s.defaults?.enable_route !== false,
    vanPriceList: (s) => s.defaults?.selling_price_list ?? null,
  },
  actions: {
    setLogin(payload: { user: string; fullName: string; email: string; language?: string }) {
      this.user = payload.user;
      this.fullName = payload.fullName;
      this.email = payload.email;
      if (payload.language) this.language = payload.language;
      persist(this.$state);
    },
    markPinVerified() {
      this.pinVerifiedAt = Date.now();
      persist(this.$state);
    },
    clearPinWindow() {
      this.pinVerifiedAt = null;
      persist(this.$state);
    },
    setRequirePin(required: boolean) {
      this.requirePin = required;
      persist(this.$state);
    },
    setDefaults(defaults: ConfigDefaults) {
      this.defaults = defaults;
      if (typeof defaults.require_pin === "boolean") this.requirePin = defaults.require_pin;
      if (defaults.full_name) this.fullName = defaults.full_name;
      if (defaults.language) this.language = defaults.language;
      persist(this.$state);
    },
    logout() {
      this.$patch(initial());
      persist(this.$state);
    },
  },
});
