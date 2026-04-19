import { apiCall } from "@/app/frappe";
import type { QueuedVisit } from "../db";

export async function drainVisit(entry: QueuedVisit): Promise<{ refName: string }> {
  const res = await apiCall<{ name: string }>("POST", "vansale.api.route.end_visit", {
    client_id: entry.clientId,
    posting_ts: entry.clientTs,
    stop_name: entry.stopName,
    ...entry.payload,
  });
  return { refName: res.name };
}
