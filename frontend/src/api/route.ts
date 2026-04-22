import { apiCall, ApiError, NetworkError } from "./client";
import { addEntry, genUuid } from "@/offline/queue";
import { isOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";
import type { QueuedVisit } from "@/offline/db";

/**
 * Route API — post-Apr 22 rewrite.
 *
 * The old "Van Route Plan" doctype is gone. A driver's day is now just
 * "every customer tagged to my sales person on the Customer's Sales
 * Team, ordered by `custom_van_sort_order` then name". Visit state
 * (in_progress/done/skipped/started_at/ended_at/invoice/payment/etc)
 * lives on a new `Van Daily Visit` doctype keyed by
 * (user, customer, visit_date).
 *
 * The server still returns `plan: null` in the payload so older APKs
 * don't crash on a missing key. New clients ignore it.
 */

export interface RouteStop {
  idx: number;
  name: string | null;
  customer: string;
  customer_name?: string | null;
  mobile_no?: string | null;
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
  visit_date: string;
  sales_person: string | null;
  /** Legacy placeholder — always null on the new server. */
  plan: null;
  stops: RouteStop[];
}

function localIsoDate(): string {
  // en-CA always yields YYYY-MM-DD regardless of the user's locale.
  return new Date().toLocaleDateString("en-CA");
}

export async function today(): Promise<TodayRoute> {
  const clientDate = localIsoDate();
  return apiCall(
    "GET",
    `vansale.api.route.today?client_date=${encodeURIComponent(clientDate)}`
  );
}

export async function startVisit(customer: string): Promise<{ name: string; started_at: string }> {
  return apiCall("POST", "vansale.api.route.start_visit", {
    customer,
    client_date: localIsoDate(),
  });
}

export interface EndVisitPayload {
  customer: string;
  invoice?: string | null;
  payment?: string | null;
  signature_file?: string | null;
  lat?: number | null;
  lng?: number | null;
  notes?: string | null;
}

/**
 * Offline-capable end-visit. Same queue pattern as save invoice.
 * `client_id` dedupes replays — server uses Van Visit Log as the
 * idempotency table.
 */
export async function endVisit(
  payload: EndVisitPayload
): Promise<{ name: string; queued?: boolean; clientId: string }> {
  const clientId = genUuid();
  const clientTs = new Date().toISOString();
  const clientDate = localIsoDate();

  if (isOnline()) {
    try {
      const res = await apiCall<{ name: string }>("POST", "vansale.api.route.end_visit", {
        client_id: clientId,
        posting_ts: clientTs,
        client_date: clientDate,
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
    stopName: `${payload.customer}:${clientDate}`,
    payload: {
      ...payload,
      client_date: clientDate,
    } as Record<string, unknown>,
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

export async function skipVisit(customer: string, reason?: string): Promise<{ status: string }> {
  return apiCall("POST", "vansale.api.route.skip_visit", {
    customer,
    reason,
    client_date: localIsoDate(),
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

export function dailyReport(clientDate?: string): Promise<DailyReport> {
  const d = clientDate || localIsoDate();
  return apiCall<DailyReport>(
    "GET",
    `vansale.api.route.daily_report?client_date=${encodeURIComponent(d)}`
  );
}
