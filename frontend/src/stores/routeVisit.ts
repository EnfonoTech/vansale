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
 *
 * v1.0.23: customer-keyed model (plan abolished). `planName` dropped,
 * `visitDate` added so an active visit from yesterday doesn't bleed
 * into today's list after midnight.
 */
import { defineStore } from "pinia";
import type { RouteStop } from "@/api/route";

const LS_KEY = "vansale.activeVisit";

interface ActiveVisit {
  visitDate: string; // YYYY-MM-DD (local)
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
    if (!raw) return { active: null };
    const parsed = JSON.parse(raw) as Partial<ActiveVisit> & { planName?: string };
    // Migrate pre-v1.0.23 shape: drop planName, synthesize visitDate from today.
    const visitDate = parsed.visitDate || new Date().toLocaleDateString("en-CA");
    if (!parsed.stop) return { active: null };
    return {
      active: {
        visitDate,
        stop: parsed.stop as RouteStop,
        startedAt: parsed.startedAt ?? Date.now(),
        notes: parsed.notes ?? "",
      },
    };
  } catch {
    return { active: null };
  }
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
    start(stop: RouteStop) {
      const visitDate = new Date().toLocaleDateString("en-CA");
      this.active = {
        visitDate,
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
