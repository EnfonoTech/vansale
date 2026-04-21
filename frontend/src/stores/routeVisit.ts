/**
 * Active visit state — persists across navigation so the "End visit"
 * button remains reachable after the user opens an invoice / payment
 * from within an active visit. See user complaint #6 (v1.0.11).
 *
 * Prior implementation kept `active` in a local ref inside
 * RouteTodayView, which unmounted (and therefore lost state) on any
 * router.push. Now we hydrate from localStorage on app boot and rely
 * on pinia reactivity to drive both the route page AND an optional
 * FAB that can surface "End visit" from any screen.
 */
import { defineStore } from "pinia";
import type { RouteStop } from "@/api/route";

const LS_KEY = "vansale.activeVisit";

interface ActiveVisit {
  planName: string;
  stop: RouteStop;
  startedAt: number;
  notes: string;
}

interface State {
  active: ActiveVisit | null;
}

function loadPersisted(): State {
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) return { active: JSON.parse(raw) as ActiveVisit };
  } catch {
    /* ignore corrupt */
  }
  return { active: null };
}

function persist(state: State): void {
  if (state.active) {
    window.localStorage.setItem(LS_KEY, JSON.stringify(state.active));
  } else {
    window.localStorage.removeItem(LS_KEY);
  }
}

export const useRouteVisitStore = defineStore("routeVisit", {
  state: (): State => loadPersisted(),
  getters: {
    hasActive: (s) => s.active !== null,
    activeCustomer: (s) => s.active?.stop.customer ?? null,
  },
  actions: {
    start(planName: string, stop: RouteStop) {
      this.active = {
        planName,
        stop: { ...stop, status: "in_progress" },
        startedAt: Date.now(),
        notes: "",
      };
      persist(this.$state);
    },
    setNotes(notes: string) {
      if (!this.active) return;
      this.active.notes = notes;
      persist(this.$state);
    },
    clear() {
      this.active = null;
      persist(this.$state);
    },
  },
});
