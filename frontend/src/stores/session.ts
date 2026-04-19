/**
 * Session state — persists across app kill so offline PIN unlock still
 * knows who the user is, which credentials to present, and when the
 * last successful PIN verification happened (for 2h grace period).
 *
 * See fatehhr lesson §5.3: PIN session window stored as `pinVerifiedAt`.
 */
import { defineStore } from "pinia";

const LS_KEY = "vansale.session";
const PIN_WINDOW_MS = 2 * 60 * 60 * 1000; // 2 hours

interface Persisted {
  user: string | null;
  fullName: string | null;
  email: string | null;
  language: string;
  pinVerifiedAt: number | null;
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
  };
}

function persist(state: Persisted): void {
  window.localStorage.setItem(LS_KEY, JSON.stringify(state));
}

export const useSessionStore = defineStore("session", {
  state: (): Persisted => loadPersisted(),
  getters: {
    isAuthenticated: (s) => Boolean(s.user),
    pinStillValid: (s) =>
      s.pinVerifiedAt !== null && Date.now() - s.pinVerifiedAt < PIN_WINDOW_MS,
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
    logout() {
      this.$patch(initial());
      persist(this.$state);
    },
  },
});
