import { apiCall, ApiError, NetworkError } from "./client";
import { addEntry, genUuid } from "@/offline/queue";
import { isOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";
import type { QueuedVisit } from "@/offline/db";

export interface RoutePlan {
  name: string;
  plan_date: string;
  warehouse?: string;
  notes?: string;
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
  return apiCall("GET", "vansale.api.route.today");
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

export function dailyReport(planDate?: string) {
  const qs = planDate ? `?plan_date=${encodeURIComponent(planDate)}` : "";
  return apiCall("GET", `vansale.api.route.daily_report${qs}`);
}
