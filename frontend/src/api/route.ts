import { apiCall, ApiError, NetworkError } from "./client";
import { addEntry, genUuid } from "@/offline/queue";
import { isOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";
import type { QueuedVisit } from "@/offline/db";

export interface RoutePlan {
  name: string;
  route_name?: string | null;
  /** Today's date (YYYY-MM-DD). Recurrence-based now \u2014 this is display-only. */
  plan_date: string;
  /** Optional anchor date from the doctype. Null for no-anchor plans. */
  effective_from?: string | null;
  frequency?: "Weekly" | "Monthly";
  warehouse?: string;
  notes?: string;
  status?: "Active" | "Completed";
  completed_at?: string | null;
  completion_summary?: DailyReport | null;
}

export interface RouteStop {
  idx: number;
  name: string;
  customer: string;
  planned_time?: string | null;
  address?: string | null;
  status: "pending" | "in_progress" | "done" | "skipped";
  started_at?: string | null;
  ended_at?: string | null;
  invoice?: string | null;
  payment?: string | null;
  signature_file?: string | null;
  notes?: string | null;
}

export interface TodayRoute {
  plan: RoutePlan | null;
  stops: RouteStop[];
}

export async function today(): Promise<TodayRoute> {
  // Send client-local YYYY-MM-DD so server resolves day-of-week against the
  // driver's phone clock, not CEST server wall time. Without this, a driver
  // in Riyadh on Wed morning can get a "Tuesday" plan because the server
  // hasn't rolled over yet (observed 2026-04-22).
  const clientDate = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD in local tz
  return apiCall("GET", `vansale.api.route.today?client_date=${encodeURIComponent(clientDate)}`);
}

export async function startVisit(planName: string, stopIdx: number): Promise<{ started_at: string }> {
  return apiCall("POST", "vansale.api.route.start_visit", { plan_name: planName, stop_idx: stopIdx });
}

export interface EndVisitPayload {
  plan_name: string;
  stop_idx: number;
  invoice?: string | null;
  payment?: string | null;
  lat?: number | null;
  lng?: number | null;
  notes?: string | null;
}

/** Offline-capable end-visit. Same pattern as save invoice. */
export async function endVisit(payload: EndVisitPayload): Promise<{ name: string; queued?: boolean; clientId: string }> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();

  if (isOnline()) {
    try {
      const res = await apiCall<{ name: string }>("POST", "vansale.api.route.end_visit", {
        client_id: clientId,
        posting_ts: clientTs,
        ...payload,
      });
      useSyncStore().refresh();
      return { ...res, clientId };
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (!(err instanceof NetworkError)) throw err;
    }
  }

  const queued: QueuedVisit = {
    clientId,
    clientTs,
    stopName: `${payload.plan_name}:${payload.stop_idx}`,
    payload: { ...payload } as Record<string, unknown>,
    createdAt: Date.now(),
    attempts: 0,
    status: "pending",
  };
  await addEntry<QueuedVisit>("visit_queue", queued);
  const sync = useSyncStore();
  await sync.refresh();
  void sync.requestDrain();
  return { name: `QUEUED:${clientId.slice(0, 8)}`, queued: true, clientId };
}

export async function skipVisit(planName: string, stopIdx: number, reason?: string): Promise<{ status: string }> {
  return apiCall("POST", "vansale.api.route.skip_visit", {
    plan_name: planName,
    stop_idx: stopIdx,
    reason,
  });
}

export interface DailyReport {
  plan_date: string;
  visits: number;
  sales: number;
  collections: number;
  returns: number;
  stop_count: number;
}

export function dailyReport(planDate?: string): Promise<DailyReport> {
  const qs = planDate ? `?plan_date=${encodeURIComponent(planDate)}` : "";
  return apiCall<DailyReport>("GET", `vansale.api.route.daily_report${qs}`);
}

export interface CompleteRouteResponse {
  status: "completed" | "already_completed" | "blocked";
  reason?: string;
  in_progress_stops?: { idx: number; customer: string }[];
  completed_at?: string | null;
  summary?: DailyReport | null;
}

/**
 * Mark a route as completed on the server. Persists `status=Completed`
 * on the Van Route Plan so reopening the plan doesn't re-prompt — the
 * v1.0.20 bug was client-only completion state.
 *
 * Pass `force=true` to close a route with in_progress stops (the "Close
 * anyway" escape hatch). Default behaviour returns `status=blocked` with
 * the list of stops the driver should resolve first.
 */
export function completeRoute(planName: string, force = false): Promise<CompleteRouteResponse> {
  return apiCall<CompleteRouteResponse>("POST", "vansale.api.route.complete_route", {
    plan_name: planName,
    force: force ? 1 : 0,
  });
}
